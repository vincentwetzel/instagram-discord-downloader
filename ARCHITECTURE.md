# Architecture

## Overview

The Instagram Discord Downloader has two user-facing entry points backed by one
synchronous downloader engine:

- `discord_bot.py` exposes the Discord `/ig_download [max_posts]`,
  `!download [limit]`, and owner-DM numeric limit commands.
- `instaloader_downloader.py` keeps command-line usage and legacy imports
  stable while delegating to the `downloader/` package.

The downloader is I/O bound and intentionally synchronous. Any Discord command
that invokes it must run the session in a worker thread so Discord's event loop
stays responsive.

## Components

1. **Discord Bot (`discord_bot.py`)**
   - Built with `discord.py`.
   - Registers the `/ig_download` slash command and keeps the legacy
     `!download [limit]` prefix command.
   - Accepts direct messages containing only a positive integer as a limited
     download request from the configured owner.
   - Restricts download commands to the configured `allowed_user_id`.
   - Prevents overlapping download sessions using an `asyncio.Lock`.
   - Enforces a single local bot process with a UDP socket bound to
     `127.0.0.1:47200`.
   - Runs the synchronous downloading script in a non-blocking thread using
     `asyncio.to_thread`.
   - Streams downloader log output through a thread-safe callback and edits the
     initial status message with live progress.
   - Truncates returned reports before sending them to Discord.
   - Sends owner DMs when the bot goes online and when it shuts down cleanly.
   - Writes runtime logs to both standard output and `discord_bot.log`, with
     uncaught exceptions routed through the same logger.

2. **Downloader Engine (`instaloader_downloader.py`, `downloader/`)**
   - Built on top of `instaloader`.
   - Keeps `instaloader_downloader.py` as the compatibility entry point.
   - Organizes auth, configuration, history tracking, reporting, version
     checks, and session orchestration in focused modules under `downloader/`.
   - Handles Instagram authentication with password, 2FA, or Firefox cookie
     extraction.
   - Fetches saved posts for the configured user.
   - Uses a local SQLite database (`download_history.db`) to track downloaded
     shortcodes and prevent duplicates.
   - Prunes downloaded-post history for shortcodes that are no longer in the
     current saved-post list.
   - Features automatic Instaloader version checking and upgrading.
   - Generates a textual report of the download session.

3. **Configuration (`settings.ini`)**
   - Stores the Discord bot token, allowed Discord user ID, and Instagram
     credentials.
   - Lives outside version control because it contains local secrets.

4. **Runtime State**
   - `download_history.db` stores downloaded post shortcodes.
   - `discord_bot.log` stores local bot startup, shutdown, and error logs.
   - The configured Instagram account folder stores downloaded media.
   - Instaloader session files may be created locally after successful login.

5. **Windows Bot Helpers (`start_bot.bat`, `stop_bot.bat`)**
   - `start_bot.bat` launches `discord_bot.py` in the background with
     `pythonw`.
   - `stop_bot.bat` stops the background bot by checking the known socket lock
     port or the console title used by the bot process.

## Downloader Package Modules

- `downloader.auth`: Session loading helpers and Firefox cookie import.
- `downloader.config`: `settings.ini` parsing and typed config object.
- `downloader.downloads`: Saved-post retrieval, duplicate filtering, downloads,
  per-post error capture, and rate-limit friendly delays.
- `downloader.history`: SQLite schema setup, shortcode reads/writes, and stale
  history pruning.
- `downloader.logging_utils`: Timestamped console logging helpers and optional
  thread-safe callbacks for Discord progress updates.
- `downloader.reporting`: Session statistics, archive counters, and report
  generation.
- `downloader.session`: High-level orchestration for a full download run.
- `downloader.timing`: Countdown sleep helper.
- `downloader.version`: Instaloader version check and optional pip upgrade.

## Data Flow

1. User sends `/ig_download max_posts:10`, `!download 10`, or a numeric direct
   message to the bot.
2. Bot verifies the invoking user matches `allowed_user_id`, checks that no
   other downloads are running, locks the session, and delegates to the
   downloader engine in a background thread.
3. Downloader checks the local Instaloader version, loads config, and
   authenticates using the saved session, credentials, 2FA, or Firefox cookies.
4. Downloader queries Instagram for saved posts and compares shortcodes against
   `download_history.db`.
5. Stale shortcode rows for unsaved posts are pruned from history.
6. New posts are downloaded locally, and successful downloads are recorded with
   `INSERT OR IGNORE`.
7. Downloader log messages are forwarded to Discord as live status-message
   edits while the session runs.
8. A text summary is generated and returned to the bot.
9. The bot truncates the summary if needed, sends it to Discord, and unlocks
   the session.
