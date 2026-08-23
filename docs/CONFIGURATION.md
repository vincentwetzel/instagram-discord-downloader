# Configuration and Runtime State

The bot reads `settings.ini` from the project directory. The file contains a
secret and an authorization setting, so it must remain local and uncommitted.

## Settings

```ini
[Discord]
discord_bot_token = YOUR_DISCORD_BOT_TOKEN
allowed_user_id = YOUR_DISCORD_USER_ID

[Storage]
base_download_path = downloads/{account_name}
```

`[Discord]` is required by the bot:

- `discord_bot_token` is the bot token from the Discord Developer Portal.
- `allowed_user_id` is the numeric Discord user ID permitted to start runs.

`[Storage]` is optional. If `base_download_path` is absent, media is written to
`downloads/<active_account>/`. The path may be absolute and may contain either
`{account_name}` or `{username}`. Both placeholders resolve to the Instagram
account discovered from the active Firefox session.

The current implementation does not read an Instagram username from
`settings.ini`. Log into the desired Instagram account in Firefox before each
run. The configured Discord user and the active Firefox account are independent
settings.

The storage template is read with interpolation disabled, so Windows paths and
literal percent signs are safe to use. The two supported placeholders are
replaced with the discovered Instagram username before the output directory is
created.

## Account isolation

One run processes one account: the account detected from Firefox. Its history
is stored in `download_history_<account>.db`, where `<account>` is the detected
username. To switch accounts, switch the active Firefox Instagram session and
start a new run. The downloader will use the new account's database and storage
directory.

The history table uses the post shortcode as its primary key. Successful
downloads use `INSERT OR IGNORE`, and rows for posts no longer in Saved posts
are pruned before the next download batch.

## Local runtime files

Expected local state includes:

- `settings.ini` — Discord credentials and optional storage configuration.
- `download_history_<account>.db` — account-specific downloaded-post history.
- `downloads/` or the configured storage directory — downloaded media.
- `logs/` — timestamped bot logs; the five newest bot logs are retained.
- Firefox cookie/profile data and Python caches — read or generated locally.

Do not delete a history database unless you intentionally want its account's
saved posts to be processed again.

The downloader does not store credentials in the history database. Firefox
cookies are read locally to create a temporary Playwright browser context; the
bot token is read only from `settings.ini` by the Discord entry point.
