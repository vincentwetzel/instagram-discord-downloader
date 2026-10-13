param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectDir
)

$ErrorActionPreference = 'Stop'
$ProjectDir = [System.IO.Path]::GetFullPath($ProjectDir)
$RunDir = Join-Path $ProjectDir 'run'
$PythonExe = $env:INSTAGRAM_DISCORD_DOWNLOADER_PYTHON_EXE
if (-not $PythonExe) {
    $PythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe'
}
$LockPath = Join-Path $RunDir 'supervisor.lock'
$PidPath = Join-Path $RunDir 'supervisor.pid'
$StopPath = Join-Path $RunDir 'stop.request'
$RestartPath = Join-Path $RunDir 'restart.request'
$BotScript = Join-Path $ProjectDir 'instagram_discord_downloader_bot.py'

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    exit 2
}
if (-not (Test-Path -LiteralPath $BotScript -PathType Leaf)) {
    exit 2
}

New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
try {
    # FileShare.None provides a process-lifetime lock and releases on exit.
    $Lock = [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    # A running supervisor will observe the start helper's restart request.
    exit 0
}

try {
    [System.IO.File]::WriteAllText($PidPath, [string] $PID)
    Remove-Item -LiteralPath $StopPath, $RestartPath -Force -ErrorAction SilentlyContinue

    while ($true) {
        $QuotedBotScript = '"' + $BotScript + '"'
        $Child = Start-Process `
            -FilePath $PythonExe `
            -ArgumentList @($QuotedBotScript, '--run-bot') `
            -WorkingDirectory $ProjectDir `
            -WindowStyle Hidden `
            -PassThru

        $RequestedAction = $null
        while (-not $Child.HasExited) {
            if (Test-Path -LiteralPath $StopPath) {
                $RequestedAction = 'stop'
                break
            }
            if (Test-Path -LiteralPath $RestartPath) {
                $RequestedAction = 'restart'
                break
            }
            Start-Sleep -Seconds 1
            $Child.Refresh()
        }

        if ($RequestedAction) {
            $Deadline = [DateTime]::UtcNow.AddSeconds(25)
            while (-not $Child.HasExited -and [DateTime]::UtcNow -lt $Deadline) {
                Start-Sleep -Milliseconds 250
                $Child.Refresh()
            }
            if (-not $Child.HasExited) {
                # A stuck bot must not retain the supervisor or request forever.
                Stop-Process -Id $Child.Id -Force -ErrorAction SilentlyContinue
                $Child.WaitForExit()
            }
        }

        if ((Test-Path -LiteralPath $StopPath) -or $RequestedAction -eq 'stop') {
            Remove-Item -LiteralPath $StopPath, $RestartPath -Force -ErrorAction SilentlyContinue
            break
        }
        if ((Test-Path -LiteralPath $RestartPath) -or $RequestedAction -eq 'restart') {
            Remove-Item -LiteralPath $RestartPath -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
            continue
        }

        # Restart after any unexpected bot exit, including exit code zero.
        Start-Sleep -Seconds 5
    }
} finally {
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    if ($Lock) {
        $Lock.Dispose()
    }
}
