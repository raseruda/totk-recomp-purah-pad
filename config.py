"""Configuração global do Purah Pad (Segunda Tela para TotK Recomp)."""
from __future__ import annotations

import ctypes
import json
import locale
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

_SETTINGS_LOCK = threading.RLock()

ROOT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULT_GAME_DIR = Path(r"C:\Games\The Legend of Zelda - Tears of the Kingdom")
CACHE_DIR = ROOT_DIR / "cache"
TILES_CACHE_DIR = CACHE_DIR / "tiles"
ICONS_CACHE_DIR = CACHE_DIR / "icons"
MASKS_CACHE_DIR = CACHE_DIR / "masks"
DATA_DIR = ROOT_DIR / "data"
WEB_DIR = ROOT_DIR / "web"

SETTINGS_PATH = DATA_DIR / "settings.json"
USER_MARKERS_PATH = DATA_DIR / "user_markers.json"
META_PATH = CACHE_DIR / "meta.json"
MAP_DATA_PATH = CACHE_DIR / "map_data.json"
ENTITIES_PATH = CACHE_DIR / "entities.json"
QUESTS_PATH = CACHE_DIR / "quests.json"
CATALOG_PATH = CACHE_DIR / "catalog.json"

CACHE_VERSION = 5
DEFAULT_PORT = 8765

SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": "USen", "label": "English (US)"},
    {"code": "EUen", "label": "English (EU)"},
    {"code": "USpt", "label": "Português (Brasil)"},
    {"code": "USes", "label": "Español (Latinoamérica)"},
    {"code": "EUes", "label": "Español (España)"},
    {"code": "USfr", "label": "Français (Canada)"},
    {"code": "EUfr", "label": "Français (France)"},
    {"code": "EUde", "label": "Deutsch"},
    {"code": "EUit", "label": "Italiano"},
    {"code": "EUnl", "label": "Nederlands"},
    {"code": "EUru", "label": "Русский"},
    {"code": "JPja", "label": "日本語"},
    {"code": "KRko", "label": "한국어"},
    {"code": "CNzh", "label": "简体中文"},
    {"code": "TWzh", "label": "繁體中文"},
]
_ROMFS_LANG_BY_LOWER: dict[str, str] = {x["code"].lower(): x["code"] for x in SUPPORTED_LANGUAGES}

DEFAULT_SETTINGS: dict[str, Any] = {
    "game_dir": str(DEFAULT_GAME_DIR),
    "lang": "auto",
    "port": DEFAULT_PORT,
    "spoiler_free": True,
    "map_mode": "spoiler_free",
    "assist_radius": 200,
    "fog_of_war": True,
    "auto_layer": True,
    "follow_link": True,
    "show_heros_path": True,
    "ui_prefs": {},
}


def normalize_locale_to_romfs(raw: str | None) -> str | None:
    """Converte código de idioma (Switch, Windows/BCP-47 ou RomFS) para o código Mals oficial do TotK."""
    if not raw:
        return None
    clean = str(raw).strip().strip('"').strip("'")
    if not clean or clean.lower() == "auto":
        return None
    clean = clean.split(".", 1)[0].split("@", 1)[0].strip()
    low = clean.lower()
    if low in _ROMFS_LANG_BY_LOWER:
        return _ROMFS_LANG_BY_LOWER[low]

    tag = low.replace("_", "-")
    parts = [p for p in tag.split("-") if p]
    if not parts:
        return None
    primary = parts[0]
    sub = parts[1:]

    if primary == "pt":
        return "USpt"
    if primary == "en":
        if any(r in sub for r in ("gb", "uk", "au", "nz", "ie", "eu", "za")):
            return "EUen"
        return "USen"
    if primary == "es":
        if "es" in sub:
            return "EUes"
        return "USes"
    if primary == "fr":
        if any(r in sub for r in ("fr", "be", "ch", "lu", "mc")):
            return "EUfr"
        return "USfr"
    if primary == "de":
        return "EUde"
    if primary == "it":
        return "EUit"
    if primary == "nl":
        return "EUnl"
    if primary == "ru":
        return "EUru"
    if primary == "ja":
        return "JPja"
    if primary == "ko":
        return "KRko"
    if primary == "zh":
        if any(r in sub for r in ("hant", "tw", "hk", "mo")):
            return "TWzh"
        return "CNzh"
    return None


