"""Leitor somente-leitura da memória do processo totk.exe (TotK Recomp v1.4.3) via Win32 ReadProcessMemory."""
from __future__ import annotations

import ctypes
import hashlib
import math
import re
import struct
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Any

from asset_builder import sample_heightmap
from save_reader import (
    ENUM_HASH_MAPS,
    POUCH_CATEGORIES,
    SAGES_LIST,
    evaluate_archives_progress,
    evaluate_quests_progress,
    evaluate_world_progress,
    normalize_layer_name,
)
from totk_formats import mmh3

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PIN_COLORS = ("Red", "Blue", "Yellow", "Green", "Purple", "LightBlue")
STAMP_TYPES = ("Sword", "Pot", "Human", "Rhombus", "Heart", "Star", "TreasureBox", "Skull", "Leaf", "Ore")
STAMP_LAYER_TO_ENUM = {"sky": "Sky", "surface": "Ground", "depths": "Underground"}

DEFAULT_MAIN_BASE = 0x7000000000
GUARD_OFFSETS = (0x787554, 0x7875A4, 0x61FDE4, 0x61FE90, 0x282964, 0x282970, 0x2097688, 0x209768C)
GUARD_SHA256_V143 = "0a2d05de9f11934c5e775c1d61b344fe609fdb9336a8e64ebd38fd706ec6b8cb"

GDM_SLOT = 0x3AD66B0
POUCH_SLOT = 0x3A81678
POUCH_PART = 0x188
POUCH_MENU = 0x1FCC0
SCENE_SLOT = 0x3ADD238

GAME_ACTOR_NAME = 0x218
GAME_ACTOR_POS = 0x2B4
GAME_ACTOR_ROT = 0x2C0

T_BOOL = 0
T_BOOLARR = 1
T_INT = 2
T_INTARR = 3
T_FLOAT = 4
T_ENUM = 5
T_ENUMARR = 6
T_VEC2ARR = 7
T_VEC3 = 8
T_VEC3ARR = 9
T_STRARR = 10

# (base, stride, value_off, count_off, data_off)
TABLE_SPECS: dict[int, tuple[int, int, int, int, int]] = {
    T_BOOL: (0x008, 0x18, 0x16, 0, 0),
    T_BOOLARR: (0x068, 0x40, 0, 0x20, 0x28),
    T_INT: (0x0C8, 0x28, 0x1C, 0, 0),
    T_INTARR: (0x128, 0x40, 0, 0x20, 0x28),
    T_FLOAT: (0x188, 0x28, 0x1C, 0, 0),
    T_ENUM: (0x248, 0x38, 0x1C, 0, 0),
    T_ENUMARR: (0x2A8, 0x50, 0, 0x20, 0x28),
    T_VEC2ARR: (0x368, 0x48, 0, 0x28, 0x30),
    T_VEC3: (0x3C8, 0x40, 0x24, 0, 0),
    T_VEC3ARR: (0x428, 0x48, 0, 0x28, 0x30),
    T_STRARR: (0x668, 0x90, 0, 0x70, 0x78),
}
MAX_TABLE = 1 << 20
MAX_ARRAY = 4096
STR_ELEM = 0x50
NAME_MAX_LEN = 64

_MAIN_LOG_RE = re.compile(r"loaded main\s+at\s+(0x[0-9a-fA-F]+)")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL

_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE

_kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_kernel32.ReadProcessMemory.restype = wintypes.BOOL

_kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_kernel32.WriteProcessMemory.restype = wintypes.BOOL

_kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
_kernel32.VirtualQueryEx.restype = ctypes.c_size_t

_kernel32.VirtualProtectEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_size_t,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.VirtualProtectEx.restype = wintypes.BOOL

_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetExitCodeProcess.restype = wintypes.BOOL

STILL_ACTIVE = 259


def find_totk_pid() -> int | None:
    """Encontra o PID do processo totk.exe em execução."""
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return None
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snap, ctypes.byref(pe)):
            return None
        while True:
            if pe.szExeFile.lower() == "totk.exe":
                return int(pe.th32ProcessID)
            if not _kernel32.Process32NextW(snap, ctypes.byref(pe)):
                break
        return None
    finally:
        _kernel32.CloseHandle(snap)


