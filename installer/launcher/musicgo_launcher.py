# -*- coding: utf-8 -*-
"""MusicGo Launcher - demarre le backend et ouvre Chromium portable en mode app."""

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

# Log file dans %TEMP% â€” visible meme si pas de console
LOG_FILE = Path(tempfile.gettempdir()) / "musicgo_launcher.log"

class _Tee:
    """Ecrit a la fois sur stdout d'origine (si dispo) et sur le fichier log."""
    def __init__(self, file_handle, original):
        self.file = file_handle
        self.original = original

    def write(self, data):
        try:
            self.file.write(data)
            self.file.flush()
        except Exception:
            pass
        try:
            if self.original is not None:
                self.original.write(data)
        except Exception:
            pass

    def flush(self):
        try:
            self.file.flush()
        except Exception:
            pass
        try:
            if self.original is not None:
                self.original.flush()
        except Exception:
            pass

# Initialise le fichier log immediatement (truncate a chaque lancement)
try:
    _log_fh = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
    _log_fh.write(f"=== MusicGo launcher start {datetime.now().isoformat()} ===\n")
    _log_fh.flush()
    sys.stdout = _Tee(_log_fh, sys.stdout)
    sys.stderr = _Tee(_log_fh, sys.stderr)
except Exception as _e:
    pass

# UTF-8 reconfigure (apres redirection â€” peut etre no-op si _Tee)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APP_PORT = 8080
APP_HOST = "127.0.0.1"

LOGO = r"""
  __  __           _       ____
 |  \/  |_   _ ___(_) ___ / ___| ___
 | |\/| | | | / __| |/ __| |  _ / _ \
 | |  | | |_| \__ \ | (__| |_| | (_) |
 |_|  |_|\__,_|___/_|\___|\____|\___/
"""

# URL telechargement Chromium portable (mini build sans installer)
CHROMIUM_ZIP_URL = (
    "https://github.com/macchrome/winchrome/releases/download/v124.0.6367.82-r1274125-Win64/"
    "124.0.6367.82-r1274125_chrome-win.zip"
)
# Fallback: on essaie plusieurs sources
CHROMIUM_FALLBACK_URLS = [
    CHROMIUM_ZIP_URL,
]


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", flush=True)


def show_error(msg: str, title: str = "MusicGo - Erreur") -> None:
    """Affiche une boite de dialogue d'erreur (pas besoin de console)."""
    full_msg = f"{msg}\n\nLog complet :\n{LOG_FILE}"
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, full_msg, title, 0x10)
    except Exception:
        print(f"[ERR] {msg}", flush=True)


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def wait_for_server(host: str, port: int, timeout: float = 30.0, proc=None) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if port_in_use(host, port):
            return True
        # Detection mort precoce du backend (poll != None = process termine)
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.3)
    return False


