# Architecture

## Overview

The project has two entry points backed by one synchronous Playwright download
engine:

- `instagram_discord_downloader_bot.py` exposes the Discord commands.
- `instaloader_downloader.py` provides an interactive command-line wrapper.
- `downloader/` contains the reusable session, media, history, reporting, and
  configuration modules.

The downloader performs browser and filesystem I/O synchronously. Discord
commands run it with `asyncio.to_thread` so the Discord event loop remains
responsive. The CLI calls the same session function directly because it does
not own an async event loop.

## Runtime components

### Discord bot

The bot:

- Uses `discord.py` with Message Content Intent enabled.
- Supports `/ig_download [max_posts]`, `!download [limit]`, and owner-only DMs
  containing a numeric limit.
- Authorizes every request against `[Discord].allowed_user_id`.
- Uses an `asyncio.Lock` to prevent overlapping download sessions.
- Relaunches the browser after recoverable failures, for at most three total
  attempts; completed shortcodes remain committed in SQLite so the next attempt
  resumes.
- Sends an initial status message and forwards downloader log messages to live
  progress edits.
- Falls back from an expired interaction webhook to a normal channel message
  when possible.
- Caps final reports and errors before sending them to Discord.
- Sends online and clean-shutdown notifications to the configured owner.
- Writes console and file logs. The bot removes older bot logs and retains the
  five most recent `discord_bot_*.log` files.
- Clears matching stale guild-scoped `ig_download` commands before syncing the
  current global slash-command schema.

On Windows, normal execution starts `supervise_instagram_discord_downloader.ps1`.
The PowerShell supervisor holds an exclusive file lock under `run/`, launches the
bot child, and restarts it after an unexpected exit. The start and stop helpers
send restart and stop requests through files under `run/`. The `--run-bot`
argument is internal and starts the child directly.

### Downloader engine

`downloader.downloads` launches headless Chromium, imports Instagram cookies
from Firefox, discovers the active account, opens its Saved posts page, and
processes post, reel, and carousel links. `instaloader_downloader.py` retains a
stable top-level entry point for older imports and direct use.

Authentication is session-based: the downloader reads the most recently active
Instagram cookie context from Firefox rather than accepting an Instagram
password or account selector. One account is processed per run.

Media retrieval is intentionally layered. Depending on what Instagram exposes,
the downloader can use page media elements, JSON metadata, Open Graph metadata,
hydrated page HTML, embed HTML, in-page fetches, browser-context requests,
canvas extraction, image screenshots, and playback-captured streams as a final
video fallback. Blob videos prefer progressive MP4 sources with audio before
DASH or captured playback streams. Carousel video candidates are grouped by
stable asset identifiers where available, ranked by quality, and selected as
unused candidates before a previously used stream is reused.

Each media item is fetched and written to a temporary file before traversal
continues. Playwright response handles are disposed after their bodies are
copied, and the temporary file is renamed to its final account-scoped filename
after all carousel items have been resolved. If a post fails, any remaining
temporary files are removed so partial media is not left in the output folder.

Downloaded filenames use the original post owner and UTC timestamp when those
values can be recovered. The downloader filters recommendation-grid media when
selecting the active post media.

### Configuration and state

The bot reads `[Discord]` from `settings.ini`. The downloader reads the optional
`[Storage].base_download_path` setting. The active Instagram account is
discovered from Firefox; there is no account selector in the Discord command.

For the detected account, the downloader uses:

- `download_history_<account>.db` for downloaded shortcode history.
- `downloads/<account>/` by default, or the configured storage template.
- `{account_name}` or `{username}` in the storage template for account-specific
  directories.

Successful shortcodes are saved with `INSERT OR IGNORE`. Before processing,
shortcodes no longer present in the current Saved posts list are pruned so a
post that is saved again can be downloaded again.

## Package modules

- `downloader.auth`: locate the Firefox cookie database.
- `downloader.config`: parse the optional storage configuration.
- `downloader.downloads`: saved-post discovery, media retrieval, carousel
  traversal, filename generation, and per-post error handling.
- `downloader.history`: SQLite schema, reads, idempotent writes, and pruning.
- `downloader.logging_utils`: timestamped logs and the optional bot callback.
- `downloader.reporting`: `DownloadStats` and final report generation.
- `downloader.session`: high-level session orchestration and CLI prompting.
- `downloader.timing`: countdown delays between session phases and downloads.

## Data flow

1. The owner starts a command or runs the CLI.
2. The bot validates authorization, limit, and session-lock state, then delegates
   the synchronous session to a worker thread.
3. The downloader locates Firefox cookies, discovers the active Instagram
   account, and opens that account's Saved posts page.
4. Saved post and reel shortcodes are collected while the page is scrolled.
5. History is initialized, stale rows are pruned, and already tracked posts are
   skipped.
6. Each new post is opened, active media is selected, and retrieval fallbacks
   are attempted until media is available or the post fails.
7. Each resolved media item is staged on disk, then renamed into the account's
   storage directory after the post's media has been collected; the shortcode
   is inserted into SQLite only after the post completes successfully.
8. Statistics and errors are formatted into a session report.
9. Recoverable browser failures relaunch the browser up to two times, with
   SQLite history preventing already completed posts from repeating.
10. The bot sends the capped report and releases the session lock.
