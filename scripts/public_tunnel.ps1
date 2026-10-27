param(
    [ValidateSet('Start', 'Run', 'Stop', 'Status')]
    [string]$Action = 'Status'
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Run this script with PowerShell 7 (pwsh).'
}
$ScriptFile = $PSCommandPath
$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root 'work/public-access'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

function Get-TunnelRunner {
    Get-CimInstance Win32_Process -Filter "Name = 'pwsh.exe'" |
        Where-Object {
            $_.ProcessId -ne $PID -and $_.CommandLine -and
            $_.CommandLine.Contains($ScriptFile) -and
            $_.CommandLine -match '-Action\s+Run(?:\s|$)'
        }
}

switch ($Action) {
    'Start' {
        $Running = @(Get-TunnelRunner)
        if ($Running.Count) {
            Write-Output "Tunnel supervisor already running: $($Running.ProcessId -join ', ')"
            return
        }
        $Arguments = '-NoProfile -File "' + $ScriptFile + '" -Action Run'
        $Process = Start-Process -FilePath (Join-Path $PSHOME 'pwsh.exe') -ArgumentList $Arguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime 'tunnel.log') -RedirectStandardError (Join-Path $Runtime 'tunnel.error.log')
        Write-Output "Tunnel supervisor started: $($Process.Id)"
    }
    'Run' {
        while ($true) {
            Write-Output "$(Get-Date -Format o) Connecting SSH reverse tunnel to LLLL"
            & ssh.exe -NT -o BatchMode=yes -o ConnectTimeout=15 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18081:127.0.0.1:18080 LLLL
            Write-Output "$(Get-Date -Format o) SSH exited ($LASTEXITCODE); reconnecting in 5 seconds"
            Start-Sleep -Seconds 5
        }
    }
    'Stop' {
        foreach ($Runner in @(Get-TunnelRunner)) {
            $Children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Runner.ProcessId)" | Where-Object { $_.Name -eq 'ssh.exe' -and $_.CommandLine -like '*127.0.0.1:18081:127.0.0.1:18080*' })
            Stop-Process -Id $Runner.ProcessId
            foreach ($Child in $Children) {
                Stop-Process -Id $Child.ProcessId -ErrorAction SilentlyContinue
            }
            Write-Output "Stopped this project's tunnel supervisor: $($Runner.ProcessId)"
        }
    }
    'Status' {
        $Running = @(Get-TunnelRunner)
        if ($Running.Count) {
            Write-Output "Tunnel supervisor running: $($Running.ProcessId -join ', ')"
        } else {
            Write-Output 'Tunnel supervisor stopped'
        }
    }
}
