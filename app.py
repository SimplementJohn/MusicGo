"""MusicGo - Music Download Server"""

import asyncio
import base64
import ctypes
import hashlib
import hmac
import io
import json
import logging
import os
import platform
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()

# --- Logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
log = logging.getLogger("musicgo")

# --- Configuration ---
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "2"))
DEFAULT_FORMAT = os.getenv("OUTPUT_FORMAT", "mp3")
DEFAULT_QUALITY = os.getenv("AUDIO_QUALITY", "320")
DEFAULT_SAMPLERATE = os.getenv("AUDIO_SAMPLERATE", "48000")
HOST = os.getenv("HOST", "127.0.0.1")  # Securité: bind localhost par défaut (pas LAN)
PORT = int(os.getenv("PORT", "8080"))

IS_WINDOWS = platform.system() == "Windows"


def _windows_known_music_dir() -> Path | None:
    """Retourne le dossier Musique Windows de l'utilisateur courant."""
    if not IS_WINDOWS:
        return None
    try:
        folder_id_music = UUID("{4BD8D571-6D19-48D3-BE97-422220080E43}")
        guid = ctypes.c_byte * 16
        folder_guid = guid.from_buffer_copy(folder_id_music.bytes_le)
        path_ptr = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_guid),
            0,
            None,
            ctypes.byref(path_ptr),
        )
        if result == 0 and path_ptr.value:
            return Path(path_ptr.value)
    except Exception:
        pass
    finally:
        try:
            if "ole32" in locals() and path_ptr.value:
                ole32.CoTaskMemFree(path_ptr)
        except Exception:
            pass
    return None


def _user_musicgo_dir() -> Path:
    """Dossier par defaut des medias pour l'utilisateur courant."""
    music_dir = _windows_known_music_dir()
    if music_dir is None:
        music_dir = Path.home() / "Music"
    return (music_dir / "MusicGo").resolve()

# --- Config file: APPDATA/MusicGo en priorité (writable sans admin) ---
def _config_dir() -> Path:
    env_dir = os.getenv("MUSICGO_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    if IS_WINDOWS:
        base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "MusicGo"
    return Path(__file__).parent

CONFIG_DIR = _config_dir()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"

# Fallback legacy: si config.json existe encore à côté de app.py, on migre
_LEGACY_CFG = Path(__file__).parent / "config.json"
if _LEGACY_CFG.exists() and not CONFIG_FILE.exists() and _LEGACY_CFG != CONFIG_FILE:
    try:
        CONFIG_FILE.write_bytes(_LEGACY_CFG.read_bytes())
        log.info("Config migrée : %s -> %s", _LEGACY_CFG, CONFIG_FILE)
    except Exception as e:
        log.warning("Migration config échouée: %s", e)

# --- Auth: PBKDF2-HMAC-SHA256 (stdlib, pas de dep externe) ---
# Format stocké : "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"
PBKDF2_ITER = 200_000
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL", "7200"))  # 2h
# token -> expiry_ts
active_tokens: dict[str, float] = {}

def hash_password(password: str, *, iterations: int = PBKDF2_ITER) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    # Legacy: ancien format SHA-256 pur (sans salt) →?" vérification + migration implicite
    if "$" not in stored and len(stored) == 64:
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored)
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(expected.hex(), hash_hex)
    except Exception:
        return False

_DEFAULT_NON_SECRET = {
    "username": "admin",
    "download_dir": str(_user_musicgo_dir()),
    "default_format": DEFAULT_FORMAT,
    "default_quality": DEFAULT_QUALITY,
    "default_samplerate": DEFAULT_SAMPLERATE,
}

def _default_config() -> dict:
    # Hash PBKDF2 (coûteux) généré seulement pour config neuve, pas à chaque load.
    cfg = dict(_DEFAULT_NON_SECRET)
    cfg["password_hash"] = hash_password("admin")
    return cfg

_config_cache: dict | None = None

def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
            for k, v in _DEFAULT_NON_SECRET.items():
                cfg.setdefault(k, v)
            if "password_hash" not in cfg:
                cfg["password_hash"] = hash_password("admin")
            _config_cache = cfg
            return cfg
        except Exception as e:
            log.warning("config corrompue, regeneration: %s", e)
    cfg = _default_config()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    _config_cache = cfg
    return cfg

def save_config(cfg: dict):
    global _config_cache
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    _config_cache = cfg

def issue_token() -> str:
    tok = secrets.token_urlsafe(32)
    active_tokens[tok] = time.time() + TOKEN_TTL_SECONDS
    return tok

def token_valid(tok: str) -> bool:
    if not tok:
        return False
    exp = active_tokens.get(tok)
    if not exp:
        return False
    if time.time() > exp:
        active_tokens.pop(tok, None)
        return False
    return True

def purge_expired_tokens():
    now = time.time()
    expired = [t for t, exp in active_tokens.items() if exp <= now]
    for t in expired:
        active_tokens.pop(t, None)

def require_auth(x_token: str | None) -> None:
    if not token_valid(x_token or ""):
        raise HTTPException(status_code=401, detail="Non authentifié")

app = FastAPI(title="MusicGo")

