# Coding Standards

This document outlines the coding standards, style guidelines, and architectural
rules for the Instagram Discord Downloader project. All contributors and AI
assistants must adhere to these standards to maintain code quality, readability,
and application stability.

## 1. Python Style Guide

- **PEP 8:** All Python code must adhere to
  [PEP 8](https://peps.python.org/pep-0008/).
- **Type Hinting:** Comprehensive type hints are mandatory for all function
  arguments and return types. Prefer modern built-in generics where they match
  the supported Python version, and use `typing` imports where needed.
- **Docstrings:** Use standard Python docstrings for all modules, classes, and
  functions. Explain what a function does, its arguments, return values, and
  any expected exceptions.
- **Imports:** Group imports logically: standard library first, followed by
  third-party libraries such as `discord` and `instaloader`, then local imports.
- **Soft Line Length:** Prefer keeping code lines reasonably short, around 88
  characters where practical, to preserve coding-agent context and improve
  review readability. Treat this as a soft rule: clarity and stable formatting
  are more important than awkward wrapping.

## 2. Architecture & Concurrency Constraints

- **Event Loop Blocking:** The Discord bot operates on an asynchronous event
  loop (`asyncio`). The downloading engine is heavily I/O bound and synchronous.
  Never call synchronous downloader I/O directly from `discord_bot.py`'s event
  loop. Wrap calls to the downloader using `asyncio.to_thread` or equivalent.
- **State Locking:** Ensure only one download session runs at a time using a
  shared lock or state flag, such as `is_downloading`, to reduce rate-limit risk
  and avoid overlapping writes.
- **Module Boundaries:** Keep orchestration in `downloader.session`, saved-post
  workflow logic in `downloader.downloads`, SQLite logic in
  `downloader.history`, report formatting in `downloader.reporting`, and
  Discord-specific behavior in `discord_bot.py`.

## 3. Database Guidelines

- **Idempotency:** When interacting with the SQLite database
  (`download_history.db`), rely on SQL constraints to maintain idempotency. Use
  `INSERT OR IGNORE` to prevent duplicate tracking of downloaded posts.
- **History Syncing:** Changes to how posts are considered downloaded, skipped,
  or stale must update `downloader.history` and any affected report counters.
- **Connection Management:** Ensure all database connections are committed when
  needed and closed after use to prevent locking the `.db` file.

## 4. Discord Integration

- **Message Limits:** Discord has a strict 2000-character limit per message.
  Any reports or logs sent back through the bot must be validated and truncated
  if they exceed this limit.
- **Error Handling:** Catch exceptions during a download session and safely
  report a summary back to the Discord channel rather than crashing the bot.
- **User Commands:** Keep command parsing simple and predictable. `!download`
  should mean unlimited downloads, while `!download <positive integer>` should
  limit the session.

## 5. Security

- **Credentials:** Never hardcode Discord tokens, Instagram usernames, or
  passwords in source code. Use `configparser` to read from `settings.ini`.
- **Version Control:** Ensure `settings.ini`, `download_history.db`, downloaded
  media files, session artifacts, and Python caches are excluded from version
  control through `.gitignore`.

## 6. Versioning & Changelog

- Follow Semantic Versioning.
- Document all notable changes in `CHANGELOG.md` following the Keep a Changelog format.
- Keep the `CHANGELOG.md` updated in the same commit as the feature addition or bug fix.
