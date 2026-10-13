@echo off
setlocal
for %%I in ("%~dp0.") do set "PROJECT_DIR=%%~fI"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE="
    for /f "delims=" %%I in ('where.exe python.exe 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
)

if not defined PYTHON_EXE (
    echo Python was not found in .venv or on PATH.
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 or later is required. Found interpreter: "%PYTHON_EXE%"
    exit /b 1
)

if not exist "%PROJECT_DIR%\instagram_discord_downloader_bot.py" (
    echo Bot entry point not found under: "%PROJECT_DIR%"
    exit /b 1
)
if not exist "%PROJECT_DIR%\supervise_instagram_discord_downloader.ps1" (
    echo Supervisor script not found under: "%PROJECT_DIR%"
    exit /b 1
)

"%PYTHON_EXE%" -c "import discord, playwright" >nul 2>&1
if errorlevel 1 (
    echo Required Python libraries are missing for: "%PYTHON_EXE%"
    echo Install them with: "%PYTHON_EXE%" -m pip install discord.py playwright playwright-stealth
    exit /b 1
)

set "RUN_DIR=%PROJECT_DIR%\run"
if not exist "%RUN_DIR%" mkdir "%RUN_DIR%" >nul 2>&1
if exist "%RUN_DIR%\stop.request" del /q "%RUN_DIR%\stop.request" >nul 2>&1
> "%RUN_DIR%\restart.request" echo restart
set "INSTAGRAM_DISCORD_DOWNLOADER_PROJECT_DIR=%PROJECT_DIR%"
set "INSTAGRAM_DISCORD_DOWNLOADER_PYTHON_EXE=%PYTHON_EXE%"

powershell -NoProfile -Command "$project = $env:INSTAGRAM_DISCORD_DOWNLOADER_PROJECT_DIR; $supervisor = Join-Path $project 'supervise_instagram_discord_downloader.ps1'; $q = [char]34; $arguments = '-NoProfile -ExecutionPolicy Bypass -File ' + $q + $supervisor + $q + ' -ProjectDir ' + $q + $project + $q; Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $project -WindowStyle Hidden" >nul 2>&1
if errorlevel 1 (
    echo Could not start the bot supervisor.
    exit /b 1
)

echo Instagram Discord Downloader start or restart requested.
exit /b 0
