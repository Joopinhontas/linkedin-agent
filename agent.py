import anthropic
import json
import os
import random
import re
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from ddgs import DDGS

from prompts import SYSTEM_PROMPT, TOPICS

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SKILL_PREFIX = "claude_skill:"
SKILLS_DIR = Path("skills")


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
    """Fetches a real incident or event from this week in cybersecurity or gaming."""
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
        "zero-day", "zero day", "backdoor", "botnet", "ddos", "infosec",
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


def fetch_claude_skill() -> dict | None:
    """Finds a trending Claude Code skill on GitHub: new repos gaining stars fast."""
    from datetime import timedelta

    already_done = set()
    if SKILLS_DIR.exists():
        already_done = {f.stem.replace("INSTALL_", "").lower() for f in SKILLS_DIR.glob("INSTALL_*.md")}

    headers = {"Accept": "application/vnd.github.v3+json"}
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    since = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    queries = [
        f"claude+skill+SKILL.md+created:>{since}",
        f"claude-code+skill+created:>{since}",
        f"claude+code+skill+created:>{since}",
    ]

    try:
        for query in queries:
            url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=15"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            items = r.json().get("items", [])
            for item in items:
                name = item.get("name", "")
                stars = item.get("stargazers_count", 0)
                if stars < 3:
                    continue
                if name.lower() in already_done:
                    continue
                description = item.get("description", "") or ""
                html_url = item.get("html_url", "")
                full_name = item.get("full_name", "")
                print(f"[Skill] Found: {full_name} ⭐{stars} ({html_url})")
                return {
                    "name": name,
                    "url": html_url,
                    "title": full_name,
                    "description": description,
                    "stars": stars,
                    "author": item.get("owner", {}).get("login", ""),
                }
    except Exception as e:
        print(f"Claude skill fetch failed: {e}")
    return None


def pick_topic(history: list) -> str:
    # Priority 1: trending Claude skill (always tried first)
    skill = fetch_claude_skill()
    if skill:
        return f"{SKILL_PREFIX}{skill['name']}|{skill['url']}|{skill['title']}|{skill['description']}"

    # Priority 2: real news event from this week
    trending = fetch_trending_topic()
    if trending:
        return trending

    # Fallback: static topic list
    print("[Topic] No trending news found, falling back to static list")
    used_recently = [h["topic"] for h in history[-5:]]
    available = [t for t in TOPICS if t not in used_recently]
    if not available:
        last = history[-1]["topic"] if history else None
        available = [t for t in TOPICS if t != last]
    return random.choice(available)


def search_sources(topic: str) -> list:
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
                sources.append({"title": r.get("title", ""), "url": r.get("href", ""), "body": r.get("body", "")[:300]})
            return sources
    except Exception as e:
        print(f"Source search failed: {e}")
        return []


def fetch_og_image(url: str) -> tuple[bytes, str] | None:
    """Fetch the Open Graph image from a news article. Returns (bytes, mime_type) or None."""
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
        mime = img_r.headers.get("content-type", "image/jpeg").split(";")[0]
        if img_r.status_code == 200 and mime.startswith("image/"):
            return img_r.content, mime
    except Exception as e:
        print(f"OG image fetch failed: {e}")
    return None


def svg_to_png(svg_path: Path) -> Path | None:
    """Convert SVG to PNG using cairosvg. Returns PNG path or None."""
    try:
        import cairosvg
        png_path = svg_path.with_suffix(".png")
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=2)
        return png_path
    except Exception as e:
        print(f"SVG→PNG conversion failed: {e}")
    return None


def upload_image_to_linkedin(image_bytes: bytes, mime_type: str, token: str, urn: str) -> str | None:
    """Upload an image to LinkedIn. Returns asset URN or None on failure."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    reg = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers=headers,
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": urn,
                "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
            }
        }
    )
    if reg.status_code != 200:
        print(f"Image register failed: {reg.status_code} {reg.text[:200]}")
        return None
    data = reg.json()
    upload_url = data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = data["value"]["asset"]
    up = requests.put(upload_url, data=image_bytes, headers={"Authorization": f"Bearer {token}", "Content-Type": mime_type})
    if up.status_code not in (200, 201):
        print(f"Image upload failed: {up.status_code}")
        return None
    return asset_urn


def generate_skill_post(skill: dict) -> str:
    """Generates a teaser LinkedIn post for a Claude skill — no install instructions."""
    today = datetime.now().strftime("%A %d %B %Y")
    prompt = f"""Today is {today}.

Write a LinkedIn TEASER post about this Claude Code skill you just discovered:

Skill name: {skill['name']}
GitHub URL: {skill['url']}
Description: {skill['description']}

