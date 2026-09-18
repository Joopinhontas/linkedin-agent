# post_now.py — post on demand with a custom topic, or approve a pending news post
#
# Usage:
#   python post_now.py "your topic here"
#   python post_now.py --from-pending
import sys
from pathlib import Path
from agent import generate_post, publish_to_linkedin, load_history, save_to_history

PENDING_FILE = Path("pending.md")


def post_from_pending():
    if not PENDING_FILE.exists():
        print("No pending post found (pending.md not found).")
        return

    content = PENDING_FILE.read_text(encoding="utf-8")
    parts = content.split("---\n\n", 1)
    header = parts[0].strip()
    post = parts[1].strip() if len(parts) > 1 else content.strip()

    topic = ""
    image_name = ""
    for line in header.splitlines():
        if line.startswith("TOPIC:"):
            topic = line.replace("TOPIC:", "").strip()
        if line.startswith("IMAGE:"):
            image_name = line.replace("IMAGE:", "").strip()

    image_path = None
    if image_name:
        candidate = PENDING_FILE.parent / image_name
        if candidate.exists():
            image_path = candidate
            print(f"✓ Image found: {candidate}")

    print(f"\nSource: {topic[:120]}")
    print(f"\n--- PENDING POST ---\n{post}\n---")

    confirm = input("\nPublish this post? (y/n): ")
    if confirm.lower() == "y":
        success = publish_to_linkedin(post, image_path)
        if success:
            save_to_history(post, topic)
            PENDING_FILE.unlink()
            if image_path and image_path.exists():
                image_path.unlink()
            print("✓ Published to LinkedIn, pending.md removed")
        else:
            print("✗ Publication failed, pending.md preserved")
    else:
        discard = input("Discard the pending post? (y/n): ")
        if discard.lower() == "y":
            PENDING_FILE.unlink()
            if image_path and image_path.exists():
                image_path.unlink()
            print("Post discarded.")
        else:
            print("Post kept in pending.md.")


if __name__ == "__main__":
    if "--from-pending" in sys.argv:
        post_from_pending()
    else:
        topic = " ".join(a for a in sys.argv[1:] if not a.startswith("--"))
        if not topic:
            print("Usage:")
            print("  python post_now.py 'your topic here'")
            print("  python post_now.py --from-pending")
            sys.exit(1)

        history = load_history()
        post = generate_post(topic, history)
        print(f"\n--- GENERATED POST ---\n{post}\n---")

        confirm = input("\nPublish? (y/n): ")
        if confirm.lower() == "y":
            success = publish_to_linkedin(post)
            if success:
                save_to_history(post, topic)
                print("✓ Published to LinkedIn")
            else:
                print("✗ Publication failed")
