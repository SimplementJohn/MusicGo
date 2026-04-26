# =============================================================================
# MusicGo — Build complet (icône + bundle + installeur Inno Setup)
# =============================================================================
# Exécute d'un seul coup :
#   1. generate-icon.py   (Pillow → musicgo.ico)
#   2. build-installer.ps1 (bundle complet)
#   3. iscc.exe musicgo-setup.iss (MusicGo-Setup-*.exe)
#
# Usage :
#   cd installer
#   .\build-all.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$script:_buildSw = [Diagnostics.Stopwatch]::StartNew()
$script:_stepSw  = [Diagnostics.Stopwatch]::StartNew()
$script:_stepName = $null

function Write-Step($msg) {
    if ($script:_stepName -ne $null) {
        $s = [math]::Round($script:_stepSw.Elapsed.TotalSeconds, 1)
        Write-Host "    [temps: ${s}s]" -ForegroundColor DarkGray
    }
    $script:_stepName = $msg
    $script:_stepSw.Restart()
    Write-Host "`n######## $msg ########" -ForegroundColor Magenta
}
function Write-Ok($msg)  { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Err($msg) { Write-Host "[XX] $msg" -ForegroundColor Red }

# -----------------------------------------------------------------------------
Write-Step "1/3 Generation de l'icone"
# -----------------------------------------------------------------------------
$icon         = Join-Path $ScriptDir "musicgo.ico"
$logoIco      = Join-Path $ScriptDir "musicgo_logo.ico"
$wizardLarge  = Join-Path $ScriptDir "assets\wizard-large.bmp"
$wizardSmall  = Join-Path $ScriptDir "assets\wizard-small.bmp"
$iconSrc   = Join-Path (Split-Path -Parent $ScriptDir) "icon.png"
$logoSrc   = Join-Path (Split-Path -Parent $ScriptDir) "logotexte.png"
# Regenere si sources plus recentes que les assets generes
$needsIconGen = (-not (Test-Path $icon)) -or (-not (Test-Path $wizardLarge)) -or (-not (Test-Path $wizardSmall)) -or (-not (Test-Path $logoIco)) `
    -or ((Test-Path $iconSrc) -and (Get-Item $iconSrc).LastWriteTime -gt (Get-Item $icon -ErrorAction SilentlyContinue).LastWriteTime) `
    -or ((Test-Path $logoSrc) -and (Get-Item $logoSrc).LastWriteTime -gt (Get-Item $wizardLarge -ErrorAction SilentlyContinue).LastWriteTime) `
    -or ((Test-Path $logoSrc) -and (Get-Item $logoSrc).LastWriteTime -gt (Get-Item $logoIco -ErrorAction SilentlyContinue).LastWriteTime)

if (-not $needsIconGen) {
    Write-Host "Icone + assets wizard deja presents (skip generation)"
} else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $py) { throw "Python introuvable dans le PATH. Installez Python 3.10+." }

    Write-Host "Verification de Pillow..."
    & $py.Source -c "import PIL" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installation de Pillow..."
        & $py.Source -m pip install --quiet pillow
        if ($LASTEXITCODE -ne 0) { throw "Echec pip install pillow" }
    }

    & $py.Source (Join-Path $ScriptDir "generate-icon.py")
    if ($LASTEXITCODE -ne 0) { throw "generate-icon.py a echoue" }
    Write-Ok "Icone + assets wizard generes"
}

# -----------------------------------------------------------------------------
Write-Step "1b/3 Compilation du launcher .exe (C# stub)"
# -----------------------------------------------------------------------------
$launcherExe = Join-Path $ScriptDir "launcher\musicgo_launcher.exe"
$launcherCs  = Join-Path $ScriptDir "launcher\musicgo_launcher_stub.cs"
$icoFile     = Join-Path $ScriptDir "musicgo.ico"

$csSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

class MusicGoLauncher {
    static string LogPath = Path.Combine(Path.GetTempPath(), "musicgo_stub.log");
    static string PyLogPath = Path.Combine(Path.GetTempPath(), "musicgo_launcher.log");

    static void StubLog(string msg) {
        try {
            File.AppendAllText(LogPath,
                "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "] " + msg + Environment.NewLine);
        } catch {}
    }

    static void ShowError(string msg) {
        string tail = "";
        try {
            if (File.Exists(PyLogPath)) {
                string content = File.ReadAllText(PyLogPath);
                tail = content.Length > 1500 ? content.Substring(content.Length - 1500) : content;
            }
        } catch {}
        string full = msg;
        if (tail.Length > 0) full += "\n\n--- Tail launcher log ---\n" + tail;
        full += "\n\nLogs :\n" + LogPath + "\n" + PyLogPath;
        MessageBox.Show(full, "MusicGo - Erreur",
            MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    [STAThread]
    static void Main(string[] args) {
        try {
            string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            StubLog("=== Stub start, dir=" + dir + ", argc=" + args.Length + " ===");

            string python = Path.Combine(dir, "python", "python.exe");
            string launcher = Path.Combine(dir, "musicgo_launcher.py");

            if (!File.Exists(python)) {
                StubLog("ERR: python.exe missing: " + python);
                ShowError("python.exe introuvable :\n" + python);
                return;
            }
            if (!File.Exists(launcher)) {
                StubLog("ERR: launcher.py missing: " + launcher);
                ShowError("musicgo_launcher.py introuvable :\n" + launcher);
                return;
            }

            // Forward args (e.g. --minimized) au python script
            string forwarded = "";
            foreach (string a in args) {
                forwarded += " \"" + a.Replace("\"", "\\\"") + "\"";
            }
            string pyArgs = "\"" + launcher + "\"" + forwarded;

            var psi = new ProcessStartInfo {
                FileName = python,
                Arguments = pyArgs,
                WorkingDirectory = dir,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            StubLog("Starting: " + python + " " + pyArgs);
            var proc = Process.Start(psi);
            StubLog("Process started, PID=" + proc.Id);

            // Detection crash precoce (5s) — code 0 = exit propre (port deja occupe etc.)
            if (proc.WaitForExit(5000)) {
                int code = proc.ExitCode;
                StubLog("Process exited early, code=" + code);
                if (code != 0) {
                    ShowError("MusicGo s'est arrete (code " + code + ").");
                }
            } else {
                StubLog("Process running after 5s, OK, stub exits");
            }
        } catch (Exception ex) {
            StubLog("EXCEPTION: " + ex.ToString());
            ShowError("Erreur stub :\n" + ex.Message);
        }
    }
}
'@

Set-Content -Path $launcherCs -Value $csSource -Encoding UTF8

# Trouve csc.exe (.NET Framework, present sur tout Windows avec .NET 4.x)
$cscCandidates = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
$csc = $null
foreach ($c in $cscCandidates) { if (Test-Path $c) { $csc = $c; break } }

if ($csc) {
    # Supprime ancien exe pour eviter conflit cache/lock
    if (Test-Path $launcherExe) { Remove-Item $launcherExe -Force -ErrorAction SilentlyContinue }

    $cscArgs = @(
        "/target:winexe",
        "/optimize+",
        "/out:$launcherExe",
        "/reference:System.Windows.Forms.dll"
    )
    if (Test-Path $icoFile) {
        $cscArgs += "/win32icon:$icoFile"
    } else {
        Write-Host "musicgo.ico introuvable, exe sans icone" -ForegroundColor Yellow
    }
    $cscArgs += $launcherCs

    $cscOutput = & $csc $cscArgs 2>&1
    if ($LASTEXITCODE -eq 0 -and (Test-Path $launcherExe)) {
        Write-Ok "musicgo_launcher.exe compile ($([math]::Round((Get-Item $launcherExe).Length/1KB))KB)"
        Remove-Item $launcherCs -Force
    } else {
        Write-Host "Compilation C# echouee :" -ForegroundColor Red
        $cscOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        Write-Host "Fallback VBS" -ForegroundColor Yellow
        $launcherExe = $null
    }
} else {
    Write-Host "csc.exe introuvable, fallback VBS" -ForegroundColor Yellow
    $launcherExe = $null
}

# -----------------------------------------------------------------------------
Write-Step "2/3 Preparation du bundle"
# -----------------------------------------------------------------------------
& (Join-Path $ScriptDir "build-installer.ps1")
if ($LASTEXITCODE -ne 0) { throw "build-installer.ps1 a echoue" }
Write-Ok "Bundle pret"

# -----------------------------------------------------------------------------
Write-Step "2b/3 Incrementation version patch"
# -----------------------------------------------------------------------------
$issFile = Join-Path $ScriptDir "musicgo-setup.iss"
$issContent = Get-Content $issFile -Raw
if ($issContent -match '#define AppVersion\s+"(\d+)\.(\d+)\.(\d+)"') {
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    $patch = [int]$Matches[3] + 1
    $newVersion = "$major.$minor.$patch"
    $issContent = $issContent -replace '#define AppVersion\s+"[\d.]+"', "#define AppVersion      `"$newVersion`""
    Set-Content $issFile $issContent -NoNewline
    Write-Ok "Version incrementee : $major.$minor.$($patch - 1) -> $newVersion"
} else {
    Write-Host "Version non trouvee dans .iss, skip increment" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
Write-Step "3/3 Compilation Inno Setup"
# -----------------------------------------------------------------------------
$isccCandidates = @(
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
)
$iscc = $null
foreach ($c in $isccCandidates) {
    if (Test-Path $c) { $iscc = $c; break }
}
if (-not $iscc) {
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    Write-Err "Inno Setup introuvable. Telechargez-le : https://jrsoftware.org/isdl.php"
    Write-Host "Le bundle est pret, compilez ensuite manuellement :" -ForegroundColor Yellow
    Write-Host "  iscc.exe `"$ScriptDir\musicgo-setup.iss`""
    exit 1
}

Write-Host "Inno Setup trouve : $iscc"
& $iscc (Join-Path $ScriptDir "musicgo-setup.iss")
if ($LASTEXITCODE -ne 0) { throw "Compilation Inno Setup a echoue (exit $LASTEXITCODE)" }

$output = Join-Path $ScriptDir "output"
$setup = Get-ChildItem -Path $output -Filter "MusicGo-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($script:_stepName -ne $null) {
    $s = [math]::Round($script:_stepSw.Elapsed.TotalSeconds, 1)
    Write-Host "    [temps: ${s}s]" -ForegroundColor DarkGray
}

$total = [math]::Round($script:_buildSw.Elapsed.TotalSeconds, 1)
Write-Host ""
Write-Ok "Build complet termine  [total: ${total}s]"
if ($setup) {
    $sizeMB = [math]::Round($setup.Length / 1MB, 1)
    Write-Host "Installeur : $($setup.FullName) ($sizeMB MB)" -ForegroundColor Cyan
}
