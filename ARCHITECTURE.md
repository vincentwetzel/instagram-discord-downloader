# Architecture

## Overview

The Instagram Discord Downloader has two user-facing entry points backed by one
synchronous browser-automation downloader engine:

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
   - Falls back to fetching the status message as a normal channel message if a
     long-running interaction webhook token expires.
   - Truncates returned reports before sending them to Discord.
   - Sends owner DMs when the bot goes online and when it shuts down cleanly.
   - Writes runtime logs to both standard output and timestamped files under
     `logs/`, with uncaught exceptions routed through the same logger.

2. **Downloader Engine (`instaloader_downloader.py`, `downloader/`)**
   - Built on top of Playwright with Firefox cookie import.
   - Keeps `instaloader_downloader.py` as the compatibility entry point.
   - Organizes auth, configuration, history tracking, reporting, timing,
     logging, and session orchestration in focused modules under `downloader/`.
   - Handles Instagram authentication by importing cookies from an active
     Firefox profile, grouping cookies by Firefox container partition, and
     testing each jar until one can access the requested account.
   - Supports one or more comma-separated Instagram usernames from
     `settings.ini`.
   - Fetches saved posts for each configured user, including post and reel
     links from the saved-posts grid.
   - Downloads post and carousel media through Playwright using captured
     network responses, progressive blob-video stream resolution, page
     metadata, in-page fetches, context requests, canvas extraction, and image
     screenshot fallback.
   - Resolves blob videos through layered metadata fallbacks: Instagram JSON
     endpoints, Open Graph video tags, hydrated page-source MP4 streams, embed
     page MP4 streams, and finally captured playback responses.
   - Deduplicates carousel video candidates by grouping URLs by video asset ID,
     scoring progressive streams above DASH segments, preferring higher quality
     candidates, and selecting unused streams before falling back to
     already-seen streams.
   - Derives output filenames from the original post owner and post timestamp,
     using URL parsing, JSON metadata, page-source state, strict title metadata,
     article header links, and DOM fallbacks.
   - Filters active media candidates to avoid downloading recommendation-grid
     media that can appear near the opened post.
   - Uses account-specific SQLite databases (`download_history_<account>.db`) to
     track downloaded shortcodes and prevent duplicates.
   - Prunes downloaded-post history for shortcodes that are no longer in the
     current saved-post list.
   - Generates a textual report of the download session.

3. **Configuration (`settings.ini`)**
   - Stores the Discord bot token, allowed Discord user ID, Instagram
     credentials, and optional storage path template.
   - Uses `[Storage].base_download_path` when configured. The downloader
     replaces `{account_name}` or `{username}` with the account currently being
     processed, falling back to `downloads/<account_name>/` when the setting is
     omitted.
   - Lives outside version control because it contains local secrets.

4. **Runtime State**
   - `download_history_<account>.db` stores downloaded post shortcodes.
   - `logs/discord_bot_<timestamp>.log` stores local bot startup, shutdown, and
     error logs. Older run logs are pruned automatically.
   - `downloads/` stores downloaded media unless `[Storage].base_download_path`
     points media at another local directory.

5. **Windows Bot Helpers (`start_bot.bat`, `stop_bot.bat`)**
   - `start_bot.bat` launches `discord_bot.py` in the background with
     `pythonw`.
   - `stop_bot.bat` stops the background bot by checking the known socket lock
     port or the console title used by the bot process.

## Downloader Package Modules

- `downloader.auth`: Session loading helpers and Firefox cookie import.
- `downloader.config`: `settings.ini` parsing and typed config object.
- `downloader.downloads`: Saved-post retrieval, Firefox cookie-jar selection,
  duplicate filtering, carousel traversal, layered media downloads,
  progressive video stream scoring, video URL candidate deduplication,
  configurable storage paths, owner/timestamp-based filenames, recommendation
  media filtering, per-post error capture, and rate-limit friendly delays.
- `downloader.history`: SQLite schema setup, shortcode reads/writes, and stale
  history pruning.
- `downloader.logging_utils`: Timestamped console logging helpers and optional
  thread-safe callbacks for Discord progress updates.
- `downloader.reporting`: Session statistics, archive counters, and report
  generation.
- `downloader.session`: High-level orchestration for a full download run.
- `downloader.timing`: Countdown sleep helper.

## Data Flow

1. User sends `/ig_download max_posts:10`, `!download 10`, or a numeric direct
   message to the bot.
2. Bot verifies the invoking user matches `allowed_user_id`, checks that no
   other downloads are running, locks the session, and delegates to the
   downloader engine in a background thread.
3. Downloader loads config, locates Firefox's active Instagram cookies, groups
   them by container partition, and launches headless Chromium contexts until
   one can access the requested account's saved-posts page.
4. Downloader queries Instagram for saved posts and reels, then compares
   shortcodes against the account-specific history database.
5. Stale shortcode rows for unsaved posts are pruned from history.
6. New posts are opened individually; active media is selected from the opened
   post, excluding recommendation-grid candidates, then captured from the DOM,
   network responses, page metadata, and fallback retrieval tiers. Blob videos
   prefer progressive MP4 metadata sources before playback capture, and
   carousel videos prefer unused asset-grouped URL candidates so multiple
   slides do not resolve to the same stream. Media is then written locally with
   owner/timestamp-based filenames.
7. Successful downloads are recorded with `INSERT OR IGNORE`.
8. Downloader log messages are forwarded to Discord as live status-message
   edits while the session runs.
9. A text summary is generated and returned to the bot.
10. The bot truncates the summary if needed, sends it to Discord, and unlocks
   the session.