STRICT RULES:
- Open with a hook about what this skill lets you DO (not how it works)
- Give 2-3 concrete, impressive examples of what you can accomplish with it
- Do NOT explain how to install it, do NOT give technical commands
- Create curiosity and desire: the reader should think "I want this"
- End EXACTLY with this CTA (only adapt the skill name):
  "💬 If you want me to walk you through the install, comment {skill['name']} below and I'll send you my free guide."
- 2-3 emojis, no more
- 150-250 words max
- Plain text only, no markdown
- 3-4 hashtags: #ClaudeAI #AI and topic-relevant ones

Output only the post text."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        temperature=0.85,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def generate_install_guide(skill: dict) -> str:
    """Generates an INSTALL_*.md guide with author info and CTA."""
    author_name = os.getenv("AUTHOR_NAME", "[YOUR NAME]")
    author_title = os.getenv("AUTHOR_TITLE", "[YOUR TITLE]")
    author_company = os.getenv("AUTHOR_COMPANY", "[YOUR COMPANY]")
    website = os.getenv("WEBSITE_URL", "https://yourwebsite.com")
    linkedin = os.getenv("LINKEDIN_URL", "")
    malt = os.getenv("MALT_URL", "")
    github = os.getenv("GITHUB_URL", "")

    links = f"👉 [{website}]({website})"
    if linkedin:
        links += f" · [LinkedIn]({linkedin})"
    if malt:
        links += f" · [Malt]({malt})"
    if github:
        links += f" · [GitHub]({github})"

    prompt = f"""Generate a complete Markdown installation guide for this Claude Code skill:

Name: {skill['name']}
GitHub URL: {skill['url']}
Description: {skill['description']}

Use EXACTLY this structure:

# {skill['name']} — Installation Guide

## About the author

{author_name}, {author_title} at {author_company}.

{links}

---

## What is {skill['name']}?

[Clear 3-4 line description of what the skill does concretely and what it changes for the user]

---

## Prerequisites

[Bullet list of requirements]

---

## Step-by-step installation

[Numbered steps with exact commands in ```bash``` blocks]

---

## How to use it

IMPORTANT: this section MUST contain EXACTLY 3 concrete examples, each with:
- A use case title (### Example 1: ...)
- The exact prompt to type in Claude Code in a code block
- One sentence explaining what the skill will do

---

## Go further

Want more tools like this?
Find me on [LinkedIn]({linkedin or website}) and check my resources at [{website}]({website}).

---
*Guide by {author_name} — [{author_company}]({website})*

Output only the Markdown content."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        temperature=0.5,
        system=f"You are {author_name}, {author_title} at {author_company}.",
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def get_skill_svg_scenarios(skill: dict) -> dict | None:
    """Ask Claude for 2 concrete usage scenarios for the animated SVG demo."""
    import json, re
    prompt = f"""Claude Code skill to demo:
Name: {skill['name']}
Description: {skill['description']}

Return ONLY a JSON object with 2 usage scenarios for an animated terminal demo.
Keep all text under 52 characters. Use English.
Types: "error" (red), "warning" (orange), "info" (gray), "success" (green).

{{
  "s1_command": "> user command for scenario 1",
  "s1_status": "[{skill['name']}] running checks...",
  "s1_lines": [
    {{"text": "result line 1", "type": "error|warning|info"}},
    {{"text": "result line 2", "type": "error|warning|info"}},
    {{"text": "result line 3", "type": "error|warning|info"}}
  ],
  "s1_summary": "summary of findings",
  "s2_command": "> fix/action command for scenario 2",
  "s2_status": "applying fixes...",
  "s2_lines": [
    {{"text": "result line 1", "type": "success"}},
    {{"text": "result line 2", "type": "success"}},
    {{"text": "result line 3", "type": "success"}}
  ],
  "s2_summary": "final success summary"
}}