# --- CORS restrictif: extension + localhost seulement ---
_allowed_origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:3000",  # dev Vite
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"^chrome-extension://.*$|^moz-extension://.*$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# --- Pré-compilation des regex hot-path ---
RE_PROGRESS_PCT   = re.compile(r"(\d+\.?\d*)%")
RE_SPEED          = re.compile(r"at\s+(\S+/s)")
RE_SPOTDL_NAME    = re.compile(r'(?:Downloaded|Skipping)\s+"(.+?)"|Processing query:\s+(.+?)$')
RE_ETA            = re.compile(r"ETA\s+(\S+)")
RE_DESTINATION    = re.compile(r"Destination:\s+(.+)")
RE_EXTRACT_DEST   = re.compile(r"\[ExtractAudio\].*?Destination:\s+(.+)")
RE_INFO_TITLE     = re.compile(
    r"\[(?:youtube|soundcloud|tiktok|generic)[^\]]*\]\s+(.+?):\s+Downloading"
)
RE_DIRECT_EXT     = re.compile(r"\.(mp3|flac|wav|ogg|aac|m4a|wma)(\?|$)")

# --- Whitelist anti-SSRF: hôtes autorisés pour téléchargement ---
ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
    "open.spotify.com", "spotify.com",
    "soundcloud.com", "www.soundcloud.com", "m.soundcloud.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "deezer.com", "www.deezer.com", "deezer.page.link",
    "music.apple.com",
}

