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

from prompts import SYSTEM_PROMPT, TOPICS

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HTTP_TIMEOUT = 15  # seconds, for every LinkedIn API call


def load_history():
    p = Path("history.json")
    if not p.exists() or p.read_text().strip() == "":
        return []
    return json.loads(p.read_text())


def save_to_history(post: str, topic: str):
    history = load_history()
    history.append({
        "date": datetime.now().isoformat(),
        "topic": topic,
        "post": post
    })
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


def pick_topic(history: list) -> str:
    # News vs. personal/opinion alternation: a "news analysis" post positions you as a
    # commentator on someone else's event. A personal/opinion/named-client post positions
    # you as someone with real experience. The second gets far more comments (and reach).
    # Without forced alternation, fetch_trending_topic() almost always finds something,
    # and the personal topics in TOPICS never get a chance to run.
    weekly_history = [h for h in history if h["topic"] != "queued_post"]
    last_was_news = bool(weekly_history) and weekly_history[-1]["topic"].startswith("this week's news")

    if not last_was_news:
        trending = fetch_trending_topic()
        if trending:
            return trending
    else:
        print("[Topic] Forcing a personal/opinion week (news was published last time)")

    # Fallback / personal week: static list
    print("[Topic] Picking a personal/opinion topic from the static list")
    used_recently = [h["topic"] for h in history[-5:]]
    available = [t for t in TOPICS if t not in used_recently]
    if not available:
        last = history[-1]["topic"] if history else None
        available = [t for t in TOPICS if t != last]
    return random.choice(available)


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


def generate_post(topic: str, history: list) -> str:
    recent = "\n".join([f"- {h['post'][:80]}..." for h in history[-3:]]) or "None"

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
2. "The twist?" - the unexpected angle most people missed
3. 2-3 bullet points of macro thesis (what this really says about the industry, not just the isolated fact)
4. Memorable closing punchline: a smart, humorous line or a realistic-but-absurd projection
5. MANDATORY right after the punchline: an open, concrete question addressed to the reader
   about THEIR own situation (their company, their team, their stack), easy to answer in a
   short comment. Without it, the post generates zero comments. No vague rhetorical question
   like "what do you think?" - it must be specific to the topic just covered.
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

Generate only the post text, ready to publish."""
        }]
    )
    return message.content[0].text


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
    print(f"[{datetime.now()}] Generating about: {topic[:80]}...")

    post = generate_post(topic, history)
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
        save_to_history(post, topic)
        print("✓ Published to LinkedIn")
    else:
        print("✗ Publication failed")


if __name__ == "__main__":
    run()
