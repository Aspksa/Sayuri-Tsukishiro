[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $Root '.runtime'
$PythonRoot = Join-Path $RuntimeRoot 'python'
$PackagesRoot = Join-Path $RuntimeRoot 'packages'
$TesseractRoot = Join-Path $RuntimeRoot 'tesseract'
$TessdataRoot = Join-Path $RuntimeRoot 'tessdata'
$PhoneRuntimeRoot = Join-Path $RuntimeRoot 'phone'
$ScrcpyRoot = Join-Path $PhoneRuntimeRoot 'scrcpy'
$Downloads = Join-Path $RuntimeRoot 'downloads'
$Logs = Join-Path $Root 'logs'
$LauncherLog = Join-Path $Logs 'launcher.log'

$PythonVersion = '3.14.8'
$PdfiumVersion = '5.13.0'
$PillowVersion = '12.3.0'
$TesseractVersion = '5.5.3'
$TessdataVersion = '4.1.0'
$ScrcpyVersion = '4.1'

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
                PdfiumFilename = 'pypdfium2-5.13.0-py3-none-win_amd64.whl'
                PdfiumSha256 = '47dcca2a8d507b5fd24f94c3c9d48fb379430f097bc20f01beff6c963ffbcedb'
                PillowFilename = 'pillow-12.3.0-cp314-cp314-win_amd64.whl'
                PillowSha256 = 'fdafc9cce40277e0f7a0feabce0ee50dd2fa1800f3b38015e51296b5e814048d'
                AutoTesseract = $true
                AutoScrcpy = $true
                ScrcpyFilename = 'scrcpy-win64-v4.1.zip'
                ScrcpySha256 = '5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db'
            }
        }
        'ARM64' {
            return @{
                Arch = 'arm64'
                Url = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embeddable-arm64.zip'
                Sha256 = '3d5cf5f4ec055b1dc2882fe6fbaaeb483d1984dd5335ae9ac692e0c6b3ce8785'
                PdfiumFilename = 'pypdfium2-5.13.0-py3-none-win_arm64.whl'
                PdfiumSha256 = '554a0b23376460af1410e3c915906895e2dac67a086b9e6ccde0643a795d3b0d'
                PillowFilename = 'pillow-12.3.0-cp314-cp314-win_arm64.whl'
                PillowSha256 = 'e91206ee562682b51b98ef4b26a6ef48fd84e15fd4c4bc5ec768eb641d206838'
                AutoTesseract = $false
                AutoScrcpy = $false
                ScrcpyFilename = $null
                ScrcpySha256 = $null
            }
        }
        default {
            throw "SAYURI-BOOT-001: Неподдерживаемая архитектура Windows: $arch. Поддерживаются AMD64 и ARM64."
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
    catch {
        return $false
    }
}

function Ensure-PortablePythonPaths {
    $pth = Get-ChildItem -LiteralPath $PythonRoot -Filter 'python*._pth' | Select-Object -First 1
    if (-not $pth) { throw 'SAYURI-BOOT-003: Не найден файл python*._pth.' }
    $lines = @(Get-Content -LiteralPath $pth.FullName)
    $changed = $false
    foreach ($required in @('..\..', '..\packages')) {
        if ($lines -notcontains $required) {
            $lines += $required
            $changed = $true
        }
    }
    if ($changed) { Set-Content -LiteralPath $pth.FullName -Value $lines -Encoding ASCII }
}

function Install-PortablePython {
    $spec = Get-RuntimeSpec
    $archive = Join-Path $Downloads ("python-{0}-{1}.zip" -f $PythonVersion, $spec.Arch)
    Write-LauncherLog "Установка переносимого Python $PythonVersion ($($spec.Arch))."
    if (Test-Path -LiteralPath $archive) {
        $cachedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($cachedHash -ne $spec.Sha256) {
            Write-LauncherLog "Контрольная сумма сохранённого runtime не совпала; архив будет удалён." 'WARN'
            Remove-Item -Force -LiteralPath $archive
        }
    }
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-LauncherLog "Загрузка Python с python.org."
        Invoke-WebRequest -UseBasicParsing -Uri $spec.Url -OutFile $archive
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actualHash -ne $spec.Sha256) {
        Remove-Item -Force -LiteralPath $archive -ErrorAction SilentlyContinue
        throw "SAYURI-BOOT-002: SHA256 Python не совпал."
    }
    if (Test-Path -LiteralPath $PythonRoot) { Remove-Item -Recurse -Force -LiteralPath $PythonRoot }
    New-Item -ItemType Directory -Force -Path $PythonRoot | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $PythonRoot -Force
    Ensure-PortablePythonPaths
    if (-not (Test-PortablePython)) {
        throw "SAYURI-BOOT-004: Переносимый Python $PythonVersion не прошёл проверку."
    }
    Write-LauncherLog "Переносимый Python установлен и проверен."
}

