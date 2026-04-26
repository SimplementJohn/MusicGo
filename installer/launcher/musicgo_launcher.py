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

# Log file dans %TEMP% — visible meme si pas de console
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

# UTF-8 reconfigure (apres redirection — peut etre no-op si _Tee)
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
CHROMIUM_FALLBACK_URLS = [
    CHROMIUM_ZIP_URL,
]

# Shared state
_backend_proc = None
_quit_event = threading.Event()
_tray_lock = threading.Lock()
_tray_running = False


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


_singleton_mutex_handle = None

def acquire_singleton() -> bool:
    """Mutex Windows global. Retourne True si c'est la 1ere instance, False sinon."""
    global _singleton_mutex_handle
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        # Local\\ scope = par session utilisateur (pas Global\\ qui exige privileges)
        handle = kernel32.CreateMutexW(None, False, "Local\\MusicGoLauncherSingleton")
        if not handle:
            return True  # fallback permissif
        last_err = kernel32.GetLastError()
        if last_err == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _singleton_mutex_handle = handle  # garde reference
        return True
    except Exception:
        return True


def is_musicgo_running(host: str, port: int) -> bool:
    """Verifie qu'une instance MusicGo valide repond sur le port."""
    if not port_in_use(host, port):
        return False
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def wait_for_server(host: str, port: int, timeout: float = 30.0, proc=None) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if port_in_use(host, port):
            return True
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


def open_app_window(url: str) -> "subprocess.Popen | None":
    """Ouvre l'app dans Chromium. Retourne le process Chromium ou None si fallback."""
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
            proc = subprocess.Popen(
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
            return proc
        except Exception as e:
            log(f"Lancement navigateur echoue: {e}", "WARN")

    # 3. Fallback navigateur par defaut (pas de tracking process)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return None


def config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "MusicGo" / "config.json"


def needs_setup() -> bool:
    return False


# ---------------------------------------------------------------------------
# System tray
# ---------------------------------------------------------------------------

def _load_tray_image(root: Path):
    """Charge l'icone pour le tray. Retourne une PIL.Image."""
    try:
        from PIL import Image
        # Essaie musicgo.ico depuis le dossier d'installation
        ico = root / "musicgo.ico"
        if ico.exists():
            img = Image.open(ico)
            img = img.convert("RGBA")
            # Prend la frame 32x32 si disponible
            try:
                img.seek(0)
                sizes = []
                try:
                    while True:
                        sizes.append((img.size, img.tell()))
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass
                # Choisit la frame 32x32 ou 16x16
                for size, frame in sizes:
                    if size == (32, 32):
                        img.seek(frame)
                        return img.copy().convert("RGBA")
                img.seek(0)
                return img.copy().convert("RGBA")
            except Exception:
                return img.convert("RGBA")
        # Fallback: carre violet
        img = Image.new("RGBA", (32, 32), (99, 102, 241, 255))
        return img
    except ImportError:
        return None


def run_tray(root: Path, url: str) -> None:
    """Affiche l'icone dans le tray systeme. Bloquant jusqu'a Quitter."""
    global _tray_running, _tray_lock

    with _tray_lock:
        if _tray_running:
            return
        _tray_running = True

    try:
        import pystray
        from PIL import Image
    except ImportError:
        log("pystray/Pillow non disponible — tray desactive", "WARN")
        _tray_running = False
        return

    img = _load_tray_image(root)
    if img is None:
        img = Image.new("RGBA", (32, 32), (99, 102, 241, 255))

    icon_ref = [None]  # liste pour mutabilite dans closures

    def on_open(icon, item):
        log("Tray: ouverture MusicGo")
        icon.stop()
        # Ouvre Chromium et surveille le nouveau process
        chrom = open_app_window(url)
        t = threading.Thread(target=_watch_chromium, args=(chrom, root, url), daemon=True)
        t.start()

    def on_quit(icon, item):
        log("Tray: quitter MusicGo")
        icon.stop()
        _do_quit()

    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir MusicGo", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quitter MusicGo", on_quit),
    )
    icon = pystray.Icon("MusicGo", img, "MusicGo", menu)
    icon_ref[0] = icon
    log("Tray systeme actif")
    icon.run()  # bloquant
    _tray_running = False


