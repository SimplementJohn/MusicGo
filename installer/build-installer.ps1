# =============================================================================
# MusicGo — Script de préparation de l'installeur Windows
# =============================================================================
# Ce script prépare le dossier 'bundle/' qui contient tout ce qu'Inno Setup
# doit embarquer dans l'installeur final :
#   - Python 3.11 embedded + dépendances pip
#   - ffmpeg.exe + ffprobe.exe
#   - yt-dlp.exe (binaire autonome)
#   - Le frontend Vite buildé (dist/)
#   - app.py, extension/, config.json
#
# Prérequis :
#   - Windows 10/11 x64, PowerShell 5.1+
#   - Node.js + npm installés (pour `npm run build`)
#   - Connexion internet (premier build uniquement)
#
# Usage :
#   cd installer
#   .\build-installer.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$script:_buildSw = [Diagnostics.Stopwatch]::StartNew()
$script:_stepSw  = [Diagnostics.Stopwatch]::StartNew()
$script:_stepName = $null

# Versions figées pour des builds reproductibles
$PYTHON_VERSION   = "3.11.9"
$PYTHON_URL       = "https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-embed-amd64.zip"
$GET_PIP_URL      = "https://bootstrap.pypa.io/get-pip.py"
$FFMPEG_URL       = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
$YTDLP_URL        = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

# Chemins absolus
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot   = Split-Path -Parent $ScriptDir
$BundleDir  = Join-Path $ScriptDir "bundle"
$CacheDir   = Join-Path $ScriptDir ".cache"
$PythonDir  = Join-Path $BundleDir "python"
$FfmpegDir  = Join-Path $BundleDir "ffmpeg"
$YtdlpDir   = Join-Path $BundleDir "yt-dlp"
$AppDir     = Join-Path $BundleDir "app"

function Write-Step($msg) {
    if ($script:_stepName -ne $null) {
        $s = [math]::Round($script:_stepSw.Elapsed.TotalSeconds, 1)
        Write-Host "    [temps: ${s}s]" -ForegroundColor DarkGray
    }
    $script:_stepName = $msg
    $script:_stepSw.Restart()
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}
function Write-Ok($msg)   { Write-Host "[OK] $msg"  -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!!] $msg"  -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[XX] $msg"  -ForegroundColor Red }

function Ensure-Dir($path) {
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
}

function Download-File($url, $dest) {
    if (Test-Path $dest) {
        Write-Host "    (cache) $dest"
        return
    }
    # S'assure que le dossier parent existe (SMB/latence peut perdre une dir creee plus tot)
    $parent = Split-Path -Parent $dest
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Write-Host "    telechargement : $url"
    try {
        # Force TLS 1.2 pour github / python.org sur anciennes versions PS
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Err "Echec du telechargement : $url"
        throw
    }
}

# -----------------------------------------------------------------------------
Write-Step "1. Preparation des dossiers"
# -----------------------------------------------------------------------------
if (Test-Path $BundleDir) {
    Write-Warn "Suppression de l'ancien bundle..."
    Remove-Item -Recurse -Force $BundleDir
}
Ensure-Dir $BundleDir
Ensure-Dir $CacheDir
Ensure-Dir $PythonDir
Ensure-Dir $FfmpegDir
Ensure-Dir $YtdlpDir
Ensure-Dir $AppDir
Write-Ok "Arborescence creee dans $BundleDir"

# -----------------------------------------------------------------------------
Write-Step "2. Python $PYTHON_VERSION embedded"
# -----------------------------------------------------------------------------
$pythonZip = Join-Path $CacheDir "python-embed-$PYTHON_VERSION.zip"
Download-File $PYTHON_URL $pythonZip

Write-Host "    extraction..."
Expand-Archive -Path $pythonZip -DestinationPath $PythonDir -Force

# Decommenter 'import site' dans python311._pth pour activer pip et site-packages
$pthFile = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $pthFile) { throw "Fichier python._pth introuvable dans l'embed." }

$pthContent = Get-Content $pthFile.FullName
$pthContent = $pthContent -replace '^#\s*import\s+site', 'import site'
# Ajoute Lib/site-packages au search path si absent
if (-not ($pthContent -match 'Lib.site-packages')) {
    $pthContent += 'Lib\site-packages'
}
Set-Content -Path $pthFile.FullName -Value $pthContent -Encoding ASCII
Write-Ok "python._pth modifie (site + Lib/site-packages actives)"

# -----------------------------------------------------------------------------
Write-Step "3. Installation de pip dans le Python embedded"
# -----------------------------------------------------------------------------
$getPip = Join-Path $CacheDir "get-pip.py"
Download-File $GET_PIP_URL $getPip

$pythonExe = Join-Path $PythonDir "python.exe"
if (-not (Test-Path $pythonExe)) { throw "python.exe introuvable dans $PythonDir" }

Write-Host "    execution de get-pip.py..."
& $pythonExe $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "Echec installation de pip (exit $LASTEXITCODE)" }
Write-Ok "pip installe"

