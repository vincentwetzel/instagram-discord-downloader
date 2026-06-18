"""Discord bot interface for the Instagram downloader."""

import asyncio
import configparser
import ctypes
import datetime
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

# Ensure logs directory exists
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

def clean_old_logs(directory: Path, keep_count: int = 5) -> None:
    """Delete oldest log files to keep only a specific number of historical runs."""
    try:
        log_files = list(directory.glob("discord_bot_*.log"))
        # Sort by modification time (oldest first)
        log_files.sort(key=lambda p: p.stat().st_mtime)
        
        # Since we are about to create a new log file, keep at most keep_count - 1 existing ones
        if len(log_files) >= keep_count:
            excess = len(log_files) - (keep_count - 1)
            for i in range(excess):
                try:
                    log_files[i].unlink()
                except Exception as e:
                    sys.stderr.write(f"Failed to delete old log file {log_files[i]}: {e}\n")
    except Exception as e:
        sys.stderr.write(f"Error cleaning old logs: {e}\n")

# Clean old logs and keep only the 5 most recent runs
clean_old_logs(logs_dir, keep_count=5)

# Create a unique timestamped log file for this run
timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_file_path = logs_dir / f"discord_bot_{timestamp_str}.log"

# Set up logging to both a file and standard output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("discord_bot")

# Enable deep diagnostic logging specifically for the downloader module 
# without getting flooded by Discord.py and Playwright network spam
logging.getLogger("downloader").setLevel(logging.DEBUG)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception occurred", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

# Import downloader orchestrator directly per module boundaries
from downloader.session import run_download_session

# Load the config to get your Discord Bot Token
config: configparser.ConfigParser = configparser.ConfigParser()
config.read(Path("settings.ini"))
TOKEN: Optional[str] = config.get("Discord", "discord_bot_token", fallback=None)
ALLOWED_USER_ID: Optional[str] = config.get("Discord", "allowed_user_id", fallback=None)
if ALLOWED_USER_ID:
    ALLOWED_USER_ID = ALLOWED_USER_ID.strip()

if ALLOWED_USER_ID == "YOUR_DISCORD_USER_ID":
    ALLOWED_USER_ID = None

# Set up Bot and Intents
intents: discord.Intents = discord.Intents.default()
intents.message_content = True

class IGDownloaderBot(commands.Bot):
    """Custom Bot class to handle clean shutdown events."""

    async def close(self) -> None:
        """Handle bot shutdown and notify the owner."""
        if ALLOWED_USER_ID and ALLOWED_USER_ID.isdigit():
            try:
                user = await self.fetch_user(int(ALLOWED_USER_ID))
                await user.send("🔴 **Instagram Downloader Bot is going OFFLINE!**")
            except Exception as e:
                logger.error(f"Failed to send shutdown DM: {e}")
        await super().close()

bot: IGDownloaderBot = IGDownloaderBot(command_prefix="!", intents=intents)

# Async lock to safely prevent triggering multiple overlapping sessions
download_lock: Optional[asyncio.Lock] = None
_is_synced: bool = False
_sent_startup_dm: bool = False
STALE_GUILD_COMMANDS: tuple[str, ...] = ("ig_download",)


def _get_download_lock() -> asyncio.Lock:
    """Get or initialize the global download lock.

    Returns:
        The initialized asyncio Lock.
    """
    global download_lock
    if download_lock is None:
        download_lock = asyncio.Lock()
    return download_lock


async def _clear_stale_guild_commands() -> None:
    """Remove old guild-scoped slash commands that can override global commands."""

    for guild in bot.guilds:
        stale_commands = [
            command
            for command in await bot.tree.fetch_commands(guild=guild)
            if command.name in STALE_GUILD_COMMANDS
        ]
        if not stale_commands:
            continue

        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
        stale_names = ", ".join(command.name for command in stale_commands)
        logger.info(
            "Cleared stale guild slash command(s) for %s: %s",
            guild.name,
            stale_names,
        )

@bot.event
async def on_ready() -> None:
    """Handle bot readiness and sync slash commands."""
    global _is_synced, _sent_startup_dm
    if not _is_synced:
        try:
            await _clear_stale_guild_commands()
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} slash command(s).")
            _is_synced = True
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    if ALLOWED_USER_ID and ALLOWED_USER_ID.isdigit() and not _sent_startup_dm:
        try:
            user = await bot.fetch_user(int(ALLOWED_USER_ID))
            await user.send("🟢 **Instagram Downloader Bot is now ONLINE!**")
            _sent_startup_dm = True
        except Exception as e:
            logger.error(f"Failed to send startup DM: {e}")

    if bot.user:
        logger.info(f"Logged in as {bot.user.name} ({bot.user.id})")
    logger.info("Ready to receive commands!")
    logger.info("------")

