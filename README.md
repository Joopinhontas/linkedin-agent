# linkedin-agent

<p align="center">
  <img src="assets/demo.svg" alt="linkedin-agent demo" width="700"/>
</p>

I got tired of the "I should post more" guilt loop. So I automated it.

Every Monday at 9am, this script picks a topic, calls Claude, and posts to LinkedIn. No UI, no queue management, no brain required. You set it up once and forget it exists — until someone comments on your post.

Costs roughly $2-3/year to run.

---

## How it works

Each run follows three tiers, in order:

**1. Trending Claude skill (~25% of runs)**
Searches GitHub for recently created Claude Code skill repos gaining stars fast. If one is found that hasn't been posted about yet, it generates a teaser post and writes a full install guide to `skills/`.

**2. Real news from this week**
Searches DuckDuckGo News for an actual cybersecurity or gaming incident from the past 7 days. Generic "what is ransomware" explainer articles are filtered out automatically. If a real incident is found, it uses that.

**3. Static topic list (fallback)**
If no news is found, it picks from your curated topic list, avoiding the last 5 topics used.

Then, regardless of the tier:

4. For technical or news topics, pulls 2 fresh sources via DuckDuckGo
5. Sends everything to Claude with your system prompt
6. Posts to LinkedIn
7. Saves to `history.json`

There's also a **post queue**: drop ideas or full drafts in `queue.md`, separated by `---`. The agent takes the first one each Monday, rewrites it through Claude (so your writing rules apply), publishes it, and removes it. Useful for pre-writing several weeks ahead, or just storing rough ideas like "Rockstar Games hack, security angle."

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

### 3. Get your access token

```bash
cp .env.example .env
python oauth_helper.py
```

It opens a browser tab, you authorize, it prints your `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN`. Paste both into `.env`.

> Tokens expire after roughly 2 months. Just rerun `oauth_helper.py` when it stops working.

### 4. Get a Claude API key

Create an account at [console.anthropic.com](https://console.anthropic.com), generate an API key, add it to `.env`.

### 5. Fill in your `.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_ACCESS_TOKEN=AQX...
LINKEDIN_PERSON_URN=urn:li:person:...

# Optional — raises GitHub API rate limit from 60 to 5000 req/hour
GITHUB_TOKEN=

# Used in auto-generated install guides when a Claude skill is posted
AUTHOR_NAME=Your Name
AUTHOR_TITLE=Your Job Title
AUTHOR_COMPANY=Your Company
WEBSITE_URL=https://yourwebsite.com
LINKEDIN_URL=https://linkedin.com/in/yourprofile
MALT_URL=
GITHUB_URL=https://github.com/yourusername
```

### 6. Customize your system prompt

Open `prompts.py` and rewrite `SYSTEM_PROMPT`. Replace the `[PLACEHOLDERS]` with your actual information: your name, your domain, your real expertise, how you write, what you want to avoid.

This is the step that actually matters. The agent will sound like you if you describe yourself well here — and like every other AI LinkedIn account if you don't. Be specific. Mention real clients, real technologies, real opinions.

Also edit `TOPICS` to match your field. The defaults are DevOps/Cloud/Security oriented.

### 7. Set up the cron job

```bash
crontab -e
```

Add this line (adjust the path):

```
0 9 * * 1 cd /path/to/linkedin-agent && /usr/bin/python3 agent.py >> agent.log 2>&1
```

Every Monday at 9am. Change `* * 1` to any schedule you want. [crontab.guru](https://crontab.guru) helps.

---

## Manual post

To post immediately on a specific topic:

```bash
python post_now.py "zero trust architecture in practice"
```

It generates the post and asks for confirmation before publishing.

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
├── oauth_helper.py   # one-time OAuth flow to get your access token
├── post_now.py       # manual post on demand
├── queue.md          # optional: pre-written posts or ideas (gitignored)
├── .env.example      # env template
├── history.json      # post history (auto-created, gitignored)
├── skills/           # auto-generated install guides (gitignored)
├── CHANGELOG.md      # version history
└── requirements.txt
```

---

## Notes

- `history.json` is gitignored. Don't delete it — it's how the agent avoids repeating itself.
- The model is `claude-opus-4-5`. You can swap it for `claude-haiku-4-5` to cut costs, though quality will drop noticeably.
- DuckDuckGo source search is best-effort. If it fails, the post generates without sources.
- Posts are in whatever language you set in your system prompt. The default topics are in English but the agent will write in French, Spanish, or anything else if you tell it to.
- If a queued post fails to publish, the entry is preserved in `queue.md` for the next run.

---

## Requirements

- Python 3.9+
- A LinkedIn account with a developer app (free)
- An Anthropic API key (~$2-3/year in usage)
