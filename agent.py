import anthropic
import functools
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from ddgs import DDGS
import os
import random
import re

from prompts import (SYSTEM_PROMPT, TOPICS, TOPICS_MIRROR, TOPICS_FIELD, TOPICS_CAREER, TOPICS_LOW_REACH,
                     CLIENT_FACTS, CURRENT_CLIENTS, PAST_CLIENTS, SPACED_THEMES)

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HTTP_TIMEOUT = 15  # seconds, for every LinkedIn API call


def load_history():
    p = Path("history.json")
    if not p.exists() or p.read_text().strip() == "":
        return []
    return json.loads(p.read_text())


def save_to_history(post: str, topic: str, hook: str | None = None):
    history = load_history()
    entry = {"date": datetime.now().isoformat(), "topic": topic, "post": post}
    if hook:
        entry["hook"] = hook
    history.append(entry)
    Path("history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2))


def fetch_trending_topic() -> str | None:
    """Looks for a real incident or event from this week in cybersecurity or gaming."""
    year = datetime.now().year
    queries = [
        f"ransomware attack company hacked {year}",
        f"data breach cyberattack disclosed {year}",
        f"critical vulnerability exploited CVE {year}",
        f"gaming studio hacked leak breach {year}",
        f"supply chain attack malware package {year}",
        f"cloud infrastructure attack AWS Azure {year}",
    ]
    skip_keywords = [
        "what is", "definition", "how to", "guide",
        "best practices", "tips", "tutorial", "introduction", "overview",
        # sports / off-topic
        "nba", "nfl", "nhl", "mlb", "fifa", "playoff", "champion", "league",
        "football", "basketball", "baseball", "tennis", "golf", "soccer",
        "election", "vote", "weather", "recipe",
    ]
    require_keywords = [
        "hack", "breach", "attack", "ransomware", "malware", "vulnerability",
        "cve", "exploit", "leak", "data", "security", "cyber", "phishing",
        "zero-day", "zero day", "backdoor", "botnet", "ddos", "infosec", "incident",
    ]
    try:
        with DDGS() as ddgs:
            for query in queries:
                results = list(ddgs.news(query, max_results=5, timelimit="w"))
                for r in results:
                    title = r.get("title", "").lower()
                    body_low = r.get("body", "").lower()
                    combined = title + " " + body_low
                    if any(kw in title for kw in skip_keywords):
                        continue
                    if not any(kw in combined for kw in require_keywords):
                        continue
                    title_raw = r.get("title", "")
                    body = r.get("body", "")[:300]
                    source = r.get("source", "")
                    print(f"[Trending] Found via '{query}': {title_raw} ({source})")
                    return (
                        f"this week's news: '{title_raw}' "
                        f"({source}). Context: {body}. "
                        f"Analyze this event from your DevOps/cybersecurity field expertise. "
                        f"If it involves a gaming studio or major tech company, connect it to "
                        f"security implications for creative environments and supply chains."
                    )
    except Exception as e:
        print(f"Trending topic fetch failed: {e}")
    return None


# News analysis is off by default: on the account this agent was built for, identity and opinion posts
# reached 30x to 100x more people than news commentary. fetch_trending_topic() stays available.
NEWS_ENABLED = False

# Topic pools and how often each is drawn. "mirror" topics attack a choice or a label the reader's own
# company has probably adopted (the format of the 30,000+ impression posts, see PERFORMANCE in prompts.py).
TOPIC_POOLS = [("mirror", 0.85), ("field", 0.10), ("career", 0.05), ("low", 0.0)]


def is_spaced(topic: str, keywords: tuple) -> bool:
    low = topic.lower()
    return any(k in low for k in keywords)


def pick_topic(history: list) -> str:
    if NEWS_ENABLED:
        news_history = [h for h in history if h["topic"] != "queued_post"]
        last_was_news = bool(news_history) and news_history[-1]["topic"].startswith("this week's news")
        if not last_was_news:
            trending = fetch_trending_topic()
            if trending:
                return trending

    names, weights = zip(*TOPIC_POOLS)
    name = random.choices(names, weights=weights)[0]
    pool = {"mirror": TOPICS_MIRROR, "field": TOPICS_FIELD, "career": TOPICS_CAREER, "low": TOPICS_LOW_REACH}[name] or TOPICS_MIRROR
    # Themes that must not dominate the feed (see SPACED_THEMES in prompts.py): at most one post per theme
    # every `gap` posts, so you don't become "the person who is always against X".
    for keywords, gap in SPACED_THEMES.values():
        if any(is_spaced(h["topic"], keywords) for h in history[-gap:]):
            pool = [t for t in pool if not is_spaced(t, keywords)] or pool
    # A topic never covered first, otherwise the least recently used one.
    last_used = {h["topic"]: i for i, h in enumerate(history)}
    never_used = [t for t in pool if t not in last_used]
    if never_used:
        return random.choice(never_used)
    return min(pool, key=lambda t: last_used[t])


# --- Humanizer (adapted from the li-human skill, MIT, Jakeschincariol/linkedin-agent-skill) ---
INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u2064\u00ad\ufeff\U000e0000-\U000e007f]")
TYPO = [("\u00a0", " "), ("\u202f", " "), ("\u2009", " "), ("\u201c", '"'), ("\u201d", '"'),
        ("\u2018", "'"), ("\u2019", "'"), ("\u2026", "..."), (" \u2014 ", ", "), ("\u2014", ", "),
        (" \u2013 ", ", "), ("\u2013", "-"), ("\u2022", "-")]
