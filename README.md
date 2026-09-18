# linkedin-agent

<p align="center">
  <img src="assets/demo.svg" alt="linkedin-agent demo" width="700"/>
</p>

I got tired of the "I should post more" guilt loop. So I automated it.

Twice a week, this script picks a topic, calls Claude, and either posts to LinkedIn directly or sends it to Discord for your approval. No UI, no brain required. Set it up once, manage it from your phone.

Costs roughly $2-3/year to run.

---

## Real results

This isn't a theoretical pitch. Numbers below are from the account this agent was actually built for, running unattended for several months.

| | |
|---|---|
| Typical baseline before tuning the format | 100-300 impressions/post |
| Best single post (a product announcement, unusually lucky topic) | 109,477 impressions · 650 likes · 50 reposts · 86 comments |
| A repeatable good outcome once the personal/opinion format was dialed in | 9,204 impressions · 9 comments, single post, zero paid promotion |
| Current baseline target after the fixes in this repo | 2,000-3,000 impressions/post |

Two mechanics moved the needle the most, both already built into `agent.py`:

1. **Alternating between news commentary and personal/opinion posts.** A "news analysis" post
   makes you a commentator on someone else's event. A personal/opinion post, especially one
   anchored to a real client or project, makes you the one with the experience. The second
   gets far more comments, and comments are what carries a post beyond your own network.
2. **Ending every post on a concrete, specific, easy-to-answer question.** Not "what do you
   think?" (too vague, ignored). A question about the reader's own stack, team, or choices.
   Posts that skip this consistently get zero comments regardless of writing quality.

Don't expect the 109k outlier every time; that one benefited from a topic that was unusually
timely. Expect the alternation and the closing question to reliably move you off a 150-impression
floor, if you post consistently and reply to comments fast (see [Notes](#notes)).

---

## How it works

Each run follows two tiers, in order, alternating with the previous run so neither one
monopolizes your feed:

**1. Real news from this week**
Searches DuckDuckGo News for an actual cybersecurity or gaming incident from the past 7 days. Generic explainers and off-topic results (sports, politics) are filtered out automatically. If a real incident is found, the post uses the "news analysis" format: main fact + key number → unexpected twist → macro thesis → memorable punchline → a closing question about the reader's own situation. The OG image from the source article is fetched automatically.

**News posts are never auto-published.** They go to `pending.md` + Discord for manual review. One click to publish, rewrite, change topic, or discard.

**2. Static topic list (personal/opinion angle)**
Picks from your curated topic list, avoiding the last 5 used. This is where named clients, opinions, and career stories live, and it's the format that tends to reach further than news commentary or product posts. See [Real results](#real-results) above.

If you'd rather write a specific idea yourself, drop it in `queue.md` and it takes priority over both tiers. See [Pre-writing posts](INSTALL.md#pre-writing-posts) in the install guide.

---

## Discord approval flow

The Discord bot watches `pending.md` every 30 seconds. When a news post is queued, it sends a full embed to your channel with 4 action buttons:

| Button | Action |
|--------|--------|
| ✅ Publish | Posts to LinkedIn (with the link in a first comment, not the post body), saves to history, cleans up |
| 🔄 Rewrite | Regenerates the post on the same topic, updates the embed |
| 🔁 New topic | Discards current post, generates a completely different one |
| 🗑️ Discard | Deletes `pending.md` without publishing |

The same bot also drafts replies to comments you receive: paste a comment (text or screenshot) directly in the channel and it answers with 3 options in your voice, ready to copy and post yourself.

---

## Quick start

Full step-by-step setup, including the LinkedIn app, OAuth token, Discord bot, `.env`, and cron job, lives in **[INSTALL.md](INSTALL.md)**.

The short version:

```bash
git clone https://github.com/Joopinhontas/linkedin-agent.git
cd linkedin-agent
pip install -r requirements.txt
cp .env.example .env
python oauth_helper.py        # follow INSTALL.md first to get your LinkedIn app credentials
```

Then edit `prompts.py` (this is the step that actually matters, see INSTALL.md), fill in `.env`, and schedule `agent.py` with cron.

---

## Project structure

```
linkedin-agent/
├── agent.py          # main logic: topic selection, generation, publishing
├── prompts.py        # system prompt and topics list, edit these
├── discord_bot.py    # Discord bot: pending post approval + comment reply drafts
├── oauth_helper.py   # one-time OAuth flow to get your access token
├── post_now.py       # manual post or publish from pending.md
├── queue.md          # optional: pre-written posts or ideas (gitignored)
├── pending.md        # news post waiting for approval (gitignored)
├── .env.example      # env template
├── history.json      # post history (auto-created, gitignored)
├── INSTALL.md         # full setup guide
├── CHANGELOG.md       # version history
└── requirements.txt
```

---

## Notes

- **The format fixes in this repo don't replace showing up.** Reply to comments within 15-20 minutes of posting: LinkedIn tests a post on a small batch first and decides whether to push it further based on early engagement. A great closing question nobody sees in time still gets zero replies.
- `history.json` is gitignored. Don't delete it, it's how the agent avoids repeating itself and how the news/opinion alternation knows what ran last.
- The model is `claude-opus-4-5`. You can swap it for `claude-haiku-4-5` to cut costs, though quality will drop noticeably.
- DuckDuckGo source search is best-effort. If it fails, the post generates without sources.
- Posts are in whatever language you set in your system prompt. The defaults are English but the agent writes in French, Spanish, or anything else if you tell it to.
- If a queued post fails to publish, the entry is preserved in `queue.md` for the next run.
- If `pending.md` already exists when the agent runs, it skips generation to avoid overwriting a post awaiting approval, and to avoid a wasted API call.

---

## Requirements

- Python 3.10+
- A LinkedIn account with a developer app (free)
- An Anthropic API key (~$2-3/year in usage)
- A Discord bot token (free), optional, for the approval flow and comment drafting

## License

See [LICENSE](LICENSE).
