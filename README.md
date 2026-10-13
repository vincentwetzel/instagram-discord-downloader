# Instagram Discord Downloader

This project downloads new posts saved by the Instagram account that is active
in Firefox. It provides a Discord bot and an interactive command-line entry
point. Downloaded post shortcodes are tracked in an account-specific SQLite
database so later runs skip posts that are already saved locally.

## Features

- `/ig_download`, `!download`, and owner-only numeric direct messages.
- Optional positive post limit for each run; omit it to process all new posts.
- Firefox-cookie authentication with one active Instagram account per run.
- Post, reel, and carousel media retrieval through layered Playwright fallbacks.
- Progressive MP4 preference for blob videos and asset-aware carousel deduplication.
- Per-item media staging to limit memory use during long carousel downloads.
- Owner/timestamp-based filenames when Instagram metadata is available.
- Account-specific history databases with idempotent writes and stale-entry pruning.
- Live Discord progress updates, runtime logs, and startup/shutdown owner DMs.
- Session locking plus a local single-instance supervisor.

## Requirements

- Windows is the supported operating system for the included batch helpers.
- Python 3.9 or newer.
- A Discord bot with Message Content Intent enabled.
- Firefox logged into Instagram with access to the account's Saved posts.

Install the Python dependencies and the Playwright Chromium browser:

```powershell
python -m pip install discord.py playwright playwright-stealth
python -m playwright install chromium
```

## Configuration

Create `settings.ini` beside the scripts:

```ini
[Discord]
discord_bot_token = YOUR_DISCORD_BOT_TOKEN
allowed_user_id = YOUR_DISCORD_USER_ID

[Storage]
base_download_path = downloads/{account_name}
```

`discord_bot_token` authenticates the bot. `allowed_user_id` is the only
Discord user allowed to start downloads. The `[Storage]` section is optional;
without it, media is stored in `downloads/<active_account>/`. The supported
placeholders are `{account_name}` and `{username}`. Absolute local paths are
also supported.

The downloader does not use an Instagram username from `settings.ini`. Before
each run, log into the desired account in Firefox. The account name is detected
from the active Instagram session and is used for the saved-post URL, history
database, and default storage folder.

Keep `settings.ini` private. Never commit it or paste the bot token into an
issue, log, or chat.

### Creating the Discord bot

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create its bot user and copy the token into `settings.ini`.
3. Enable **Message Content Intent** under **Privileged Gateway Intents**.
4. Invite the bot with the `bot` scope and at least **Send Messages** and
   **Read Message History** permissions.
5. Enable Discord Developer Mode and copy your user ID into `allowed_user_id`.

## Running

On Windows, start the supervised bot with:

```bat
start_instagram_discord_downloader.bat
```

The helper checks the Python interpreter and required libraries before starting
the PowerShell supervisor. The supervisor uses an exclusive file lock under
`run/` and restarts the child bot process after an unexpected exit. Running
`python instagram_discord_downloader_bot.py` directly also starts the supervisor
in the background. Use the helper scripts to start, restart, or stop it:

- `start_instagram_discord_downloader.bat`
- `stop_instagram_discord_downloader.bat`

For sign-in startup, create a shortcut to
`start_instagram_discord_downloader.bat` in `shell:startup` and set **Start in**
to the project directory.

For an interactive run without Discord:

```powershell
python instaloader_downloader.py
```

The CLI prompts for an optional positive post limit. Press Enter for unlimited.
It uses the same Firefox session, account discovery, history database, and
storage rules as the bot.

## Discord commands

| Command | Result |
| --- | --- |
| `/ig_download` | Download all new saved posts. |
| `/ig_download max_posts:10` | Download at most 10 posts. |
| `!download` | Prefix-command equivalent of the slash command. |
| `!download 10` | Prefix-command equivalent with a limit. |
| Owner DM containing `10` | Start a limited run from a direct message. |

Only the configured owner can use these commands. A second request is rejected
while a session is running. The slash command accepts only the optional
`max_posts` argument; it does not select an Instagram account.

## Runtime files

- `download_history_<account>.db`: SQLite history for the detected account.
- `downloads/` or the configured storage path: downloaded media.
- `logs/discord_bot_<timestamp>.log`: bot and downloader diagnostics. The
  supervisor and child each create timestamped logs; the bot retains the five
  most recent bot log files.
- `settings.ini`: local credentials and storage configuration.

These files, browser artifacts, and Python caches are ignored by Git. A report
is returned to Discord at the end of a run; long reports and errors are capped
before they are sent.

## Recovery behavior

The supervisor restarts the child after an unexpected exit. During a download,
recoverable browser failures trigger up to two additional browser attempts.
Successful posts are written to SQLite as they finish, so a resumed attempt
skips work already completed. Authentication failures, rate-limit failures, and
other non-recoverable errors are reported without retrying indefinitely.

## Documentation

- [Architecture](docs/ARCHITECTURE.md): components, data flow, and module boundaries.
- [Configuration](docs/CONFIGURATION.md): settings and account-scoped state.
- [Operations](docs/OPERATIONS.md): startup, recovery, and troubleshooting.
- [Coding standards](docs/CODING_STANDARDS.md): project development rules.
- [Changelog](docs/CHANGELOG.md): notable changes.
