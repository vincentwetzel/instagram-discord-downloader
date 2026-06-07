# Instagram Discord Downloader

A Discord bot and command-line downloader for saving new Instagram saved posts
to your local machine with Instaloader. Downloads are tracked in SQLite so
repeat runs skip posts that were already saved.

## Features

- Trigger downloads from Discord with `!download` or `!download <limit>`.
- Run the downloader directly from the terminal for manual sessions.
- Authenticate with an Instaloader session file, Instagram credentials, 2FA, or
  Firefox cookies as a fallback.
- Track downloaded post shortcodes in `download_history.db` with idempotent
  `INSERT OR IGNORE` writes.
- Prune stale history entries when posts are no longer in saved posts.
- Return a session report to Discord, truncated safely for Discord's message
  limit.

## Setup

1. **Install dependencies:**

   ```bash
   pip install discord.py instaloader
   ```

2. **Create `settings.ini`:**

   Add the file in the project root. The Discord section is required for the
   bot. The Instagram password is optional if you already have a valid
   Instaloader session file or Firefox cookies.

   ```ini
   [Discord]
   token = YOUR_DISCORD_BOT_TOKEN

   [Credentials]
   ig_name = your_instagram_username
   pw = your_instagram_password
   ```

3. **Run the Discord bot:**

   ```bash
   python discord_bot.py
   ```

4. **Or run the downloader directly:**

   ```bash
   python instaloader_downloader.py
   ```

## Usage

- Invite the bot to your server.
- Type `!download` in a channel to download all new saved posts.
- Type `!download 10` to limit the session to a maximum of 10 posts.

Downloaded media is written to a folder named after the configured Instagram
account. Local runtime state such as `settings.ini`, `download_history.db`,
media folders, and Python caches are intentionally ignored by Git.

## Project Layout

- `discord_bot.py`: Discord command surface and concurrency lock.
- `instaloader_downloader.py`: Compatibility entry point for CLI use and older
  imports.
- `downloader/`: Focused modules for auth, configuration, downloads, history,
  reporting, timing, logging, and Instaloader version checks.
- `ARCHITECTURE.md`: Component and data-flow overview.
- `CODING_STANDARDS.md`: Style, concurrency, database, and security rules.
- `CHANGELOG.md`: Notable project changes.
