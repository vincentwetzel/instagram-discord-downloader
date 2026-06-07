# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog,
and this project adheres to Semantic Versioning.

## [Unreleased]
### Added
- Initial project documentation (`ARCHITECTURE.md`, `AGENTS.md`, `CHANGELOG.md`, `README.md`).
- Soft code line-length guidance to preserve coding-agent context.
- Modular downloader package split from `instaloader_downloader.py`.
- Discord and CLI usage documentation, including local runtime-state notes.
- Downloader package module overview and data-flow documentation.
- SQLite stale-history pruning for posts no longer saved on Instagram.

### Changed
- `instaloader_downloader.py` now acts as a compatibility entry point that
  re-exports downloader helpers and delegates session execution to
  `downloader.session`.
- Download session reports now include stale history pruning counts.

## [1.0.0] - Initial Implementation
### Added
- `discord_bot.py` to handle Discord commands (`!download`).
- `instaloader_downloader.py` to handle Instagram interactions.
- SQLite database tracking to prevent duplicate downloads.
- Firefox cookie extraction fallback for Instagram authentication.
- Auto-updater for the `instaloader` package.
- Concurrent session locking in the Discord bot to prevent rate limit triggers.