Return only the JSON."""
    try:
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(match.group() if match else text)
    except Exception as e:
        print(f"SVG scenarios generation failed: {e}")
        return None


def generate_skill_svg(skill: dict, d: dict) -> str:
    """Builds the animated terminal SVG demo for a skill."""
    from xml.sax.saxutils import escape as xe

    COLOR_MAP = {
        "error": "#f85149", "warning": "#e3b341",
        "info": "#8b949e",  "success": "#3fb950",
    }

    def txt(y, content, color, kt):
        return (
            f'    <text x="20" y="{y}" fill="{color}" opacity="0">\n'
            f'      <tspan>{xe(str(content))}</tspan>\n'
            f'      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"\n'
            f'        keyTimes="0;{kt};1" values="0;1;1" calcMode="discrete"/>\n'
            f'    </text>'
        )

    def sep(y, kt):
        return txt(y, "─" * 50, "#21262d", kt)

    l1 = [l.get("text", "") for l in d.get("s1_lines", [{}, {}, {}])]
    c1 = [COLOR_MAP.get(l.get("type", "info"), "#8b949e") for l in d.get("s1_lines", [{}, {}, {}])]
    l2 = [l.get("text", "") for l in d.get("s2_lines", [{}, {}, {}])]
    while len(l1) < 3: l1.append(""); c1.append("#8b949e")
    while len(l2) < 3: l2.append("")

    sn      = xe(skill.get("name", "skill"))
    s1_cmd  = xe(d.get("s1_command", "> run the skill"))
    s1_stat = xe(d.get("s1_status",  "Processing..."))
    s1_sum  = xe(d.get("s1_summary", "Done"))
    s2_cmd  = xe(d.get("s2_command", "> apply fixes"))
    s2_stat = xe(d.get("s2_status",  "Applying fixes..."))
    s2_sum  = xe(d.get("s2_summary", "✓ All done"))

    return f'''<svg viewBox="0 0 700 290" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>text {{ font-family: 'SF Mono','Menlo','Monaco','Consolas','Courier New',monospace; font-size: 12.5px; }}</style>
    <clipPath id="cmd1">
      <rect x="20" y="51" width="0" height="18">
        <animate attributeName="width" dur="18s" repeatCount="indefinite"
          keyTimes="0;0.001;0.065;1" values="0;0;82;82" calcMode="linear"/>
      </rect>
    </clipPath>
  </defs>
  <rect width="700" height="290" rx="10" fill="#0d1117" stroke="#30363d" stroke-width="1"/>
  <rect width="700" height="34" rx="10" fill="#161b22"/>
  <rect y="10" width="700" height="24" fill="#161b22"/>
  <circle cx="20" cy="17" r="5.5" fill="#ff5f56"/>
  <circle cx="38" cy="17" r="5.5" fill="#ffbd2e"/>
  <circle cx="56" cy="17" r="5.5" fill="#27c93f"/>
  <text x="350" y="22" text-anchor="middle" font-size="12" fill="#8b949e">{sn} — claude</text>

  <!-- SCENE 1 -->
  <g>
    <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
      keyTimes="0;0.44;0.50;1" values="1;1;0;0" calcMode="linear"/>
    <text x="20" y="66" fill="#58a6ff" clip-path="url(#cmd1)">$ claude</text>
    <rect y="52" width="8" height="15" fill="#c9d1d9">
      <animate attributeName="x" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.001;0.065;1" values="20;20;102;102" calcMode="linear"/>
      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.075;0.076;1" values="1;1;0;0" calcMode="discrete"/>
    </rect>
    <text x="20" y="88" fill="#c9d1d9" opacity="0">
      <tspan>{s1_cmd}</tspan>
      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.10;1" values="0;1;1" calcMode="discrete"/>
    </text>
    <text x="20" y="110" fill="#e3b341" opacity="0">
      <tspan>{s1_stat}</tspan>
      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.16;1" values="0;1;1" calcMode="discrete"/>
    </text>
{sep(127, "0.20")}
{txt(147, l1[0], c1[0], "0.24")}
{txt(165, l1[1], c1[1], "0.28")}
{txt(183, l1[2], c1[2], "0.32")}
{sep(200, "0.36")}
{txt(220, s1_sum, "#f85149", "0.40")}
  </g>

  <!-- SCENE 2 -->
  <g opacity="0">
    <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
      keyTimes="0;0.49;0.50;0.93;1" values="0;0;1;1;0" calcMode="linear"/>
    <text x="20" y="66" fill="#58a6ff">$ claude</text>
    <text x="20" y="88" fill="#c9d1d9" opacity="0">
      <tspan>{s2_cmd}</tspan>
      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.54;1" values="0;1;1" calcMode="discrete"/>
    </text>
    <text x="20" y="110" fill="#484f58" opacity="0">
      <tspan>{s2_stat}</tspan>
      <animate attributeName="opacity" dur="18s" repeatCount="indefinite"
        keyTimes="0;0.58;1" values="0;1;1" calcMode="discrete"/>
    </text>
{sep(127, "0.61")}
{txt(147, l2[0], "#3fb950", "0.64")}
{txt(165, l2[1], "#3fb950", "0.68")}
{txt(183, l2[2], "#3fb950", "0.72")}
{sep(200, "0.76")}
{txt(220, s2_sum, "#3fb950", "0.80")}
  </g>

  <text x="680" y="282" text-anchor="end" font-size="10" fill="#21262d">{sn}</text>
</svg>'''


def generate_post(topic: str, history: list) -> str:
    if topic.startswith(SKILL_PREFIX):
        parts = topic[len(SKILL_PREFIX):].split("|", 3)
        skill = {
            "name": parts[0],
            "url": parts[1],
            "title": parts[2] if len(parts) > 2 else parts[0],
            "description": parts[3] if len(parts) > 3 else ""
        }
        return generate_skill_post(skill)

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
            sources_context = "\n\nFacts and sources available (cite inline in parentheses when used):\n"
            for s in sources:
                name = s["url"].split("/")[2].replace("www.", "").split(".")[0].capitalize()
                sources_context += f"- [{name}] {s['title']}: {s['body']}\n"

    today = datetime.now().strftime("%A %d %B %Y")

    format_instruction = ""
    if is_news:
        format_instruction = """
