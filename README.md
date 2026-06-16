# Instagram Discord Downloader

A Discord bot and command-line downloader for saving new Instagram saved posts
to your local machine with Playwright-driven browser automation. Downloads are
tracked in account-specific SQLite databases so repeat runs skip posts that were
already saved.

## Features

- Trigger downloads from Discord with `/ig_download`, `!download`, or a numeric
  direct message to the bot owner account. Supports batch processing of multiple
  accounts in sequence.
- Limit a session with `/ig_download max_posts:10`, `!download 10`, or a DM
  containing only a positive integer.
- Send owner direct messages when the bot comes online or shuts down cleanly.
- Show live progress by editing the initial Discord status message.
- Write Discord bot runtime logs to both the console and timestamped files under
  `logs/`, keeping only recent runs.
- Prevent overlapping sessions with an async download lock and a local
  single-instance socket lock.
- Authenticate by reusing an active Firefox Instagram session cookie database.
- Track downloaded post shortcodes in `download_history_<account>.db` with
  idempotent `INSERT OR IGNORE` writes.
- Prune stale history entries when posts are no longer in saved posts.
- Return a session report to Discord, truncated safely for Discord's message
  limit.

## Setup

### 1. Create a Discord Bot

If you've never made a Discord bot before, follow these steps:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and log in with your Discord account.
2. Click the **New Application** button in the top right, give it a name (like
   "IG Downloader"), and click **Create**.
3. On the left menu, click **Bot**.
4. Under the **Privileged Gateway Intents** section, toggle
   **Message Content Intent** to ON and save changes. This is required for the
   bot to read `!download` commands.
5. Scroll up to the **Token** section and click **Reset Token**. Copy this long
   string of text. **Keep this secret!** This is your `YOUR_DISCORD_BOT_TOKEN`.

### 2. Invite the Bot to Your Server

1. Still in the Developer Portal, click **OAuth2** > **URL Generator** on the
   left menu.
2. Under **Scopes**, check the box for `bot`.
3. Under **Bot Permissions**, check `Send Messages` and `Read Message History`.
4. Scroll down, copy the **Generated URL**, and paste it into a new tab in your
   web browser.
5. Select your Discord server from the dropdown and authorize the bot to join.

### 3. Get Your Discord User ID

To ensure only you can trigger downloads, you need your unique User ID.

1. Open Discord, go to **User Settings** (the gear icon bottom left) >
   **Advanced**.
2. Toggle **Developer Mode** to ON.
3. Close settings, right-click your own profile name in any chat or server
   sidebar, and click **Copy User ID**. This is your `YOUR_DISCORD_USER_ID`.

### 4. Install Dependencies

Make sure you have Python installed. Open your computer's terminal or command
prompt in this folder and run:

```bash
pip install discord.py playwright playwright-stealth
playwright install chromium
```

### 5. Configuration (`settings.ini`)

Create a file named `settings.ini` in the same folder as the scripts and paste
the following inside it, replacing the placeholder text with your actual
details:

```ini
[Discord]
discord_bot_token = YOUR_DISCORD_BOT_TOKEN
allowed_user_id = YOUR_DISCORD_USER_ID
[Credentials]
ig_name = first_username, second_username
```

The downloader uses your active Firefox Instagram session for authentication.
Log into Instagram in Firefox as the account you want to download before running
the bot. For multiple configured usernames, switch the active Firefox session to
the account being processed.

### 6. Run the Bot

In your terminal or command prompt, run:

```bash
python discord_bot.py
```

If you see log messages saying "Logged in as..." and
"Ready to receive commands!", you are good to go. The same startup and error
logs are also written to timestamped files under `logs/` for troubleshooting.

On Windows, you can also use:

- `start_bot.bat` to launch the bot in the background with `pythonw`.
- `stop_bot.bat` to stop the background bot process by the local socket lock
  port or console title.

## Usage

Now that the bot is running and in your server:

- Go to your Discord server and type `/ig_download` (or `!download`) in any
  channel the bot can see to download **all** new saved posts.
- Use `/ig_download max_posts:10` (or `!download 10`) to limit the session to a
  maximum of 10 posts.
- Send the bot a direct message containing only a number, such as `10`, to run
  a limited session from DMs.

If the bot reports that no Firefox session was found or that the account does
not match, log into the requested Instagram account in Firefox and run the
command again.

## Command-Line Usage

Run the downloader directly without Discord:

```bash
python instaloader_downloader.py
```

Downloaded media is written under `downloads/`. Local runtime state such as
`settings.ini`, `download_history_<account>.db`, `logs/`, media files, browser
session artifacts, and Python caches are intentionally ignored by Git.

## Project Layout

- `discord_bot.py`: Discord command surface, owner authorization, progress
  updates, shutdown notices, runtime logging, and concurrency locks.
- `instaloader_downloader.py`: Compatibility entry point for CLI use and older
  imports.
- `downloader/`: Focused modules for auth, configuration, downloads, history,
  reporting, timing, logging, and Instaloader version checks.
- `start_bot.bat` / `stop_bot.bat`: Windows helpers for background bot
  management.
- `ARCHITECTURE.md`: Component and data-flow overview.
- `CODING_STANDARDS.md`: Style, concurrency, database, and security rules.
- `CHANGELOG.md`: Notable project changes.
