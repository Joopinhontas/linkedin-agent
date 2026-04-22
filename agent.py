import anthropic
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from ddgs import DDGS
import os
import random

from prompts import SYSTEM_PROMPT, TOPICS

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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

def pick_topic(history: list) -> str:
    used_recently = [h["topic"] for h in history[-5:]]
    available = [t for t in TOPICS if t not in used_recently]
    if not available:
        last = history[-1]["topic"] if history else None
        available = [t for t in TOPICS if t != last]
    return random.choice(available)

def search_sources(topic: str) -> list:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                topic + " site:kubernetes.io OR site:cve.mitre.org OR site:thehackernews.com OR site:blog.gitguardian.com OR site:grafana.com OR site:cloud.google.com OR site:docs.microsoft.com OR site:securityweek.com",
                max_results=2
            ))
            sources = []
            for r in results:
                sources.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", "")
                })
            return sources
    except Exception as e:
        print(f"Source search failed: {e}")
        return []

def generate_post(topic: str, history: list) -> str:
    recent = "\n".join([f"- {h['post'][:80]}..." for h in history[-3:]]) or "None"

    topics_with_sources = [
        "CVE", "ransomware", "pipeline", "CI/CD", "Kubernetes", "Docker",
        "Terraform", "Ansible", "observability", "Grafana", "security",
        "cloud", "backup", "secret", "RBAC", "ArgoCD", "IaC", "monitoring"
    ]
    needs_sources = any(kw.lower() in topic.lower() for kw in topics_with_sources)

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

def run():
    history = load_history()
    topic = pick_topic(history)
    print(f"[{datetime.now()}] Generating post on: {topic}")

    post = generate_post(topic, history)
    print(f"\n--- GENERATED POST ---\n{post}\n---")

    success = publish_to_linkedin(post)
    if success:
        save_to_history(post, topic)
        print("✓ Published to LinkedIn")
    else:
        print("✗ Publication failed")

if __name__ == "__main__":
    run()