# -----------------------------------------------------------------------------
Write-Step "4. Installation des dependances Python (requirements.txt)"
# -----------------------------------------------------------------------------
$req = Join-Path $RepoRoot "requirements.txt"
if (-not (Test-Path $req)) { throw "requirements.txt introuvable : $req" }

# Cache site-packages par hash de requirements.txt + spotdl
$reqHash     = (Get-FileHash $req -Algorithm MD5).Hash
$cacheKey    = "$reqHash-spotdl"
$spCache     = Join-Path $CacheDir "site-packages-$cacheKey"
$SitePackDir = Join-Path $PythonDir "Lib\site-packages"

if (Test-Path $spCache) {
    Write-Host "    (cache) copie site-packages depuis cache..."
    Copy-Item -Path "$spCache\*" -Destination $SitePackDir -Recurse -Force
    # Compile .pyc si manquants dans cache
    if (-not (Test-Path (Join-Path $SitePackDir "fastapi\__pycache__"))) {
        Write-Host "    pre-compilation .pyc (cache sans pyc)..."
        & $pythonExe -m compileall -q -j 0 $SitePackDir 2>&1 | Out-Null
        # Regenere cache avec pyc
        Remove-Item -Recurse -Force $spCache
        New-Item -ItemType Directory -Force -Path $spCache | Out-Null
        Copy-Item -Path "$SitePackDir\*" -Destination $spCache -Recurse -Force
    }
    Write-Ok "Dependances Python restaurees depuis cache"
} else {
    Write-Host "    pip install -r requirements.txt..."
    & $pythonExe -m pip install --no-warn-script-location -r $req
    if ($LASTEXITCODE -ne 0) { throw "Echec pip install (exit $LASTEXITCODE)" }

    Write-Host "    pip install spotdl (optionnel, pour Spotify/Deezer/Apple Music)..."
    & $pythonExe -m pip install --no-warn-script-location spotdl
    if ($LASTEXITCODE -ne 0) { Write-Warn "spotdl non installe (non bloquant)" }

    Write-Host "    pre-compilation .pyc (cold start ~10x plus rapide)..."
    & $pythonExe -m compileall -q -j 0 $SitePackDir 2>&1 | Out-Null

    Write-Host "    mise en cache site-packages..."
    New-Item -ItemType Directory -Force -Path $spCache | Out-Null
    Copy-Item -Path "$SitePackDir\*" -Destination $spCache -Recurse -Force
    Write-Ok "Dependances Python installees, compilees et mises en cache"
}

# -----------------------------------------------------------------------------
Write-Step "5. Telechargement de ffmpeg + ffprobe"
# -----------------------------------------------------------------------------
$ffmpegZip = Join-Path $CacheDir "ffmpeg-win64.zip"
Download-File $FFMPEG_URL $ffmpegZip

Write-Host "    extraction (bin only)..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($ffmpegZip)
try {
    foreach ($entry in $zip.Entries) {
        $name = $entry.Name
        if ($name -eq "ffmpeg.exe" -or $name -eq "ffprobe.exe") {
            $dest = Join-Path $FfmpegDir $name
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
            Write-Host "    extrait: $name"
        }
    }
} finally {
    $zip.Dispose()
}

$ffmpegExe  = Join-Path $FfmpegDir "ffmpeg.exe"
$ffprobeExe = Join-Path $FfmpegDir "ffprobe.exe"
if (-not (Test-Path $ffmpegExe) -or -not (Test-Path $ffprobeExe)) {
    throw "ffmpeg.exe ou ffprobe.exe introuvable dans l'archive extraite"
}
Write-Ok "ffmpeg + ffprobe copies dans $FfmpegDir"

# -----------------------------------------------------------------------------
Write-Step "6. Telechargement de yt-dlp.exe"
# -----------------------------------------------------------------------------
$ytdlpExe = Join-Path $YtdlpDir "yt-dlp.exe"
Download-File $YTDLP_URL $ytdlpExe
Write-Ok "yt-dlp.exe telecharge dans $YtdlpDir"

# -----------------------------------------------------------------------------
Write-Step "7. Build du frontend Vite (npm run build)"
# -----------------------------------------------------------------------------
Push-Location $RepoRoot
try {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm introuvable dans le PATH. Installez Node.js."
    }

    if (-not (Test-Path (Join-Path $RepoRoot "node_modules"))) {
        Write-Host "    npm install..."
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install a echoue" }
    }

    Write-Host "    npm run build..."
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build a echoue" }
} finally {
    Pop-Location
}
Write-Ok "Frontend buildé dans $RepoRoot\dist"

# -----------------------------------------------------------------------------
Write-Step "8. Copie des fichiers de l'application"
# -----------------------------------------------------------------------------
$filesToCopy = @(
    @{ Src = "app.py";           Dst = "app.py"           },
    @{ Src = "requirements.txt"; Dst = "requirements.txt" }
    # config.json volontairement absent : genere a la 1ere execution avec les
    # defauts utilisateur (~/Music/MusicGo). Eviter de bundler le config dev
    # qui contient le download_dir specifique a la machine de build.
)