BANNED_EMOJI = ("\U0001F680", "\U0001F525", "\u2728")  # rocket, fire, sparkles
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]\ufe0f?")


def clean_text(post: str) -> str:
    """Mechanical cleanup: invisible characters, long dashes, curly quotes, non-breaking spaces."""
    post = INVISIBLE.sub("", post)
    for a, b in TYPO:
        post = post.replace(a, b)
    for e in BANNED_EMOJI:
        post = post.replace(e + " ", "").replace(e, "")
    return re.sub(r",\s*,", ",", post)


def dedupe_emojis(post: str, history: list) -> str:
    """Same emoji sequence as the previous post: strip them (too visible a signature from post to post)."""
    if not history:
        return post
    prev = EMOJI_RE.findall(history[-1].get("post", ""))
    cur = EMOJI_RE.findall(post)
    if len(cur) >= 2 and cur[:2] == prev[:2]:
        post = re.sub(r"(?m)^" + EMOJI_RE.pattern + r"\s*", "", post)
    return post


def fit_first_line(post: str, limit: int = 140) -> str:
    """Mobile truncates around 140 characters before "see more": keep line 1 under it by isolating sentences."""
    lines = post.split("\n")
    if not lines or len(lines[0]) <= limit:
        return post
    sentences = re.split(r"(?<=[.!?])\s+", lines[0].strip())
    head = sentences[0]
    i = 1
    while i < len(sentences) and len(head) + 1 + len(sentences[i]) <= limit:
        head += " " + sentences[i]
        i += 1
    if len(head) > limit or i == len(sentences):
        return post  # the first sentence alone is too long: left to the reviewer
    return "\n".join([head, "", " ".join(sentences[i:])] + lines[1:])


def style_flags(post: str, history: list | None = None) -> list[str]:
    """Tells of generated text, handed to the reviewer for a rewrite (no destructive regex)."""
    flags = []
    first = post.strip().splitlines()[0] if post.strip() else ""
    if len(first) > 140:
        flags.append(f"Line 1 is {len(first)} characters: bring it under 140 without losing its meaning.")
    rhetorical = re.findall(r"(?:^|[.!\n]\s*)(?:\S+\s){0,4}\S+\s?\?\s+[A-ZÀ-Ý]", post)
    if len(rhetorical) > 1:
        flags.append(f"{len(rhetorical)} short rhetorical questions answered right away ('The result? ...'): keep one at most.")
    not_x = len(re.findall(r"(?i)\b(?:it's not|it is not|ce n'est pas)\b[^.]{0,80}\b(?:it's|it is|c'est)\b", post))
    if not_x > 1:
        flags.append("Several 'It's not X, it's Y' constructions: keep one at most.")
    if len(re.findall(r"(?m)^(?:(?:No|Pas de) [^.]+\.\s*){3}", post)) > 1:
        flags.append("Several 'No X. No Y. No Z.' triads: keep one at most.")
    if re.search(r"\S - \S", post):
        flags.append("A spaced hyphen ' - ' is used as a long dash mid-sentence: use a colon or a comma.")
    tags = re.findall(r"#\w+", post)
    if len(tags) > 2:
        flags.append(f"{len(tags)} hashtags: keep 2 niche ones at most.")
    if history:
        prev = EMOJI_RE.findall(history[-1].get("post", ""))
        cur = EMOJI_RE.findall(post)
        if len(cur) >= 3 and cur[:3] == prev[:3]:
            flags.append("Same emojis as the previous post, in the same order: change or remove them.")
    return flags