def _watch_chromium(chrom_proc: "subprocess.Popen | None", root: Path, url: str) -> None:
    """Surveille le process Chromium. Quand il se ferme, affiche le tray."""
    if chrom_proc is None:
        # Pas de process a surveiller (fallback navigateur par defaut)
        log("Pas de process Chromium a surveiller")
        return
    log(f"Surveillance Chromium PID {chrom_proc.pid}")
    chrom_proc.wait()
    if _quit_event.is_set():
        return
    log("Chromium ferme — affichage tray systeme")
    run_tray(root, url)


def _do_quit() -> None:
    """Arrete le backend et signale la fin du launcher."""
    global _backend_proc
    _quit_event.set()
    try:
        if _backend_proc is not None and _backend_proc.poll() is None:
            _backend_proc.terminate()
            try:
                _backend_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _backend_proc.kill()
    except Exception as e:
        log(f"Erreur arret backend: {e}", "WARN")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    global _backend_proc

    minimized = "--minimized" in sys.argv

    # Empeche 2 launchers concurrents (autostart + click manuel race)
    if not acquire_singleton():
        print("[INFO] Instance MusicGo deja en cours, sortie propre.", flush=True)
        url_check = f"http://127.0.0.1:{APP_PORT}"
        if not minimized and is_musicgo_running(APP_HOST, APP_PORT):
            open_app_window(url_check)
        return 0

    root = install_dir()
    print(LOGO)
    log(f"Dossier d'installation: {root}")
    log(f"Python interpreter: {sys.executable}")
    log(f"Python version: {sys.version}")
    log(f"sys.path: {sys.path}")
    if minimized:
        log("Mode: demarre minimise dans le tray")

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

    url = f"http://127.0.0.1:{APP_PORT}"

    if port_in_use(APP_HOST, APP_PORT):
        if is_musicgo_running(APP_HOST, APP_PORT):
            log(f"Instance MusicGo deja active sur {APP_PORT}, ouverture fenetre.")
            if not minimized:
                open_app_window(url)
                time.sleep(3)
            return 0
        else:
            log(f"Port {APP_PORT} occupe par autre process (pas MusicGo)", "ERR")
            show_error(
                f"Port {APP_PORT} deja utilise par une autre application.\n\n"
                "Fermez l'application qui occupe ce port et relancez MusicGo."
            )
            return 1

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
    _backend_proc = proc
    log(f"Backend PID: {proc.pid}")

    t = threading.Thread(target=pipe_output, args=(proc.stdout, "[backend]"), daemon=True)
    t.start()

    if not wait_for_server(APP_HOST, APP_PORT, timeout=120, proc=proc):
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
            log("Le serveur n'a pas demarre a temps (120s).", "ERR")
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

    log(f"Serveur pret: {url}", "OK")

    if minimized:
        # Demarre directement dans le tray sans ouvrir Chromium
        log("Demarrage minimise — tray systeme sans ouvrir Chromium")
        tray_thread = threading.Thread(target=run_tray, args=(root, url), daemon=True)
        tray_thread.start()
    else:
        # Ouvre Chromium et surveille sa fermeture
        chrom_proc = open_app_window(url)
        watch_thread = threading.Thread(
            target=_watch_chromium, args=(chrom_proc, root, url), daemon=True
        )
        watch_thread.start()

    log("MusicGo tourne. Fermeture de la fenetre Chromium minimise dans le tray.")

    # Attend signal quitter ou mort inattendue du backend
    try:
        while not _quit_event.is_set():
            if proc.poll() is not None:
                log(f"Backend arrete (code {proc.returncode})", "WARN")
                _quit_event.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log("Arret demande...")
        _do_quit()

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
