"""Servidor HTTP local e SSE do Purah Pad (Segunda Tela para TotK Recomp)."""
from __future__ import annotations

import argparse
import gzip
import json
import math
import mimetypes
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import asset_builder
from config import (
    CATALOG_PATH,
    ENTITIES_PATH,
    MAP_DATA_PATH,
    QUESTS_PATH,
    SUPPORTED_LANGUAGES,
    USER_MARKERS_PATH,
    WEB_DIR,
    detect_game_language,
    ensure_dirs,
    find_latest_save_slot,
    get_game_dir,
    load_settings,
    normalize_locale_to_romfs,
    resolve_effective_language,
    save_settings,
)
from live_memory import LiveMemoryReader
from save_reader import SaveProgressReader, read_album_photos, read_footprint_sav

TILE_URL_RE = re.compile(r"^/api/tile/(surface|sky|depths|surface_fog|sky_fog)/([0-4])/(\d{1,2})/(\d{1,2})\.png$")
ICON_URL_RE = re.compile(r"^/api/icon/(map|item|picturebook|picturebook_detail|chara|chara_pic)/([A-Za-z0-9_.\-^]+)\.png$")
MASK_URL_RE = re.compile(r"^/api/mask/([A-Za-z0-9_\-]+)\.png$")
ALBUM_URL_RE = re.compile(r"^/api/album/([A-Za-z0-9_.\-]+\.jpg)$")
MARKER_ID_RE = re.compile(r"^/api/markers/([A-Za-z0-9_\-]+)$")
GAME_PIN_ID_RE = re.compile(r"^/api/game/pins/(\d+)$")
GAME_STAMP_ID_RE = re.compile(r"^/api/game/stamps/(\d+)$")

_UI_PREF_ENUMS: dict[str, tuple[str, ...]] = {
    "mapMode": ("spoiler_free", "assist", "full"),
    "layer": ("sky", "surface", "depths"),
    "activeTab": ("map", "inventory", "quests", "archives", "wiki"),
}
_UI_PREF_BOOLS = (
    "fogOfWar",
    "hideCompleted",
    "autoLayer",
    "followLink",
    "showHeroPath",
    "showPins",
    "showQuests",
    "showCustom",
    "sidebarCollapsed",
    "nearbyOpen",
    "nearbyManuallyClosed",
    "archiveSpoiler",
    "wikiShopsOnly",
    "wikiAllRanks",
)
_UI_PREF_FLOATS: dict[str, tuple[float, float]] = {
    "zoom": (0.06, 2.6),
    "camX": (-6500.0, 6500.0),
    "camZ": (-5500.0, 5500.0),
}
_UI_PREF_STRS = ("nearbyFilter", "invCat", "questCat", "questStatus", "archiveSub", "archiveCat", "wikiCat")
_ALLOWED_ENTITY_KEYS = ("npcs", "animals", "plants", "monsters")