def url_is_safe(url: str) -> bool:
    """Bloque file://, gopher://, intranet, hôtes inconnus (anti-SSRF)."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    # Bloque adresses internes
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return False
    if host.startswith(("10.", "192.168.", "169.254.", "172.")):
        return False
    # Whitelist stricte OU URL de média direct
    if host in ALLOWED_HOSTS:
        return True
    if any(host.endswith("." + d) for d in ALLOWED_HOSTS):
        return True
    # Fichier média direct (mp3/flac/etc.) sur hôte public →?' autorisé
    if RE_DIRECT_EXT.search(url.lower()):
        return True
    return False

# --- Download directory setup ---
DOWNLOAD_DIR: Path = Path("./downloads")


def _safe_default_download_dir() -> Path:
    """Defaut user-writable : ~/Music/MusicGo."""
    return _user_musicgo_dir()


def setup_download_dir() -> Path:
    global DOWNLOAD_DIR
    cfg = load_config()
    target = Path(cfg.get("download_dir", "") or "")
    fallback = _safe_default_download_dir()

    if not target or str(target).strip() in ("", "."):
        target = fallback

    try:
        target.mkdir(parents=True, exist_ok=True)
        DOWNLOAD_DIR = target
    except (OSError, PermissionError) as e:
        log.warning("download_dir invalide (%s) : %s -> fallback %s", target, e, fallback)
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception as e2:
            log.error("fallback download_dir aussi en echec: %s", e2)
            # Dernier recours : tempdir
            fallback = Path(tempfile.gettempdir()) / "MusicGo"
            fallback.mkdir(parents=True, exist_ok=True)
        DOWNLOAD_DIR = fallback
        cfg["download_dir"] = str(fallback)
        try:
            save_config(cfg)
        except Exception as e3:
            log.warning("save_config fallback echoue: %s", e3)

    log.info("Download dir: %s", DOWNLOAD_DIR)
    return DOWNLOAD_DIR


# --- Source detection ---
def detect_source(url: str) -> str:
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "spotify.com" in url_lower or "open.spotify" in url_lower:
        return "spotify"
    if "soundcloud.com" in url_lower:
        return "soundcloud"
    if "tiktok.com" in url_lower or "vm.tiktok" in url_lower:
        return "tiktok"
    if "deezer.com" in url_lower or "deezer.page" in url_lower:
        return "deezer"
    if "music.apple.com" in url_lower:
        return "applemusic"
    if RE_DIRECT_EXT.search(url_lower):
        return "direct"
    return "unknown"


def is_playlist_url(url: str, source: str) -> bool:
    url_lower = url.lower()
    if source == "youtube":
        return "list=" in url_lower or "/playlist" in url_lower
    if source == "spotify":
        return "/album/" in url_lower or "/playlist/" in url_lower
    if source == "soundcloud":
        return "/sets/" in url_lower
    if source == "deezer":
        return "/playlist/" in url_lower or "/album/" in url_lower
    if source == "applemusic":
        return "/playlist/" in url_lower or "/album/" in url_lower
    return False


# --- Cover art embedding ---
async def embed_cover(filepath: Path, thumbnail_url: str) -> bool:
    """Download thumbnail and embed as cover art using mutagen + ffmpeg.

    Handles any input format (WebP, PNG, JPEG) by converting to JPEG via
    ffmpeg before embedding, which is required for ID3 tags in MP3 files.
    """
    if not thumbnail_url or not filepath.exists():
        return False

    try:
        # 1. Download the thumbnail in a thread so we don't block the event loop
        # (urllib.urlopen is synchronous and would freeze all asyncio tasks)
        req = urllib.request.Request(
            thumbnail_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MusicGo/1.0)"},
        )
        def _fetch():
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        raw_data = await asyncio.to_thread(_fetch)

        # 2. Convert to JPEG via ffmpeg pipe (handles WebP/PNG/any format)
        ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", "pipe:0",
            "-vf", "scale=500:500:force_original_aspect_ratio=decrease,pad=500:500:(ow-iw)/2:(oh-ih)/2:white",
            "-f", "image2", "-vcodec", "mjpeg", "-q:v", "2",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        jpg_data, _ = await asyncio.wait_for(ffmpeg.communicate(input=raw_data), timeout=15)

        if not jpg_data:
            jpg_data = raw_data  # fallback: use raw bytes

        # 3. Embed into the audio file based on format
        suffix = filepath.suffix.lower()

        if suffix == ".mp3":
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, APIC, ID3NoHeaderError
            try:
                audio = MP3(str(filepath), ID3=ID3)
                if audio.tags is None:
                    audio.add_tags()
            except ID3NoHeaderError:
                audio = MP3(str(filepath))
                audio.add_tags()
            audio.tags.delall("APIC")
            audio.tags.add(APIC(
                encoding=3,        # UTF-8
                mime="image/jpeg",
                type=3,            # Front cover
                desc="Cover",
                data=jpg_data,
            ))
            audio.save(v2_version=3)

        elif suffix == ".flac":
            from mutagen.flac import FLAC, Picture
            audio = FLAC(str(filepath))
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = jpg_data
            audio.add_picture(pic)
            audio.save()

        elif suffix in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(str(filepath))
            if audio.tags is None:
                audio.add_tags()
            audio.tags["covr"] = [MP4Cover(jpg_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        elif suffix in (".ogg", ".opus"):
            from mutagen.oggvorbis import OggVorbis
            from mutagen.flac import Picture
            audio = OggVorbis(str(filepath))
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = jpg_data
            pic.width = pic.height = 500
            pic.depth = 24
            encoded = base64.b64encode(pic.write()).decode("ascii")
            audio["metadata_block_picture"] = [encoded]
            audio.save()

        else:
            return False

        log.info("Cover embedded: %s", filepath.name)
        return True

    except Exception as e:
        log.warning("embed_cover failed for %s: %s", filepath.name, e)
        return False


def normalize_samplerate(fmt: str, samplerate: str) -> str:
    value = str(samplerate or "0").strip() or "0"
    if fmt == "mp3" and value not in ("0", "32000", "44100", "48000"):
        return "48000"
    return value


# --- Queue and state ---
class DownloadItem:
    def __init__(self, url: str, title: str, source: str, thumbnail: str = "",
                 fmt: str = "mp3", quality: str = "320", samplerate: str = DEFAULT_SAMPLERATE):
        self.id = str(uuid.uuid4())[:8]
        self.url = url
        self.title = title
        self.source = source
        self.thumbnail = thumbnail
        self.format = fmt
        self.quality = quality
        self.samplerate = normalize_samplerate(fmt, samplerate)
        self.status = "waiting"
        self.progress = 0.0
        self.speed = ""
        self.eta = ""
        self.error = ""
        self.filename = ""
        self.duration = ""
        self.added_at = datetime.now(timezone.utc).isoformat()
        self.completed_at = ""
        self.phase_label = ""
        self.cancelled = False
        self.process: asyncio.subprocess.Process | None = None

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "title": self.title,
            "source": self.source, "thumbnail": self.thumbnail,
            "format": self.format, "quality": self.quality,
            "status": self.status, "progress": self.progress,
            "speed": self.speed, "eta": self.eta, "error": self.error,
            "filename": self.filename, "duration": self.duration,
            "added_at": self.added_at, "completed_at": self.completed_at,
            "phase_label": self.phase_label,
        }


class DownloadManager:
    def __init__(self):
        self.queue: list[DownloadItem] = []
        self.library: list[dict] = []
        self.active_count = 0
        self.ws_clients: list[WebSocket] = []
        self._queue_lock = asyncio.Lock()

    async def broadcast(self, msg: dict):
        if not self.ws_clients:
            return
        results = await asyncio.gather(
            *[ws.send_json(msg) for ws in self.ws_clients],
            return_exceptions=True,
        )
        self.ws_clients = [
            ws for ws, r in zip(self.ws_clients, results)
            if not isinstance(r, Exception)
        ]

    async def broadcast_state(self):
        await self.broadcast({
            "type": "state",
            "queue": [item.to_dict() for item in self.queue],
            "library": self.library,
        })

    async def broadcast_progress(self, item: "DownloadItem"):
        """Partial update →?" n'envoie pas la library entiere."""
        await self.broadcast({
            "type": "progress",
            "id": item.id,
            "progress": item.progress,
            "speed": item.speed,
            "eta": item.eta,
            "filename": item.filename,
            "title": item.title,
            "phase_label": item.phase_label,
            "status": item.status,
        })

    async def add_item(self, url: str, title: str, source: str,
                       thumbnail: str = "", fmt: str = "mp3",
                       quality: str = "320", samplerate: str = DEFAULT_SAMPLERATE) -> DownloadItem:
        item = DownloadItem(url, title, source, thumbnail, fmt, quality, samplerate)
        self.queue.append(item)
        await self.broadcast_state()
        asyncio.ensure_future(self.process_queue())
        return item

    async def remove_item(self, item_id: str) -> bool:
        for i, item in enumerate(self.queue):
            if item.id == item_id:
                if item.status in ("waiting", "error"):
                    self.queue.pop(i)
                    await self.broadcast_state()
                    return True
                elif item.status == "downloading":
                    await self._cancel_item(item)
                    return True
        return False

    async def _cancel_item(self, item: DownloadItem):
        """Kill the download subprocess and its entire process tree."""
        item.cancelled = True
        # Remove from queue immediately so UI updates right away
        self.queue = [i for i in self.queue if i.id != item.id]
        await self.broadcast_state()

        if item.process and item.process.pid:
            pid = item.process.pid
            try:
                if IS_WINDOWS:
                    # taskkill /F /T kills the process AND all its children
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True
                    )
                else:
                    import os, signal
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                # Fallback
                try:
                    item.process.kill()
                except Exception:
                    pass

    async def clear_queue(self):
        items_to_cancel = [i for i in self.queue if i.status == "downloading"]
        # Remove waiting/error items immediately
        self.queue = [i for i in self.queue if i.status == "downloading"]
        await self.broadcast_state()
        # Now cancel active downloads (they'll remove themselves from queue)
        for item in items_to_cancel:
            await self._cancel_item(item)

    async def process_queue(self):
        async with self._queue_lock:
            while True:
                waiting = [i for i in self.queue if i.status == "waiting"]
                if not waiting or self.active_count >= MAX_PARALLEL:
                    break
                item = waiting[0]
                item.status = "downloading"
                self.active_count += 1
                asyncio.ensure_future(self._download(item))

    async def _download(self, item: DownloadItem):
        item.progress = 0
        await self.broadcast_state()

        try:
            if item.source == "spotify":
                await self._download_spotify(item)
            elif item.source in ("deezer", "applemusic"):
                await self._download_spotdl(item)
            else:
                await self._download_ytdlp(item)
        except Exception as e:
            if not item.cancelled:
                item.status = "error"
                item.error = str(e)[:200]
        finally:
            item.process = None
            self.active_count -= 1
            if not item.cancelled:
                if item.status == "downloading":
                    item.status = "error"
                    item.error = "Download stopped unexpectedly"
                await self.broadcast_state()
            asyncio.ensure_future(self.process_queue())

    async def _download_ytdlp(self, item: DownloadItem):
        output_template = "%(title)s.%(ext)s"
        fmt = item.format
        quality = item.quality
        samplerate = item.samplerate

        # Use a local temp dir for .part files to avoid rename failures on
        # network filesystems (CIFS/NFS) caused by encoding or locking issues.
        tmp_dir = Path(tempfile.gettempdir()) / "musicgo"
        tmp_dir.mkdir(exist_ok=True)

        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist",
               "--no-part", "--trim-filenames", "200",
               "--paths", f"home:{DOWNLOAD_DIR}",
               "--paths", f"temp:{tmp_dir}"]

        if fmt == "mp4":
            cmd += [
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--embed-metadata",
            ]
        else:
            cmd += [
                "-x",
                "--audio-format", fmt,
                "--audio-quality", f"{quality}k" if fmt == "mp3" else "0",
                "--embed-metadata",
                "--no-write-thumbnail",
                "--no-embed-thumbnail",
            ]

        if fmt == "mp4":
            cmd += ["--no-write-thumbnail", "--no-embed-thumbnail"]

        cmd += ["--newline", "--progress"]

        postproc_args = []
        if samplerate and samplerate != "0":
            postproc_args += ["-ar", samplerate]
        if postproc_args:
            cmd += ["--postprocessor-args", "ExtractAudio+ffmpeg_o:" + " ".join(postproc_args)]

        cmd += ["-o", output_template, item.url]

        kwargs = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT}
        if not IS_WINDOWS:
            kwargs["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        item.process = process

        # Phase tracking: yt-dlp downloads in multiple 0→?'100% cycles
        # (video stream, then audio stream, then ffmpeg conversion).
        # We map each phase to a sub-range so the bar never goes backwards.
        phase_count = 0
        last_raw_pct = -1.0
        max_dl_phases = 2 if fmt == "mp4" else 1
        last_error_lines: list[str] = []
        item.phase_label = "Téléchargement"

        async for line in process.stdout:
            if item.cancelled:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            # Collect non-download lines for better error reporting
            if not text.startswith("[download]"):
                last_error_lines.append(text)
                if len(last_error_lines) > 15:
                    last_error_lines.pop(0)

            # Detect thumbnail post-processing (in case yt-dlp config enables it)
            # Only switch to MINIATURE phase once the main download is done (>= 75%)
            # to avoid the label firing early when yt-dlp fetches the thumbnail in parallel.
            if any(m in text for m in ("[ThumbnailsConvertor]", "[EmbedThumbnail]")) and item.progress >= 75.0:
                item.phase_label = "Miniature"
                item.progress = max(item.progress, 88.0)
                item.speed = ""
                item.eta = ""
                await self.broadcast_progress(item)
                continue

            # Detect ffmpeg post-processing phase
            if any(m in text for m in ("[ExtractAudio]", "[Merger]", "[ffmpeg]", "[VideoConvertor]")):
                if "[Merger]" in text:
                    item.phase_label = "Fusion"
                else:
                    item.phase_label = "Conversion"
                item.progress = max(item.progress, 85.0)
                item.speed = ""
                item.eta = ""

                extract_match = RE_EXTRACT_DEST.search(text)
                if extract_match:
                    item.filename = Path(extract_match.group(1).strip()).name

                await self.broadcast_progress(item)
                continue

            progress_match = RE_PROGRESS_PCT.search(text)
            if progress_match:
                raw_pct = float(progress_match.group(1))

                # Detect phase change: progress jumped back after being high
                if last_raw_pct > 50.0 and raw_pct < 15.0 and phase_count < max_dl_phases - 1:
                    phase_count += 1
                last_raw_pct = raw_pct

                # Map raw % to weighted overall progress
                if fmt == "mp4":
                    if phase_count == 0:
                        mapped = raw_pct * 0.40          # 0→?"40%
                        item.phase_label = "Vidéo"
                    else:
                        mapped = 40.0 + raw_pct * 0.40   # 40→?"80%
                        item.phase_label = "Audio"
                else:
                    mapped = raw_pct * 0.82              # 0→?"82%
                    item.phase_label = "Téléchargement"

                # Monotonic: never go backwards
                item.progress = max(item.progress, mapped)

            speed_match = RE_SPEED.search(text)
            if speed_match:
                item.speed = speed_match.group(1)

            eta_match = RE_ETA.search(text)
            if eta_match:
                item.eta = eta_match.group(1)

            dest_match = RE_DESTINATION.search(text)
            if dest_match:
                item.filename = Path(dest_match.group(1).strip()).name

            info_match = RE_INFO_TITLE.search(text)
            if info_match and (item.title.startswith("http") or not item.title):
                item.title = info_match.group(1)

            await self.broadcast_progress(item)

        await process.wait()

        if item.cancelled:
            return
        if process.returncode == 0:
            item.status = "done"
            item.progress = 100
            item.completed_at = datetime.now(timezone.utc).isoformat()
            if not item.filename:
                ext = fmt if fmt != "mp4" else "mp4"
                item.filename = f"{item.title}.{ext}"
            self.library.insert(0, item.to_dict())
        else:
            # Extract a meaningful error from yt-dlp's output
            error_text = "yt-dlp exited with error"
            for ln in reversed(last_error_lines):
                if "ERROR" in ln or ("error" in ln.lower() and len(ln) > 10):
                    clean = re.sub(r"^\[.*?\]\s*(?:ERROR:|error:)?\s*", "", ln, flags=re.IGNORECASE).strip()
                    if clean and len(clean) > 5:
                        error_text = clean[:200]
                        break
            item.status = "error"
            item.error = error_text

    async def _download_spotify(self, item: DownloadItem):
        """Download Spotify track - try spotdl first, fallback to yt-dlp search."""
        # First try spotdl
        try:
            success = await self._run_spotdl(item)
            if success:
                return
        except Exception:
            pass

        # Fallback: search on YouTube via yt-dlp
        search_query = item.title if not item.title.startswith("http") else item.url
        if search_query.startswith("http"):
            # Extract track info from spotify URL for search
            search_query = item.url

        item.error = ""
        item.progress = 0

        # Use yt-dlp with the spotify URL directly (yt-dlp has spotify extractors)
        await self._download_ytdlp(item)

    async def _download_spotdl(self, item: DownloadItem):
        """Download via spotdl (for Spotify, Deezer, Apple Music)."""
        success = await self._run_spotdl(item)
        if not success:
            item.status = "error"
            item.error = "spotdl failed"

    async def _run_spotdl(self, item: DownloadItem) -> bool:
        fmt = item.format if item.format != "mp4" else "mp3"
        quality = item.quality

        cmd = [
            "spotdl", "download", item.url,
            "--output", str(DOWNLOAD_DIR / "{title} - {artists}.{output-ext}"),
            "--format", fmt,
            "--bitrate", f"{quality}k" if fmt == "mp3" else "auto",
        ]

        kwargs = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT}
        if not IS_WINDOWS:
            kwargs["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
        item.process = process
        item.phase_label = "Téléchargement"

        async for line in process.stdout:
            if item.cancelled:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            progress_match = RE_PROGRESS_PCT.search(text)
            if progress_match:
                raw_pct = float(progress_match.group(1))
                item.progress = max(item.progress, raw_pct * 0.82)

            name_match = RE_SPOTDL_NAME.search(text)
            if name_match:
                found_name = (name_match.group(1) or name_match.group(2) or "").strip()
                if found_name:
                    item.filename = found_name + f".{fmt}"
                    if item.title.startswith("http"):
                        item.title = found_name

            await self.broadcast_progress(item)

        await process.wait()

        if item.cancelled:
            return False
        if process.returncode == 0:
            item.status = "done"
            item.progress = 100
            item.completed_at = datetime.now(timezone.utc).isoformat()
            if not item.filename:
                item.filename = f"{item.title}.{fmt}"
            if item.thumbnail:
                item.phase_label = "Cover"
                item.progress = 95.0
                await self.broadcast({
                    "type": "progress", "id": item.id,
                    "progress": 95.0, "speed": "", "eta": "",
                    "filename": item.filename, "title": item.title,
                    "phase_label": "Cover",
                })
                filepath = DOWNLOAD_DIR / item.filename
                await embed_cover(filepath, item.thumbnail)
            self.library.insert(0, item.to_dict())
            return True
        return False


manager = DownloadManager()


# --- Analyze URL ---
async def analyze_url(url: str) -> dict:
    source = detect_source(url)
    is_playlist = is_playlist_url(url, source)
    tracks = []

    if source == "spotify":
        tracks = await _analyze_spotify(url, is_playlist)
    elif source in ("deezer", "applemusic"):
        tracks = await _analyze_spotdl_source(url, source, is_playlist)
    elif source in ("youtube", "soundcloud", "tiktok", "unknown"):
        tracks = await _analyze_ytdlp(url)
    elif source == "direct":
        filename = url.split("/")[-1].split("?")[0]
        tracks = [{"url": url, "title": filename}]

    if not tracks:
        tracks = [{"url": url, "title": url}]

    return {
        "url": url,
        "source": source,
        "is_playlist": is_playlist or len(tracks) > 1,
        "track_count": len(tracks),
        "tracks": tracks,
    }


async def _analyze_ytdlp(url: str) -> list:
    cmd = [sys.executable, "-m", "yt_dlp", "--dump-json", "--flat-playlist", url]
    tracks = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
                title = info.get("title", info.get("id", ""))
                track_url = info.get("webpage_url") or info.get("url") or url
                duration = info.get("duration")
                dur_str = ""
                if duration:
                    mins = int(duration) // 60
                    secs = int(duration) % 60
                    dur_str = f"{mins}:{secs:02d}"
                # Get thumbnail
                thumbnail = ""
                thumbnails = info.get("thumbnails")
                if thumbnails and isinstance(thumbnails, list):
                    # Pick a medium quality thumbnail
                    for t in reversed(thumbnails):
                        if t.get("url"):
                            thumbnail = t["url"]
                            break
                if not thumbnail:
                    thumbnail = info.get("thumbnail", "")
                tracks.append({
                    "url": track_url,
                    "title": title,
                    "duration": dur_str,
                    "thumbnail": thumbnail,
                })
            except json.JSONDecodeError:
                continue
    except (asyncio.TimeoutError, Exception):
        pass
    return tracks


async def _analyze_spotify(url: str, is_playlist: bool) -> list:
    """Analyze Spotify URL using spotdl to get track metadata."""
    tracks = []

    # Try spotdl save to get structured metadata
    try:
        tmpfile = f"_musicgo_tmp_{uuid.uuid4().hex[:8]}.spotdl"
        proc = await asyncio.create_subprocess_exec(
            "spotdl", "save", url, "--save-file", tmpfile,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(proc.communicate(), timeout=30)

        tmppath = Path(tmpfile)
        if tmppath.exists():
            try:
                data = json.loads(tmppath.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for t in data:
                        name = t.get("name", "")
                        artists = t.get("artists", [])
                        artist = artists[0] if artists else ""
                        title = f"{artist} - {name}" if artist else name
                        song_url = t.get("url", url) if is_playlist else url
                        # Spotify cover art
                        cover = t.get("cover_url", "")
                        tracks.append({
                            "url": song_url,
                            "title": title,
                            "thumbnail": cover,
                        })
            finally:
                tmppath.unlink(missing_ok=True)
    except Exception:
        pass

    # Fallback: single track with URL as title
    if not tracks:
        tracks = [{"url": url, "title": url, "thumbnail": ""}]

    return tracks


async def _analyze_spotdl_source(url: str, source: str, is_playlist: bool) -> list:
    """Analyze Deezer / Apple Music URL via spotdl."""
    # spotdl can handle deezer and apple music URLs
    return await _analyze_spotify(url, is_playlist)


# --- API Routes ---
@app.post("/api/analyze")
async def api_analyze(body: dict):
    # Endpoint public (extension navigateur sans token) mais SSRF-guard strict.
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "URL required"}, 400)
    if not url_is_safe(url):
        log.warning("Analyze refused (SSRF guard): %s", url[:200])
        return JSONResponse({"error": "URL non supportée ou bloquée"}, 400)
    try:
        result = await analyze_url(url)
        return result
    except Exception as e:
        log.exception("analyze_url error")
        return JSONResponse({"error": "Analyse impossible"}, 500)


@app.post("/api/queue/add")
async def api_queue_add(body: dict):
    # Endpoint public (extension) avec SSRF-guard par URL.
    tracks = body.get("tracks", [])
    added = []
    for track in tracks:
        url = track.get("url", "")
        if not url_is_safe(url):
            log.warning("Track refusée (SSRF): %s", url[:200])
            continue
        title = track.get("title", url)
        source = track.get("source", detect_source(url))
        thumbnail = track.get("thumbnail", "")
        fmt = track.get("format", DEFAULT_FORMAT)
        quality = track.get("quality", DEFAULT_QUALITY)
        samplerate = track.get("samplerate", DEFAULT_SAMPLERATE)
        item = await manager.add_item(url, title, source, thumbnail, fmt, quality, samplerate)
        added.append(item.to_dict())
    return {"added": added}


@app.get("/api/queue")
async def api_queue():
    return {"queue": [item.to_dict() for item in manager.queue]}


@app.delete("/api/queue/{item_id}")
async def api_queue_remove(item_id: str):
    ok = await manager.remove_item(item_id)
    return {"removed": ok}


@app.delete("/api/queue")
async def api_queue_clear():
    await manager.clear_queue()
    return {"cleared": True}


@app.post("/api/auth/login")
async def auth_login(body: dict):
    cfg = load_config()
    username = body.get("username", "")
    password = body.get("password", "")
    # Compare avec hmac.compare_digest pour éviter timing attacks sur username
    user_match = hmac.compare_digest(username, cfg["username"])
    pwd_match = verify_password(password, cfg["password_hash"])
    if user_match and pwd_match:
        # Upgrade du hash legacy (SHA-256 pur) vers PBKDF2 à la connexion
        if "$" not in cfg["password_hash"]:
            cfg["password_hash"] = hash_password(password)
            save_config(cfg)
            log.info("Hash mot de passe migré vers PBKDF2")
        purge_expired_tokens()
        token = issue_token()
        return {"token": token}
    raise HTTPException(status_code=401, detail="Identifiants incorrects")

@app.post("/api/auth/check")
async def auth_check(body: dict):
    return {"valid": token_valid(body.get("token", ""))}

@app.post("/api/auth/logout")
async def auth_logout(body: dict):
    active_tokens.pop(body.get("token", ""), None)
    return {"ok": True}


def _pick_directory_dialog(current_dir: str = "") -> str | None:
    """Ouvre un selecteur de dossier natif sur Windows."""
    if not IS_WINDOWS:
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        log.warning("tkinter indisponible pour selection dossier: %s", e)
        return None

    initial_dir = current_dir.strip() or str(DOWNLOAD_DIR) or str(_user_musicgo_dir())
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            root.update()
        except Exception:
            pass
        selected = filedialog.askdirectory(
            initialdir=initial_dir,
            mustexist=False,
            title="Choisir le dossier de telechargement MusicGo",
        )
        if not selected:
            return None
        return str(Path(selected).resolve())
    except Exception as e:
        log.warning("selection dossier echouee: %s", e)
        return None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


@app.post("/api/settings/pick-folder")
async def api_settings_pick_folder(body: dict | None = None):
    if not IS_WINDOWS:
        return JSONResponse({"ok": False, "detail": "Selection de dossier disponible uniquement sur Windows"}, status_code=400)
    current_dir = ""
    if isinstance(body, dict):
        current_dir = str(body.get("current_dir", "")).strip()
    selected = await asyncio.to_thread(_pick_directory_dialog, current_dir)
    if not selected:
        return {"ok": False, "cancelled": True}
    return {"ok": True, "path": selected}

_SETTINGS_WHITELIST = (
    "username", "download_dir",
    "default_format", "default_quality", "default_samplerate",
)

@app.get("/api/settings")
async def api_get_settings():
    cfg = load_config()
    return {k: cfg.get(k, "") for k in _SETTINGS_WHITELIST}

@app.post("/api/settings")
async def api_save_settings(body: dict):
    cfg = load_config()
    for key in ("username", "download_dir", "default_format", "default_quality", "default_samplerate"):
        if key in body:
            cfg[key] = str(body[key]).strip()
    if body.get("new_password"):
        cfg["password_hash"] = hash_password(body["new_password"])
    save_config(cfg)
    # Apply audio defaults + download dir hot-reload
    global DEFAULT_FORMAT, DEFAULT_QUALITY, DEFAULT_SAMPLERATE
    DEFAULT_FORMAT = cfg["default_format"]
    DEFAULT_QUALITY = cfg["default_quality"]
    DEFAULT_SAMPLERATE = cfg["default_samplerate"]
    try:
        setup_download_dir()
    except Exception as e:
        log.warning("setup_download_dir après save: %s", e)
    return {"ok": True}


@app.get("/api/library")
async def api_library():
    return {"library": manager.library}


@app.delete("/api/library")
async def api_library_clear(x_token: str = Header(None)):
    require_auth(x_token)
    manager.library.clear()
    await manager.broadcast_state()
    return {"cleared": True}


@app.post("/api/library/remove")
async def api_library_remove(body: dict, x_token: str = Header(None)):
    require_auth(x_token)
    ids = set(body.get("ids", []))
    manager.library = [i for i in manager.library if i["id"] not in ids]
    await manager.broadcast_state()
    return {"removed": len(ids)}


@app.post("/api/library/open")
async def api_library_open(body: dict):
    item_id = str(body.get("id", "")).strip()
    item = next((i for i in manager.library if i["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    file_path = DOWNLOAD_DIR / item["filename"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier absent du disque")
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", str(file_path)])
    else:
        subprocess.Popen(["xdg-open", str(file_path.parent)])
    return {"ok": True}


@app.get("/api/extension/download")
async def extension_download(request: Request):
    """Serve the extension folder as a downloadable ZIP, with the server URL injected."""
    ext_path = (Path(__file__).parent / "extension").resolve()
    if not ext_path.exists():
        return JSONResponse({"error": "Dossier extension introuvable"}, 404)

    # Derive the actual server URL from the incoming request so the extension
    # always points to the right host (works for localhost or LAN IP).
    host = request.headers.get("host", f"localhost:{PORT}")
    server_url = f"{request.url.scheme}://{host}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(ext_path.rglob("*")):
            if not file.is_file():
                continue
            arc_name = str(file.relative_to(ext_path.parent))
            if file.name == "background.js":
                content = file.read_text("utf-8").replace(
                    "http://localhost:8080", server_url
                )
                zf.writestr(arc_name, content)
            elif file.name == "manifest.json":
                content = file.read_text("utf-8").replace(
                    "http://localhost:8080/*", f"{server_url}/*"
                )
                zf.writestr(arc_name, content)
            else:
                zf.write(file, arc_name)
    data = buf.getvalue()

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=musicgo-extension.zip"},
    )


@app.post("/api/extension/launch")
async def extension_launch():
    """Launch Chrome or Edge with the MusicGo extension pre-loaded (dedicated profile).
    Protégé par HOST=127.0.0.1 (localhost only).
    """
    ext_path = (Path(__file__).parent / "extension").resolve()
    # Profile dans APPDATA (writable, pas besoin de droits admin)
    profile_path = (CONFIG_DIR / "chrome-profile").resolve()

    if not ext_path.exists():
        return JSONResponse({"success": False, "error": "Dossier extension introuvable"}, 404)

    # Candidate browser paths (Windows + Linux + macOS)
    candidates = [
        # Chrome Windows
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        # Edge Windows
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        # Linux
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/microsoft-edge"),
        # macOS
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]

    browser = None
    for c in candidates:
        if c.exists():
            browser = str(c)
            break

    if not browser:
        # Fallback: try PATH
        for name in ("google-chrome", "chromium", "chromium-browser", "msedge"):
            try:
                r = subprocess.run(
                    ["where" if IS_WINDOWS else "which", name],
                    capture_output=True, text=True
                )
                if r.returncode == 0:
                    browser = r.stdout.strip().splitlines()[0]
                    break
            except Exception:
                pass

    if not browser:
        return JSONResponse({"success": False, "error": "Chrome ou Edge introuvable sur ce système"})

    cmd = [
        browser,
        f"--user-data-dir={profile_path}",
        f"--load-extension={ext_path}",
        "--no-first-run",
        "--no-default-browser-check",
        f"http://localhost:{PORT}",
    ]

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

    return {"success": True, "browser": Path(browser).stem}


@app.get("/api/config")
async def api_config():
    return {
        "download_dir": str(DOWNLOAD_DIR),
        "max_parallel": MAX_PARALLEL,
        "output_format": DEFAULT_FORMAT,
        "audio_quality": DEFAULT_QUALITY,
    }


# --- WebSocket ---
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    manager.ws_clients.append(ws)
    await ws.send_json({
        "type": "state",
        "queue": [item.to_dict() for item in manager.queue],
        "library": manager.library,
    })
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in manager.ws_clients:
            manager.ws_clients.remove(ws)


# --- Setup initial (1er lancement) ---
def _default_download_dir() -> str:
    """Dossier Musique/MusicGo de l'utilisateur courant."""
    return str(_user_musicgo_dir())
_SETUP_HTML_TMPL = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MusicGo - Configuration</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  .card {{ background: #16213e; border-radius: 16px; padding: 40px; width: 500px;
           box-shadow: 0 8px 32px rgba(0,0,0,.5); }}
  .logo {{ text-align: center; margin-bottom: 28px; }}
  h1 {{ text-align: center; font-size: 1.6rem; margin-bottom: 8px; color: #e94560; }}
  .sub {{ text-align: center; color: #aaa; margin-bottom: 28px; font-size: .9rem; }}
  label {{ display: block; font-size: .85rem; color: #bbb; margin-bottom: 6px; }}
  .hint {{ font-size: .8rem; color: #666; margin-top: 6px; }}
  input {{ width: 100%; background: #0f3460; border: 1px solid #1a5276; border-radius: 8px;
           padding: 11px 14px; color: #fff; font-size: .95rem; outline: none; }}
  input:focus {{ border-color: #e94560; }}
  .btn-ok {{ width: 100%; background: #e94560; color: #fff; padding: 14px;
             font-size: 1rem; margin-top: 22px; border-radius: 10px; border: none;
             cursor: pointer; transition: opacity .15s; font-weight: 600; }}
  .btn-ok:hover {{ opacity: .85; }}
  .err {{ color: #e94560; font-size: .83rem; margin-top: 10px; text-align: center; display:none; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg width="56" height="56" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="28" cy="28" r="26" stroke="#e94560" stroke-width="3"/>
      <polygon points="22,18 22,38 40,28" fill="#fff"/>
    </svg>
  </div>
  <h1>Bienvenue sur MusicGo</h1>
  <p class="sub">Ou souhaitez-vous enregistrer vos musiques ?</p>
  <label>Dossier de telechargement</label>
  <input id="dir" type="text" value="{default_dir}" />
  <p class="hint">Modifiez le chemin si necessaire, puis cliquez sur Commencer.</p>
  <div class="err" id="err">Veuillez entrer un chemin valide.</div>
  <button class="btn-ok" onclick="save()">Commencer</button>
</div>
<script>
async function save() {{
  const dir = document.getElementById('dir').value.trim();
  if (!dir) {{ document.getElementById('err').style.display = 'block'; return; }}
  document.getElementById('err').style.display = 'none';
  const btn = document.querySelector('.btn-ok');
  btn.disabled = true; btn.textContent = 'Enregistrement...';
  const r = await fetch('/api/setup/init', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{download_dir: dir}})
  }}).then(r => r.json()).catch(() => ({{ok: false, error: 'Erreur reseau.'}}));
  if (r.ok) {{ window.location.href = '/'; }}
  else {{
    document.getElementById('err').textContent = r.error || 'Erreur.';
    document.getElementById('err').style.display = 'block';
    btn.disabled = false; btn.textContent = 'Commencer';
  }}
}}
</script>
</body>
</html>"""

@app.get("/setup")
async def setup_page():
    cfg = load_config()
    if cfg.get("setup_done"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/")
    from fastapi.responses import HTMLResponse
    html = _SETUP_HTML_TMPL.format(default_dir=_default_download_dir().replace("\\", "\\\\"))
    return HTMLResponse(html)

@app.post("/api/setup/init")
async def api_setup_init(body: dict):
    download_dir = str(body.get("download_dir", "")).strip()
    if not download_dir:
        return JSONResponse({"ok": False, "error": "Dossier vide"}, status_code=400)
    p = Path(download_dir)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Impossible de creer le dossier: {e}"}, status_code=400)
    cfg = load_config()
    cfg["download_dir"] = str(p.resolve())
    cfg["setup_done"] = True
    save_config(cfg)
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = p.resolve()
    return {"ok": True}

# --- Serve frontend (production: built Vite files in dist/) ---
DIST_DIR = Path(__file__).parent / "dist"

if DIST_DIR.is_dir():
    @app.get("/")
    async def index():
        return FileResponse(DIST_DIR / "index.html")

    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        file_path = DIST_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(DIST_DIR / "index.html")
else:
    log.info("No dist/ folder found. Use 'npm run dev' (port 3000) + 'python app.py' (port 8080)")


AUDIO_EXTS = frozenset((".mp3", ".flac", ".wav", ".ogg", ".aac", ".m4a", ".wma", ".opus", ".mp4"))

def _scan_library_sync(download_dir: Path) -> list[dict]:
    """Scan disque via scandir →?" stat gratuit par DirEntry, pas de syscall par fichier."""
    out: list[dict] = []
    try:
        with os.scandir(download_dir) as it:
            for entry in it:
                if not entry.is_file(follow_symlinks=False):
                    continue
                suffix = os.path.splitext(entry.name)[1].lower()
                if suffix not in AUDIO_EXTS:
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                ts = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                stem = entry.name[: -len(suffix)] if suffix else entry.name
                out.append({
                    "id": str(uuid.uuid4())[:8],
                    "url": "", "title": stem, "source": "library",
                    "thumbnail": "", "format": suffix[1:],
                    "quality": "", "status": "done", "progress": 100,
                    "speed": "", "eta": "", "error": "",
                    "filename": entry.name, "duration": "",
                    "added_at": ts, "completed_at": ts,
                })
    except Exception as e:
        log.warning("scan library echoue: %s", e)
    return out


# --- Startup ---
async def _purge_tokens_loop():
    while True:
        await asyncio.sleep(600)
        purge_expired_tokens()

@app.on_event("startup")
async def startup():
    setup_download_dir()
    items = await asyncio.to_thread(_scan_library_sync, DOWNLOAD_DIR)
    manager.library.extend(items)
    manager.library.sort(key=lambda x: x.get("completed_at", ""), reverse=True)
    log.info("Library loaded: %d files (from %s)", len(manager.library), DOWNLOAD_DIR)
    log.info("Config: %s", CONFIG_FILE)
    log.info("Server listening on http://%s:%d", HOST, PORT)
    asyncio.ensure_future(_purge_tokens_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
