# Install guide

Full setup, start to finish. Budget 20-30 minutes, most of it waiting on LinkedIn's app review screens.

## 1. Clone and install

```bash
git clone https://github.com/Joopinhontas/linkedin-agent.git
cd linkedin-agent
pip install -r requirements.txt
```

Python 3.10 or newer required.

## 2. Create a LinkedIn app

Go to the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps/new) and create a new app.

Under **Auth**:
- Add `http://localhost:8000/callback` as an authorized redirect URL
- Enable these OAuth scopes: `openid`, `profile`, `w_member_social`

Copy your **Client ID** and **Client Secret**, you'll need them in step 6.

> If port 8000 is already used by something else on your machine, pick a different port
> consistently in both the LinkedIn app's redirect URL and `oauth_helper.py`.

## 3. Get your LinkedIn access token

```bash
cp .env.example .env
```

Open `.env` and fill in `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` from step 2. Then:

```bash
python oauth_helper.py
```

It opens a browser tab, you authorize, it prints your `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN`. Paste both into `.env`.

> Tokens expire after roughly 2 months. When publishing starts failing with an
> `EXPIRED_ACCESS_TOKEN` error, just rerun `oauth_helper.py` and update `.env`.

## 4. Get a Claude API key

Create an account at [console.anthropic.com](https://console.anthropic.com), generate an API key, add it to `.env` as `ANTHROPIC_API_KEY`.

## 5. Set up the Discord bot (optional but recommended)

Without the bot, news posts pile up in `pending.md` and you have to publish them manually with `python post_now.py --from-pending`. With the bot, you get a message on your phone with one-click buttons, and you can paste comments you receive to get reply drafts.

**Create the bot:**
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → New Application → Bot
2. Copy the token → add `DISCORD_BOT_TOKEN=...` to `.env`
3. Discord Settings → Advanced → Developer Mode, then right-click your channel → Copy Channel ID → add `DISCORD_CHANNEL_ID=...` to `.env`
4. Bot → Privileged Gateway Intents → enable **Message Content Intent** (needed to read comments you paste in the channel; the bot still works for post approval without it)
5. Invite URL: OAuth2 → URL Generator → scopes: `bot` → permissions: Send Messages, Embed Links, Attach Files, Use Application Commands

**Run the bot** (keep it running alongside the cron job):

```bash
python discord_bot.py
```

Or in a tmux session: `tmux new -s discord-bot` then `python discord_bot.py`.

**Keep it running across reboots and crashes.** A simple approach: a cron entry that checks
every few minutes and restarts the bot if it's not running.

```bash
#!/bin/bash
# bot_watchdog.sh
cd /path/to/linkedin-agent || exit 1
pgrep -f "python3 discord_bot.py" >/dev/null || nohup python3 discord_bot.py >> discord_bot.log 2>&1 &
```

```
@reboot sleep 30 && /path/to/linkedin-agent/bot_watchdog.sh
*/5 * * * * /path/to/linkedin-agent/bot_watchdog.sh
```

If you'd rather use a proper service manager, a `systemd --user` unit with `Restart=always`
works too, but requires `loginctl enable-linger` on most distros to survive logout, which
usually needs `sudo` once.

## 6. Fill in your `.env`

```env
ANTHROPIC_API_KEY=sk-ant-...
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_ACCESS_TOKEN=AQX...
LINKEDIN_PERSON_URN=urn:li:person:...

# Discord bot, for pending post approval and comment reply drafts
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=
```

## 7. Customize your system prompt

Open `prompts.py` and rewrite `SYSTEM_PROMPT`. Replace every `[PLACEHOLDER]` with your actual information: your name, your domain, your real expertise, how you write, what you want to avoid.

**This is the step that actually matters.** The agent will sound like you if you describe yourself well here, and like every other AI LinkedIn account if you don't. Be specific. Mention real clients, real technologies, real opinions. Never let it invent a client, a number, or an incident you didn't actually experience: the `PERFORMANCE` rules already tell it to stick to real anchors, but the raw material has to come from you.

Also edit `TOPICS`: aim for 30-50 entries, mixing evergreen technical topics with personal/opinion angles and named real clients or projects. The defaults are DevOps/Cloud/Security oriented, replace or extend them to match your field. See [Real results](README.md#real-results) in the README for why the personal/opinion entries matter as much as the technical ones.

Also update `COMMENT_SYSTEM_PROMPT` in `discord_bot.py` the same way if you plan to use the comment-drafting feature: it needs your identity and a real reply you once wrote, to calibrate your actual tone.

## 8. Set up the cron job

```bash
crontab -e
```

Add these two lines (adjust the path), one for each weekly slot:

```
0 9 * * 1 cd /path/to/linkedin-agent && /usr/bin/python3 agent.py >> agent.log 2>&1
0 10 * * 3 cd /path/to/linkedin-agent && /usr/bin/python3 agent.py >> agent.log 2>&1
```

Monday 9am and Wednesday 10am, both running the same script: the news/opinion alternation in `pick_topic()` takes care of not repeating the same format twice in a row. [crontab.guru](https://crontab.guru) helps with the schedule syntax if you want a different cadence.

## Manual post

To post immediately on a specific topic:

```bash
python post_now.py "zero trust architecture in practice"
```

To publish a post currently waiting in `pending.md`:

```bash
python post_now.py --from-pending
```

## Pre-writing posts

Create a `queue.md` file with your ideas or drafts, separated by `---`:

```
Studio hack, security angle for AAA teams

---

Zero trust isn't a product, it's a decision. Here's what it looked like in practice at a client with 2000 endpoints...

---

Why I stopped using Kubernetes for small teams
```

Each run, the agent takes the first entry, sends it through Claude (applying all your prompt rules), and publishes it directly (no approval step, since you wrote it yourself). Rough ideas and full drafts both work. If publishing fails, the entry is preserved in `queue.md` for the next run.

## Troubleshooting

- **`EXPIRED_ACCESS_TOKEN` on publish**: rerun `oauth_helper.py` (step 3) and update `.env`, then restart `discord_bot.py` so it picks up the new token.
- **Image missing from a published post**: check `agent.log` or `discord_bot.log` for `Image upload failed` or `OG image too large`. Images over 8 MB are skipped automatically; anything else is usually a transient LinkedIn API error, safe to retry.
- **Discord bot not sending anything for a pending post**: confirm the bot process is actually running (`pgrep -f discord_bot.py`) and that `DISCORD_CHANNEL_ID` matches the channel you're watching.
- **`PrivilegedIntentsRequired` on bot startup**: enable "Message Content Intent" in the Developer Portal (step 5.4). The bot falls back to approval-only mode automatically if you skip this, so it isn't fatal, just less useful.