function Download-VerifiedPyPIWheel {
    param([string]$Project, [string]$Version, [string]$Filename, [string]$Sha256)
    $wheel = Join-Path $Downloads $Filename
    if (Test-Path -LiteralPath $wheel) {
        $cachedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheel).Hash.ToLowerInvariant()
        if ($cachedHash -ne $Sha256) {
            Write-LauncherLog "SHA256 сохранённого $Filename не совпал; файл будет удалён." 'WARN'
            Remove-Item -Force -LiteralPath $wheel
        }
    }
    if (-not (Test-Path -LiteralPath $wheel)) {
        $metadata = Invoke-RestMethod -Uri "https://pypi.org/pypi/$Project/$Version/json"
        $asset = $metadata.urls | Where-Object { $_.filename -eq $Filename } | Select-Object -First 1
        if (-not $asset) { throw "SAYURI-SPATIAL-001: На PyPI не найден $Filename." }
        Write-LauncherLog "Загрузка $Project $Version с PyPI."
        Invoke-WebRequest -UseBasicParsing -Uri $asset.url -OutFile $wheel
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheel).Hash.ToLowerInvariant()
    if ($actualHash -ne $Sha256) {
        Remove-Item -Force -LiteralPath $wheel -ErrorAction SilentlyContinue
        throw "SAYURI-SPATIAL-002: SHA256 $Filename не совпал."
    }
    return $wheel
}

