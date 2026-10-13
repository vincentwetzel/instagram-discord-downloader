@echo off
setlocal
for %%I in ("%~dp0.") do set "PROJECT_DIR=%%~fI"
set "RUN_DIR=%PROJECT_DIR%\run"
set "STOP_PATH=%RUN_DIR%\stop.request"
set "PID_PATH=%RUN_DIR%\supervisor.pid"

if not exist "%PID_PATH%" (
    echo No running supervisor was found.
    exit /b 0
)

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%" >nul 2>&1
> "%STOP_PATH%" echo stop

for /l %%I in (1,1,35) do (
    if not exist "%PID_PATH%" (
        echo Instagram Discord Downloader stopped.
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)

echo Stop requested, but the supervisor has not exited yet.
echo Check the newest log under "%PROJECT_DIR%\logs".
exit /b 1