@bot.event
async def on_message(message: discord.Message) -> None:
    """Handle incoming messages to support lazy integer DMs.

    If the user DMs a pure integer, it's treated as a maximum post download limit.

    Args:
        message: The incoming Discord message.
    """
    if message.author == bot.user:
        return

    # Check if the message is in a DM and is a positive integer
    if message.guild is None:
        content_stripped = message.content.strip()
        if content_stripped.isdigit():
            max_posts = int(content_stripped)
            await _handle_download_session(
                user_id=message.author.id,
                max_posts=max_posts,
                send_initial=message.channel.send,
                send_final=message.channel.send,
            )
            return

    await bot.process_commands(message)

async def _handle_download_session(
    user_id: int,
    max_posts: Optional[int],
    send_initial: Callable[[str], Awaitable[Any]],
    send_final: Callable[[str], Awaitable[Any]],
    interaction: Optional[discord.Interaction] = None,
) -> None:
    """Shared logic for prefix and slash download commands.

    Args:
        user_id: The Discord ID of the user invoking the command.
        max_posts: Optional maximum number of posts to download.
        send_initial: Async callable to send the initial response.
        send_final: Async callable to send the final report.
        interaction: Optional slash command interaction context.
    """
    if str(user_id) != ALLOWED_USER_ID:
        await send_initial("❌ You are not authorized to use this command.")
        return

    lock = _get_download_lock()
    if lock.locked():
        await send_initial(
            "⏳ A download session is already running. "
            "Please wait for it to finish."
        )
        return

    if max_posts is not None and max_posts <= 0:
        await send_initial(
            "❌ Please provide a positive integer for the maximum post limit."
        )
        return

    async with lock:
        limit_text = f"limited to {max_posts} posts" if max_posts else "unlimited"

        status_msg: Optional[discord.Message] = None
        try:
            initial_text = (
                f"🚀 Starting Instagram download session {limit_text}...\n"
                "This may take a while depending on the number of posts and rate limits."
            )
            res = await send_initial(initial_text)
            if isinstance(res, discord.Message):
                status_msg = res
            elif interaction:
                try:
                    status_msg = await interaction.original_response()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to send initial response: {e}")
            return
            
        # Setup queue and thread-safe callback for live progress updates
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def log_callback(msg: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, msg)

        from downloader.logging_utils import set_log_callback
        set_log_callback(log_callback)

        log_lines: list[str] = []

        async def update_status_loop() -> None:
            nonlocal status_msg
            last_update_time = 0.0
            update_needed = False
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                        log_lines.append(msg)
                        if len(log_lines) > 8:
                            log_lines.pop(0)
                        update_needed = True
                        queue.task_done()

                        while not queue.empty():
                            msg = queue.get_nowait()
                            log_lines.append(msg)
                            if len(log_lines) > 8:
                                log_lines.pop(0)
                            update_needed = True
                            queue.task_done()
                    except asyncio.TimeoutError:
                        pass

                    now = loop.time()
                    if update_needed and (now - last_update_time >= 2.0) and status_msg:
                        try:
                            logs_text = "\n".join(log_lines)
                            await status_msg.edit(
                                content=(
                                    f"🚀 Starting Instagram download session {limit_text}...\n"
                                    f"**Progress Updates:**\n```\n{logs_text}\n```"
                                )
                            )
                            last_update_time = now
                            update_needed = False
                        except discord.NotFound:
                            logger.warning("Status message was deleted; stopping live progress updates.")
                            status_msg = None
                        except discord.HTTPException as edit_err:
                            if edit_err.code == 50027:
                                if status_msg and interaction and isinstance(interaction.channel, discord.abc.Messageable):
                                    logger.warning("Webhook token expired; attempting to fetch as regular message to continue updates.")
                                    try:
                                        status_msg = await interaction.channel.fetch_message(status_msg.id)
                                        logs_text = "\n".join(log_lines)
                                        await status_msg.edit(
                                            content=(
                                                f"🚀 Starting Instagram download session {limit_text}...\n"
                                                f"**Progress Updates:**\n```\n{logs_text}\n```"
                                            )
                                        )
                                        last_update_time = now
                                        update_needed = False
                                    except Exception as fetch_err:
                                        logger.error(f"Failed to convert status message: {fetch_err}")
                                        status_msg = None
                                else:
                                    logger.warning("Webhook token expired; stopping live progress updates.")
                                    status_msg = None
                            else:
                                logger.error(f"Failed to edit status message: {edit_err}")
                        except Exception as edit_err:
                            logger.error(f"Failed to edit status message: {edit_err}")
            except asyncio.CancelledError:
                if update_needed and status_msg:
                    try:
                        logs_text = "\n".join(log_lines)
                        await status_msg.edit(
                            content=(
                                f"🚀 Starting Instagram download session {limit_text}...\n"
                                f"**Progress Updates:**\n```\n{logs_text}\n```"
                            )
                        )
                    except Exception:
                        pass

        update_task = asyncio.create_task(update_status_loop())

        try:
            # Use asyncio.to_thread so the synchronous script doesn't
            # freeze the Discord bot
            report = await asyncio.to_thread(run_download_session, max_posts)
            
            # Ensure total message doesn't exceed Discord's 2000 char limit
            max_report_len = 1900
            if len(report) > max_report_len:
                report = report[:max_report_len] + "\n...[Report Truncated]"
                
            await send_final(f"✅ **Download Session Complete!**\n```\n{report}\n```")
        except Exception as e:
            try:
                error_msg = str(e)
                if len(error_msg) > 1900:
                    error_msg = error_msg[:1900] + "\n...[Error Truncated]"
                await send_final(
                    "❌ **An error occurred during the download session:**\n"
                    f"```\n{error_msg}\n```"
                )
            except Exception as final_e:
                logger.error(f"Failed to send final error report: {final_e}")
        finally:
            set_log_callback(None)
            update_task.cancel()
            try:
                await update_task
            except asyncio.CancelledError:
                pass

