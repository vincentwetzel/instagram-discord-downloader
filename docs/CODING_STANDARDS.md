# Coding Standards

These rules apply to changes in the Instagram Discord Downloader.

## Python style

- Follow [PEP 8](https://peps.python.org/pep-0008/).
- Use `snake_case` for functions, variables, and modules; `PascalCase` for
  classes; and `UPPER_SNAKE_CASE` for constants.
- Add complete type hints to function arguments and return values.
- Use Google-style docstrings for modules, classes, and functions. Include
  `Args:`, `Returns:`, and `Raises:` sections where applicable.
- Prefer f-strings, `pathlib`, context managers, and specific exception types.
- Keep lines near 88 characters where practical and group imports by standard
  library, third-party, and local modules.
- Use `downloader.logging_utils.log()` for downloader-package console output and
  the configured bot logger for bot lifecycle and error messages.

## Architecture and concurrency

- Keep Discord orchestration in `instagram_discord_downloader_bot.py`.
- Keep session orchestration in `downloader.session`, media workflow in
  `downloader.downloads`, SQLite operations in `downloader.history`, and report
  formatting in `downloader.reporting`.
- Never call the synchronous downloader directly from the Discord event loop;
  use `asyncio.to_thread` or an equivalent worker mechanism.
- Use the bot's async session lock to prevent overlapping download sessions.
- Preserve the one-account-per-run model. The active account is discovered from
  Firefox cookies, and account-specific state must remain isolated.
- Keep media fallbacks observable. Prefer progressive MP4 streams with audio
  before DASH or captured playback streams, and deduplicate carousel videos by
  stable asset identifiers where possible.

## Database

- Use `download_history_<account>.db` for account-specific history.
- Use the shortcode as the idempotent key and rely on SQLite constraints with
  `INSERT OR IGNORE` for successful-download writes.
- Update `downloader.history` and report counters whenever the definition of a
  downloaded, skipped, stale, or failed post changes.
- Commit writes and close every database connection.

## Discord integration

- Keep reports and errors within Discord's 2000-character message limit before
  adding formatting wrappers.
- Record per-post failures in `DownloadStats` and return a useful summary.
- Keep command parsing predictable: no limit means unlimited, while a positive
  integer limits the session.
- Preserve authorization through the configured `allowed_user_id`.

## Security and local state

- Never hardcode tokens, usernames, passwords, or browser session details.
- Read Discord credentials with `configparser`; use the active Firefox session
  for Instagram authentication.
- Keep settings, history databases, media, browser artifacts, logs, and Python
  caches out of version control.

## Versioning and workflow

- Follow Semantic Versioning and keep `docs/CHANGELOG.md` in the same change as
  notable behavior updates.
- Prefer Conventional Commits such as `feat:`, `fix:`, and `docs:`.
- Add new third-party dependencies to dependency tracking and explain why they
  are needed.
- Use a virtual environment for development and keep pull requests focused.

## Tooling and tests

- Prefer Black-compatible formatting, `isort`, `ruff` or `flake8`, and strict
  type checking such as `mypy` or `pyright`.
- Use `pytest` for tests when applicable.
- Mock Instagram, Firefox, Playwright, and Discord boundaries; tests must not
  call live services.
