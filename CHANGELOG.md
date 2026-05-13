# Changelog

## [2.3.0] - 2026-05-13

### Added
- **`discord_bot.py`**: standalone Discord bot for managing pending posts from Discord.
  - Watches `pending.md` every 30 seconds. When a new post is detected, sends it as a Discord embed (full text + OG image if available) with 3 action buttons.
  - **✅ Publish** — calls `publish_to_linkedin()`, saves to history, cleans up `pending.md`.
  - **🔄 Rewrite** — calls `generate_post()` with the same topic, updates `pending.md` and the Discord message in place.
  - **🗑️ Discard** — deletes `pending.md` (and OG image if present).
  - Uses persistent views: buttons survive bot restarts.
  - Requires `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` in `.env`.
- `discord.py>=2.0` and `cairosvg` added to `requirements.txt`.
- `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` added to `.env.example`.

## [2.2.0] - 2026-05-12

### Added
- **OG image for news posts**: when a news-based post is saved to `pending.md`, the agent now fetches the Open Graph image from the first source article and saves it alongside the post. `post_now.py` reads the `IMAGE:` header and attaches it when publishing.
- **Animated SVG demo for skill posts**: every skill post now auto-generates a `demo-<skillname>.svg` in the `skills/` folder — a 2-scene animated terminal showing the skill in action.
- **SVG→PNG conversion for LinkedIn**: the demo SVG is converted to a high-res PNG (scale 2×) via `cairosvg` and attached as an image when publishing the skill post.
- **`require_keywords` filter**: news results must contain at least one security-related keyword (`hack`, `breach`, `ransomware`, `cve`, `exploit`, `zero-day`, etc.) checked against the combined title and body — prevents off-topic articles from being selected.
- **Sports and off-topic `skip_keywords`**: results mentioning `nba`, `nfl`, `playoff`, `football`, `election`, etc. are now filtered out at the title level.
- **Inline source citation rules** (`prompts.py`): posts must cite sources as `(Reuters)`, `(Bloomberg)`, `(TechCrunch)` etc. inline in the prose. Block source lists at the end are explicitly banned.
- **"News analysis" post format** (`prompts.py`): mandatory structure for news posts — main fact + key number → "The twist?" → 2-3 macro thesis bullets → memorable closing punchline. No CTA. Up to 420 words.

### Changed
- `fetch_trending_topic()`: topic selection now checks `title + body` combined (not title only) against `require_keywords` before accepting a result.
- `run()`: news posts now save an `IMAGE:` header in `pending.md` with the OG image filename.
- `run()`: skill posts now pass the generated PNG to `publish_to_linkedin()` for image attachment.
- `prompts.py`: word count updated from 350 to 420 words max for the news analysis format.
- Skill posts now always generate a `demo-<slug>.svg` (and PNG) — previously optional.

### Fixed
- NBA playoff results were being selected as "ransomware" topics due to DuckDuckGo query matching. Fixed by `require_keywords` + combined body check.

## [2.1.0] - 2026-05-08

### Added
- **Post queue (`queue.md`)**: pre-write multiple posts or ideas weeks in advance. Entries are separated by `---`. Each Monday, the agent takes the first entry, rewrites it through Claude (applying all prompt rules), publishes it, and removes it from the queue. If the queue is empty, the agent generates automatically as usual.
- **Idea-to-post**: queue entries can be anything from a rough idea ("Rockstar Games hack, angle: what AAA studios should have in place") to a full draft. Claude handles the development either way.
- **Retry safety**: if publication fails, the queue entry is preserved for the next run.

## [2.0.0] - 2026-05-08

### Added
- **Trending news fetch**: agent now searches for real cybersecurity and gaming incidents from the past week (DuckDuckGo News) and uses them as the post topic when available. Generic explainer articles are filtered out automatically.
- **Claude skill discovery**: agent searches GitHub API for trending Claude Code skills (repos gaining stars fast, created in the last 60 days) and generates teaser posts for them.
- **Skill teaser posts**: when a Claude skill is selected, the post focuses on what you can DO with it (no install instructions), ending with a CTA that invites readers to comment for a free guide.
- **Auto-generated install guides**: when a skill post is created, a full `INSTALL_<skillname>.md` is generated locally in the `skills/` folder — with author intro, prerequisites, step-by-step install, and 3 concrete usage examples.
- **3-tier topic priority**: (1) trending Claude skill ~25% of runs, (2) this week's real news event, (3) static topic list fallback.
- **Company @mentions for news posts**: when the post is about a specific company incident, the agent now mentions them with @ naturally in the text.
- **Anti-cliché rules**: banned phrases that read as AI-generated ("at 3am", "game changer", "spoiler", em dash —).
- **Performance rules**: prompt rules derived from analyzing high vs low impression posts (named client anchor, counterintuitive twist, concrete numbers).
- **GITHUB_TOKEN support**: optional env var to raise GitHub API rate limit from 60 to 5000 req/hour.
- **Author branding via env vars**: install guides now pull author info (name, title, website, LinkedIn, Malt, GitHub) from `.env` instead of being hardcoded.

### Changed
- `pick_topic()` now tries trending news and skills before falling back to static list.
- `search_sources()` now handles news topics without site: restriction for better source matching.
- `generate_post()` now routes skill topics to a dedicated skill post generator.
- `run()` now generates the install guide file when a skill topic is published.
- `TOPICS` list reorganized: gaming+cyber crossover topics moved to top, generic topics moved to fallback.
- `MENTIONS` updated to include company @mention rule for news-driven posts.
- `HUMANISATION` updated with explicit cliché ban list.

### Fixed
- Year was hardcoded as "2025" in search queries — now uses `datetime.now().year` dynamically.

## [1.0.0] - 2026-04-14

### Added
- Initial release: topic selection from static list, DuckDuckGo source search, Claude generation, LinkedIn publish via API.
- `history.json` to avoid repeating recent topics.
- `oauth_helper.py` for LinkedIn OAuth flow.
- `post_now.py` for manual on-demand posts.
