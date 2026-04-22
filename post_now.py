# post_now.py — post on demand with a custom topic
#
# Usage: python post_now.py "your topic here"

import sys
from agent import generate_post, publish_to_linkedin, load_history, save_to_history

topic = " ".join(sys.argv[1:])
if not topic:
    print("Usage: python post_now.py 'your topic here'")
    exit(1)

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
