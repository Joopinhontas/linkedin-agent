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
        "best practices", "tips", "tutorial", "introduction", "overview"
    ]
    try:
        with DDGS() as ddgs:
            for query in queries:
                results = list(ddgs.news(query, max_results=5, timelimit="w"))
                for r in results:
                    title = r.get("title", "").lower()
                    if any(kw in title for kw in skip_keywords):
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
    # Priority 1 (~25% of runs): trending Claude skill from GitHub
    if random.random() < 0.25:
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
                results = list(ddgs.text(query, max_results=2))
            else:
                results = list(ddgs.text(
                    topic + " site:kubernetes.io OR site:cve.mitre.org OR site:thehackernews.com OR site:blog.gitguardian.com OR site:grafana.com OR site:cloud.google.com OR site:docs.microsoft.com OR site:securityweek.com",
                    max_results=2
                ))
            sources = []
            for r in results:
                sources.append({"title": r.get("title", ""), "url": r.get("href", "")})
            return sources
    except Exception as e:
        print(f"Source search failed: {e}")
        return []


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
    needs_sources = topic.startswith("this week's news") or any(kw.lower() in topic.lower() for kw in topics_with_sources)

    sources_block = ""
    if needs_sources:
        sources = search_sources(topic)
        if sources:
            sources_block = "\n\nFurther reading:\n"
            for s in sources:
                sources_block += f"-> {s['title']}: {s['url']}\n"

    today = datetime.now().strftime("%A %d %B %Y")

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        temperature=0.9,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Today is {today}.
Generate a LinkedIn post about: {topic}

Recent posts (do not repeat these angles):
{recent}

{f"At the end of the post, append this block exactly as-is: {sources_block}" if sources_block else ""}

Output only the post text, ready to publish."""
        }]
    )
    return message.content[0].text


def publish_to_linkedin(post_text: str) -> bool:
    token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    urn = os.getenv("LINKEDIN_PERSON_URN")

    payload = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": post_text},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }

    r = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        },
        json=payload
    )
    return r.status_code == 201


QUEUE_FILE = Path("queue.md")


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

    # If it's a skill topic, also generate the INSTALL guide
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

    success = publish_to_linkedin(post)
    if success:
        save_to_history(post, topic)
        print("✓ Published to LinkedIn")
    else:
        print("✗ Publication failed")


if __name__ == "__main__":
    run()