STORY_BANK_FILE = Path(__file__).parent / "story_bank.md"


def story_bank() -> str:
    """Your real experiences (private file, gitignored). Only lines starting with "- " count as entries."""
    if not STORY_BANK_FILE.exists():
        return ""
    return "\n".join(l for l in STORY_BANK_FILE.read_text(encoding="utf-8").splitlines() if l.startswith("- "))


def best_posts(history: list, n: int = 2) -> list:
    """Your most-viewed posts (impressions recorded with the Discord `!stats` command), used as a reference."""
    own = [h for h in history if h.get("impressions") and not h["topic"].startswith("this week's news")]
    return sorted(own, key=lambda h: h["impressions"], reverse=True)[:n]


# Opening shapes, drawn at random, weighted by what worked, never one of the last 3 used: two posts that work
# must not end up looking alike (a visible recipe). Every shape targets the reader or their company.
HOOK_STYLES = {
    "label": "Open with 'Unpopular opinion:' followed by a short claim aimed straight at the reader's company (\"... for your company\"). Used rarely, it keeps its punch.",
    "claim": "Open with a dry claim under 12 words, no label, contradicting what the reader's company probably did.",
    "quote": "Open with a line in quotes that everyone has heard at work (plausible, mundane, revealing), then take it apart.",
    "question": "Open with a direct question about the reader's own company, one they would rather not answer honestly.",
    "blacklist": "Open by listing 2 or 3 things every company does or recommends, then break the rhythm with one sentence saying why it's wrong.",
    "number": "Open with a raw number alone on its line (sourced, or presented as your field estimate) that concerns the reader's company.",
    "comparison": "Open with an everyday comparison outside tech (cooking, sport, music, games) that sums up in one line the mistake most companies make.",
    "confession": "Open with a mistake you made too, then turn it quickly toward the reader: \"and your company is probably making it right now\".",
}
HOOK_WEIGHTS = {"label": 3, "claim": 3, "quote": 2, "question": 2, "blacklist": 2, "number": 1, "comparison": 1, "confession": 1}
LABEL_GAP = 6  # "Unpopular opinion:" at most once every 6 posts


def pick_hook(history: list) -> str:
    recent = [h.get("hook") for h in history[-3:] if h.get("hook")]
    available = [k for k in HOOK_STYLES if k not in recent]
    if any(h.get("hook") == "label" or h.get("post", "").lstrip().lower().startswith(("unpopular opinion", "opinion impopulaire"))
           for h in history[-LABEL_GAP:]):
        available = [k for k in available if k != "label"]
    available = available or ["claim"]
    return random.choices(available, weights=[HOOK_WEIGHTS[k] for k in available])[0]


@functools.lru_cache(maxsize=16)
def _search_sources_cached(topic: str) -> tuple:
    return tuple(_search_sources_impl(topic))


def search_sources(topic: str) -> list:
    """DuckDuckGo source search, with a process-local cache (avoids duplicate requests
    between post generation and OG image fetching)."""
    return list(_search_sources_cached(topic))


def _search_sources_impl(topic: str) -> list:
    try:
        with DDGS() as ddgs:
            is_news = topic.startswith("this week's news")
            if is_news:
                raw = topic.split("Context:")[0].replace("this week's news: ", "").strip("'\" ()")
                query = raw.split(".")[0][:120]
                results = list(ddgs.text(query, max_results=5))
            else:
                results = list(ddgs.text(
                    topic + " site:kubernetes.io OR site:cve.mitre.org OR site:thehackernews.com OR site:blog.gitguardian.com OR site:grafana.com OR site:cloud.google.com OR site:docs.microsoft.com OR site:securityweek.com",
                    max_results=3
                ))
            sources = []
            for r in results:
                sources.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "body": r.get("body", "")[:300]
                })
            return sources
    except Exception as e:
        print(f"Source search failed: {e}")
        return []


OG_IMAGE_MAX_BYTES = 8 * 1024 * 1024  # Discord's limit on a non-boosted server; LinkedIn allows more, no need to go higher