Use the "news analysis" format MANDATORY:
1. Main fact + key number as hook
2. "The twist?" — the unexpected angle most people missed
3. 2-3 bullet macro thesis (what this really says about the industry)
4. Memorable closing punchline: smart humor or an absurd-but-realistic projection
NO CTA. Length: 300-420 words. Cite sources inline: (Reuters), (Bloomberg), (TechCrunch), etc."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1400,
        temperature=0.9,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Today is {today}.
Generate a LinkedIn post about: {topic}

Recent posts (do not repeat these angles):
{recent}
{sources_context}
{format_instruction}

Output only the post text, ready to publish."""
        }]
    )
    return message.content[0].text


def publish_to_linkedin(post_text: str, image_path: Path | None = None) -> bool:
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    urn   = os.getenv("LINKEDIN_PERSON_URN")

    asset_urn = None
    if image_path and image_path.exists():
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        asset_urn = upload_image_to_linkedin(image_path.read_bytes(), mime, token, urn)
        if asset_urn:
            print(f"✓ Image uploaded: {image_path.name}")
        else:
            print("⚠ Image upload failed — posting without image")

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
        json={
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": media},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }
    )
    return r.status_code == 201


QUEUE_FILE = Path("queue.md")
PENDING_FILE = Path("pending.md")


def pop_queue() -> str | None:
    """Returns the first draft from queue.md and removes it from the file."""
    if not QUEUE_FILE.exists():
        return None
    content = QUEUE_FILE.read_text(encoding="utf-8")
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

    # If posts are queued, take the first one
    draft = pop_queue()
    if draft:
        topic = "queued_post"
        print(f"[{datetime.now()}] Queued post found, sending to Claude...")

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            temperature=0.85,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""Here is a draft or idea for a LinkedIn post I pre-wrote:

---
{draft}
---

Develop and rewrite it following ALL prompt rules (no em dash, no clichés, LinkedIn format, well-placed emojis, punchy hook).
If it's just an idea or a few words, develop it into a full LinkedIn post.
Keep the tone, key ideas, and any CTA if present.
Output only the final post text, ready to publish."""
            }]
        )
        post = message.content[0].text
        print(f"\n--- POST REWRITTEN BY CLAUDE ---\n{post}\n---")

        success = publish_to_linkedin(post)
        if success:
            save_to_history(post, topic)
            print("✓ Published to LinkedIn — queue updated")
        else:
            print("✗ Publication failed — queue.md entry preserved for retry")
        return

    topic = pick_topic(history)
    print(f"[{datetime.now()}] Generating post on: {topic[:80]}...")

    post = generate_post(topic, history)
    print(f"\n--- GENERATED POST ---\n{post}\n---")

    # News-based posts are held for manual review — a news story can be false
    # or unverified. Publish manually with: python post_now.py --from-pending
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
        print(f"\n⚠ News-based post — publication suspended.")
        print(f"  Verify the facts, then publish with: python post_now.py --from-pending")
        return

    # If it's a skill topic, also generate the INSTALL guide + demo SVG + PNG for LinkedIn
    image_path = None
    if topic.startswith(SKILL_PREFIX):
        parts = topic[len(SKILL_PREFIX):].split("|", 3)
        skill = {
            "name": parts[0],
            "url": parts[1],
            "title": parts[2] if len(parts) > 2 else parts[0],
            "description": parts[3] if len(parts) > 3 else ""
        }
        SKILLS_DIR.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", skill["name"])
        install_path = SKILLS_DIR / f"INSTALL_{safe_name}.md"
        guide = generate_install_guide(skill)
        install_path.write_text(guide, encoding="utf-8")
        print(f"✓ Install guide generated: {install_path}")

        scenarios = get_skill_svg_scenarios(skill)
        if scenarios:
            svg_content = generate_skill_svg(skill, scenarios)
            svg_path = SKILLS_DIR / f"demo-{safe_name}.svg"
            svg_path.write_text(svg_content, encoding="utf-8")
            print(f"✓ Demo SVG generated: {svg_path}")
            image_path = svg_to_png(svg_path)
            if image_path:
                print(f"✓ PNG for LinkedIn: {image_path.name}")

    success = publish_to_linkedin(post, image_path)
    if success:
        save_to_history(post, topic)
        print("✓ Published to LinkedIn")
    else:
        print("✗ Publication failed")


if __name__ == "__main__":
    run()
