@echo off
echo ===================================================
echo Stopping Instagram Discord Downloader Bot...
echo ===================================================

:: Method 1: Try to kill by Window Title (if run via standard python.exe)
taskkill /F /FI "WINDOWTITLE eq IG_Discord_Bot_Running*" /T >nul 2>&1
set "KILLED="
if %errorlevel% equ 0 set KILLED=1

:: Method 2: Try to find the PID using port 47200 (UDP) and kill it (works for pythonw.exe)
for /f "tokens=4" %%a in ('netstat -aon ^| findstr "127.0.0.1:47200"') do (
    taskkill /F /PID %%a >nul 2>&1 && set KILLED=1
)

if defined KILLED (
    echo [OK] Bot successfully stopped.
) else (
    echo [INFO] No running bot was found.
)
