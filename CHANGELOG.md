# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog,
and this project adheres to Semantic Versioning.

## [Unreleased]
### Added
- Added support for a custom `base_download_path` under a `[Storage]` section
  in `settings.ini`, including dynamic `{account_name}` and `{username}` folder
  mapping.
- Discord bot runtime logging to both standard output and timestamped files
  under `logs/`, including uncaught exception logging.
- Direct Message (DM) notifications sent to the bot owner when the bot goes
  online or offline cleanly.
- Initial project documentation (`ARCHITECTURE.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`).
- Batch files (`start_bot.bat` and `stop_bot.bat`) for easier Windows bot management.
- Single-instance socket lock in `discord_bot.py` to prevent multiple
  simultaneous bot instances.
- Slash command support with `/ig_download`, alongside the existing `!download`
  command.
- Owner-only numeric DM shortcut for limited download sessions.
- Live Discord progress updates by forwarding downloader log messages to the
  initial status message.

### Changed
- Replaced Discord bot startup and error `print()` calls with structured logger
  calls.
- Updated Discord configuration to use `discord_bot_token` and `allowed_user_id`.
- Improved download reports with archive size and remaining-download counters.
- Renamed downloaded media files to include the source post owner and UTC timestamp.
- Enforced strict Google-style docstrings across Discord command handlers in
  `discord_bot.py`.
- Bubble up critical authentication exceptions during individual post downloads
  to prevent zombie sessions.
- Expanded `README.md` to include explicit, beginner-friendly instructions for
  setting up the Discord Developer Portal, bot intents, and finding User IDs.

### Fixed
- Fixed a bug where pruning of stale database entries would be incorrectly
  skipped if the user had zero saved posts.
- Fixed a bug where `ConnectionException` (e.g., rate limit triggers) would be
  inadvertently swallowed by the generic exception block, failing to abort the
  session early.
- Fixed pyright type checking errors in `discord_bot.py` (channel send
  compatibility check via `discord.abc.Messageable`) and `downloader/auth.py`
  (explicit conversion of cookies to `dict`).

## [1.0.0] - Initial Implementation
### Added
- `discord_bot.py` to handle Discord commands (`!download`).
- `instaloader_downloader.py` to handle Instagram interactions.
- SQLite database tracking to prevent duplicate downloads.
- Firefox cookie extraction fallback for Instagram authentication.
- Auto-updater for the `instaloader` package.
- Concurrent session locking in the Discord bot to prevent rate limit triggers.