function Expand-Wheel {
    param([string]$Wheel)
    New-Item -ItemType Directory -Force -Path $PackagesRoot | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $temp = Join-Path $RuntimeRoot ("wheel-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($Wheel, $temp)
        Get-ChildItem -LiteralPath $temp -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $PackagesRoot -Recurse -Force
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Test-SpatialPython {
    $python = Join-Path $PythonRoot 'python.exe'
    if (-not (Test-Path -LiteralPath $python)) { return $false }
    try {
        $code = "import importlib.metadata as m; import pypdfium2; from PIL import Image; print(m.version('pypdfium2') + '|' + m.version('Pillow'))"
        $reported = & $python -c $code 2>$null
        return ($LASTEXITCODE -eq 0 -and $reported.Trim() -eq "$PdfiumVersion|$PillowVersion")
    }
    catch { return $false }
}

function Install-SpatialPython {
    $spec = Get-RuntimeSpec
    Write-LauncherLog "Подготовка Spatial DNA: PDFium $PdfiumVersion + Pillow $PillowVersion."
    if (Test-Path -LiteralPath $PackagesRoot) { Remove-Item -LiteralPath $PackagesRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $PackagesRoot | Out-Null
    $pdfium = Download-VerifiedPyPIWheel -Project 'pypdfium2' -Version $PdfiumVersion -Filename $spec.PdfiumFilename -Sha256 $spec.PdfiumSha256
    Expand-Wheel -Wheel $pdfium
    $pillow = Download-VerifiedPyPIWheel -Project 'pillow' -Version $PillowVersion -Filename $spec.PillowFilename -Sha256 $spec.PillowSha256
    Expand-Wheel -Wheel $pillow
    if (-not (Test-SpatialPython)) {
        throw "SAYURI-SPATIAL-003: PDFium/Pillow не прошли проверку импорта."
    }
    Write-LauncherLog "Spatial DNA: PDFium $PdfiumVersion + Pillow $PillowVersion готовы."
}

function Resolve-Tesseract {
    $local = Join-Path $TesseractRoot 'tesseract.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    $command = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $candidate = Join-Path $base 'Tesseract-OCR\tesseract.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Install-LocalTesseract {
    $spec = Get-RuntimeSpec
    if (-not $spec.AutoTesseract) {
        throw 'SAYURI-SPATIAL-004: Автоматическая установка Tesseract для этой архитектуры не предусмотрена.'
    }
    $filename = 'tesseract-ocr-w64-setup-5.5.3.20260724.exe'
    $installer = Join-Path $Downloads $filename
    $expected = 'bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4'
    if (Test-Path -LiteralPath $installer) {
        $cached = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
        if ($cached -ne $expected) { Remove-Item -Force -LiteralPath $installer }
    }
    if (-not (Test-Path -LiteralPath $installer)) {
        Write-LauncherLog "Загрузка Tesseract OCR $TesseractVersion с GitHub."
        $url = "https://github.com/tesseract-ocr/tesseract/releases/download/$TesseractVersion/$filename"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Remove-Item -Force -LiteralPath $installer -ErrorAction SilentlyContinue
        throw 'SAYURI-SPATIAL-005: SHA256 Tesseract installer не совпал.'
    }
    if (Test-Path -LiteralPath $TesseractRoot) { Remove-Item -LiteralPath $TesseractRoot -Recurse -Force }
    Write-LauncherLog "Установка локального Tesseract OCR $TesseractVersion."
    & $installer /S /currentuser "/D=$TesseractRoot"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $TesseractRoot 'tesseract.exe'))) {
        throw "SAYURI-SPATIAL-006: Локальный Tesseract не установлен (код $LASTEXITCODE)."
    }
}

function Ensure-TessdataFile {
    param([string]$Name, [string]$Sha256)
    New-Item -ItemType Directory -Force -Path $TessdataRoot | Out-Null
    $target = Join-Path $TessdataRoot $Name
    if (Test-Path -LiteralPath $target) {
        $cachedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
        if ($cachedHash -eq $Sha256) { return }
        Remove-Item -Force -LiteralPath $target
    }
    $url = "https://github.com/tesseract-ocr/tessdata_best/raw/$TessdataVersion/$Name"
    Write-LauncherLog "Загрузка OCR-модели $Name."
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $target
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
    if ($actualHash -ne $Sha256) {
        Remove-Item -Force -LiteralPath $target -ErrorAction SilentlyContinue
        throw "SAYURI-SPATIAL-007: SHA256 OCR-модели $Name не совпал."
    }
}

function Ensure-SpatialRuntime {
    Ensure-PortablePythonPaths
    if (-not (Test-SpatialPython)) {
        try { Install-SpatialPython }
        catch {
            Write-LauncherLog ("Spatial DNA: PDFium/Pillow недоступны; запуск продолжится в ограниченном режиме. " + $_.Exception.Message) 'WARN'
        }
    }
    else {
        Write-LauncherLog "Spatial DNA: PDFium $PdfiumVersion + Pillow $PillowVersion готовы."
    }

    $tesseract = Resolve-Tesseract
    if (-not $tesseract) {
        try {
            Install-LocalTesseract
            $tesseract = Resolve-Tesseract
        }
        catch {
            Write-LauncherLog ("Spatial DNA: Tesseract недоступен; запуск продолжится без OCR. " + $_.Exception.Message) 'WARN'
        }
    }
    if ($tesseract) {
        $env:SAYURI_TESSERACT = $tesseract
        Write-LauncherLog "Spatial DNA: Tesseract OCR готов."
    }

    try {
        Ensure-TessdataFile -Name 'eng.traineddata' -Sha256 '8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba'
        Ensure-TessdataFile -Name 'rus.traineddata' -Sha256 'b617eb6830ffabaaa795dd87ea7fd251adfe9cf0efe05eb9a2e8128b7728d6b6'
        $env:SAYURI_TESSDATA = $TessdataRoot
        $env:TESSDATA_PREFIX = $TessdataRoot
        Write-LauncherLog "Spatial DNA: OCR-модели rus+eng готовы."
    }
    catch {
        Write-LauncherLog ("Spatial DNA: OCR-модели недоступны; запуск продолжится без OCR. " + $_.Exception.Message) 'WARN'
    }
}

function Test-PhoneRuntime {
    $scrcpy = Join-Path $ScrcpyRoot 'scrcpy.exe'
    $adb = Join-Path $ScrcpyRoot 'adb.exe'
    return ((Test-Path -LiteralPath $scrcpy) -and (Test-Path -LiteralPath $adb))
}

function Install-PhoneRuntime {
    $spec = Get-RuntimeSpec
    if (-not $spec.AutoScrcpy) {
        throw 'SAYURI-PHONE-001: Автоматический scrcpy runtime для этой архитектуры не предусмотрен.'
    }

    New-Item -ItemType Directory -Force -Path $PhoneRuntimeRoot | Out-Null
    $archive = Join-Path $Downloads $spec.ScrcpyFilename
    if (Test-Path -LiteralPath $archive) {
        $cached = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
        if ($cached -ne $spec.ScrcpySha256) {
            Write-LauncherLog "SHA256 сохранённого scrcpy runtime не совпал; архив будет удалён." 'WARN'
            Remove-Item -Force -LiteralPath $archive
        }
    }

    if (-not (Test-Path -LiteralPath $archive)) {
        Write-LauncherLog "Загрузка официального scrcpy $ScrcpyVersion с GitHub."
        $url = "https://github.com/Genymobile/scrcpy/releases/download/v$ScrcpyVersion/$($spec.ScrcpyFilename)"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
    }

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actual -ne $spec.ScrcpySha256) {
        Remove-Item -Force -LiteralPath $archive -ErrorAction SilentlyContinue
        throw 'SAYURI-PHONE-002: SHA256 scrcpy runtime не совпал.'
    }

    $temp = Join-Path $RuntimeRoot ("scrcpy-" + [Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $ScrcpyRoot) {
        Remove-Item -LiteralPath $ScrcpyRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $ScrcpyRoot, $temp | Out-Null
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $temp -Force
        $scrcpyExe = Get-ChildItem -LiteralPath $temp -Filter 'scrcpy.exe' -File -Recurse | Select-Object -First 1
        if (-not $scrcpyExe) {
            throw 'SAYURI-PHONE-003: В официальном архиве не найден scrcpy.exe.'
        }
        $sourceDir = $scrcpyExe.Directory.FullName
        Get-ChildItem -LiteralPath $sourceDir -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $ScrcpyRoot -Recurse -Force
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-PhoneRuntime)) {
        throw 'SAYURI-PHONE-004: scrcpy/ADB runtime не прошёл проверку.'
    }
    Write-LauncherLog "Телефон Sayuri: scrcpy $ScrcpyVersion и ADB готовы."
}

