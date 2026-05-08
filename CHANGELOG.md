# Changelog

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
