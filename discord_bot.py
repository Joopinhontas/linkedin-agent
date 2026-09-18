"""
Discord bot for validating LinkedIn posts held in pending.md, and for drafting
replies to comments on your posts.

Run: python discord_bot.py
Watches pending.md and sends a message with 4 action buttons whenever a new post
is queued. Also: paste a comment you received on LinkedIn (text or screenshot)
directly in the channel, and the bot replies with 3 draft answers in your voice.

Setup (one time):
  1. https://discord.com/developers/applications -> New Application -> Bot
  2. Copy the token -> add DISCORD_BOT_TOKEN=... to .env
  3. Discord Settings -> Advanced -> Developer Mode
     Right-click your channel -> Copy Channel ID -> add DISCORD_CHANNEL_ID=... to .env
  4. Bot -> Privileged Gateway Intents -> enable "Message Content Intent"
     (needed to read comments pasted in the channel; without it the bot still
     works for post validation, just not comment drafting)
  5. Invite the bot: OAuth2 -> URL Generator -> scopes: bot
     Permissions: Send Messages, Embed Links, Attach Files, Use Application Commands
"""
import asyncio
import functools
import os
from pathlib import Path

import discord
from discord import ui
from dotenv import load_dotenv

load_dotenv()

PENDING_FILE = Path("pending.md")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
POLL_INTERVAL = 30  # seconds


# ---------------------------------------------------------------------------
# pending.md helpers
# ---------------------------------------------------------------------------

def parse_pending():
    """Reads pending.md, returns (topic, image_path | None, post_text) or None."""
    if not PENDING_FILE.exists():
        return None
    content = PENDING_FILE.read_text(encoding="utf-8")
    parts = content.split("---\n\n", 1)
    header = parts[0].strip()
    post_text = parts[1].strip() if len(parts) > 1 else content.strip()
    topic, image_name = "", ""
    for line in header.splitlines():
        if line.startswith("TOPIC:"):
            topic = line.replace("TOPIC:", "").strip()
        if line.startswith("IMAGE:"):
            image_name = line.replace("IMAGE:", "").strip()
    image_path = None
    if image_name:
        c = PENDING_FILE.parent / image_name
        if c.exists():
            image_path = c
    return topic, image_path, post_text


