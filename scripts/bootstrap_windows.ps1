[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $Root '.runtime'
$PythonRoot = Join-Path $RuntimeRoot 'python'
$Downloads = Join-Path $RuntimeRoot 'downloads'
$Logs = Join-Path $Root 'logs'
$LauncherLog = Join-Path $Logs 'launcher.log'
$PythonVersion = '3.14.8'

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $Downloads, $Logs | Out-Null

function Write-LauncherLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '{0} | {1} | {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-RuntimeSpec {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
    switch ($arch.ToUpperInvariant()) {
        'AMD64' {
            return @{
                Arch = 'amd64'
                Url = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embeddable-amd64.zip'
                Sha256 = '80292f0e640e373a54bf09f3b94a1472f976f24a10c5bed0d9622e4e44d67447'
            }
        }
        'ARM64' {
            return @{
                Arch = 'arm64'
                Url = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embeddable-arm64.zip'
                Sha256 = '3d5cf5f4ec055b1dc2882fe6fbaaeb483d1984dd5335ae9ac692e0c6b3ce8785'
            }
        }
        default {
            throw "SAYURI-BOOT-001: Unsupported Windows architecture: $arch. Supported: AMD64, ARM64."
        }
    }
}

function Test-PortablePython {
    $python = Join-Path $PythonRoot 'python.exe'
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    try {
        $reported = & $python -c "import platform; print(platform.python_version())" 2>$null
        return ($LASTEXITCODE -eq 0 -and $reported.Trim() -eq $PythonVersion)
    }
    catch { return $false }
}

function Install-PortablePython {
    $spec = Get-RuntimeSpec
    $archive = Join-Path $Downloads ("python-{0}-{1}.zip" -f $PythonVersion, $spec.Arch)
    Write-LauncherLog "Installing portable Python $PythonVersion ($($spec.Arch)) into project runtime."

    if (Test-Path -LiteralPath $archive) {
        $cachedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($cachedHash -ne $spec.Sha256) {
            Write-LauncherLog "Cached runtime hash mismatch; removing archive." 'WARN'
            Remove-Item -Force -LiteralPath $archive
        }
    }

    if (-not (Test-Path -LiteralPath $archive)) {
        Write-LauncherLog "Downloading Python runtime from python.org."
        Invoke-WebRequest -UseBasicParsing -Uri $spec.Url -OutFile $archive
    }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actualHash -ne $spec.Sha256) {
        Remove-Item -Force -LiteralPath $archive -ErrorAction SilentlyContinue
        throw "SAYURI-BOOT-002: Python runtime SHA256 mismatch. Expected $($spec.Sha256), got $actualHash."
    }

    if (Test-Path -LiteralPath $PythonRoot) {
        Remove-Item -Recurse -Force -LiteralPath $PythonRoot
    }
    New-Item -ItemType Directory -Force -Path $PythonRoot | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $PythonRoot -Force

    $pth = Get-ChildItem -LiteralPath $PythonRoot -Filter 'python*._pth' | Select-Object -First 1
    if (-not $pth) {
        throw 'SAYURI-BOOT-003: Embedded Python _pth file was not found after extraction.'
    }
    $lines = Get-Content -LiteralPath $pth.FullName
    if ($lines -notcontains '..\..') {
        $lines += '..\..'
        Set-Content -LiteralPath $pth.FullName -Value $lines -Encoding ASCII
    }

    if (-not (Test-PortablePython)) {
        throw "SAYURI-BOOT-004: Portable Python $PythonVersion failed its runtime check."
    }
    Write-LauncherLog "Portable Python installation verified."
}

try {
    Write-LauncherLog "Launcher started. Root=$Root"
    if (-not (Test-PortablePython)) {
        Install-PortablePython
    }
    else {
        Write-LauncherLog "Portable Python $PythonVersion already ready."
    }

    $python = Join-Path $PythonRoot 'python.exe'
    Push-Location $Root
    try {
        Write-LauncherLog 'Running preflight checks.'
        & $python -m app.preflight
        if ($LASTEXITCODE -ne 0) {
            throw "SAYURI-PREFLIGHT-001: Preflight exited with code $LASTEXITCODE."
        }

        Write-LauncherLog 'Starting Sayuri local server. Browser will open automatically after health check.'
        & $python -m app.main
        $exitCode = $LASTEXITCODE
        Write-LauncherLog "Sayuri process finished with code $exitCode."
        exit $exitCode
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-LauncherLog $_.Exception.Message 'ERROR'
    Write-LauncherLog $_.ScriptStackTrace 'ERROR'
    exit 1
}