def _sanitize_ui_prefs(raw: Any) -> dict[str, Any]:
    """Valida e limita campos de preferências da UI antes de salvar em settings.json."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, allowed in _UI_PREF_ENUMS.items():
        v = raw.get(k)
        if isinstance(v, str) and v in allowed:
            out[k] = v
    for k in _UI_PREF_BOOLS:
        v = raw.get(k)
        if isinstance(v, bool):
            out[k] = v
    ar = raw.get("assistRadius")
    if isinstance(ar, (int, float)) and not isinstance(ar, bool) and math.isfinite(ar):
        out["assistRadius"] = max(50, min(1000, int(round(ar))))
    for k, (lo, hi) in _UI_PREF_FLOATS.items():
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[k] = round(max(lo, min(hi, float(v))), 4)
    for k in _UI_PREF_STRS:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:32]
    cats = raw.get("enabledCats")
    if isinstance(cats, list):
        clean_cats: list[str] = []
        seen_c: set[str] = set()
        for item in cats:
            if isinstance(item, str):
                s = item.strip()[:48]
                if s and s not in seen_c:
                    seen_c.add(s)
                    clean_cats.append(s)
                    if len(clean_cats) >= 64:
                        break
        out["enabledCats"] = clean_cats
    ents = raw.get("enabledEntities")
    if isinstance(ents, list):
        clean_ents: list[str] = []
        for item in ents:
            if isinstance(item, str) and item in _ALLOWED_ENTITY_KEYS and item not in clean_ents:
                clean_ents.append(item)
        out["enabledEntities"] = clean_ents
    return out


def _get_lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


class PurahPadRuntime:
    """Gerencia cache estático, leitor ao vivo, leitor de save e marcadores do usuário."""

    def __init__(
        self,
        game_dir: Path,
        lang: str = "USen",
        lang_setting: str = "auto",
        lang_source: str = "default",
        lan: bool = False,
        port: int = 8765,
    ) -> None:
        ensure_dirs()
        self.game_dir = game_dir
        self.lang = lang
        self.lang_setting = lang_setting
        self.lang_source = lang_source
        self.lan = lan
        self.port = port
        self.stop_event = threading.Event()

        self._static_lock = threading.Lock()
        self.map_data: dict[str, Any] | None = None
        self.quests_data: dict[str, Any] | None = None
        self.catalog_data: dict[str, Any] | None = None
        self._static_bytes: dict[str, bytes] = {}
        self._static_gz: dict[str, bytes] = {}

        self._state_lock = threading.Lock()
        self._sse_cond = threading.Condition(self._state_lock)
        self._live_seq = 0
        self._latest_live: dict[str, Any] = {"mode": "offline", "status": "offline", "player": None, "map": {"pins": [], "stamps": []}}
        self._latest_snapshot: dict[str, Any] = {"mode": "offline", "status": "offline"}

        self._live_reader = LiveMemoryReader(game_dir)
        self._save_reader: SaveProgressReader | None = None
        self._save_mtime: float = -1.0
        self._save_slot_dir: Path | None = None
        self._profile_dir: Path | None = None
        self._save_snapshot_cache: dict[str, Any] | None = None

        self._fp_mtime: float = -1.0
        self._fp_cache: dict[str, Any] = {"paths": {"surface": [], "sky": [], "depths": []}, "deaths": [], "count": 0}

        self._markers_lock = threading.Lock()
        self._markers: list[dict[str, Any]] = self._load_markers()

    def _load_markers(self) -> list[dict[str, Any]]:
        if USER_MARKERS_PATH.is_file():
            try:
                data = json.loads(USER_MARKERS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return []

    def _save_markers(self) -> None:
        tmp = USER_MARKERS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._markers, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(USER_MARKERS_PATH)

    def get_markers(self) -> list[dict[str, Any]]:
        with self._markers_lock:
            return list(self._markers)

    def add_marker(self, body: dict[str, Any]) -> dict[str, Any]:
        marker = {
            "id": uuid.uuid4().hex[:10],
            "title": str(body.get("title") or "Marcador")[:80],
            "note": str(body.get("note") or "")[:1000],
            "icon": str(body.get("icon") or "star")[:32],
            "color": str(body.get("color") or "#f0c850")[:16],
            "layer": str(body.get("layer") or "surface") if body.get("layer") in ("surface", "sky", "depths") else "surface",
            "x": round(float(body.get("x", 0.0)), 2),
            "z": round(float(body.get("z", 0.0)), 2),
            "createdAt": int(time.time()),
        }
        with self._markers_lock:
            self._markers.append(marker)
            self._save_markers()
        return marker

    def update_marker(self, mid: str, body: dict[str, Any]) -> dict[str, Any] | None:
        with self._markers_lock:
            for m in self._markers:
                if m.get("id") == mid:
                    if "title" in body:
                        m["title"] = str(body["title"] or "Marcador")[:80]
                    if "note" in body:
                        m["note"] = str(body["note"] or "")[:1000]
                    if "icon" in body:
                        m["icon"] = str(body["icon"] or "star")[:32]
                    if "color" in body:
                        m["color"] = str(body["color"] or "#f0c850")[:16]
                    if body.get("layer") in ("surface", "sky", "depths"):
                        m["layer"] = body["layer"]
                    if "x" in body:
                        m["x"] = round(float(body["x"]), 2)
                    if "z" in body:
                        m["z"] = round(float(body["z"]), 2)
                    self._save_markers()
                    return dict(m)
        return None

    def delete_marker(self, mid: str) -> bool:
        with self._markers_lock:
            before = len(self._markers)
            self._markers = [m for m in self._markers if m.get("id") != mid]
            if len(self._markers) != before:
                self._save_markers()
                return True
        return False

    def _load_static_caches(self) -> None:
        if not asset_builder.is_cache_ready(self.game_dir, self.lang):
            return
        with self._static_lock:
            if self.map_data is None and MAP_DATA_PATH.is_file():
                raw = MAP_DATA_PATH.read_bytes()
                self.map_data = json.loads(raw.decode("utf-8"))
                self._static_bytes["map_data"] = raw
                self._static_gz["map_data"] = gzip.compress(raw, compresslevel=5)
            if self.quests_data is None and QUESTS_PATH.is_file():
                raw = QUESTS_PATH.read_bytes()
                self.quests_data = json.loads(raw.decode("utf-8"))
                self._static_bytes["quests"] = raw
                self._static_gz["quests"] = gzip.compress(raw, compresslevel=5)
            if self.catalog_data is None and CATALOG_PATH.is_file():
                raw = CATALOG_PATH.read_bytes()
                self.catalog_data = json.loads(raw.decode("utf-8"))
                self._static_bytes["catalog"] = raw
                self._static_gz["catalog"] = gzip.compress(raw, compresslevel=5)
            if "entities" not in self._static_bytes and ENTITIES_PATH.is_file():
                raw = ENTITIES_PATH.read_bytes()
                self._static_bytes["entities"] = raw
                self._static_gz["entities"] = gzip.compress(raw, compresslevel=5)

    def get_static_payload(self, name: str, accept_gzip: bool) -> tuple[bytes, bool] | None:
        with self._static_lock:
            if name not in self._static_bytes:
                return None
            if accept_gzip and name in self._static_gz:
                return self._static_gz[name], True
            return self._static_bytes[name], False

    def start_background_tasks(self, force_rebuild: bool = False) -> None:
        if not force_rebuild and asset_builder.is_cache_ready(self.game_dir, self.lang):
            asset_builder.build_all(self.game_dir, lang=self.lang, force=False)
            self._load_static_caches()
            with self._static_lock:
                self._refresh_save_if_needed(self.map_data, self.quests_data, self.catalog_data)
            if self._save_reader is not None:
                self._latest_live = self._save_reader.build_live_pose()
                if self._save_snapshot_cache is not None:
                    self._latest_snapshot = dict(self._save_snapshot_cache)
        else:
            threading.Thread(target=self._run_builder, args=(force_rebuild,), daemon=True, name="AssetBuilder").start()
        threading.Thread(target=self._poll_loop, daemon=True, name="GamePoller").start()

    def trigger_rebuild(self) -> None:
        if asset_builder.get_build_status().get("state") == "building":
            return
        asset_builder._set_status(state="building", step="init", progress=0, total=100, message="Rebuilding cache...", error="")
        with self._static_lock:
            self.map_data = None
            self.quests_data = None
            self.catalog_data = None
            self._static_bytes.clear()
            self._static_gz.clear()
        threading.Thread(target=self._run_builder, args=(True,), daemon=True, name="AssetBuilder").start()

    def get_settings(self) -> dict[str, Any]:
        cfg = load_settings()
        return {
            "lang": self.lang,
            "lang_setting": self.lang_setting,
            "lang_source": self.lang_source,
            "ui_prefs": _sanitize_ui_prefs(cfg.get("ui_prefs") or {}),
        }

    def update_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        lang_requested = "lang" in body
        if lang_requested:
            raw_lang = str(body.get("lang") or "auto").strip()
            norm = normalize_locale_to_romfs(raw_lang)
            new_setting = "auto" if (not raw_lang or raw_lang.lower() == "auto" or norm is None) else norm
            updates["lang"] = new_setting

        if isinstance(body.get("ui_prefs"), dict):
            cur_cfg = load_settings()
            merged_prefs = _sanitize_ui_prefs(cur_cfg.get("ui_prefs") or {})
            merged_prefs.update(_sanitize_ui_prefs(body["ui_prefs"]))
            updates["ui_prefs"] = merged_prefs
            if "mapMode" in merged_prefs:
                updates["map_mode"] = merged_prefs["mapMode"]
                updates["spoiler_free"] = merged_prefs["mapMode"] == "spoiler_free"
            if "assistRadius" in merged_prefs:
                updates["assist_radius"] = merged_prefs["assistRadius"]
            if "fogOfWar" in merged_prefs:
                updates["fog_of_war"] = merged_prefs["fogOfWar"]
            if "autoLayer" in merged_prefs:
                updates["auto_layer"] = merged_prefs["autoLayer"]
            if "followLink" in merged_prefs:
                updates["follow_link"] = merged_prefs["followLink"]
            if "showHeroPath" in merged_prefs:
                updates["show_heros_path"] = merged_prefs["showHeroPath"]

        cfg = save_settings(updates) if updates else load_settings()
        rebuilding = False
        if lang_requested:
            eff_lang, saved_setting, src = resolve_effective_language(self.game_dir, cfg)
            self.lang_setting = saved_setting
            self.lang_source = src
            if eff_lang != self.lang or not asset_builder.is_cache_ready(self.game_dir, eff_lang):
                self.lang = eff_lang
                self.trigger_rebuild()
                rebuilding = True

        return {
            "ok": True,
            "lang": self.lang,
            "lang_setting": self.lang_setting,
            "lang_source": self.lang_source,
            "rebuilding": rebuilding,
            "ui_prefs": _sanitize_ui_prefs(cfg.get("ui_prefs") or {}),
        }

    def _run_builder(self, force: bool) -> None:
        try:
            asset_builder.build_all(self.game_dir, lang=self.lang, force=force)
            self._load_static_caches()
            with self._static_lock:
                self._save_mtime = -1.0
                self._refresh_save_if_needed(self.map_data, self.quests_data, self.catalog_data)
        except Exception:
            pass

    def _refresh_save_if_needed(self, map_data: dict[str, Any] | None, quests_data: dict[str, Any] | None, catalog_data: dict[str, Any] | None) -> bool:
        slot_dir, profile_dir = find_latest_save_slot(self.game_dir)
        self._save_slot_dir = slot_dir
        self._profile_dir = profile_dir
        if not slot_dir:
            return False
        prog = slot_dir / "progress.sav"
        try:
            mt = prog.stat().st_mtime
        except OSError:
            return False

        if self._save_reader is None or mt != self._save_mtime or (map_data is not None and self._save_snapshot_cache is None):
            try:
                self._save_reader = SaveProgressReader(prog)
                self._save_mtime = mt
                album_dir = (profile_dir / "album") if profile_dir else None
                self._save_snapshot_cache = self._save_reader.build_full_snapshot(
                    map_data, quests_data, catalog_data, album_dir
                )
                return True
            except Exception:
                return False
        return False

    def get_footprint_data(self) -> dict[str, Any]:
        slot_dir, _ = find_latest_save_slot(self.game_dir)
        if slot_dir:
            fp_file = slot_dir / "footprint.sav"
            if fp_file.is_file():
                try:
                    mt = fp_file.stat().st_mtime
                    if mt != self._fp_mtime:
                        self._fp_cache = read_footprint_sav(fp_file)
                        self._fp_mtime = mt
                except OSError:
                    pass
        out = dict(self._fp_cache)
        out["session_trail"] = self._live_reader.get_session_trail()
        return out

    def get_album_dir(self) -> Path | None:
        if self._profile_dir and (self._profile_dir / "album").is_dir():
            return self._profile_dir / "album"
        _, profile_dir = find_latest_save_slot(self.game_dir)
        if profile_dir and (profile_dir / "album").is_dir():
            return profile_dir / "album"
        return None

    def _poll_loop(self) -> None:
        tick = 0
        was_live_ready = False
        while not self.stop_event.is_set():
            self._load_static_caches()
            with self._static_lock:
                map_data = self.map_data
                quests_data = self.quests_data
                catalog_data = self.catalog_data

            save_changed = self._refresh_save_if_needed(map_data, quests_data, catalog_data)
            live_pose = self._live_reader.read_live_pose()

            if live_pose is not None and live_pose.get("status") == "ready":
                trail = self._live_reader.get_session_trail()
                live_pose["trailTail"] = trail[-25:] if trail else []
                with self._sse_cond:
                    self._latest_live = live_pose
                    self._live_seq += 1
                    self._sse_cond.notify_all()

                if not was_live_ready or tick % 10 == 0 or save_changed:
                    guids = self._save_reader.guids if self._save_reader else set()
                    album = read_album_photos(self.get_album_dir(), self._save_reader)
                    snap = self._live_reader.read_full_snapshot(
                        map_data, quests_data, catalog_data, guids, album
                    )
                    if snap and snap.get("status") == "ready":
                        with self._state_lock:
                            self._latest_snapshot = snap
                was_live_ready = True
            else:
                was_live_ready = False
                if self._save_reader is not None:
                    fallback_live = self._save_reader.build_live_pose()
                    if live_pose is not None:
                        fallback_live["mode"] = "title"
                        fallback_live["gameStatus"] = live_pose.get("status")
                        fallback_live["pid"] = live_pose.get("pid")
                    with self._sse_cond:
                        changed = (
                            self._latest_live.get("mode") != fallback_live.get("mode")
                            or save_changed
                            or tick % 10 == 0
                        )
                        self._latest_live = fallback_live
                        if changed:
                            self._live_seq += 1
                            self._sse_cond.notify_all()
                    if self._save_snapshot_cache is not None:
                        snap_copy = dict(self._save_snapshot_cache)
                        if live_pose is not None:
                            snap_copy["mode"] = "title"
                            snap_copy["gameStatus"] = live_pose.get("status")
                            snap_copy["pid"] = live_pose.get("pid")
                        with self._state_lock:
                            self._latest_snapshot = snap_copy
                else:
                    offline = {
                        "mode": "title" if live_pose else "offline",
                        "status": live_pose.get("status") if live_pose else "offline",
                        "pid": live_pose.get("pid") if live_pose else None,
                        "player": None,
                        "map": {"pins": [], "stamps": []},
                    }
                    with self._sse_cond:
                        self._latest_live = offline
                        if tick % 10 == 0:
                            self._live_seq += 1
                            self._sse_cond.notify_all()
                    with self._state_lock:
                        self._latest_snapshot = offline

            if tick > 0 and tick % 100 == 0 and self.lang_setting == "auto":
                if asset_builder.get_build_status().get("state") != "building":
                    eff_lang, src = detect_game_language(self.game_dir)
                    self.lang_source = src
                    if eff_lang != self.lang:
                        self.lang = eff_lang
                        self.trigger_rebuild()

            tick += 1
            self.stop_event.wait(0.1)

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            live = dict(self._latest_live)
        lan_ip = _get_lan_ip() if self.lan else None
        return {
            "build": asset_builder.get_build_status(),
            "connection_mode": live.get("mode", "offline"),
            "game_status": live.get("status", "offline"),
            "pid": live.get("pid"),
            "game_dir": str(self.game_dir),
            "lang": self.lang,
            "lang_setting": self.lang_setting,
            "lang_source": self.lang_source,
            "supported_languages": SUPPORTED_LANGUAGES,
            "save_slot": self._save_slot_dir.name if self._save_slot_dir else None,
            "save_mtime": int(self._save_mtime) if self._save_mtime > 0 else None,
            "lan_url": f"http://{lan_ip}:{self.port}" if lan_ip else None,
        }

    def get_live(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._latest_live)

    def get_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._latest_snapshot)

    def _push_live_refresh(self) -> None:
        live_pose = self._live_reader.read_live_pose()
        if live_pose is not None and live_pose.get("status") == "ready":
            trail = self._live_reader.get_session_trail()
            live_pose["trailTail"] = trail[-25:] if trail else []
            with self._sse_cond:
                self._latest_live = live_pose
                self._live_seq += 1
                self._sse_cond.notify_all()
            with self._state_lock:
                if self._latest_snapshot.get("mode") == "live":
                    self._latest_snapshot["map"] = live_pose["map"]

    def set_game_pin(self, body: dict[str, Any]) -> dict[str, Any]:
        res = self._live_reader.set_game_pin(
            color=str(body.get("color") or "Blue"),
            x=float(body.get("x", 0.0)),
            z=float(body.get("z", 0.0)),
            layer=str(body.get("layer") or "surface"),
        )
        self._push_live_refresh()
        return res

    def remove_game_pin(self, slot: int) -> dict[str, Any]:
        res = self._live_reader.remove_game_pin(slot)
        self._push_live_refresh()
        return res

    def add_game_stamp(self, body: dict[str, Any]) -> dict[str, Any]:
        res = self._live_reader.add_game_stamp(
            stamp_type=str(body.get("type") or "Star"),
            x=float(body.get("x", 0.0)),
            z=float(body.get("z", 0.0)),
            layer=str(body.get("layer") or "surface"),
        )
        self._push_live_refresh()
        return res

    def remove_game_stamp(self, slot: int) -> dict[str, Any]:
        res = self._live_reader.remove_game_stamp(slot)
        self._push_live_refresh()
        return res


class PurahPadHTTPHandler(BaseHTTPRequestHandler):
    """Manipulador HTTP/SSE do Purah Pad."""

    server_version = "PurahPad/1.0"

    @property
    def runtime(self) -> PurahPadRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return  # Mantém stdout limpo durante polling 10 Hz

    def _send_bytes(
        self,
        code: int,
        ctype: str,
        body: bytes,
        cache_control: str = "no-store",
        gzipped: bool = False,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, data: Any) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(code, "application/json; charset=utf-8", raw)

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 1024 * 1024:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/status":
            self._send_json(200, self.runtime.get_status())
            return
        if path == "/api/settings":
            self._send_json(200, self.runtime.get_settings())
            return
        if path == "/api/live":
            self._send_json(200, self.runtime.get_live())
            return
        if path == "/api/snapshot":
            self._send_json(200, self.runtime.get_snapshot())
            return
        if path == "/api/footprint":
            self._send_json(200, self.runtime.get_footprint_data())
            return
        if path == "/api/markers":
            self._send_json(200, {"markers": self.runtime.get_markers()})
            return
        if path == "/api/stream":
            self._handle_sse()
            return

        if path in ("/api/static/map_data", "/api/static/quests", "/api/static/catalog", "/api/static/entities"):
            key = path.rsplit("/", 1)[-1]
            accept_gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
            payload = self.runtime.get_static_payload(key, accept_gz)
            if payload is None:
                self._send_json(503, {"error": "Cache ainda em preparação"})
                return
            body, is_gz = payload
            self._send_bytes(200, "application/json; charset=utf-8", body, cache_control="no-cache", gzipped=is_gz)
            return

        m_mask = MASK_URL_RE.match(path)
        if m_mask:
            mpath = asset_builder.get_mask_path(m_mask.group(1))
            if not mpath or not mpath.is_file():
                self._send_bytes(404, "text/plain", b"Mask not found")
                return
            self._send_bytes(200, "image/png", mpath.read_bytes(), cache_control="public, max-age=86400")
            return

        m_tile = TILE_URL_RE.match(path)
        if m_tile:
            layer, lod_s, col_s, row_s = m_tile.groups()
            tpath = asset_builder.get_or_decode_tile(self.runtime.game_dir, layer, int(lod_s), int(col_s), int(row_s))
            if not tpath or not tpath.is_file():
                self._send_bytes(404, "text/plain", b"Tile not found")
                return
            self._send_bytes(200, "image/png", tpath.read_bytes(), cache_control="public, max-age=86400")
            return

        m_icon = ICON_URL_RE.match(path)
        if m_icon:
            kind, name = m_icon.groups()
            ipath = asset_builder.get_or_decode_icon(self.runtime.game_dir, kind, name)
            if not ipath or not ipath.is_file():
                self._send_bytes(404, "text/plain", b"Icon not found")
                return
            self._send_bytes(200, "image/png", ipath.read_bytes(), cache_control="public, max-age=86400")
            return

        m_alb = ALBUM_URL_RE.match(path)
        if m_alb:
            fname = m_alb.group(1)
            alb_dir = self.runtime.get_album_dir()
            if not alb_dir:
                self._send_bytes(404, "text/plain", b"Album not found")
                return
            target = (alb_dir / fname).resolve()
            if target.parent != alb_dir.resolve() or not target.is_file():
                self._send_bytes(404, "text/plain", b"Photo not found")
                return
            self._send_bytes(200, "image/jpeg", target.read_bytes(), cache_control="public, max-age=3600")
            return

        # Arquivos estáticos web/
        rel = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if target.parent != WEB_DIR.resolve() or not target.is_file():
            self._send_bytes(404, "text/plain; charset=utf-8", b"Not found")
            return
        ctype, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        self._send_bytes(200, ctype or "application/octet-stream", target.read_bytes(), cache_control="no-cache")

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/markers":
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"error": "JSON inválido"})
                return
            marker = self.runtime.add_marker(body)
            self._send_json(201, marker)
            return
        if path in ("/api/game/pins", "/api/game/stamps"):
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"error": "JSON inválido"})
                return
            try:
                res = (
                    self.runtime.set_game_pin(body)
                    if path == "/api/game/pins"
                    else self.runtime.add_game_stamp(body)
                )
                self._send_json(200, res)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
            return
        if path == "/api/rebuild":
            self.runtime.trigger_rebuild()
            self._send_json(202, {"status": "rebuilding"})
            return
        if path == "/api/settings":
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"error": "Invalid JSON"})
                return
            res = self.runtime.update_settings(body)
            self._send_json(200, res)
            return
        self._send_json(404, {"error": "Rota não encontrada"})

    def do_PUT(self) -> None:
        path = unquote(urlparse(self.path).path)
        m = MARKER_ID_RE.match(path)
        if not m:
            self._send_json(404, {"error": "Rota não encontrada"})
            return
        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "JSON inválido"})
            return
        updated = self.runtime.update_marker(m.group(1), body)
        if not updated:
            self._send_json(404, {"error": "Marcador não encontrado"})
            return
        self._send_json(200, updated)

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        m_pin = GAME_PIN_ID_RE.match(path)
        if m_pin:
            try:
                self._send_json(200, self.runtime.remove_game_pin(int(m_pin.group(1))))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
            return
        m_st = GAME_STAMP_ID_RE.match(path)
        if m_st:
            try:
                self._send_json(200, self.runtime.remove_game_stamp(int(m_st.group(1))))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
            return
        m = MARKER_ID_RE.match(path)
        if not m:
            self._send_json(404, {"error": "Rota não encontrada"})
            return
        if not self.runtime.delete_marker(m.group(1)):
            self._send_json(404, {"error": "Marcador não encontrado"})
            return
        self._send_json(200, {"deleted": m.group(1)})

    def _handle_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_seq = -1
        try:
            while not self.runtime.stop_event.is_set():
                with self.runtime._sse_cond:
                    if self.runtime._live_seq == last_seq:
                        self.runtime._sse_cond.wait(timeout=1.0)
                    last_seq = self.runtime._live_seq
                    payload = json.dumps(self.runtime._latest_live, ensure_ascii=False, separators=(",", ":"))
                chunk = f"data: {payload}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return


class PurahPadHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], runtime: PurahPadRuntime) -> None:
        self.runtime = runtime
        super().__init__(server_address, PurahPadHTTPHandler)


def create_server(
    game_dir: Path | None = None,
    port: int = 8765,
    lan: bool = False,
    rebuild: bool = False,
) -> tuple[PurahPadHTTPServer, PurahPadRuntime]:
    settings = load_settings()
    gdir = game_dir or get_game_dir()
    eff_lang, lang_setting, lang_source = resolve_effective_language(gdir, settings)
    host = "0.0.0.0" if lan else "127.0.0.1"
    runtime = PurahPadRuntime(
        gdir,
        lang=eff_lang,
        lang_setting=lang_setting,
        lang_source=lang_source,
        lan=lan,
        port=port,
    )
    srv = PurahPadHTTPServer((host, port), runtime)
    runtime.port = srv.server_address[1]
    runtime.start_background_tasks(force_rebuild=rebuild)
    return srv, runtime


def main() -> None:
    ap = argparse.ArgumentParser(description="Servidor Purah Pad para TotK Recomp.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="Escuta em 0.0.0.0 para celular/tablet na rede local")
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    srv, runtime = create_server(
        game_dir=Path(args.game_dir) if args.game_dir else None,
        port=args.port,
        lan=args.lan,
        rebuild=args.rebuild,
    )
    print(f"Purah Pad ouvindo em http://127.0.0.1:{runtime.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop_event.set()
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