function Ensure-PhoneRuntime {
    if (Test-PhoneRuntime) {
        Write-LauncherLog "Телефон Sayuri: scrcpy $ScrcpyVersion и ADB готовы."
        return
    }
    try {
        Install-PhoneRuntime
    }
    catch {
        Write-LauncherLog ("Телефон Sayuri: локальный runtime недоступен; проект запустится без управления телефоном. " + $_.Exception.Message) 'WARN'
    }
}

try {
    Write-LauncherLog "Запуск. Корень проекта: $Root"
    if (-not (Test-PortablePython)) { Install-PortablePython }
    else { Write-LauncherLog "Переносимый Python $PythonVersion готов." }

    Ensure-SpatialRuntime
    Ensure-PhoneRuntime

    $python = Join-Path $PythonRoot 'python.exe'
    Push-Location $Root
    try {
        Write-LauncherLog 'Проверка системы перед запуском.'
        & $python -m app.preflight
        if ($LASTEXITCODE -ne 0) {
            throw "SAYURI-PREFLIGHT-001: Предварительная проверка завершилась с кодом $LASTEXITCODE."
        }
        Write-LauncherLog 'Запуск локального сервера Саюри. Браузер откроется после проверки готовности.'
        & $python -m app.main
        $exitCode = $LASTEXITCODE
        Write-LauncherLog "Процесс Саюри завершён с кодом $exitCode."
        exit $exitCode
    }
    finally { Pop-Location }
}
catch {
    Write-LauncherLog $_.Exception.Message 'ERROR'
    if ($_.ScriptStackTrace) { Write-LauncherLog $_.ScriptStackTrace 'ERROR' }
    exit 1
}
