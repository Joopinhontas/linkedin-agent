# linkedin-agent

<p align="center">
  <img src="assets/demo.svg" alt="linkedin-agent demo" width="700"/>
</p>

I got tired of the "I should post more" guilt loop. So I automated it.

Every Monday at 9am, this script picks a topic, calls Claude, and either posts to LinkedIn directly or sends it to Discord for your approval. No UI, no brain required. Set it up once, manage it from your phone.

Costs roughly $2-3/year to run.

---

## How it works

Each run follows three tiers, in order:

**1. Trending Claude skill**
Searches GitHub for recently created Claude Code skill repos gaining stars fast. If one is found that hasn't been posted about yet, it generates a teaser post, writes a full install guide to `skills/`, renders an animated terminal demo SVG, converts it to PNG, and publishes with the image attached.

**2. Real news from this week**
Searches DuckDuckGo News for an actual cybersecurity or gaming incident from the past 7 days. Generic explainers and off-topic results (sports, politics) are filtered out automatically. If a real incident is found, the post uses the "news analysis" format: main fact + key number → unexpected twist → macro thesis → memorable punchline. The OG image from the source article is fetched automatically.

**News posts are never auto-published.** They go to `pending.md` + Discord for manual review. One click to publish, rewrite, change topic, or discard.

**3. Static topic list (fallback)**
If no news is found, picks from your curated topic list, avoiding the last 5 used.

---

## Discord approval flow

The Discord bot watches `pending.md` every 30 seconds. When a news post is queued, it sends a full embed to your channel with 4 action buttons:

| Button | Action |
|--------|--------|
| ✅ Publish | Posts to LinkedIn, saves to history, cleans up |
| 🔄 Rewrite | Regenerates the post on the same topic, updates the embed |
| 🔁 New topic | Discards current post, generates a completely different one |
| 🗑️ Discard | Deletes `pending.md` without publishing |

Skill posts publish directly (no approval needed — no fake news risk).

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/joopinhontas/linkedin-agent.git
cd linkedin-agent
pip install -r requirements.txt
```

### 2. Create a LinkedIn app

Go to the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps/new) and create a new app.

Under **Auth**:
- Add `http://localhost:8000/callback` as an authorized redirect URL
- Enable these OAuth scopes: `openid`, `profile`, `w_member_social`

Copy your **Client ID** and **Client Secret**.

### 3. Get your LinkedIn access token

```bash
cp .env.example .env
python oauth_helper.py
```

It opens a browser tab, you authorize, it prints your `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN`. Paste both into `.env`.

> Tokens expire after roughly 2 months. Just rerun `oauth_helper.py` when it stops working.

### 4. Get a Claude API key

Create an account at [console.anthropic.com](https://console.anthropic.com), generate an API key, add it to `.env`.

### 5. Set up the Discord bot (optional but recommended)

Without the bot, news posts pile up in `pending.md` and you have to publish them manually with `python post_now.py --from-pending`. With the bot, you get a message on your phone with one-click buttons.

**Create the bot:**
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → New Application → Bot
2. Copy the token → add `DISCORD_BOT_TOKEN=...` to `.env`
3. Discord Settings → Advanced → Developer Mode, then right-click your channel → Copy Channel ID → add `DISCORD_CHANNEL_ID=...` to `.env`
4. Invite URL: OAuth2 → URL Generator → scopes: `bot` → permissions: Send Messages, Embed Links, Attach Files, Use Application Commands

**Run the bot** (keep it running alongside the cron job):

```bash
python discord_bot.py
```

Or in a tmux session: `tmux new -s discord-bot` then `python discord_bot.py`.

### 6. Fill in your `.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_ACCESS_TOKEN=AQX...
LINKEDIN_PERSON_URN=urn:li:person:...

# Optional — raises GitHub API rate limit from 60 to 5000 req/hour
GITHUB_TOKEN=

# Discord bot — for pending post approval
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=

# Used in auto-generated install guides when a Claude skill is posted
AUTHOR_NAME=Your Name
AUTHOR_TITLE=Your Job Title
AUTHOR_COMPANY=Your Company
WEBSITE_URL=https://yourwebsite.com
LINKEDIN_URL=https://linkedin.com/in/yourprofile
MALT_URL=
GITHUB_URL=https://github.com/yourusername
```

### 7. Customize your system prompt

Open `prompts.py` and rewrite `SYSTEM_PROMPT`. Replace the `[PLACEHOLDERS]` with your actual information: your name, your domain, your real expertise, how you write, what you want to avoid.

This is the step that actually matters. The agent will sound like you if you describe yourself well here — and like every other AI LinkedIn account if you don't. Be specific. Mention real clients, real technologies, real opinions.

Also edit `TOPICS` to match your field. The defaults are DevOps/Cloud/Security oriented.

### 8. Set up the cron job

```bash
crontab -e
```

Add this line (adjust the path):

```
0 9 * * 1 cd /path/to/linkedin-agent && /usr/bin/python3 agent.py >> agent.log 2>&1
```

Every Monday at 9am. [crontab.guru](https://crontab.guru) helps with the schedule syntax.

---

## Manual post

To post immediately on a specific topic:

```bash
python post_now.py "zero trust architecture in practice"
```

To publish a post currently waiting in `pending.md`:

```bash
python post_now.py --from-pending
```

---

## Pre-writing posts

Create a `queue.md` file with your ideas or drafts, separated by `---`:

```
Rockstar Games hack, security angle for AAA studios

---

Zero trust isn't a product, it's a decision. Here's what it looked like in practice at a client with 2000 endpoints...

---

Why I stopped using Kubernetes for small teams
```

Each Monday, the agent takes the first entry, sends it through Claude (applying all your prompt rules), and publishes it. Rough ideas and full drafts both work.

---

## Project structure

```
linkedin-agent/
├── agent.py          # main logic: topic selection, generation, publishing
├── prompts.py        # system prompt and topics list — edit these
├── discord_bot.py    # Discord bot for pending post approval (4 action buttons)
├── oauth_helper.py   # one-time OAuth flow to get your access token
├── post_now.py       # manual post or publish from pending.md
├── queue.md          # optional: pre-written posts or ideas (gitignored)
├── pending.md        # news post waiting for approval (gitignored)
├── .env.example      # env template
├── history.json      # post history (auto-created, gitignored)
├── skills/           # auto-generated install guides + demo SVGs (gitignored)
├── CHANGELOG.md      # version history
└── requirements.txt
```

---

## Notes

- `history.json` is gitignored. Don't delete it — it's how the agent avoids repeating itself.
- The model is `claude-opus-4-5`. You can swap it for `claude-haiku-4-5` to cut costs, though quality will drop noticeably.
- DuckDuckGo source search is best-effort. If it fails, the post generates without sources.
- Posts are in whatever language you set in your system prompt. The defaults are English but the agent writes in French, Spanish, or anything else if you tell it to.
- `cairosvg` is required for SVG→PNG conversion on skill posts. It needs `libcairo2` on Linux: `sudo apt install libcairo2`.
- If a queued post fails to publish, the entry is preserved in `queue.md` for the next run.
- If `pending.md` already exists when the agent runs, it skips generation to avoid overwriting a post awaiting approval.

---

## Requirements

- Python 3.10+
- A LinkedIn account with a developer app (free)
- An Anthropic API key (~$2-3/year in usage)
- A Discord bot token (free) — optional, for the approval flow
