@echo off
echo ===================================================
echo Starting Instagram Discord Downloader Bot in background...
echo ===================================================

:: Run the bot in the background using pythonw
start "" pythonw discord_bot.py

echo [OK] Bot has been launched. This window will now close.
timeout /t 3 >nul