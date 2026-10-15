# publish_scheduled.py: publishes scheduled_post.md (a post you approved in advance), then retires it.
# File format: "TOPIC: ...", "HOOK: ...", a blank line, "---", a blank line, then the post text.
# Meant for a one-off cron entry tagged "# scheduled-post", which removes itself after a successful run:
#   8 8 14 10 * cd /path/to/linkedin-agent && python publish_scheduled.py >> agent.log 2>&1 # scheduled-post
import json
import subprocess
from datetime import datetime
from pathlib import Path

from agent import publish_to_linkedin, save_to_history, PUBLISHED_NOTICE

SCHEDULED = Path(__file__).parent / "scheduled_post.md"


def remove_cron_entry():
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    kept = "\n".join(l for l in current.splitlines() if "# scheduled-post" not in l) + "\n"
    subprocess.run(["crontab", "-"], input=kept, text=True, check=True)


def main():
    if not SCHEDULED.exists():
        print("No scheduled post.")
        remove_cron_entry()
        return
    header, post = SCHEDULED.read_text(encoding="utf-8").split("---\n\n", 1)
    meta = dict(l.split(": ", 1) for l in header.strip().splitlines() if ": " in l)
    post = post.strip()
    if publish_to_linkedin(post):
        PUBLISHED_NOTICE.write_text(json.dumps({"at": datetime.now().isoformat(), "first": post.splitlines()[0]}),
                                    encoding="utf-8")
        save_to_history(post, meta.get("TOPIC", "scheduled_post"), meta.get("HOOK"))
        SCHEDULED.rename(SCHEDULED.with_name(f"scheduled_post.published-{datetime.now():%Y%m%d}.md"))
        print("✓ Scheduled post published to LinkedIn")
        remove_cron_entry()
    else:
        print("✗ Publication failed: scheduled_post.md and the cron entry are kept for a retry")


if __name__ == "__main__":
    main()