def build_env(root: Path) -> dict:
    env = os.environ.copy()
    python_dir = root / "python"
    ffmpeg_dir = root / "ffmpeg"
    ytdlp_dir  = root / "yt-dlp"
    app_dir    = root / "app"
    site_pkg   = python_dir / "Lib" / "site-packages"

    prefix = os.pathsep.join(
        str(p) for p in (ffmpeg_dir, ytdlp_dir, python_dir) if p.exists()
    )
    env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    extra = os.pathsep.join(
        str(p) for p in (app_dir, site_pkg, python_dir) if p.exists()
    )
    env["PYTHONPATH"] = extra + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def pipe_output(stream, prefix: str) -> None:
    try:
        for line in iter(stream.readline, b""):
            if not line:
                break
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            if text:
                print(f"{prefix} {text}", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Chromium portable
# ---------------------------------------------------------------------------

def chromium_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "MusicGo" / "chromium"


def chromium_exe(chrom_dir: Path) -> Path | None:
    for pattern in ("chrome.exe", "chromium.exe"):
        for f in chrom_dir.rglob(pattern):
            return f
    return None


def download_chromium(chrom_dir: Path) -> bool:
    """Telecharge et extrait Chromium portable. Retourne True si OK."""
    import urllib.request
    log("Telechargement de Chromium portable (premiere utilisation, ~150MB)...")
    chrom_dir.mkdir(parents=True, exist_ok=True)
    zip_path = chrom_dir.parent / "chromium.zip"

    for url in CHROMIUM_FALLBACK_URLS:
        try:
            log(f"Source: {url}")
            urllib.request.urlretrieve(url, zip_path)
            break
        except Exception as e:
            log(f"Echec: {e}", "WARN")
            if zip_path.exists():
                zip_path.unlink()
    else:
        return False

    try:
        log("Extraction de Chromium...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(chrom_dir)
        zip_path.unlink()
        return chromium_exe(chrom_dir) is not None
    except Exception as e:
        log(f"Extraction echouee: {e}", "ERR")
        return False


def find_system_chromium() -> str | None:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local) / "Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path(local) / "Microsoft/Edge/Application/msedge.exe",
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def open_app_window(url: str) -> bool:
    local = os.environ.get("LOCALAPPDATA", "")
    profile_dir = Path(local) / "MusicGo" / "chromium-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    # 1. Chromium portable MusicGo
    chrom_dir = chromium_dir()
    exe = chromium_exe(chrom_dir)
    if not exe and not chrom_dir.exists():
        ok = download_chromium(chrom_dir)
        if ok:
            exe = chromium_exe(chrom_dir)
        else:
            log("Telechargement Chromium echoue, utilisation du navigateur systeme.", "WARN")

    # 2. Fallback Chrome/Edge systeme
    if not exe:
        sys_browser = find_system_chromium()
        if sys_browser:
            exe = Path(sys_browser)
            log("Chromium portable indisponible, utilisation de Chrome/Edge systeme.")

    if exe:
        try:
            subprocess.Popen(
                [
                    str(exe),
                    f"--app={url}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=TranslateUI",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            log(f"Lancement navigateur echoue: {e}", "WARN")

    # 3. Fallback navigateur par defaut
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return False


def config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "MusicGo" / "config.json"


def needs_setup() -> bool:
    return False

def main() -> int:
    root = install_dir()
    print(LOGO)
    log(f"Dossier d'installation: {root}")
    log(f"Python interpreter: {sys.executable}")
    log(f"Python version: {sys.version}")
    log(f"sys.path: {sys.path}")

    python_log_exe = root / "python" / "python.exe"
    python_exe = python_log_exe if python_log_exe.exists() else (root / "python" / "pythonw.exe")
    app_py = root / "app" / "app.py"

    log(f"python.exe attendu: {python_exe}")
    log(f"app.py attendu: {app_py}")

    if not python_exe.exists():
        show_error(f"Python embarque introuvable :\n{python_exe}\n\nReinstallez MusicGo.")
        return 1

    if not app_py.exists():
        show_error(f"app.py introuvable :\n{app_py}\n\nReinstallez MusicGo.")
        return 1

    if port_in_use(APP_HOST, APP_PORT):
        log(f"Port {APP_PORT} deja utilise, ouverture sur instance existante.")
        url = f"http://localhost:{APP_PORT}"
        open_app_window(url)
        time.sleep(3)
        return 0

    env = build_env(root)
    log(f"PYTHONPATH: {env.get('PYTHONPATH', '')}")
    log(f"PATH (head): {env.get('PATH', '')[:300]}")

    # Verifie que les imports critiques fonctionnent dans le Python embedded
    log("Verification imports critiques...")
    if not python_log_exe.exists():
        python_log_exe = python_exe
    check = subprocess.run(
        [str(python_log_exe), "-c",
         "import sys; "
         "import fastapi, uvicorn, yt_dlp, dotenv, aiofiles, mutagen, multipart; "
         "print('IMPORTS_OK', fastapi.__version__, uvicorn.__version__)"],
        env=env, capture_output=True, text=True, timeout=20,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),  # type: ignore[attr-defined]
    )
    log(f"Import check stdout: {check.stdout.strip()}")
    log(f"Import check stderr: {check.stderr.strip()}")
    if check.returncode != 0 or "IMPORTS_OK" not in check.stdout:
        show_error(
            "Imports Python casses.\n\n"
            f"stderr :\n{check.stderr[:600]}\n\n"
            "Reinstallez MusicGo."
        )
        return 1
    log("Imports OK")

    # Verifie que app.py s'importe sans erreur
    log("Verification import app.py...")
    app_check = subprocess.run(
        [str(python_log_exe), "-c",
         "import sys; sys.path.insert(0, r'" + str(app_py.parent) + "'); "
         "import importlib.util as u; "
         "spec = u.spec_from_file_location('musicgo_app', r'" + str(app_py) + "'); "
         "mod = u.module_from_spec(spec); spec.loader.exec_module(mod); "
         "print('APP_IMPORT_OK')"],
        cwd=str(app_py.parent), env=env, capture_output=True, text=True, timeout=30,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),  # type: ignore[attr-defined]
    )
    log(f"App import stdout: {app_check.stdout.strip()}")
    log(f"App import stderr: {app_check.stderr.strip()}")
    if app_check.returncode != 0 or "APP_IMPORT_OK" not in app_check.stdout:
        show_error(
            "app.py ne s'importe pas correctement.\n\n"
            f"stderr :\n{app_check.stderr[-800:]}\n\n"
            "Reinstallez MusicGo."
        )
        return 1
    log("App import OK")

    log("Demarrage du backend MusicGo...")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        [str(python_log_exe), str(app_py)],
        cwd=str(app_py.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log(f"Backend PID: {proc.pid}")

    t = threading.Thread(target=pipe_output, args=(proc.stdout, "[backend]"), daemon=True)
    t.start()

    if not wait_for_server(APP_HOST, APP_PORT, timeout=120, proc=proc):
        # Recupere les logs backend deja captures
        time.sleep(0.5)
        died = proc.poll() is not None
        exit_code = proc.returncode if died else None

        if died:
            log(f"Backend mort precocement, code={exit_code}", "ERR")
            show_error(
                f"MusicGo backend a crashe (code {exit_code}).\n\n"
                "Voir log pour traceback Python complet."
            )
        else:
            log("Le serveur n'a pas demarre a temps (60s).", "ERR")
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            show_error(
                "MusicGo backend n'a pas demarre dans les 120 secondes.\n\n"
                "Causes possibles :\n"
                "- Antivirus bloque python.exe\n"
                "- Port 8080 occupe\n"
                "- Erreur dans app.py (voir log)\n"
            )
        return 1

    url = f"http://localhost:{APP_PORT}"
    log(f"Serveur pret: {url}", "OK")
    open_app_window(url)

    log("MusicGo tourne. Fermez cette fenetre pour arreter le serveur.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        log("Arret demande...")
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    log("MusicGo arrete.", "OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:
        tb = traceback.format_exc()
        try:
            print(tb, flush=True)
        except Exception:
            pass
        show_error(f"Erreur fatale :\n{e}\n\n{tb[:600]}")
        sys.exit(1)