def _read_totk_ini_language(ini_path: Path) -> str | None:
    if not ini_path.is_file():
        return None
    try:
        lines = ini_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    section = ""
    found_lang: str | None = None
    found_locale: str | None = None
    for raw_line in lines:
        line = re.split(r"[#;]", raw_line, maxsplit=1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if "=" not in line:
            continue
        if section not in ("", "language"):
            continue
        k, v = line.split("=", 1)
        k_low = k.strip().lower()
        val = v.strip()
        if k_low == "lang" and val:
            found_lang = normalize_locale_to_romfs(val) or found_lang
        elif k_low == "locale" and val:
            found_locale = normalize_locale_to_romfs(val) or found_locale
    return found_lang or found_locale


def _read_windows_locale() -> str | None:
    try:
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        loc = locale.windows_locale.get(lcid)
        if loc:
            norm = normalize_locale_to_romfs(loc)
            if norm:
                return norm
    except Exception:
        pass
    try:
        loc_tuple = locale.getlocale()
        if loc_tuple and loc_tuple[0]:
            norm = normalize_locale_to_romfs(loc_tuple[0])
            if norm:
                return norm
    except Exception:
        pass
    return None


def detect_game_language(game_dir: Path | str | None = None) -> tuple[str, str]:
    """Detecta o idioma do TotK Recomp (env -> totk.ini -> totk-install.json -> Windows -> USen)."""
    env_raw = os.environ.get("TOTK_LANG") or os.environ.get("TOTK_LOCALE")
    if env_raw:
        norm = normalize_locale_to_romfs(env_raw)
        if norm:
            return norm, "env"

    base = Path(game_dir) if game_dir else DEFAULT_GAME_DIR
    ini_lang = _read_totk_ini_language(base / "totk.ini")
    if ini_lang:
        return ini_lang, "totk.ini"

    inst_path = base / "totk-install.json"
    if inst_path.is_file():
        try:
            inst = json.loads(inst_path.read_text(encoding="utf-8"))
            norm = normalize_locale_to_romfs(inst.get("lang"))
            if norm:
                return norm, "totk-install.json"
        except (OSError, json.JSONDecodeError):
            pass

    win_lang = _read_windows_locale()
    if win_lang:
        return win_lang, "windows"

    return "USen", "default"


def resolve_effective_language(
    game_dir: Path | str | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Retorna (codigo_romfs_efetivo, configuracao_salva, origem)."""
    cfg = settings if settings is not None else load_settings()
    raw_setting = str(cfg.get("lang") or "auto").strip()
    if not raw_setting or raw_setting.lower() == "auto":
        code, source = detect_game_language(game_dir or DEFAULT_GAME_DIR)
        return code, "auto", source
    norm = normalize_locale_to_romfs(raw_setting)
    if norm:
        return norm, norm, "manual"
    code, source = detect_game_language(game_dir or DEFAULT_GAME_DIR)
    return code, "auto", source


def ensure_dirs() -> None:
    """Garante que os diretórios de cache e dados existam."""
    for d in (CACHE_DIR, TILES_CACHE_DIR, ICONS_CACHE_DIR, MASKS_CACHE_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """Lê data/settings.json mesclado com os valores padrão."""
    with _SETTINGS_LOCK:
        ensure_dirs()
        cfg = dict(DEFAULT_SETTINGS)
        cfg["ui_prefs"] = {}
        if SETTINGS_PATH.is_file():
            try:
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cfg.update(loaded)
                    if not isinstance(cfg.get("ui_prefs"), dict):
                        cfg["ui_prefs"] = {}
            except (OSError, json.JSONDecodeError):
                pass
        return cfg


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Atualiza e persiste data/settings.json de forma atômica."""
    with _SETTINGS_LOCK:
        cfg = load_settings()
        cfg.update(updates)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)
        return cfg


def _looks_like_game_dir(p: Path) -> bool:
    return (p / "totk.exe").is_file() or (p / "romfs").is_dir() or (p / "totk.ini").is_file()


def get_game_dir(override: str | Path | None = None) -> Path:
    """Resolve o diretório de instalação do TotK Recomp."""
    if override:
        return Path(override)
    env = os.environ.get("TOTK_GAME_DIR")
    if env:
        return Path(env)
    if _looks_like_game_dir(ROOT_DIR.parent):
        return ROOT_DIR.parent
    if _looks_like_game_dir(ROOT_DIR):
        return ROOT_DIR
    saved = load_settings().get("game_dir")
    if saved and _looks_like_game_dir(Path(saved)):
        return Path(saved)
    if DEFAULT_GAME_DIR.is_dir():
        return DEFAULT_GAME_DIR
    return ROOT_DIR.parent


def find_latest_save_slot(game_dir: Path | str | None = None) -> tuple[Path | None, Path | None]:
    """Encontra a pasta slot_XX mais recente e o diretório do perfil (com album/).

    Retorna (slot_dir, profile_uid_dir) ou (None, None) se nenhum save existir.
    """
    base = Path(game_dir) if game_dir else get_game_dir()
    save_root = base / "profile" / "save"
    if not save_root.is_dir():
        return None, None

    best_sav: Path | None = None
    best_mtime = -1.0
    for uid_dir in save_root.iterdir():
        if not uid_dir.is_dir():
            continue
        for slot_dir in uid_dir.glob("slot_*"):
            prog = slot_dir / "progress.sav"
            if prog.is_file():
                try:
                    mt = prog.stat().st_mtime
                except OSError:
                    continue
                if mt > best_mtime:
                    best_mtime = mt
                    best_sav = prog

    if best_sav is not None:
        slot_dir = best_sav.parent
        return slot_dir, slot_dir.parent

    # Fallback: retorna ao menos o perfil caso haja álbum sem slot
    for uid_dir in save_root.iterdir():
        if uid_dir.is_dir() and (uid_dir / "album").is_dir():
            return None, uid_dir
    return None, None
