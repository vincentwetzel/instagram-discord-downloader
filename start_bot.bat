@echo off
echo ===================================================
echo Stopping any running bot instances...
echo ===================================================

:: Kill visible console-based running instances via their title
taskkill /FI "WINDOWTITLE eq IG_Discord_Bot_Running" /F >nul 2>&1

:: Kill headless background pythonw instances running this specific script
powershell -Command "Get-CimInstance Win32_Process -Filter \"CommandLine Like '%%discord_bot.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo ===================================================
echo Starting Instagram Discord Downloader Bot in background...
echo ===================================================

:: Run the bot in the background using pythonw
start "" pythonw discord_bot.py

echo [OK] Bot has been launched. This window will now close.
timeout /t 3 >nul