@bot.command(
    name="download",
    help="Run the Instagram downloader. Examples: !download, !download 10",
)
async def download(
    ctx: commands.Context,
    max_posts: Optional[int] = None,
) -> None:
    """Legacy prefix command handler (!download).

    Args:
        ctx: Discord command context.
        max_posts: Optional maximum number of posts to download.
    """
    await _handle_download_session(ctx.author.id, max_posts, ctx.send, ctx.send)

@download.error
async def download_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Handle bad arguments for the download prefix command.

    Args:
        ctx: Discord command context.
        error: The error raised during command parsing.
    """
    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ Please provide a valid integer for the maximum post limit. "
            "Example: `!download 10`"
        )

@bot.tree.command(name="ig_download", description="Run the Instagram downloader.")
@app_commands.describe(
    max_posts="Maximum number of posts to download (optional)",
)
async def slash_download(
    interaction: discord.Interaction,
    max_posts: Optional[int] = None,
) -> None:
    """Modern slash command handler (/ig_download).

    Args:
        interaction: Discord slash command interaction.
        max_posts: Optional limit on posts to download.
    """
    
    async def send_final_safe(msg: str) -> Union[discord.Message, discord.WebhookMessage, None]:
        """Safely send the final report, falling back to channel if webhook expires.

        Args:
            msg: The message content to send.

        Returns:
            The sent message object or None.
        """
        try:
            return await interaction.followup.send(msg)
        except (discord.NotFound, discord.HTTPException) as e:
            if not isinstance(e, discord.NotFound) and e.code != 50027:
                raise
            # Webhook expired (takes > 15 mins) or not found, try sending to channel directly
            if isinstance(interaction.channel, discord.abc.Messageable):
                try:
                    return await interaction.channel.send(
                        f"<@{interaction.user.id}> {msg}"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    await _handle_download_session(
        interaction.user.id,
        max_posts,
        interaction.response.send_message,
        send_final_safe,
        interaction=interaction,
    )

def _enforce_single_instance() -> socket.socket:
    """Ensure only one instance of the bot is running at a time.

    Returns:
        A bound socket acting as an instance lock.
    """
    if os.name == "nt":
        # Set a unique console title so the stop.bat script can find and kill it easily
        ctypes.windll.kernel32.SetConsoleTitleW("IG_Discord_Bot_Running")
        
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Bind to a specific local port
        lock_socket.bind(("127.0.0.1", 47200))
        return lock_socket
    except OSError:
        logger.error("❌ Another instance of the bot is already running. Please close it first.")
        sys.exit(1)

if __name__ == "__main__":
    _lock = _enforce_single_instance()
    
    if not TOKEN or TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        logger.error(
            "❌ Please add your Discord bot token to settings.ini "
            "under the [Discord] section."
        )
        sys.exit(1)

    if not ALLOWED_USER_ID or not ALLOWED_USER_ID.isdigit():
        logger.error(
            "❌ Please add a valid numeric Discord user ID to settings.ini "
            "under the [Discord] section (allowed_user_id) to secure your bot."
        )
        sys.exit(1)
    else:
        logger.info("Starting Instagram Discord Downloader Bot...")
        bot.run(TOKEN, log_handler=None)