foreach ($f in $filesToCopy) {
    $src = Join-Path $RepoRoot $f.Src
    if (-not (Test-Path $src)) { Write-Warn "Fichier manquant : $src"; continue }
    Copy-Item $src (Join-Path $AppDir $f.Dst) -Force
    Write-Host "    [copie] $($f.Src)"
}

# dist/
$distSrc = Join-Path $RepoRoot "dist"
$distDst = Join-Path $AppDir  "dist"
if (Test-Path $distSrc) {
    Copy-Item $distSrc $distDst -Recurse -Force
    Write-Host "    [copie] dist/"
} else { Write-Warn "dist/ manquant, le build Vite a peut-etre echoue" }

# extension/
$extSrc = Join-Path $RepoRoot "extension"
$extDst = Join-Path $AppDir  "extension"
if (Test-Path $extSrc) {
    Copy-Item $extSrc $extDst -Recurse -Force
    Write-Host "    [copie] extension/"
} else { Write-Warn "extension/ manquant" }

Write-Ok "Fichiers de l'application copies dans $AppDir"

# -----------------------------------------------------------------------------
Write-Step "9. Copie du launcher + VBS wrapper"
# -----------------------------------------------------------------------------
$launcherSrc = Join-Path $ScriptDir "launcher\musicgo_launcher.py"
$launcherDst = Join-Path $BundleDir "musicgo_launcher.py"
if (-not (Test-Path $launcherSrc)) { throw "Launcher introuvable : $launcherSrc" }
Copy-Item $launcherSrc $launcherDst -Force
Write-Ok "Launcher py copie : $launcherDst"

# Stub .exe (compile par build-all.ps1 avant cette etape)
$exeSrc = Join-Path $ScriptDir "launcher\musicgo_launcher.exe"
if (Test-Path $exeSrc) {
    Copy-Item $exeSrc (Join-Path $BundleDir "musicgo_launcher.exe") -Force
    Write-Ok "Launcher exe copie"
}

# VBS fallback
$vbsSrc = Join-Path $ScriptDir "launcher\launcher_hidden.vbs"
if (Test-Path $vbsSrc) {
    Copy-Item $vbsSrc (Join-Path $BundleDir "launcher_hidden.vbs") -Force
    Write-Ok "VBS fallback copie"
}

# -----------------------------------------------------------------------------
Write-Step "10. Verification finale"
# -----------------------------------------------------------------------------
$checks = @(
    (Join-Path $PythonDir "python.exe"),
    (Join-Path $PythonDir "pythonw.exe"),
    (Join-Path $PythonDir "Lib\site-packages\fastapi"),
    (Join-Path $PythonDir "Lib\site-packages\yt_dlp"),
    (Join-Path $FfmpegDir "ffmpeg.exe"),
    (Join-Path $FfmpegDir "ffprobe.exe"),
    (Join-Path $YtdlpDir  "yt-dlp.exe"),
    (Join-Path $AppDir    "app.py"),
    (Join-Path $AppDir    "dist\index.html"),
    (Join-Path $AppDir    "extension\manifest.json"),
    (Join-Path $BundleDir "musicgo_launcher.py"),
    (Join-Path $BundleDir "musicgo_launcher.exe")
)

$missing = @()
foreach ($c in $checks) {
    if (Test-Path $c) {
        Write-Host "    [ok] $c"
    } else {
        Write-Host "    [XX] $c" -ForegroundColor Red
        $missing += $c
    }
}

if ($missing.Count -gt 0) {
    Write-Err "Elements manquants, bundle incomplet :"
    $missing | ForEach-Object { Write-Host "    - $_" }
    exit 1
}

Write-Step "10b. Pre-compilation .pyc app + launcher"
& $pythonExe -m compileall -q -j 0 (Join-Path $AppDir "app.py") 2>&1 | Out-Null
& $pythonExe -m compileall -q -j 0 (Join-Path $BundleDir "musicgo_launcher.py") 2>&1 | Out-Null
Write-Ok ".pyc compiles"

if ($script:_stepName -ne $null) {
    $s = [math]::Round($script:_stepSw.Elapsed.TotalSeconds, 1)
    Write-Host "    [temps: ${s}s]" -ForegroundColor DarkGray
}

# Taille totale du bundle
$size = (Get-ChildItem -Path $BundleDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
$total = [math]::Round($script:_buildSw.Elapsed.TotalSeconds, 1)
Write-Host ""
Write-Ok "Bundle complet : $BundleDir ($([math]::Round($size, 1)) MB)  [total: ${total}s]"
Write-Host ""
Write-Host "Etape suivante :" -ForegroundColor Cyan
Write-Host "  Compilez l'installeur avec Inno Setup :"
Write-Host "    & `"`$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe`" `"$ScriptDir\musicgo-setup.iss`""
Write-Host "  (ou si Inno Setup installe dans Program Files:)"
Write-Host "    & `"`${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe`" `"$ScriptDir\musicgo-setup.iss`""
