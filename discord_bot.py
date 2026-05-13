"""
Discord bot for validating LinkedIn posts held in pending.md.

Run: python discord_bot.py
Watches pending.md and sends a message with 3 action buttons whenever a new post is queued.

Setup (one time):
  1. https://discord.com/developers/applications → New Application → Bot
  2. Copy the token → add DISCORD_BOT_TOKEN=... to .env
  3. Discord Settings → Advanced → Developer Mode
     Right-click your channel → Copy Channel ID → add DISCORD_CHANNEL_ID=... to .env
  4. Invite the bot: OAuth2 → URL Generator → scopes: bot
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
    """Read pending.md → (topic, image_path | None, post_text) or None."""
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


def build_embed(topic: str, post_text: str) -> discord.Embed:
    desc = post_text if len(post_text) <= 4096 else post_text[:4090] + "\n…"
    embed = discord.Embed(
        title="📝 LinkedIn post — pending validation",
        description=desc,
        color=discord.Color.blue(),
    )
    footer = (topic[:250] + "…") if len(topic) > 250 else topic
    embed.set_footer(text=footer)
    return embed


# ---------------------------------------------------------------------------
# View with the 3 action buttons
# ---------------------------------------------------------------------------

class PostView(ui.View):
    """Persistent view — re-reads pending.md on each interaction."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="✅ Publish", style=discord.ButtonStyle.success, custom_id="pending_post")
    async def post_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No post pending.", ephemeral=True)
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
            embed.title = "✅ Published on LinkedIn"
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send("✅ Published!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Publish failed — pending.md kept.", ephemeral=True)

    @ui.button(label="🔄 Rewrite", style=discord.ButtonStyle.primary, custom_id="pending_rewrite")
    async def rewrite_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No post pending.", ephemeral=True)
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

    @ui.button(label="🗑️ Discard", style=discord.ButtonStyle.danger, custom_id="pending_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        pending = parse_pending()
        if not pending:
            await interaction.response.send_message("No post pending.", ephemeral=True)
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
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self._pending_mtime: float | None = None

    async def setup_hook(self):
        self.add_view(PostView())  # re-register persistent view on restart
        asyncio.create_task(self._watch_pending())

    async def on_ready(self):
        print(f"✓ Bot connected: {self.user}")
        print(f"  Watching pending.md every {POLL_INTERVAL}s")

    async def _watch_pending(self):
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            print(f"❌ Channel not found: {CHANNEL_ID}")
            return

        while not self.is_closed():
            try:
                if PENDING_FILE.exists():
                    mtime = PENDING_FILE.stat().st_mtime
                    if mtime != self._pending_mtime:
                        self._pending_mtime = mtime
                        pending = parse_pending()
                        if pending:
                            topic, image_path, post_text = pending
                            embed = build_embed(topic, post_text)
                            kwargs: dict = {"embed": embed, "view": PostView()}
                            if image_path and image_path.exists():
                                f = discord.File(str(image_path), filename=image_path.name)
                                embed.set_image(url=f"attachment://{image_path.name}")
                                kwargs["file"] = f
                            await channel.send(**kwargs)
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
        print("   1. https://discord.com/developers/applications → New Application → Bot")
        print("   2. Copy token → add DISCORD_BOT_TOKEN=... to .env")
        exit(1)
    if not CHANNEL_ID:
        print("❌ DISCORD_CHANNEL_ID missing from .env")
        print("   Discord Settings → Advanced → Developer Mode enabled")
        print("   Right-click your channel → Copy Channel ID")
        exit(1)
    LinkedInBot().run(BOT_TOKEN)
