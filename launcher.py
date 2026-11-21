"""Inicializador do Purah Pad na segunda tela (Monitor 2) via Edge/Chrome App Mode."""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from config import CACHE_DIR, DEFAULT_PORT, load_settings
from server import create_server

MONITORINFOF_PRIMARY = 0x00000001
SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), _MONITORENUMPROC, wintypes.LPARAM]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL


def list_monitors() -> list[dict[str, Any]]:
    """Lista os monitores do Windows ordenando o secundário primeiro para o alvo."""
    monitors: list[dict[str, Any]] = []

    @_MONITORENUMPROC
    def cb(hmon: int, _hdc: int, _rect: Any, _lparam: int) -> bool:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcWork
            monitors.append(
                {
                    "device": info.szDevice,
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    "x": int(r.left),
                    "y": int(r.top),
                    "width": int(r.right - r.left),
                    "height": int(r.bottom - r.top),
                }
            )
        return True

    _user32.EnumDisplayMonitors(None, None, cb, 0)
    return monitors


def pick_secondary_monitor() -> dict[str, Any]:
    """Escolhe o primeiro monitor não-primário, ou o primário se houver só uma tela."""
    mons = list_monitors()
    for m in mons:
        if not m["primary"]:
            return m
    return mons[0] if mons else {"device": "DEFAULT", "primary": True, "x": 0, "y": 0, "width": 1280, "height": 720}


def find_browser_executable() -> Path | None:
    """Encontra msedge.exe ou chrome.exe instalado."""
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    if local:
        candidates.append(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for c in candidates:
        if c.is_file():
            return c
    return None


def pick_free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return 0


def _find_app_window(pid: int | None) -> int | None:
    found: list[int] = []

    @_WNDENUMPROC
    def cb(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        ln = _user32.GetWindowTextLengthW(hwnd)
        if ln <= 0:
            return True
        buf = ctypes.create_unicode_buffer(ln + 1)
        _user32.GetWindowTextW(hwnd, buf, ln + 1)
        title = buf.value
        if "Purah Pad" in title:
            found.append(hwnd)
            return False
        if pid:
            wpid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(cb, 0)
    return found[0] if found else None


def move_window_to_monitor(pid: int | None, mon: dict[str, Any], timeout_s: float = 8.0) -> bool:
    """Move a janela do Purah Pad para o monitor alvo e a maximiza."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        hwnd = _find_app_window(pid)
        if hwnd:
            _user32.ShowWindow(hwnd, SW_RESTORE)
            _user32.SetWindowPos(
                hwnd,
                None,
                mon["x"],
                mon["y"],
                mon["width"],
                mon["height"],
                SWP_NOZORDER | SWP_SHOWWINDOW,
            )
            _user32.ShowWindow(hwnd, SW_MAXIMIZE)
            return True
        time.sleep(0.15)
    return False


def _watch_parent_pid(pid: int, on_exit: Any) -> None:
    """Aguarda o encerramento do totk.exe e fecha o Purah Pad junto."""
    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    h = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return
    try:
        _kernel32.WaitForSingleObject(h, INFINITE)
    finally:
        _kernel32.CloseHandle(h)
    on_exit()


def main() -> None:
    import argparse
    from config import get_game_dir

    ap = argparse.ArgumentParser(description="Inicia o Purah Pad maximizado no Monitor 2.")
    ap.add_argument("--lan", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Apenas mostra monitores e navegador detectados")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--watch-pid", type=int, default=0)
    args = ap.parse_args()

    mon = pick_secondary_monitor()
    browser = find_browser_executable()
    gdir = get_game_dir(args.game_dir)
    if args.dry_run:
        print("Game dir:", gdir)
        print("Monitores:", list_monitors())
        print("Alvo (Monitor 2):", mon)
        print("Navegador:", browser)
        return

    mutex = _kernel32.CreateMutexW(None, False, "Local\\TotK_PurahPad_Launcher_Mutex")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = _find_app_window(None)
        if hwnd:
            _user32.ShowWindow(hwnd, SW_MAXIMIZE)
            _user32.SetForegroundWindow(hwnd)
        if mutex:
            _kernel32.CloseHandle(mutex)
        return

    settings = load_settings()
    port = pick_free_port(int(settings.get("port", DEFAULT_PORT)))
    srv, runtime = create_server(game_dir=gdir, port=port, lan=args.lan)
    srv_thread = threading.Thread(target=srv.serve_forever, daemon=True, name="HTTPServer")
    srv_thread.start()

    url = f"http://127.0.0.1:{runtime.port}"
    print(f"Purah Pad rodando em {url} -> Monitor {mon['device']} ({mon['width']}x{mon['height']} @ {mon['x']},{mon['y']})")

    if args.no_browser or browser is None:
        if args.watch_pid:
            threading.Thread(
                target=_watch_parent_pid,
                args=(args.watch_pid, lambda: runtime.stop_event.set()),
                daemon=True,
            ).start()
        try:
            while not runtime.stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            runtime.stop_event.set()
            srv.shutdown()
            srv.server_close()
            if mutex:
                _kernel32.CloseHandle(mutex)
        return

    profile_dir = CACHE_DIR / "edge_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--new-window",
        f"--window-position={mon['x']},{mon['y']}",
        f"--window-size={mon['width']},{mon['height']}",
    ]
    proc = subprocess.Popen(cmd)
    move_window_to_monitor(proc.pid, mon, timeout_s=8.0)

    if args.watch_pid:
        def close_browser_on_game_exit() -> None:
            hwnd = _find_app_window(proc.pid)
            if hwnd:
                _user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                time.sleep(0.5)
            if proc.poll() is None:
                proc.terminate()

        threading.Thread(
            target=_watch_parent_pid,
            args=(args.watch_pid, close_browser_on_game_exit),
            daemon=True,
        ).start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        runtime.stop_event.set()
        srv.shutdown()
        srv.server_close()
        if mutex:
            _kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
