# Architecture

## Overview

The Instagram Discord Downloader has two user-facing entry points backed by one
synchronous downloader engine:

- `discord_bot.py` exposes the Discord `!download [limit]` command.
- `instaloader_downloader.py` keeps command-line usage and legacy imports
  stable while delegating to the `downloader/` package.

The downloader is I/O bound and intentionally synchronous. Any Discord command
that invokes it must run the session in a worker thread so Discord's event loop
stays responsive.

## Components

1. **Discord Bot (`discord_bot.py`)**
   - Built with `discord.py`.
   - Listens for the `!download [limit]` command.
   - Prevents overlapping download sessions using a global state lock.
   - Runs the synchronous downloading script in a non-blocking thread using
     `asyncio.to_thread`.
   - Truncates returned reports before sending them to Discord.

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
   - Features automatic Instaloader version checking and upgrading.
   - Generates a textual report of the download session.

3. **Configuration (`settings.ini`)**
   - Stores the Discord bot token and Instagram credentials.
   - Lives outside version control because it contains local secrets.

4. **Runtime State**
   - `download_history.db` stores downloaded post shortcodes.
   - The configured Instagram account folder stores downloaded media.
   - Instaloader session files may be created locally after successful login.

## Downloader Package Modules

- `downloader.auth`: Session loading helpers and Firefox cookie import.
- `downloader.config`: `settings.ini` parsing and typed config object.
- `downloader.downloads`: Saved-post retrieval, duplicate filtering, downloads,
  per-post error capture, and rate-limit friendly delays.
- `downloader.history`: SQLite schema setup, shortcode reads/writes, and stale
  history pruning.
- `downloader.logging_utils`: Timestamped console logging helpers.
- `downloader.reporting`: Session statistics and report generation.
- `downloader.session`: High-level orchestration for a full download run.
- `downloader.timing`: Countdown sleep helper.
- `downloader.version`: Instaloader version check and optional pip upgrade.

## Data Flow

1. User sends `!download 10` in Discord.
2. Bot verifies no other downloads are running, locks the state, and delegates
   to the downloader engine in a background thread.
3. Downloader checks the local Instaloader version, loads config, and
   authenticates using the saved session, credentials, 2FA, or Firefox cookies.
4. Downloader queries Instagram for saved posts and compares shortcodes against
   `download_history.db`.
5. Stale shortcode rows for unsaved posts are pruned from history.
6. New posts are downloaded locally, and successful downloads are recorded with
   `INSERT OR IGNORE`.
7. A text summary is generated and returned to the bot.
8. The bot truncates the summary if needed, sends it to Discord, and unlocks
   the state.