def fetch_og_image(url: str) -> tuple[bytes, str] | None:
    """Fetches an article's Open Graph image. Returns (bytes, mime_type) or None.
    Rejects oversized images (Discord and LinkedIn both enforce size limits)."""
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', r.text
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', r.text
        )
        if not match:
            return None
        img_url = match.group(1)
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        img_r = requests.get(img_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if img_r.status_code != 200:
            return None
        mime = img_r.headers.get("content-type", "image/jpeg").split(";")[0]
        if not mime.startswith("image/"):
            return None
        if len(img_r.content) > OG_IMAGE_MAX_BYTES:
            print(f"OG image too large ({len(img_r.content) / 1024 / 1024:.1f} MB), skipped: {img_url}")
            return None
        return img_r.content, mime
    except Exception as e:
        print(f"OG image fetch failed: {e}")
    return None


def upload_image_to_linkedin(image_bytes: bytes, mime_type: str, token: str, urn: str) -> str | None:
    """Uploads an image to LinkedIn. Returns the asset URN, or None on failure."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    reg = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers=headers,
        timeout=HTTP_TIMEOUT,
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": urn,
                "serviceRelationships": [{
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }]
            }
        }
    )
    if reg.status_code != 200:
        print(f"Image register failed: {reg.status_code} {reg.text[:200]}")
        return None
    data = reg.json()
    upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = data["value"]["asset"]
    up = requests.put(upload_url, data=image_bytes, timeout=60,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": mime_type})
    if up.status_code not in (200, 201):
        print(f"Image upload failed: {up.status_code}")
        return None
    return asset_urn


def generate_post(topic: str, history: list, hook: str | None = None) -> str:
    recent = "\n".join([f"- {h['post'][:80]}..." for h in history[-3:]]) or "None"
    hook = hook or pick_hook(history)
    stories = story_bank()
    story_block = ("STORY BANK (your real experiences, the only ones you may tell as an anecdote; use ONE at most, "
                   "only if it truly serves the topic):\n" + stories + "\n") if stories else ""
    best = best_posts(history)
    best_block = ""
    if best:
        best_block = ("YOUR BEST-PERFORMING POSTS (reference for SUBSTANCE: level of conviction, field anchoring, a closing "
                      "question that forces a side). Reuse NONE of their sentences, openings or structure:\n"
                      + "\n".join(f"--- {h['impressions']} impressions, {h.get('comments', '?')} comments ---\n{h['post']}" for h in best)
                      + "\n")
    recent_openers = "\n".join(
        f"- {h['post'].strip().splitlines()[0][:120]}" for h in history[-6:] if h.get("post", "").strip()
    ) or "None"

    topics_with_sources = [
        "CVE", "ransomware", "pipeline", "CI/CD", "Kubernetes", "Docker",
        "Terraform", "Ansible", "observability", "Grafana", "security",
        "cloud", "backup", "secret", "RBAC", "ArgoCD", "IaC", "monitoring"
    ]
    is_news = topic.startswith("this week's news")
    needs_sources = is_news or any(kw.lower() in topic.lower() for kw in topics_with_sources)

    sources_context = ""
    if needs_sources:
        sources = search_sources(topic)
        if sources:
            sources_context = "\n\nAvailable facts and sources (cite them inline in parentheses when you use them):\n"
            for s in sources:
                name = s["url"].split("/")[2].replace("www.", "").split(".")[0].capitalize()
                sources_context += f"- [{name}] {s['title']}: {s['body']}\n"

    today = datetime.now().strftime("%A %B %d, %Y")

    format_instruction = ""
    if is_news:
        format_instruction = """
You MUST use the "news analysis" format:
1. Main fact + key number as the hook
2. "The twist?": the unexpected angle most people missed
3. 2-3 bullet points of macro thesis (what this really says about the industry, not just the isolated fact)
4. Memorable closing punchline: a smart, humorous line or a realistic-but-absurd projection
5. MANDATORY right after the punchline: an open, concrete question addressed to the reader
   about THEIR own situation (their company, their team, their stack), easy to answer in a
   short comment. No vague rhetorical question like "what do you think?".
No promotional CTA or link. Length: 300-420 words. Inline citations: (Reuters), (Bloomberg), (TechCrunch), etc."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1400,
        temperature=0.9,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Today is {today}.
Generate a LinkedIn post about: {topic}

Recent posts (don't repeat these):
{recent}
{sources_context}
{format_instruction}

{best_block}{story_block}
OPENING FOR THIS POST (the shape is imposed, the substance is free): {HOOK_STYLES[hook]}
First lines of your latest posts: reuse neither their wording, nor their structure, nor their first word.
{recent_openers}
Also vary the layout from one post to the next (paragraph length, emoji placement, with or without a lone
sentence on its own line) so your posts don't read like a repeated recipe.

Generate only the post text, ready to publish."""
        }]
    )
    draft = clean_text(message.content[0].text)
    flags = style_flags(draft, history)
    if flags:
        print("[humanizer] " + " | ".join(flags))
    return dedupe_emojis(fact_guard(draft, flags), history)


def fact_guard(post: str, flags: list[str] | None = None) -> str:
    """Second pass before publishing. Language models invent anecdotes and numbers about named clients even when told
    not to, and personal posts go out without human review: this pass neutralizes them, fixes the style tells, and
    applies your tone rules about current and past clients (CURRENT_CLIENTS / PAST_CLIENTS in prompts.py)."""
    style_block = ""
    if flags:
        style_block = "Also fix these tells of generated writing, rewriting as little as possible:\n" + \
            "\n".join(f"- {f}" for f in flags) + "\n"
    named = ", ".join(CURRENT_CLIENTS + PAST_CLIENTS) or "(none listed)"
    current = ", ".join(CURRENT_CLIENTS) or "(none)"
    past = ", ".join(PAST_CLIENTS) or "(none)"
    try:
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1600,
            temperature=0,
            messages=[{"role": "user", "content": f"""You are proofreading a LinkedIn post before it is published under the author's name.

Real facts allowed about the author's clients:
{CLIENT_FACTS}
Real experiences allowed (story bank, numbers included):
{story_bank() or "(empty)"}

Rule: any passage attributing to a NAMED client ({named}) an incident, a duration, a number, a decision, a project or
an anecdote ABSENT from the facts above must be rewritten as an anonymous recurring pattern ("at a client", "what I
often see", "across several missions"), keeping the idea and the rhythm. What matches the facts stays as is.
{style_block}Tone rule on clients: the current engagement ({current}) appears ONLY positively (what the author brings).
Any passage describing a conflict, a refusal or a disagreement in a context that could be the current engagement
must be DELETED entirely, stitching the text back together ("at a client" is not enough: the client would recognize
it). Past clients ({past}) are never criticized: rewrite any criticism as "before / after, thanks to me and the team".
Also neutralize: any unsourced numeric comparison about a price or a bill (make it qualitative), and any precise,
unverifiable technical claim about compatibility or integration between tools (remove it or make it cautious).
Change nothing else: not the tone, not the structure, not the closing question, not the length.
Never use an em dash or an en dash.

Answer only with the final post, no commentary.

POST:
{post}"""}],
        )
        checked = msg.content[0].text.strip()
        return fit_first_line(clean_text(checked if len(checked) > len(post) * 0.6 else post))
    except Exception as e:
        print(f"fact_guard skipped: {e}")
        return fit_first_line(clean_text(post))


def add_first_comment(post_urn: str, comment_text: str, token: str, actor_urn: str) -> bool:
    """Adds a comment on a post that was just published (typically the link, so an
    external link in the body doesn't hurt organic reach)."""
    import urllib.parse
    encoded = urllib.parse.quote(post_urn, safe="")
    r = requests.post(
        f"https://api.linkedin.com/v2/socialActions/{encoded}/comments",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        },
        timeout=HTTP_TIMEOUT,
        json={"actor": actor_urn, "message": {"text": comment_text}}
    )
    if r.status_code not in (200, 201):
        print(f"⚠ First comment failed: {r.status_code} {r.text[:200]}")
        return False
    return True


def publish_to_linkedin(post_text: str, image_path: Path | None = None, first_comment: str | None = None) -> bool:
    """Publishes a post. If first_comment is set, it's added as a comment right after
    publishing instead of living in the post body - LinkedIn's algorithm penalizes posts
    with an external link in the main text, so keep any link out of post_text and pass
    it here instead."""
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    urn   = os.getenv("LINKEDIN_PERSON_URN")

    asset_urn = None
    if image_path and image_path.exists():
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        asset_urn = upload_image_to_linkedin(image_path.read_bytes(), mime, token, urn)
        if asset_urn:
            print(f"✓ Image uploaded: {image_path.name}")
        else:
            print("⚠ Image upload failed, post published without image")

    if asset_urn:
        media = {
            "shareCommentary": {"text": post_text},
            "shareMediaCategory": "IMAGE",
            "media": [{"status": "READY", "media": asset_urn, "description": {"text": ""}, "title": {"text": ""}}]
        }
    else:
        media = {"shareCommentary": {"text": post_text}, "shareMediaCategory": "NONE"}

    r = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        },
        timeout=HTTP_TIMEOUT,
        json={
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": media},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
    )
    success = r.status_code == 201

    if success and first_comment:
        post_urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id")
        if post_urn and add_first_comment(post_urn, first_comment, token, urn):
            print(f"✓ First comment added: {first_comment}")
        elif not post_urn:
            print("⚠ Couldn't find the post URN in the response, skipping first comment")

    return success


QUEUE_FILE = Path("queue.md")
PENDING_FILE = Path("pending.md")
PUBLISHED_NOTICE = Path("published.json")  # read by discord_bot.py: reminder of the first 60-90 minutes window


def pop_queue() -> str | None:
    """Returns the first draft in the queue and removes it from the file."""
    if not QUEUE_FILE.exists():
        return None
    content = QUEUE_FILE.read_text(encoding="utf-8")
    # Entries are separated by "---"
    entries = [e.strip() for e in content.split("---") if e.strip()]
    if not entries:
        QUEUE_FILE.unlink()
        return None
    draft = entries[0]
    remaining = entries[1:]
    if remaining:
        QUEUE_FILE.write_text("\n\n---\n\n".join(remaining) + "\n", encoding="utf-8")
    else:
        QUEUE_FILE.unlink()
    return draft


def run():
    history = load_history()

    # If there are drafts queued up, take the first one
    draft = pop_queue()
    if draft:
        topic = "queued_post"
        print(f"[{datetime.now()}] Found a queued post, sending to Claude...")

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            temperature=0.85,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""Here's a LinkedIn post draft or idea I wrote ahead of time:

---
{draft}
---

Expand and rewrite it following ALL the rules in the prompt (no em dash, no clichés, LinkedIn
format, well-placed emojis, punchy hook). If it's just an idea or a few words, fully develop it
into a complete LinkedIn post. Keep the tone, the key ideas, and the CTA if there is one.
Generate only the final post text, ready to publish."""
            }]
        )
        post = message.content[0].text
        print(f"\n--- POST REWRITTEN BY CLAUDE ---\n{post}\n---")
        success = publish_to_linkedin(post)
        if success:
            save_to_history(post, topic)
            print("✓ Published to LinkedIn, queue updated")
        else:
            print("✗ Publication failed, queue.md kept for retry")
        return

    # If a post is already waiting for approval, don't overwrite it.
    # This guard runs BEFORE generation to avoid a wasted Claude API call.
    if PENDING_FILE.exists():
        print("⚠ pending.md already exists, skipping generation to avoid overwriting the pending post.")
        print("  Publish or delete the existing post via Discord or post_now.py --from-pending")
        return

    topic = pick_topic(history)
    hook = pick_hook(history)
    print(f"[{datetime.now()}] Generating about: {topic[:80]}... (opening: {hook})")

    post = generate_post(topic, history, hook)
    print(f"\n--- GENERATED POST ---\n{post}\n---")

    # News-based posts are never auto-published. Save it with the source article's
    # OG image for manual review instead.
    if topic.startswith("this week's news"):
        og_image_path = None
        sources = search_sources(topic)
        if sources:
            for s in sources:
                result = fetch_og_image(s["url"])
                if result:
                    img_bytes, mime = result
                    ext = ".jpg" if "jpeg" in mime else ".png"
                    og_image_path = PENDING_FILE.with_suffix(ext)
                    og_image_path.write_bytes(img_bytes)
                    print(f"✓ OG image saved: {og_image_path.name}")
                    break
        PENDING_FILE.write_text(
            f"TOPIC: {topic}\nIMAGE: {og_image_path.name if og_image_path else ''}\n\n---\n\n{post}\n",
            encoding="utf-8"
        )
        print("\n⚠ News-based post, publication held for review.")
        print("  Check the facts, then publish with: python post_now.py --from-pending")
        return

    success = publish_to_linkedin(post)
    if success:
        PUBLISHED_NOTICE.write_text(json.dumps({"at": datetime.now().isoformat(), "first": post.strip().splitlines()[0]}),
                                    encoding="utf-8")
        save_to_history(post, topic, hook)
        print("✓ Published to LinkedIn")
    else:
        print("✗ Publication failed")


if __name__ == "__main__":
    import sys
    import time
    if not sys.stdin.isatty():
        # Started by cron: random 0-15 min delay, so posts don't go out at the exact same minute every week.
        time.sleep(random.randint(0, 900))
    run()