def save_pending(topic: str, image_path, post_text: str):
    image_name = image_path.name if image_path else ""
    PENDING_FILE.write_text(
        f"TOPIC: {topic}\nIMAGE: {image_name}\n\n---\n\n{post_text}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Comment reply drafting
#
# Paste a comment you got on LinkedIn in the Discord channel, the bot answers
# with 3 draft replies in your voice. You still pick one and post it yourself:
# this is a drafting aid, not an auto-reply bot.
# ---------------------------------------------------------------------------

COMMENT_SYSTEM_PROMPT = """You are [YOUR FULL NAME], [YOUR JOB TITLE] at [YOUR COMPANY / freelance].
[Optional: one line of real background that makes your voice recognizable, e.g. "10 years in
critical IT environments (Client A, Client B)." or a personal detail you're comfortable using
publicly.]

You reply to comments received under your LinkedIn posts. Goal: replies indistinguishable from
a busy, real, approachable expert. Never robotic, never a customer-support tone.

YOUR TONE REFERENCE: replace this with a short reply you actually wrote once, that sounds
unmistakably like you (casual, a little imperfect, alive). Every reply below should be able
to sit next to it without clashing. Example placeholder:
"Ha, it's not! Been replying to comments for the last hour and still haven't had time for coffee :)"

HUMANIZER RULES, ABSOLUTE: breaking any of these reads as AI-generated instantly.
- Default: 1 to 2 sentences. A 5-word reply is often the best one.
  A precise technical question: 3 sentences max, about 40 words. NEVER more.
- Answer ONE point of the comment, the most interesting one. A human never covers every
  point raised. Ignoring part of a comment is human, not lazy.
- NEVER validate-then-restate as an opener: "You raise a great point about...", "That's a fair
  concern", "Good question" are all banned. If they're right, concede in 3 words: "Yeah, exact.",
  "True.", "Fair point there."
- NEVER a list, numbered or not. NEVER bullet structure. A comment reply is one flow of text.
- NEVER a closing thank-you ("Thanks for this insight", "Appreciate the feedback").
- NEVER a summary sentence ("The key is finding the right balance between...", "It's all about
  the tradeoffs"): end sharp, on substance, or on a light joke.
- NEVER an em dash, NEVER an en dash, NEVER markdown, NEVER a hashtag.
- Also banned: "Great question", "Excellent point", "Exactly this", "Feel free to", "Happy to",
  "You raise", "Good catch" as an opener, any three-item list.
- Don't name your own product/company in every reply: speak like an engineer, not a brand.
  Generic terms ("the engine", "the pipeline", "on my end") are enough. Only give the link if
  someone explicitly asks where to see it.
- Imperfections welcome: start with "Yeah", "Nah", "So", relaxed punctuation, an occasional
  ":)". No deliberate typos though.
- Mirror the register: informal if they're informal, more formal if they are. Reply in whatever
  language the comment was written in.
- Emoji: rare, never more than one.
- A critical, mocking, or "this is AI" comment: self-deprecation or a light jab back, never a
  long justification. Never get defensive.
- A factually wrong comment: push back directly, with the actual argument, no apology needed.
- NO number that isn't in the facts you actually gave this prompt. Never invent a statistic,
  a percentage, or a "most of our clients" claim.

FACTS ABOUT YOUR WORK/PRODUCT: replace this section with the real, specific, non-negotiable
facts about whatever you're often asked about (a tool you built, your methodology, your stack).
This is the only source of truth the model should draw numbers or capability claims from. If
a commenter points out a real limitation, acknowledge it honestly: that's more credible than
denying it.
- [FACT 1]
- [FACT 2]
- [FACT 3]

Your recent LinkedIn posts are provided as context: the comment probably relates to one of them.

STRICT OUTPUT FORMAT: exactly 3 reply variants, separated by a line containing only "---".
No numbering, no surrounding text. The 3 variants must differ: one very short, one
technical/concrete, one with a personal touch or dry humor."""


def generate_comment_replies(comment_text: str, image_blocks: list) -> list[str]:
    """3 humanized reply drafts for a LinkedIn comment. Blocking call, run in an executor."""
    from agent import client, load_history

    history = load_history()
    recent_posts = "\n\n=== POST ===\n".join(h["post"][:600] for h in history[-2:]) or "None"

    content: list = []
    if comment_text:
        content.append({"type": "text", "text": f"Comment received:\n{comment_text}"})
    content.extend(image_blocks)
    if image_blocks and not comment_text:
        content.append({"type": "text", "text": "The comment is in the screenshot above."})
    content.append({"type": "text", "text": f"\nMy recent posts (context):\n=== POST ===\n{recent_posts}"})

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        temperature=0.9,
        system=COMMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    variants = [v.strip() for v in message.content[0].text.split("---") if v.strip()]
    return variants[:3]


def build_embed(topic: str, post_text: str) -> discord.Embed:
    desc = post_text if len(post_text) <= 4096 else post_text[:4090] + "\n..."
    embed = discord.Embed(
        title="📝 LinkedIn post pending approval",
        description=desc,
        color=discord.Color.blue(),
    )
    footer = (topic[:250] + "...") if len(topic) > 250 else topic
    embed.set_footer(text=footer)
    return embed


# ---------------------------------------------------------------------------
# View with the action buttons
# ---------------------------------------------------------------------------

class PostView(ui.View):
    """Persistent view. Re-reads pending.md on every interaction."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="✅ Publish", style=discord.ButtonStyle.success, custom_id="pending_post")
    async def post_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No pending post.", ephemeral=True)
            return
        topic, image_path, post_text = pending
        await interaction.response.defer()

        from agent import publish_to_linkedin, save_to_history
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(
            None, functools.partial(publish_to_linkedin, post_text, image_path)
        )

        if success:
            save_to_history(post_text, topic)
            PENDING_FILE.unlink(missing_ok=True)
            if image_path and image_path.exists():
                image_path.unlink(missing_ok=True)
            embed = build_embed(topic, post_text)
            embed.color = discord.Color.green()
            embed.title = "✅ Published to LinkedIn"
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send("✅ Published!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Publication failed, pending.md kept.", ephemeral=True)

    @ui.button(label="🔄 Rewrite", style=discord.ButtonStyle.primary, custom_id="pending_rewrite")
    async def rewrite_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No pending post.", ephemeral=True)
            return
        topic, image_path, _ = pending
        await interaction.response.defer()
        await interaction.followup.send("⏳ Rewriting...", ephemeral=True)

        from agent import generate_post, load_history
        loop = asyncio.get_running_loop()
        history = await loop.run_in_executor(None, load_history)
        new_post = await loop.run_in_executor(
            None, functools.partial(generate_post, topic, history)
        )
        save_pending(topic, image_path, new_post)

        embed = build_embed(topic, new_post)
        if image_path and image_path.exists():
            embed.set_image(url=f"attachment://{image_path.name}")
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send("✅ Post rewritten.", ephemeral=True)

    @ui.button(label="🔁 New topic", style=discord.ButtonStyle.secondary, custom_id="pending_new_topic")
    async def new_topic_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if pending:
            _, image_path, _ = pending
            PENDING_FILE.unlink(missing_ok=True)
            if image_path and image_path.exists():
                image_path.unlink(missing_ok=True)

        await interaction.response.defer()
        await interaction.followup.send("⏳ Generating a post on a different topic...", ephemeral=True)

        from agent import pick_topic, generate_post, load_history, search_sources, fetch_og_image

        loop = asyncio.get_running_loop()
        history = await loop.run_in_executor(None, load_history)
        topic = await loop.run_in_executor(None, functools.partial(pick_topic, history))
        new_post = await loop.run_in_executor(None, functools.partial(generate_post, topic, history))

        og_image_path = None
        if "this week's news" in topic:
            sources = await loop.run_in_executor(None, functools.partial(search_sources, topic))
            for s in sources:
                result = await loop.run_in_executor(None, functools.partial(fetch_og_image, s["url"]))
                if result:
                    img_bytes, mime = result
                    ext = ".jpg" if "jpeg" in mime else ".png"
                    og_image_path = PENDING_FILE.with_suffix(ext)
                    og_image_path.write_bytes(img_bytes)
                    break

        save_pending(topic, og_image_path, new_post)

        embed = build_embed(topic, new_post)
        kwargs: dict = {"embed": embed, "view": PostView()}
        if og_image_path and og_image_path.exists():
            f = discord.File(str(og_image_path), filename=og_image_path.name)
            embed.set_image(url=f"attachment://{og_image_path.name}")
            kwargs["file"] = f

        await interaction.message.delete()
        await interaction.channel.send(**kwargs)

    @ui.button(label="🗑️ Discard", style=discord.ButtonStyle.danger, custom_id="pending_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No pending post.", ephemeral=True)
            return
        topic, image_path, post_text = pending
        PENDING_FILE.unlink(missing_ok=True)
        if image_path and image_path.exists():
            image_path.unlink(missing_ok=True)
        embed = build_embed(topic, post_text)
        embed.color = discord.Color.red()
        embed.title = "🗑️ Post discarded"
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("🗑️ Discarded.", ephemeral=True)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class LinkedInBot(discord.Client):
    def __init__(self, use_message_content: bool = True):
        intents = discord.Intents.default()
        # Needed to read comments pasted in the channel.
        # Requires "Message Content Intent" enabled in the Developer Portal
        # (Bot -> Privileged Gateway Intents).
        intents.message_content = use_message_content
        super().__init__(intents=intents)
        self._pending_mtime: float | None = None

    async def setup_hook(self):
        self.add_view(PostView())  # re-register the persistent view on restart
        asyncio.create_task(self._watch_pending())

    async def on_ready(self):
        print(f"✓ Bot connected: {self.user}")
        print(f"  Watching pending.md every {POLL_INTERVAL}s")
        print(f"  Paste a LinkedIn comment in the channel to get 3 reply drafts")

    async def on_message(self, message: discord.Message):
        """Any human message in the channel is treated as a LinkedIn comment to draft a reply for."""
        if message.author.bot or message.channel.id != CHANNEL_ID:
            return

        text = message.content.strip()
        image_blocks = []
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                import base64
                data = await att.read()
                image_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att.content_type.split(";")[0],
                        "data": base64.b64encode(data).decode(),
                    },
                })

        # channel.send everywhere: message.reply needs the "Read Message History"
        # permission, which the bot may not have in the channel.
        if not text and not image_blocks:
            await message.channel.send(
                "⚠ Received an empty message. If you did send text, enable "
                "**Message Content Intent**: Developer Portal -> your app -> Bot -> "
                "Privileged Gateway Intents, then restart the bot."
            )
            return

        async with message.channel.typing():
            loop = asyncio.get_running_loop()
            try:
                variants = await loop.run_in_executor(
                    None, functools.partial(generate_comment_replies, text, image_blocks)
                )
            except Exception as e:
                await message.channel.send(f"❌ Generation error: {e}")
                return

        await message.channel.send(f"💬 {len(variants)} drafts (copy the one you like):")
        for v in variants:
            await message.channel.send(v)

    async def _watch_pending(self):
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Channel not found: {CHANNEL_ID}")
            return

        DISCORD_MAX_FILE_BYTES = 8 * 1024 * 1024  # limit on a non-boosted server

        while not self.is_closed():
            try:
                if PENDING_FILE.exists():
                    mtime = PENDING_FILE.stat().st_mtime
                    if mtime != self._pending_mtime:
                        pending = parse_pending()
                        if pending:
                            topic, image_path, post_text = pending
                            embed = build_embed(topic, post_text)
                            kwargs: dict = {"embed": embed, "view": PostView()}
                            oversized = image_path and image_path.exists() and image_path.stat().st_size > DISCORD_MAX_FILE_BYTES
                            if image_path and image_path.exists() and not oversized:
                                f = discord.File(str(image_path), filename=image_path.name)
                                embed.set_image(url=f"attachment://{image_path.name}")
                                kwargs["file"] = f
                            try:
                                await channel.send(**kwargs)
                            except discord.HTTPException as send_err:
                                # Image too large or rejected by Discord: retry without it
                                # instead of losing the whole post silently.
                                print(f"[watch] send with image failed ({send_err}), retrying without image")
                                embed2 = build_embed(topic, post_text)
                                await channel.send(embed=embed2, view=PostView())
                            if oversized:
                                print(f"⚠ Image {image_path.name} > 8 MB, sent without it (Discord limit)")
                            # Only mark the mtime as "seen" after a successful send.
                            self._pending_mtime = mtime
                            print(f"✓ Discord message sent for: {topic[:60]}...")
            except Exception as e:
                print(f"[watch] {e}")
            await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN missing from .env")
        print("   1. https://discord.com/developers/applications -> New Application -> Bot")
        print("   2. Copy the token -> add DISCORD_BOT_TOKEN=... to .env")
        exit(1)
    if not CHANNEL_ID:
        print("❌ DISCORD_CHANNEL_ID missing from .env")
        print("   Discord Settings -> Advanced -> Developer Mode enabled")
        print("   Right-click your channel -> Copy Channel ID")
        exit(1)
    try:
        LinkedInBot().run(BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("⚠ Message Content Intent isn't enabled in the Developer Portal.")
        print("  -> https://discord.com/developers/applications -> your app -> Bot -> Privileged Gateway Intents")
        print("  Restarting WITHOUT comment reading (pending.md validation still works).")
        LinkedInBot(use_message_content=False).run(BOT_TOKEN)