def detect_main_base(game_dir: Path | None) -> int:
    """Lê o endereço base do módulo main no logs/totk.log ou usa 0x7000000000."""
    if game_dir:
        log_file = game_dir / "logs" / "totk.log"
        if log_file.is_file():
            try:
                with log_file.open("r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if i > 80:
                            break
                        m = _MAIN_LOG_RE.search(line)
                        if m:
                            return int(m.group(1), 16)
            except OSError:
                pass
    return DEFAULT_MAIN_BASE


def _pos_ok(p: tuple[float, float, float]) -> bool:
    return (
        all(math.isfinite(v) for v in p)
        and abs(p[0]) <= 8000.0
        and abs(p[1]) <= 8000.0
        and abs(p[2]) <= 8000.0
    )


class LiveMemoryReader:
    """Conexão read-only ao processo totk.exe com verificação do guard v1.4.3."""

    def __init__(self, game_dir: Path | None = None) -> None:
        self.game_dir = game_dir
        self.pid: int | None = None
        self.handle: int | None = None
        self.can_write: bool = False
        self.main_base: int = DEFAULT_MAIN_BASE
        self.guard_ok: int = 0  # 0=não checado, 1=ok, -1=incompatível
        self._lock = threading.RLock()
        self._table_cache: dict[int, tuple[int, int, int, int]] = {}
        self._trail: list[dict[str, Any]] = []
        self._last_trail_pos: tuple[float, float, str] | None = None

    def close(self) -> None:
        with self._lock:
            if self.handle:
                _kernel32.CloseHandle(self.handle)
            self.handle = None
            self.pid = None
            self.can_write = False
            self.guard_ok = 0
            self._table_cache.clear()

    def _ensure_connected(self) -> bool:
        if self.handle and self.pid:
            code = wintypes.DWORD(0)
            if _kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)) and code.value == STILL_ACTIVE:
                return True
            self.close()

        pid = find_totk_pid()
        if not pid:
            return False
        h = _kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION,
            False,
            pid,
        )
        can_write = bool(h)
        if not h:
            h = _kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        self.pid = pid
        self.handle = h
        self.can_write = can_write
        self.main_base = detect_main_base(self.game_dir)
        self.guard_ok = 0
        self._table_cache.clear()
        return True

    def read_bytes(self, addr: int, size: int) -> bytes | None:
        if not self.handle or addr < 0x10000 or addr > (1 << 47) or size <= 0:
            return None
        buf = (ctypes.c_ubyte * size)()
        read_n = ctypes.c_size_t(0)
        ok = _kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(addr),
            buf,
            ctypes.c_size_t(size),
            ctypes.byref(read_n),
        )
        if not ok or read_n.value != size:
            return None
        return bytes(buf)

    def _write_bytes(self, addr: int, data: bytes) -> bool:
        if not self.handle or not self.can_write or addr < 0x10000 or addr > (1 << 47) or not data:
            return False
        mbi = MEMORY_BASIC_INFORMATION()
        if _kernel32.VirtualQueryEx(
            self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            if mbi.Protect == PAGE_READONLY:
                old_prot = wintypes.DWORD(0)
                _kernel32.VirtualProtectEx(
                    self.handle,
                    ctypes.c_void_p(addr),
                    ctypes.c_size_t(len(data)),
                    PAGE_READWRITE,
                    ctypes.byref(old_prot),
                )
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        written = ctypes.c_size_t(0)
        ok = _kernel32.WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(addr),
            buf,
            ctypes.c_size_t(len(data)),
            ctypes.byref(written),
        )
        return bool(ok and written.value == len(data))

    def _gd_arr_bufs(self, gdm: int, t_type: int, name: str) -> tuple[int, int, int] | None:
        e = self._lookup_entry(gdm, t_type, name)
        if not e:
            return None
        _, _, _, c_off, d_off = TABLE_SPECS[t_type]
        cnt = self.read_u32(e + c_off)
        buf0 = self.read_u64(e + d_off)
        buf1 = self.read_u64(e + d_off + 0x10)
        if cnt is None or not buf0 or cnt > MAX_ARRAY:
            return None
        return cnt, buf0, (buf1 or 0)

    def read_u8(self, addr: int) -> int | None:
        b = self.read_bytes(addr, 1)
        return b[0] if b else None

    def read_i32(self, addr: int) -> int | None:
        b = self.read_bytes(addr, 4)
        return struct.unpack("<i", b)[0] if b else None

    def read_u32(self, addr: int) -> int | None:
        b = self.read_bytes(addr, 4)
        return struct.unpack("<I", b)[0] if b else None

    def read_u64(self, addr: int) -> int | None:
        b = self.read_bytes(addr, 8)
        return struct.unpack("<Q", b)[0] if b else None

    def _check_guard(self) -> str | None:
        """Retorna None se o guard passou, ou string de status ('starting' | 'unsupported')."""
        if self.guard_ok == 1:
            return None
        if self.guard_ok == -1:
            return "unsupported"
        words: list[bytes] = []
        for off in GUARD_OFFSETS:
            w = self.read_bytes(self.main_base + off, 4)
            if w is None:
                return "starting"
            words.append(w)
        digest = hashlib.sha256(b"".join(words)).hexdigest()
        if digest == GUARD_SHA256_V143:
            self.guard_ok = 1
            return None
        self.guard_ok = -1
        return "unsupported"

    def _read_table_hdr(self, gdm: int, t_type: int) -> tuple[int, int, int, int] | None:
        """Retorna (count, entries_ptr, index_ptr, cap) de uma tabela do GameDataMgr."""
        base = TABLE_SPECS[t_type][0]
        raw = self.read_bytes(gdm + base + 8, 0x20)
        if not raw:
            return None
        count = struct.unpack_from("<i", raw, 0)[0]
        entries, index, _used, cap = struct.unpack_from("<QQII", raw, 8)
        if count <= 0 or count > MAX_TABLE or cap == 0 or cap > 2 * MAX_TABLE or not entries or not index:
            return None
        return count, entries, index, cap

    def _lookup_entry(self, gdm: int, t_type: int, name: str) -> int | None:
        hdr = self._table_cache.get(t_type)
        if hdr is None:
            hdr = self._read_table_hdr(gdm, t_type)
            if hdr is None:
                return None
            self._table_cache[t_type] = hdr
        count, entries, index, cap = hdr
        h = mmh3(name)
        if h == 0:
            return None
        slot = h % cap
        stride = TABLE_SPECS[t_type][1]
        for _ in range(min(cap, 64)):
            cell = self.read_bytes(index + 8 * slot, 8)
            if not cell:
                return None
            c_hash, c_idx = struct.unpack("<II", cell)
            if c_hash == 0:
                return None
            if c_hash == h:
                return entries + c_idx * stride if c_idx < count else None
            slot = (slot + 1) % cap
        return None

    def _gd_int(self, gdm: int, name: str, default: int | None = None) -> int | None:
        e = self._lookup_entry(gdm, T_INT, name)
        if not e:
            return default
        v = self.read_i32(e + TABLE_SPECS[T_INT][2])
        return default if v is None else v

    def _gd_float(self, gdm: int, name: str, default: float | None = None) -> float | None:
        e = self._lookup_entry(gdm, T_FLOAT, name)
        if not e:
            return default
        b = self.read_bytes(e + TABLE_SPECS[T_FLOAT][2], 4)
        if not b:
            return default
        v = struct.unpack("<f", b)[0]
        return v if math.isfinite(v) else default

    def _gd_bool(self, gdm: int, name: str) -> bool:
        e = self._lookup_entry(gdm, T_BOOL, name)
        if not e:
            return False
        b = self.read_u8(e + TABLE_SPECS[T_BOOL][2])
        return bool(b & 1) if b is not None else False

    def _gd_enum(self, gdm: int, name: str, kind: str) -> str | None:
        e = self._lookup_entry(gdm, T_ENUM, name)
        if not e:
            return None
        h = self.read_u32(e + TABLE_SPECS[T_ENUM][2])
        return ENUM_HASH_MAPS[kind].get(h) if h is not None else None

    def _gd_vec3(self, gdm: int, name: str) -> tuple[float, float, float] | None:
        e = self._lookup_entry(gdm, T_VEC3, name)
        if not e:
            return None
        b = self.read_bytes(e + TABLE_SPECS[T_VEC3][2], 12)
        if not b:
            return None
        p = struct.unpack("<3f", b)
        return p if all(math.isfinite(x) for x in p) else None

    def _gd_arr_hdr(self, gdm: int, t_type: int, name: str) -> tuple[int, int] | None:
        e = self._lookup_entry(gdm, t_type, name)
        if not e:
            return None
        _, _, _, c_off, d_off = TABLE_SPECS[t_type]
        cnt = self.read_u32(e + c_off)
        data_ptr = self.read_u64(e + d_off)
        if cnt is None or not data_ptr or cnt > MAX_ARRAY:
            return None
        return cnt, data_ptr

    def _read_words(self, gdm: int, t_type: int, name: str, first: int, n: int, signed: bool = True) -> list[int] | None:
        hdr = self._gd_arr_hdr(gdm, t_type, name)
        if not hdr:
            return None
        cnt, ptr = hdr
        if first > cnt or n > cnt - first:
            return None
        raw = self.read_bytes(ptr + 4 * first, 4 * n)
        if not raw:
            return None
        fmt = f"<{n}{'i' if signed else 'I'}"
        return list(struct.unpack(fmt, raw))

    def _read_names(self, gdm: int, name: str, first: int, n: int) -> list[str] | None:
        hdr = self._gd_arr_hdr(gdm, T_STRARR, name)
        if not hdr:
            return None
        cnt, ptr = hdr
        if first > cnt or n > cnt - first:
            return None
        raw = self.read_bytes(ptr + first * STR_ELEM, n * STR_ELEM)
        if not raw:
            return None
        out: list[str] = []
        for i in range(n):
            chunk = raw[i * STR_ELEM : (i + 1) * STR_ELEM]
            data_ptr, cap = struct.unpack_from("<Qi", chunk, 0)
            length = cap if 0 < cap < NAME_MAX_LEN else NAME_MAX_LEN
            self_addr = ptr + (first + i) * STR_ELEM
            if data_ptr == self_addr + 0x0C:
                sbytes = chunk[0x0C : 0x0C + length]
            elif data_ptr:
                sbytes = self.read_bytes(data_ptr, length) or b""
            else:
                sbytes = b""
            nul = sbytes.find(b"\0")
            if nul < 0:
                out.append("")
                continue
            s = sbytes[:nul].decode("ascii", "ignore")
            if s and all(c.isalnum() or c == "_" for c in s):
                out.append(s)
            else:
                out.append("")
        return out

    def _read_player_actor(self) -> int:
        module = self.read_u64(self.main_base + SCENE_SLOT)
        if not module:
            return 0
        scene = self.read_u64(module + 0x1E8)
        if not scene:
            return 0
        count = self.read_i32(scene + 0x50)
        if count is None or count < 14 or count > 256:
            return 0
        components = self.read_u64(scene + 0x58)
        if not components:
            return 0
        resident = self.read_u64(components + 13 * 8)
        if not resident:
            return 0
        rcount = self.read_i32(resident + 0x20)
        if rcount is None or rcount < 1 or rcount > 64:
            return 0
        links = self.read_u64(resident + 0x28)
        if not links:
            return 0
        for i in range(rcount):
            data = self.read_u64(links + i * 0x70 + 8)
            if not data:
                continue
            actor = self.read_u64(data + 0x40)
            if not actor:
                continue
            name_ptr = self.read_u64(actor + GAME_ACTOR_NAME)
            if not name_ptr:
                continue
            nm = self.read_bytes(name_ptr, 7)
            if nm != b"Player\0":
                continue
            pos_b = self.read_bytes(actor + GAME_ACTOR_POS, 12)
            if not pos_b:
                continue
            pos = struct.unpack("<3f", pos_b)
            if _pos_ok(pos) and (pos[0] != 0.0 or pos[1] != 0.0 or pos[2] != 0.0):
                return actor
        return 0

    def _bulk_read_scalar_table(self, gdm: int, t_type: int) -> dict[int, int]:
        """Lê em lote toda uma tabela hash (T_BOOL, T_INT ou T_ENUM) para dict {hash: valor}."""
        hdr = self._read_table_hdr(gdm, t_type)
        if hdr is None:
            return {}
        count, entries_ptr, index_ptr, cap = hdr
        _, stride, val_off, _, _ = TABLE_SPECS[t_type]
        idx_bytes = self.read_bytes(index_ptr, cap * 8)
        ent_bytes = self.read_bytes(entries_ptr, count * stride)
        if not idx_bytes or not ent_bytes:
            return {}
        out: dict[int, int] = {}
        is_bool = t_type == T_BOOL
        for slot in range(cap):
            h, e_idx = struct.unpack_from("<II", idx_bytes, slot * 8)
            if h == 0 or e_idx >= count:
                continue
            off = e_idx * stride + val_off
            if is_bool:
                out[h] = ent_bytes[off] & 1
            else:
                out[h] = struct.unpack_from("<I", ent_bytes, off)[0]
        return out

    def _append_trail_point(self, x: float, z: float, layer: str) -> None:
        if self._last_trail_pos is not None:
            lx, lz, ll = self._last_trail_pos
            if ll == layer and ((x - lx) ** 2 + (z - lz) ** 2) < 64.0:
                return
        self._last_trail_pos = (x, z, layer)
        self._trail.append({"x": round(x, 1), "z": round(z, 1), "layer": layer})
        if len(self._trail) > 4000:
            self._trail = self._trail[-3000:]

    def get_session_trail(self) -> list[dict[str, Any]]:
        return list(self._trail)

    def _read_pins_and_stamps(self, gdm: int) -> dict[str, list[dict[str, Any]]]:
        pins: list[dict[str, Any]] = []
        p_pos_hdr = self._gd_arr_hdr(gdm, T_VEC3ARR, "MapData.IconData.MapPinData.Pos")
        p_typ_hdr = self._gd_arr_hdr(gdm, T_ENUMARR, "MapData.IconData.MapPinData.Type")
        if p_pos_hdr and p_typ_hdr:
            n = min(p_pos_hdr[0], p_typ_hdr[0], 300)
            if n > 0:
                pos_b = self.read_bytes(p_pos_hdr[1], n * 12)
                typ_b = self.read_bytes(p_typ_hdr[1], n * 4)
                if pos_b and typ_b:
                    for i in range(n):
                        px, py, pz = struct.unpack_from("<3f", pos_b, i * 12)
                        pt = struct.unpack_from("<I", typ_b, i * 4)[0]
                        ty = ENUM_HASH_MAPS["pin"].get(pt)
                        if ty and ty != "Invalid" and all(math.isfinite(v) for v in (px, py, pz)):
                            pins.append(
                                {
                                    "slot": i,
                                    "x": round(px, 2),
                                    "y": round(py, 2),
                                    "z": round(pz, 2),
                                    "type": ty,
                                    "layer": normalize_layer_name(None, py),
                                }
                            )

        stamps: list[dict[str, Any]] = []
        s_pos_hdr = self._gd_arr_hdr(gdm, T_VEC2ARR, "MapData.IconData.StampData.Pos")
        s_typ_hdr = self._gd_arr_hdr(gdm, T_ENUMARR, "MapData.IconData.StampData.Type")
        s_lyr_hdr = self._gd_arr_hdr(gdm, T_ENUMARR, "MapData.IconData.StampData.Layer")
        if s_pos_hdr and s_typ_hdr and s_lyr_hdr:
            n = min(s_pos_hdr[0], s_typ_hdr[0], s_lyr_hdr[0], 300)
            if n > 0:
                pos_b = self.read_bytes(s_pos_hdr[1], n * 8)
                typ_b = self.read_bytes(s_typ_hdr[1], n * 4)
                lyr_b = self.read_bytes(s_lyr_hdr[1], n * 4)
                if pos_b and typ_b and lyr_b:
                    for i in range(n):
                        sx, sz = struct.unpack_from("<2f", pos_b, i * 8)
                        st = struct.unpack_from("<I", typ_b, i * 4)[0]
                        sl = struct.unpack_from("<I", lyr_b, i * 4)[0]
                        ty = ENUM_HASH_MAPS["stamp"].get(st)
                        ly = ENUM_HASH_MAPS["layer"].get(sl)
                        if ty and ty != "Invalid" and math.isfinite(sx) and math.isfinite(sz):
                            stamps.append(
                                {
                                    "slot": i,
                                    "x": round(sx, 2),
                                    "z": round(sz, 2),
                                    "type": ty,
                                    "layer": normalize_layer_name(ly),
                                }
                            )
        return {"pins": pins, "stamps": stamps}

    def _gate(self) -> tuple[str, int, int, int | None]:
        """Retorna (status, gdm, actor, part_or_None)."""
        if not self._ensure_connected():
            return "offline", 0, 0, None
        g_err = self._check_guard()
        if g_err:
            return g_err, 0, 0, None
        gdm = self.read_u64(self.main_base + GDM_SLOT) or 0
        if not gdm:
            return "starting", 0, 0, None
        self._table_cache.clear()
        max_life = self._gd_int(gdm, "PlayerStatus.MaxLife")
        if max_life is None or max_life < 4 or max_life > 400:
            return "starting", 0, 0, None
        pouch_ptr = self.read_u64(self.main_base + POUCH_SLOT) or 0
        part = self.read_u32(pouch_ptr + POUCH_PART) if pouch_ptr else None
        if part is None or part >= 2:
            part = None
        actor = self._read_player_actor()
        if not actor:
            return "title", gdm, 0, part
        return "ready", gdm, actor, part

    def read_live_pose(self) -> dict[str, Any] | None:
        """Leitura leve em 10 Hz de posição, rotação, HUD, pins e carimbos. Retorna None se offline."""
        with self._lock:
            return self._read_live_pose_locked()

    def _read_live_pose_locked(self) -> dict[str, Any] | None:
        status, gdm, actor, _part = self._gate()
        if status == "offline":
            return None
        if status != "ready":
            return {"mode": "live", "status": status, "pid": self.pid}

        pos_b = self.read_bytes(actor + GAME_ACTOR_POS, 12)
        rot_b = self.read_bytes(actor + GAME_ACTOR_ROT, 36)
        pos: tuple[float, float, float] | None = None
        if pos_b:
            cand = struct.unpack("<3f", pos_b)
            if _pos_ok(cand):
                pos = cand
        if pos is None:
            pos = self._gd_vec3(gdm, "World_PlayerPos")

        heading: float | None = None
        if rot_b:
            rot = struct.unpack("<9f", rot_b)
            if (
                math.isfinite(rot[2])
                and math.isfinite(rot[8])
                and abs(rot[2]) <= 2.0
                and abs(rot[8]) <= 2.0
                and (rot[2] != 0.0 or rot[8] != 0.0)
            ):
                h = math.degrees(math.atan2(rot[2], -rot[8]))
                heading = round(h + 360.0 if h < 0 else h, 1)

        raw_layer = self._gd_enum(gdm, "MapData.CurrentLayer", "layer")
        layer = normalize_layer_name(raw_layer, pos[1] if pos else None)
        if pos is not None:
            self._append_trail_point(pos[0], pos[2], layer)

        buff_id = self._gd_int(gdm, "PlayerStatus.CookBuff", 0) or 0
        cook_buff = None
        if buff_id > 0:
            cook_buff = {
                "id": buff_id,
                "level": self._gd_int(gdm, "PlayerStatus.CookBuffLv", 0) or 0,
                "time": self._gd_float(gdm, "PlayerStatus.CookBuffTime", 0.0) or 0.0,
            }

        pouch_ptr = self.read_u64(self.main_base + POUCH_SLOT) or 0
        menu_flag = self.read_u8(pouch_ptr + POUCH_MENU) if pouch_ptr else 0
        pause_menu = bool(menu_flag) if menu_flag is not None else False

        player = {
            "life": self._gd_int(gdm, "PlayerStatus.Life", 12),
            "maxLife": self._gd_int(gdm, "PlayerStatus.MaxLife", 12),
            "extraLife": self._gd_int(gdm, "PlayerStatus.ExtraLife", 0),
            "breakLife": self._gd_int(gdm, "PlayerStatus.BreakLife", 0),
            "temporaryLife": self._gd_int(gdm, "PlayerStatus.TemporaryLife", 0),
            "rupees": self._gd_int(gdm, "PlayerStatus.CurrentRupee", 0),
            "poes": self._gd_int(gdm, "PlayerStatus.CurrentMamo", 0),
            "maxStamina": self._gd_float(gdm, "PlayerStatus.MaxStamina", 1000.0),
            "extraStamina": self._gd_float(gdm, "PlayerStatus.ExtraStamina", 0.0),
            "maxEnergy": self._gd_float(gdm, "PlayerStatus.MaxEnergy", 100.0),
            "extraEnergy": self._gd_float(gdm, "PlayerStatus.ExtraEnergy", 0.0),
            "ability": self._gd_enum(gdm, "PlayerStatus.CurrentSpecialPower", "power") or "None",
            "cookBuff": cook_buff,
            "pos": [round(x, 2) for x in pos] if pos else None,
            "heading": heading,
            "layer": layer,
        }

        return {
            "mode": "live",
            "status": "ready",
            "pid": self.pid,
            "player": player,
            "map": self._read_pins_and_stamps(gdm),
            "pauseMenu": pause_menu,
        }

    def read_full_snapshot(
        self,
        map_data: dict[str, Any] | None,
        quests_data: dict[str, Any] | None,
        catalog_data: dict[str, Any] | None,
        save_guids: set[str] | None,
        album: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        """Lê snapshot completo (inventário, sábios, mapa, missões, arquivos) ao vivo do totk.exe."""
        with self._lock:
            return self._read_full_snapshot_locked(map_data, quests_data, catalog_data, save_guids, album)

    def _read_full_snapshot_locked(
        self,
        map_data: dict[str, Any] | None,
        quests_data: dict[str, Any] | None,
        catalog_data: dict[str, Any] | None,
        save_guids: set[str] | None,
        album: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        live = self._read_live_pose_locked()
        if live is None:
            return None
        if live.get("status") != "ready":
            return live

        status, gdm, actor, part = self._gate()
        if status != "ready" or part is None:
            return {"mode": "live", "status": status, "pid": self.pid}

        int_hdr_before = self._read_table_hdr(gdm, T_INT)

        armor_head = (self._read_words(gdm, T_INTARR, "Pouch.Armor.EquipIndexes.Head", 0, 2) or [-1, -1])[part]
        armor_upper = (self._read_words(gdm, T_INTARR, "Pouch.Armor.EquipIndexes.Upper", 0, 2) or [-1, -1])[part]
        armor_bottom = (self._read_words(gdm, T_INTARR, "Pouch.Armor.EquipIndexes.Bottom", 0, 2) or [-1, -1])[part]

        pouch: dict[str, list[dict[str, Any]]] = {}
        for key, cat, slots, has_life, has_fuse, has_stock, has_effect, equip_field in POUCH_CATEGORIES:
            names = self._read_names(gdm, f"Pouch.{cat}.Content.Name", part * slots, slots)
            if not names:
                pouch[key] = []
                continue
            life_arr = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.Content.Life", part * slots, slots) if has_life else None
            stock_arr = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.Content.StockNum", part * slots, slots) if has_stock else None
            et_arr = self._read_words(gdm, T_ENUMARR, f"Pouch.{cat}.Content.Effect.Type", part * slots, slots, signed=False) if has_effect else None
            ev_arr = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.Content.Effect.Value", part * slots, slots) if has_effect else None
            fuse_arr = self._read_names(gdm, f"Pouch.{cat}.Content.Combined.Name", part * slots, slots) if has_fuse else None
            fl_arr = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.Content.Combined.Life", part * slots, slots) if has_fuse else None
            col_arr = self._read_words(gdm, T_ENUMARR, "Pouch.Armor.Content.ColorVariation", part * slots, slots, signed=False) if key == "armor" else None

            is_food = key == "food"
            heal_arr = self._read_words(gdm, T_INTARR, "Pouch.Food.Content.LifeRecover", part * slots, slots) if is_food else None
            fe_arr = self._read_words(gdm, T_ENUMARR, "Pouch.Food.Content.Effect.Type", part * slots, slots, signed=False) if is_food else None
            flv_arr = self._read_words(gdm, T_INTARR, "Pouch.Food.Content.Effect.Level", part * slots, slots) if is_food else None
            ft_arr = self._read_words(gdm, T_INTARR, "Pouch.Food.Content.Effect.Time", part * slots, slots) if is_food else None
            pr_arr = self._read_words(gdm, T_INTARR, "Pouch.Food.Content.Price", part * slots, slots) if is_food else None
            fm_arr = self._read_names(gdm, "Pouch.Food.Content.MaterialName", part * slots * 5, slots * 5) if is_food else None

            equipped_idx = -1
            if equip_field:
                eq = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.{equip_field}", 0, 2)
                if eq and part < len(eq):
                    equipped_idx = eq[part]

            items_out: list[dict[str, Any]] = []
            for s in range(slots):
                nm = names[s]
                if not nm:
                    continue
                entry: dict[str, Any] = {"name": nm, "slot": s}
                if life_arr:
                    entry["life"] = life_arr[s]
                if stock_arr:
                    entry["count"] = stock_arr[s]
                if et_arr:
                    ef = ENUM_HASH_MAPS["effect"].get(et_arr[s])
                    if ef and ef != "None":
                        entry["effect"] = {"type": ef, "value": ev_arr[s] if ev_arr else 0}
                if fuse_arr and fuse_arr[s]:
                    entry["fuse"] = fuse_arr[s]
                    if fl_arr:
                        entry["fuseLife"] = fl_arr[s]
                if col_arr:
                    cv = ENUM_HASH_MAPS["color"].get(col_arr[s])
                    if cv and cv != "None":
                        entry["color"] = cv
                if is_food:
                    if heal_arr:
                        entry["heal"] = heal_arr[s]
                    if fe_arr:
                        fe_name = ENUM_HASH_MAPS["food"].get(fe_arr[s])
                        if fe_name and fe_name != "None":
                            entry["effect"] = fe_name
                            if flv_arr:
                                entry["level"] = flv_arr[s]
                            if ft_arr:
                                entry["time"] = ft_arr[s]
                    if pr_arr:
                        entry["price"] = pr_arr[s]
                    if fm_arr:
                        mats = [fm_arr[s * 5 + m] for m in range(5) if fm_arr[s * 5 + m]]
                        if mats:
                            entry["materials"] = mats
                if equip_field:
                    entry["equipped"] = s == equipped_idx
                elif key == "armor":
                    entry["equipped"] = s in (armor_head, armor_upper, armor_bottom)
                else:
                    entry["equipped"] = False
                items_out.append(entry)
            pouch[key] = items_out

        slots_valid = {}
        for key, cat in (("weapons", "Weapon"), ("bows", "Bow"), ("shields", "Shield")):
            v = self._read_words(gdm, T_INTARR, f"Pouch.{cat}.ValidNum", 0, 2)
            if v and v[part] > 0:
                slots_valid[key] = v[part]

        abilities = [
            nm
            for nm in (self._read_names(gdm, "Pouch.SpecialPower.Content.Name", part * 10, 10) or [])
            if nm
        ]

        sages = []
        for sname in SAGES_LIST:
            joined = self._gd_bool(gdm, f"PlayerStatus.Companion.{sname}.IsGet")
            summoned = self._gd_bool(gdm, f"PlayerStatus.Companion.{sname}.IsSummon")
            cond = self._gd_enum(gdm, f"PlayerStatus.Companion.{sname}.JoiningCondition", "joining")
            mn = self._gd_int(gdm, f"PlayerStatus.Companion.{sname}.ForUI.RemainingMinute", 0) or 0
            sec = self._gd_int(gdm, f"PlayerStatus.Companion.{sname}.ForUI.RemainingSecond", 0) or 0
            energy = self._gd_float(gdm, f"PlayerStatus.Companion.{sname}.RemainingEnergy")
            s_obj: dict[str, Any] = {"id": sname, "joined": joined, "summoned": summoned, "condition": cond}
            if mn >= 0 and sec >= 0:
                s_obj["cooldown"] = mn * 60 + sec
            if energy is not None:
                s_obj["energy"] = round(energy, 2)
            sages.append(s_obj)

        # Leitura em lote das tabelas escalares para progresso de mapa, missões e arquivos
        bool_table = self._bulk_read_scalar_table(gdm, T_BOOL)
        enum_table = self._bulk_read_scalar_table(gdm, T_ENUM)
        int_table = self._bulk_read_scalar_table(gdm, T_INT)
        all_flags = {**bool_table, **int_table, **enum_table}

        # Verifica consistência contra troca de save/tela título durante a leitura
        st2, gdm2, actor2, part2 = self._gate()
        int_hdr_after = self._read_table_hdr(gdm, T_INT) if st2 == "ready" else None
        if (
            st2 != "ready"
            or gdm2 != gdm
            or actor2 != actor
            or part2 != part
            or not int_hdr_before
            or not int_hdr_after
            or int_hdr_before[1] != int_hdr_after[1]
        ):
            return {"mode": "live", "status": "title", "pid": self.pid}

        guids = save_guids or set()
        done, found = evaluate_world_progress(map_data, all_flags, guids) if map_data else ({}, {})
        quests = evaluate_quests_progress(quests_data, bool_table, enum_table) if quests_data else {}
        archives = evaluate_archives_progress(catalog_data, bool_table, enum_table) if catalog_data else {}

        return {
            **live,
            "partition": part,
            "pouch": pouch,
            "slots": slots_valid,
            "abilities": abilities,
            "sages": sages,
            "progress": {"done": done, "found": found},
            "quests": quests,
            "archives": archives,
            "album": album or [],
        }

    # ---- Escrita de Pinos & Carimbos na memória do totk.exe ----

    def _require_ready_write(self) -> int:
        status, gdm, _actor, _part = self._gate()
        if status == "offline":
            raise RuntimeError("O jogo não está aberto no momento.")
        if status != "ready":
            raise RuntimeError("Entre em um save no jogo antes de criar ou remover marcadores.")
        if not self.can_write:
            raise RuntimeError("Sem permissão de escrita na memória do totk.exe.")
        return gdm

    def _write_arr_both(self, bufs: tuple[int, int, int], offset_bytes: int, data: bytes) -> bool:
        _, buf0, buf1 = bufs
        ok0 = self._write_bytes(buf0 + offset_bytes, data)
        ok1 = self._write_bytes(buf1 + offset_bytes, data) if buf1 else True
        return ok0 and ok1

    def set_game_pin(self, color: str, x: float, z: float, layer: str, y: float | None = None) -> dict[str, Any]:
        """Cria ou move um pino colorido (1..6) diretamente na memória do jogo."""
        if color not in PIN_COLORS:
            raise ValueError(f"Cor de pino inválida: {color}")
        if layer not in STAMP_LAYER_TO_ENUM:
            layer = "surface"
        x = max(-5500.0, min(5500.0, float(x)))
        z = max(-4500.0, min(4500.0, float(z)))

        with self._lock:
            gdm = self._require_ready_write()
            pos_bufs = self._gd_arr_bufs(gdm, T_VEC3ARR, "MapData.IconData.MapPinData.Pos")
            typ_bufs = self._gd_arr_bufs(gdm, T_ENUMARR, "MapData.IconData.MapPinData.Type")
            fit_bufs = self._gd_arr_bufs(gdm, T_BOOLARR, "MapData.IconData.MapPinData.IsFit")
            if not pos_bufs or not typ_bufs or not fit_bufs:
                raise RuntimeError("Tabelas de pinos não encontradas na memória.")
            n = min(pos_bufs[0], typ_bufs[0], 6)
            typ_raw = self.read_bytes(typ_bufs[1], n * 4)
            if not typ_raw:
                raise RuntimeError("Falha ao ler slots de pinos.")
            types = list(struct.unpack(f"<{n}I", typ_raw))
            target_hash = mmh3(color)
            invalid_hash = mmh3("Invalid")

            slot = next((i for i, th in enumerate(types) if th == target_hash), None)
            if slot is None:
                slot = next((i for i, th in enumerate(types) if th == invalid_hash), None)
            if slot is None:
                raise ValueError("Limite de 6 pinos do jogo atingido.")

            if y is None:
                y = sample_heightmap(self.game_dir, layer, x, z) if self.game_dir else 150.0
            else:
                y = float(y)

            pos_bytes = struct.pack("<3f", x, y, z)
            if not self._write_arr_both(pos_bufs, slot * 12, pos_bytes):
                raise RuntimeError("Falha ao gravar posição do pino.")

            fit_raw = self.read_bytes(fit_bufs[1], 4)
            fit_word = struct.unpack("<I", fit_raw)[0] if fit_raw else 0
            fit_word |= 1 << slot
            self._write_arr_both(fit_bufs, 0, struct.pack("<I", fit_word))

            if not self._write_arr_both(typ_bufs, slot * 4, struct.pack("<I", target_hash)):
                raise RuntimeError("Falha ao gravar tipo do pino.")

            return {
                "slot": slot,
                "type": color,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "layer": normalize_layer_name(None, y),
            }

    def remove_game_pin(self, slot: int) -> dict[str, Any]:
        """Remove o pino do slot especificado (0..5) marcando como Invalid."""
        if not (0 <= slot < 6):
            raise ValueError("Slot de pino inválido")
        with self._lock:
            gdm = self._require_ready_write()
            typ_bufs = self._gd_arr_bufs(gdm, T_ENUMARR, "MapData.IconData.MapPinData.Type")
            if not typ_bufs or slot >= typ_bufs[0]:
                raise RuntimeError("Tabela de pinos não encontrada.")
            if not self._write_arr_both(typ_bufs, slot * 4, struct.pack("<I", mmh3("Invalid"))):
                raise RuntimeError("Falha ao remover pino.")
            return {"slot": slot, "removed": True}

    def add_game_stamp(self, stamp_type: str, x: float, z: float, layer: str) -> dict[str, Any]:
        """Adiciona um carimbo no mapa diretamente na memória do jogo."""
        if stamp_type not in STAMP_TYPES:
            raise ValueError(f"Tipo de carimbo inválido: {stamp_type}")
        if layer not in STAMP_LAYER_TO_ENUM:
            raise ValueError(f"Camada inválida: {layer}")
        x = max(-5500.0, min(5500.0, float(x)))
        z = max(-4500.0, min(4500.0, float(z)))

        with self._lock:
            gdm = self._require_ready_write()
            pos_bufs = self._gd_arr_bufs(gdm, T_VEC2ARR, "MapData.IconData.StampData.Pos")
            typ_bufs = self._gd_arr_bufs(gdm, T_ENUMARR, "MapData.IconData.StampData.Type")
            lyr_bufs = self._gd_arr_bufs(gdm, T_ENUMARR, "MapData.IconData.StampData.Layer")
            if not pos_bufs or not typ_bufs or not lyr_bufs:
                raise RuntimeError("Tabelas de carimbos não encontradas na memória.")
            n = min(pos_bufs[0], typ_bufs[0], lyr_bufs[0], 300)
            typ_raw = self.read_bytes(typ_bufs[1], n * 4)
            if not typ_raw:
                raise RuntimeError("Falha ao ler slots de carimbos.")
            types = list(struct.unpack(f"<{n}I", typ_raw))
            invalid_hash = mmh3("Invalid")

            slot = next((i for i, th in enumerate(types) if th == invalid_hash), None)
            if slot is None:
                raise ValueError("Limite de 300 carimbos no mapa atingido.")

            layer_hash = mmh3(STAMP_LAYER_TO_ENUM[layer])
            type_hash = mmh3(stamp_type)

            if not self._write_arr_both(pos_bufs, slot * 8, struct.pack("<2f", x, z)):
                raise RuntimeError("Falha ao gravar posição do carimbo.")
            if not self._write_arr_both(lyr_bufs, slot * 4, struct.pack("<I", layer_hash)):
                raise RuntimeError("Falha ao gravar camada do carimbo.")
            if not self._write_arr_both(typ_bufs, slot * 4, struct.pack("<I", type_hash)):
                raise RuntimeError("Falha ao gravar tipo do carimbo.")

            return {"slot": slot, "type": stamp_type, "x": round(x, 2), "z": round(z, 2), "layer": layer}

    def remove_game_stamp(self, slot: int) -> dict[str, Any]:
        """Remove um carimbo no slot especificado (0..299) marcando como Invalid."""
        if not (0 <= slot < 300):
            raise ValueError("Slot de carimbo inválido")
        with self._lock:
            gdm = self._require_ready_write()
            typ_bufs = self._gd_arr_bufs(gdm, T_ENUMARR, "MapData.IconData.StampData.Type")
            if not typ_bufs or slot >= typ_bufs[0]:
                raise RuntimeError("Tabela de carimbos não encontrada.")
            if not self._write_arr_both(typ_bufs, slot * 4, struct.pack("<I", mmh3("Invalid"))):
                raise RuntimeError("Falha ao remover carimbo.")
            return {"slot": slot, "removed": True}
