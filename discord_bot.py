import os
import discord
from discord.ext import commands
import asyncio
import configparser

# Import your refactored downloader
import instaloader_downloader

# Load the config to get your Discord Bot Token
config = configparser.ConfigParser()
config.read("settings.ini")
TOKEN = config.get("Discord", "token", fallback=None)

# Set up Bot and Intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# State tracker to prevent triggering multiple overlapping sessions
is_downloading = False

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("Ready to receive commands!")
    print("------")

@bot.command(name="download", help="Run the Instagram downloader. Example: !download 10")
async def download(ctx, max_posts: int = None):
    global is_downloading
    
    if is_downloading:
        await ctx.send("⏳ A download session is already running. Please wait for it to finish.")
        return

    is_downloading = True
    limit_text = f"limited to {max_posts} posts" if max_posts else "with no limit"
    await ctx.send(f"🚀 Starting Instagram download session {limit_text}...\nThis may take a while depending on the number of posts and rate limits.")
    
    try:
        # Use asyncio.to_thread so the synchronous script doesn't freeze the Discord bot
        report = await asyncio.to_thread(instaloader_downloader.run_download_session, max_posts)
        
        # The report shouldn't exceed Discord's 2000 char limit but we truncate just in case
        if len(report) > 1990:
            report = report[:1980] + "\n...[Report Truncated]"
            
        await ctx.send(f"✅ **Download Session Complete!**\n```\n{report}\n```")
    except Exception as e:
        await ctx.send(f"❌ **An error occurred during the download session:**\n```\n{e}\n```")
    finally:
        is_downloading = False

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Please add your Discord bot token to settings.ini under the [Discord] section.")
    else:
        bot.run(TOKEN)