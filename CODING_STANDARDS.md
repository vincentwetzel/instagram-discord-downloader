# Coding Standards

This document outlines the coding standards, style guidelines, and architectural
rules for the Instagram Discord Downloader project. All contributors and AI
assistants must adhere to these standards to maintain code quality, readability,
and application stability.

## 1. Python Style Guide

- **PEP 8:** All Python code must adhere to
  [PEP 8](https://peps.python.org/pep-0008/).
- **Naming Conventions:** Use `snake_case` for variables, functions, and module
  names. Use `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- **Comments:** Code should be as self-documenting as possible. Use inline
  comments primarily to explain *why* a particular approach was taken, rather
  than *what* the code is doing.
- **Type Hinting:** Comprehensive type hints are mandatory for all function
  arguments and return types. Assume **Python 3.9+** to leverage modern built-in
  generics (e.g., `list[str]`), but use `typing` imports where needed.
- **Docstrings:** Use **Google-style** docstrings for all modules, classes, and
  functions (using `Args:`, `Returns:`, and `Raises:` sections). Explain what a
  function does, its arguments, return values, and any expected exceptions.
- **String Formatting:** Prefer f-strings (`f"..."`) over `.format()` or `%`
  formatting for readability and performance.
- **Path Management:** Prefer the modern `pathlib` module for file and
  directory path manipulations over string concatenation or `os.path`.
- **Imports:** Group imports logically: standard library first, followed by
  third-party libraries such as `discord`, `playwright`, and
  `playwright_stealth`, then local imports.
- **Soft Line Length:** Prefer keeping code lines reasonably short, around 88
  characters where practical, to preserve coding-agent context and improve
  review readability. Treat this as a soft rule: clarity and stable formatting
  are more important than awkward wrapping.
- **Logging:** Use `downloader.logging_utils.log()` for console output within
  the downloader package to ensure consistent, timestamped logging. Use the
  configured `discord_bot.py` logger for bot startup, shutdown, and error
  messages so console and file logs stay consistent.
- **Resource Management:** Prefer context managers (`with` statements) for file
  I/O, network streams, and locks to guarantee proper cleanup of resources
  even when exceptions occur.
- **Exception Handling:** Avoid bare `except:` clauses. Always catch specific
  exceptions (for example, Playwright or SQLite exceptions) or at minimum
  `Exception` to avoid swallowing system-level exits.

## 2. Architecture & Concurrency Constraints

- **Event Loop Blocking:** The Discord bot operates on an asynchronous event
  loop (`asyncio`). The downloading engine is heavily I/O bound and synchronous.
  Never call synchronous downloader I/O directly from `discord_bot.py`'s event
  loop. Wrap calls to the downloader using `asyncio.to_thread` or equivalent.
- **State Locking:** Ensure only one download session runs at a time using an
  async-aware lock, such as `asyncio.Lock`, to reduce rate-limit risk and avoid
  overlapping writes.
- **Module Boundaries:** Keep orchestration in `downloader.session`, saved-post
  workflow logic in `downloader.downloads`, SQLite logic in
  `downloader.history`, report formatting in `downloader.reporting`, and
  Discord-specific behavior in `discord_bot.py`.
- **Account Scope:** Download sessions process one configured Instagram account
  per run. Users may switch accounts between runs by changing `ig_name` and
  switching Firefox to that account, but the code should not iterate multiple
  configured accounts in one session.
- **Media Retrieval:** Keep Instagram media fallback logic layered and
  observable. Blob-video handling should prefer progressive audio-included MP4
  sources before DASH or captured playback fallbacks, and carousel stream
  deduplication should compare stable asset identifiers rather than raw CDN
  URLs alone.

## 3. Database Guidelines

- **Idempotency:** When interacting with the account-specific SQLite databases
  (`download_history_<account>.db`), rely on SQL constraints to maintain
  idempotency. Use `INSERT OR IGNORE` to prevent duplicate tracking of
  downloaded posts.
- **Account Isolation:** Keep history databases and default download folders
  keyed by the configured Instagram account name so manually switched accounts
  retain separate state across runs.
- **History Syncing:** Changes to how posts are considered downloaded, skipped,
  or stale must update `downloader.history` and any affected report counters.
- **Connection Management:** Ensure all database connections are committed when
  needed and closed after use to prevent locking the `.db` file.

## 4. Discord Integration

- **Message Limits:** Discord has a strict 2000-character limit per message.
  Any reports or logs sent back through the bot must be validated and truncated
  if they exceed this limit.
- **Error Handling & Reporting:** Catch exceptions during a download session,
  especially per-post download failures, and record them in the `DownloadStats`
  dataclass. Safely report this summary back to the Discord channel rather than
  crashing the bot.
- **User Commands:** Keep command parsing simple and predictable. `!download`
  should mean unlimited downloads, while `!download <positive integer>` should
  limit the session.

## 5. Security

- **Credentials:** Never hardcode Discord tokens, Instagram usernames, or
  browser session details in source code. Use `configparser` to read the
  per-run Instagram username and Discord credentials from `settings.ini`;
  derive Instagram authentication from the user's active Firefox cookies.
- **Version Control:** Ensure `settings.ini`, `download_history*`, downloaded
  media files, browser session artifacts, logs, and Python caches are excluded
  from version control through `.gitignore`.

## 6. Versioning, Workflow & Changelog

- Follow Semantic Versioning.
- Document all notable changes in `CHANGELOG.md` following the Keep a Changelog format.
- Keep the `CHANGELOG.md` updated in the same commit as the feature addition or bug fix.
- **Commit Messages:** Prefer Conventional Commits (e.g., `feat:`, `fix:`,
  `docs:`, `refactor:`) to maintain a clean and easily readable git history.
- **Dependencies:** If a new third-party library is required, it must be
  justified and added to the project's dependency tracking (e.g.,
  `requirements.txt`).

## 7. Tooling & Linting

- **Formatting:** The 88-character line limit and general structure align with
  `black`. Code should ideally be formatted with it.
  Use `isort` to automatically enforce the logical import grouping rules.
- **Type Checking:** Code should pass strict type checking (e.g., `mypy`).
- **Linting:** Use standard linters like `flake8` or `ruff` to catch unused
  imports, unused variables, and style violations.

## 8. Testing (If Applicable)

- **Framework:** Use `pytest` for any unit testing.
- **Mocking:** Automated tests should never hit the live Instagram or Discord
  APIs. Mock external network requests using `unittest.mock` or `pytest-mock`.

## 9. Development Workflow & Pull Requests

- **Virtual Environments:** Always use a Python virtual environment (e.g.,
  `venv`) for local development to avoid polluting global packages.
- **Branching:** Use descriptive branch names based on the work being done
  (e.g., `feature/slash-commands`, `bugfix/rate-limit-crash`,
  `docs/update-readme`).
- **Pull Requests:** Keep PRs small and focused on a single issue or feature.
  Ensure all local tests and type checks pass before requesting a review.
