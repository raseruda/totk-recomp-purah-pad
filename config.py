"""Configuração global do Purah Pad (Segunda Tela para TotK Recomp)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
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

CACHE_VERSION = 4
DEFAULT_PORT = 8765

DEFAULT_SETTINGS: dict[str, Any] = {
    "game_dir": str(DEFAULT_GAME_DIR),
    "lang": "USpt",
    "port": DEFAULT_PORT,
    "spoiler_free": True,
    "map_mode": "spoiler_free",
    "assist_radius": 200,
    "fog_of_war": True,
    "auto_layer": True,
    "follow_link": True,
    "show_heros_path": True,
}


def ensure_dirs() -> None:
    """Garante que os diretórios de cache e dados existam."""
    for d in (CACHE_DIR, TILES_CACHE_DIR, ICONS_CACHE_DIR, MASKS_CACHE_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    """Lê data/settings.json mesclado com os valores padrão."""
    ensure_dirs()
    cfg = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.is_file():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Atualiza e persiste data/settings.json de forma atômica."""
    cfg = load_settings()
    cfg.update(updates)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)
    return cfg


def get_game_dir(override: str | Path | None = None) -> Path:
    """Resolve o diretório de instalação do TotK Recomp."""
    if override:
        return Path(override)
    env = os.environ.get("TOTK_GAME_DIR")
    if env:
        return Path(env)
    if (ROOT_DIR.parent / "totk.exe").is_file():
        return ROOT_DIR.parent
    return Path(load_settings().get("game_dir") or DEFAULT_GAME_DIR)


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
