# Changelog

Notable changes are recorded here in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. Versions follow Semantic Versioning.

## [Unreleased]

### Added

- Architecture, configuration, operations, and coding-standard guides under
  `docs/`.
- Project-specific Windows helpers:
  `start_instagram_discord_downloader.bat` and
  `stop_instagram_discord_downloader.bat`.
- Discord runtime logging to the console and timestamped files, with retention
  of the five newest bot logs.
- Downloader progress is included in the bot log, and failed download
  sessions now record full tracebacks.
- Owner online/offline direct-message notifications.
- `/ig_download` slash-command support alongside the `!download` command.
- Owner-only numeric DM shortcut for limited runs.
- Live progress updates and interaction-webhook fallback for long sessions.
- Layered Playwright media retrieval for posts, reels, and carousels.
- Account-aware storage templates using `{account_name}` or `{username}`.

### Changed

- Documented the current one-account-per-run model: the account is discovered
  from the active Firefox Instagram session.
- Documented the supervisor/child process model and UDP single-instance lock.
- Improved blob-video selection by preferring progressive audio-included MP4
  metadata sources before playback-captured streams.
- Improved carousel video selection with stable asset grouping, quality scoring,
  and unused-candidate preference.
- Added owner and UTC timestamp information to downloaded filenames when
  available.
- Added recommendation-media filtering, stale-history pruning, archive counts,
  and remaining-download counts to the documented behavior.

### Fixed

- Recoverable Playwright failures now relaunch the browser up to two times and
  resume from SQLite history after a computer sleep or wake cycle.
- Prevented the connection watchdog from waiting forever for the first ready
  event after startup or a network interruption.
- Preserved progress updates when an interaction webhook token expires.
- Avoided stale guild slash-command registrations overriding the current
  command schema.
- Avoided swallowing critical authentication or rate-limit failures during a
  session.

## [1.0.0] - Initial implementation

### Added

- Discord `!download` command and the original downloader entry point.
- SQLite tracking to prevent duplicate downloads.
- Firefox cookie extraction for Instagram authentication.
- Automatic `instaloader` package update support from the original implementation.
- Session locking in the Discord bot.
