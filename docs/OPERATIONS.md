# Operations Guide

## Start and stop

Run the supervised bot from the project directory:

```powershell
python instagram_discord_downloader_bot.py
```

The supervisor owns `127.0.0.1:47200`, launches the bot child process, and
restarts it after an unexpected child exit. Press `Ctrl+C` in the supervisor
window to stop it cleanly.

On Windows, use these helpers when running in the background:

```text
start_instagram_discord_downloader.bat
stop_instagram_discord_downloader.bat
```

The start helper stops matching existing bot processes before launching a new
background process. The stop helper looks for the bot window title and the
single-instance UDP port. Both helpers are project-local files and should be
run from the project directory.

For a direct run without Discord:

```powershell
python instaloader_downloader.py
```

The CLI asks for a positive post limit; press Enter for unlimited.

## Before a download

1. Log into Instagram in Firefox using the account to process.
2. Leave the Firefox profile available so its cookie database can be found.
3. Confirm `settings.ini` contains a valid bot token and numeric owner ID.
4. Confirm the configured storage location is writable.
5. Start only one bot process.

During a carousel download, the downloader stages each media item in a hidden
`.part` file in the configured storage directory. These files are renamed to
their final filenames after the post is collected and are removed when the
post fails. A leftover `.part` file from an interrupted process is incomplete
media and can be deleted safely after confirming no download is running.

## Commands

- `/ig_download` or `!download` processes all new saved posts.
- `/ig_download max_posts:10` or `!download 10` limits the run to 10 posts.
- An owner DM containing only `10` starts a limited run.

The bot rejects other users, rejects non-positive limits, and rejects a second
request while a session is already running.

## Troubleshooting

### No Firefox session or Instagram cookies found

Log into Instagram in Firefox and retry. If Firefox has multiple profiles,
activate the profile containing the Instagram session before starting the bot.
The account is detected from that session; it is not selected by a Discord
argument or a username setting.

### The active account or Saved page is wrong

Sign out of other Instagram Firefox profiles, switch to the intended account,
and start a new run. Check the log for the `Active Instagram account discovered`
message and ensure the account has access to Saved posts.

### The slash command has the wrong shape

Restart the bot. On readiness it removes matching stale guild registrations and
syncs the current global `/ig_download` command. Discord may take a short time
to refresh its command cache.

### The bot is already running

Run `stop_instagram_discord_downloader.bat` and then start the bot again. The
single-instance lock is a UDP socket, not a lock file. If the stop helper cannot
find the process, inspect the latest log and check which process owns port
`47200` before terminating it manually.

### A run fails or media is missing

Review the newest `logs/discord_bot_<timestamp>.log`. Confirm the Firefox
session and network connection, then retry. The downloader uses multiple media
fallbacks, but Instagram layout or session changes can still prevent a post
from being resolved. Keep the history database unless you deliberately want to
reprocess that account's posts.

If the computer sleeps during a run, the downloader detects a lost browser
connection, relaunches the browser, and resumes from the account history. The
retry is bounded at three total browser attempts; if wake recovery still fails,
the report and log contain the underlying browser error.

The log contains bot lifecycle events, Discord library output, downloader
progress, and full tracebacks for failed download sessions. The background
helper uses `pythonw`, so the log is the primary place to inspect output after
startup or a crash. The supervisor and child each create a timestamped log;
the child log normally contains the Discord connection and download details.

### Discord reports are incomplete

The bot caps long reports and errors before sending them. Use the local log for
the complete session details, including per-post error information.

## Maintenance

Keep settings, databases, media, logs, browser artifacts, and Python caches out
of version control. When behavior changes, update the relevant architecture or
configuration section and add a concise entry to `docs/CHANGELOG.md`.
