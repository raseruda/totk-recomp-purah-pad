"""Compila o mod drop-in winmm.dll (proxy x64) e empacota a pasta mod_release/ pronta para uso."""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = Path(__file__).resolve().parent / "build"
RELEASE_DIR = ROOT_DIR / "mod_release"
SYSTEM_WINMM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "winmm.dll"
VCVARS64 = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat")

EMBED_PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
KEEP_RUNTIME_BINARIES = frozenset({
    "python312.dll",
    "python3.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "libffi-8.dll",
    "_ctypes.pyd",
    "_socket.pyd",
    "select.pyd",
    "_queue.pyd",
    "unicodedata.pyd",
    "_uuid.pyd",
    "_wmi.pyd",
    "pyexpat.pyd",
})
PY_SOURCE_FILES = (
    "config.py",
    "totk_formats.py",
    "asset_builder.py",
    "save_reader.py",
    "live_memory.py",
    "server.py",
    "launcher.py",
)


def parse_pe_exports(dll_path: Path) -> list[tuple[int, str | None]]:
    """Extrai todos os exports (ordinal, nome_ou_None) da tabela de exportação PE32+."""
    data = dll_path.read_bytes()
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    n_sec = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_sz = struct.unpack_from("<H", data, pe_off + 20)[0]
    exp_rva, _exp_sz = struct.unpack_from("<II", data, pe_off + 24 + 112)
    sec_off = pe_off + 24 + opt_sz

    secs: list[tuple[int, int, int]] = []
    for i in range(n_sec):
        vsz, vrva, rsz, rptr = struct.unpack_from("<IIII", data, sec_off + i * 40 + 8)
        secs.append((vrva, max(vsz, rsz), rptr))

    def rva2off(rva: int) -> int | None:
        for vrva, sz, rptr in secs:
            if vrva <= rva < vrva + sz:
                return rptr + (rva - vrva)
        return None

    eo = rva2off(exp_rva)
    assert eo is not None
    ord_base, n_funcs, n_names, funcs_rva, names_rva, ords_rva = struct.unpack_from("<6I", data, eo + 16)
    fo = rva2off(funcs_rva)
    no = rva2off(names_rva)
    oo = rva2off(ords_rva)
    assert fo is not None and no is not None and oo is not None

    name_by_idx: dict[int, str] = {}
    name_rvas = struct.unpack_from(f"<{n_names}I", data, no)
    name_ords = struct.unpack_from(f"<{n_names}H", data, oo)
    for nr, idx in zip(name_rvas, name_ords):
        off = rva2off(nr)
        if off is not None:
            nul = data.index(b"\0", off)
            name_by_idx[idx] = data[off:nul].decode("ascii", "strict")

    func_rvas = struct.unpack_from(f"<{n_funcs}I", data, fo)
    exports: list[tuple[int, str | None]] = []
    for idx, frva in enumerate(func_rvas):
        if frva == 0:
            continue
        exports.append((ord_base + idx, name_by_idx.get(idx)))
    return exports


def generate_sources(exports: list[tuple[int, str | None]]) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    n = len(exports)

    # 1. winmm_proxy.def
    def_lines = ["LIBRARY winmm", "EXPORTS"]
    for idx, (ordinal, name) in enumerate(exports):
        if name:
            def_lines.append(f"  {name}=purah_stub_{idx} @{ordinal}")
        else:
            def_lines.append(f"  ord_{ordinal}=purah_stub_{idx} @{ordinal} NONAME")
    (BUILD_DIR / "winmm_proxy.def").write_text("\n".join(def_lines) + "\n", encoding="ascii")

    # 2. winmm_stubs.asm (MASM x64)
    asm_lines = ["EXTERN g_winmm_procs:QWORD", ".code"]
    for idx in range(n):
        asm_lines.append(f"purah_stub_{idx} PROC")
        asm_lines.append(f"    jmp qword ptr [g_winmm_procs + {idx * 8}]")
        asm_lines.append(f"purah_stub_{idx} ENDP")
    asm_lines.append("END")
    (BUILD_DIR / "winmm_stubs.asm").write_text("\n".join(asm_lines) + "\n", encoding="ascii")

    # 3. winmm_proxy.c
    c_names = []
    c_ords = []
    for ordinal, name in exports:
        c_names.append(f'"{name}"' if name else "NULL")
        c_ords.append(str(ordinal))

    c_src = f'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

#define NUM_EXPORTS {n}
#ifndef LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR
#define LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR 0x00000100
#endif
#ifndef LOAD_LIBRARY_SEARCH_DEFAULT_DIRS
#define LOAD_LIBRARY_SEARCH_DEFAULT_DIRS 0x00001000
#endif

FARPROC g_winmm_procs[NUM_EXPORTS] = {{0}};
static HMODULE g_real_winmm = NULL;
static HANDLE g_mutex = NULL;
static volatile HWND g_app_hwnd = NULL;

static const char *const g_export_names[NUM_EXPORTS] = {{
    {", ".join(c_names)}
}};

static const WORD g_export_ordinals[NUM_EXPORTS] = {{
    {", ".join(c_ords)}
}};

static void init_real_winmm(void) {{
    if (g_real_winmm) return;
    wchar_t sys_dir[MAX_PATH];
    wchar_t dll_path[MAX_PATH + 32];
    UINT len = GetSystemDirectoryW(sys_dir, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) return;
    lstrcpynW(dll_path, sys_dir, MAX_PATH);
    lstrcatW(dll_path, L"\\\\winmm.dll");
    g_real_winmm = LoadLibraryW(dll_path);
    if (!g_real_winmm) return;
    for (int i = 0; i < NUM_EXPORTS; ++i) {{
        LPCSTR proc_id = g_export_names[i] ? g_export_names[i] : (LPCSTR)(ULONG_PTR)g_export_ordinals[i];
        g_winmm_procs[i] = GetProcAddress(g_real_winmm, proc_id);
    }}
}}

static int ends_with_ci(const wchar_t *str, const wchar_t *suffix) {{
    int sl = lstrlenW(str);
    int xl = lstrlenW(suffix);
    if (sl < xl) return 0;
    return CompareStringOrdinal(str + (sl - xl), xl, suffix, xl, TRUE) == CSTR_EQUAL;
}}

static int file_exists(const wchar_t *path) {{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}}

static void log_loader_error(const wchar_t *purah_dir, const char *msg) {{
    wchar_t data_dir[MAX_PATH * 2];
    wchar_t log_path[MAX_PATH * 2];
    swprintf_s(data_dir, MAX_PATH * 2, L"%ls\\\\data", purah_dir);
    CreateDirectoryW(data_dir, NULL);
    swprintf_s(log_path, MAX_PATH * 2, L"%ls\\\\purah_pad_loader.log", data_dir);
    HANDLE hf = CreateFileW(
        log_path,
        FILE_APPEND_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (hf != INVALID_HANDLE_VALUE) {{
        DWORD written = 0;
        DWORD len = (DWORD)lstrlenA(msg);
        WriteFile(hf, msg, len, &written, NULL);
        WriteFile(hf, "\\r\\n", 2, &written, NULL);
        CloseHandle(hf);
    }}
}}

static DWORD WINAPI launch_purah_pad_thread(LPVOID param) {{
    HMODULE hSelf = (HMODULE)param;
    Sleep(250);

    wchar_t mod_path[MAX_PATH * 2];
    wchar_t game_dir[MAX_PATH * 2];
    wchar_t purah_dir[MAX_PATH * 2];
    wchar_t py_dir[MAX_PATH * 2];
    wchar_t dll_path[MAX_PATH * 2];

    DWORD n = GetModuleFileNameW(hSelf, mod_path, MAX_PATH * 2);
    if (n == 0 || n >= MAX_PATH * 2) return 0;

    lstrcpynW(game_dir, mod_path, MAX_PATH * 2);
    int last_sep = -1;
    for (int i = 0; game_dir[i]; ++i) {{
        if (game_dir[i] == L'\\\\' || game_dir[i] == L'/') last_sep = i;
    }}
    if (last_sep <= 0) return 0;
    game_dir[last_sep] = L'\\0';

    swprintf_s(purah_dir, MAX_PATH * 2, L"%ls\\\\PurahPad", game_dir);
    swprintf_s(py_dir, MAX_PATH * 2, L"%ls\\\\python", purah_dir);

    static const wchar_t *const preload_dlls[] = {{
        L"vcruntime140.dll",
        L"vcruntime140_1.dll",
        L"libffi-8.dll",
        L"python3.dll"
    }};
    for (int i = 0; i < 4; ++i) {{
        swprintf_s(dll_path, MAX_PATH * 2, L"%ls\\\\%ls", py_dir, preload_dlls[i]);
        if (file_exists(dll_path)) {{
            LoadLibraryExW(dll_path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        }}
    }}

    swprintf_s(dll_path, MAX_PATH * 2, L"%ls\\\\python312.dll", py_dir);
    if (!file_exists(dll_path)) {{
        log_loader_error(purah_dir, "Missing PurahPad\\\\python\\\\python312.dll");
        return 0;
    }}

    HMODULE hPy = LoadLibraryExW(dll_path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!hPy) {{
        log_loader_error(purah_dir, "LoadLibraryExW failed on PurahPad\\\\python\\\\python312.dll");
        return 0;
    }}

    typedef void (__cdecl *PFN_Py_InitializeEx)(int);
    typedef int  (__cdecl *PFN_Py_IsInitialized)(void);
    typedef int  (__cdecl *PFN_PyRun_SimpleString)(const char *);

    PFN_Py_InitializeEx pInitEx = (PFN_Py_InitializeEx)GetProcAddress(hPy, "Py_InitializeEx");
    PFN_Py_IsInitialized pIsInit = (PFN_Py_IsInitialized)GetProcAddress(hPy, "Py_IsInitialized");
    PFN_PyRun_SimpleString pRunSimple = (PFN_PyRun_SimpleString)GetProcAddress(hPy, "PyRun_SimpleString");

    if (!pInitEx || !pIsInit || !pRunSimple) {{
        log_loader_error(purah_dir, "Failed to resolve CPython entry points in python312.dll");
        return 0;
    }}

    if (!pIsInit()) {{
        pInitEx(0);
    }}

    char utf8_gdir[MAX_PATH * 6];
    int ulen = WideCharToMultiByte(CP_UTF8, 0, game_dir, -1, utf8_gdir, (int)sizeof(utf8_gdir), NULL, NULL);
    if (ulen <= 1) {{
        log_loader_error(purah_dir, "WideCharToMultiByte failed for game_dir");
        return 0;
    }}
    int raw_bytes = ulen - 1;
    char hex_gdir[MAX_PATH * 12 + 1];
    static const char hex_digits[] = "0123456789abcdef";
    for (int i = 0; i < raw_bytes; ++i) {{
        unsigned char b = (unsigned char)utf8_gdir[i];
        hex_gdir[i * 2] = hex_digits[(b >> 4) & 0xF];
        hex_gdir[i * 2 + 1] = hex_digits[b & 0xF];
    }}
    hex_gdir[raw_bytes * 2] = '\\0';

    char py_code[MAX_PATH * 16];
    int nfmt = _snprintf_s(
        py_code,
        sizeof(py_code),
        _TRUNCATE,
        "import sys, os\\n"
        "_gd = bytes.fromhex('%s').decode('utf-8')\\n"
        "_pp = os.path.join(_gd, 'PurahPad')\\n"
        "if _pp not in sys.path:\\n"
        "    sys.path.insert(0, _pp)\\n"
        "import launcher\\n"
        "launcher.run_embedded(_gd, %llu)\\n",
        hex_gdir,
        (unsigned long long)(ULONG_PTR)&g_app_hwnd
    );
    if (nfmt < 0) {{
        log_loader_error(purah_dir, "Python bootstrap script truncated");
        return 0;
    }}
    if (pRunSimple(py_code) != 0) {{
        log_loader_error(purah_dir, "PyRun_SimpleString returned non-zero");
    }}
    return 0;
}}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {{
    if (fdwReason == DLL_PROCESS_ATTACH) {{
        DisableThreadLibraryCalls(hinstDLL);
        init_real_winmm();

        wchar_t exe_path[MAX_PATH * 2];
        DWORD len = GetModuleFileNameW(NULL, exe_path, MAX_PATH * 2);
        if (len > 0 && len < MAX_PATH * 2 && ends_with_ci(exe_path, L"\\\\totk.exe")) {{
            g_mutex = CreateMutexW(NULL, FALSE, L"Local\\\\TotK_PurahPad_AutoStart_Mutex");
            if (g_mutex && GetLastError() != ERROR_ALREADY_EXISTS) {{
                HANDLE th = CreateThread(NULL, 0, launch_purah_pad_thread, hinstDLL, 0, NULL);
                if (th) CloseHandle(th);
            }}
        }}
    }} else if (fdwReason == DLL_PROCESS_DETACH) {{
        HWND app_hwnd = g_app_hwnd;
        if (app_hwnd != NULL) {{
            HMODULE hUser32 = GetModuleHandleW(L"user32.dll");
            if (hUser32) {{
                typedef BOOL (WINAPI *PFN_PostMessageW)(HWND, UINT, WPARAM, LPARAM);
                PFN_PostMessageW pPostMessageW = (PFN_PostMessageW)GetProcAddress(hUser32, "PostMessageW");
                if (pPostMessageW) pPostMessageW(app_hwnd, 0x0010, 0, 0);
            }}
        }}
        if (lpvReserved == NULL && g_mutex) {{
            CloseHandle(g_mutex);
            g_mutex = NULL;
        }}
    }}
    return TRUE;
}}
'''
    (BUILD_DIR / "winmm_proxy.c").write_text(c_src, encoding="utf-8")


def compile_proxy() -> Path:
    if not VCVARS64.is_file():
        raise FileNotFoundError(f"vcvars64.bat não encontrado: {VCVARS64}")

    bat_path = BUILD_DIR / "build.bat"
    bat_path.write_text(
        "@echo off\n"
        f'call "{VCVARS64}" >nul\n'
        f'cd /d "{BUILD_DIR}"\n'
        "ml64 /nologo /c /Fo winmm_stubs.obj winmm_stubs.asm || exit /b 1\n"
        "cl /nologo /O2 /W3 /LD /MT winmm_proxy.c winmm_stubs.obj "
        "/link /DEF:winmm_proxy.def /OUT:winmm.dll kernel32.lib || exit /b 1\n",
        encoding="ascii",
    )
    res = subprocess.run(["cmd.exe", "/c", str(bat_path)], capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        raise RuntimeError(f"Compilação falhou com código {res.returncode}")
    out_dll = BUILD_DIR / "winmm.dll"
    if not out_dll.is_file():
        raise FileNotFoundError("winmm.dll não foi gerada")
    return out_dll


def _download_embed_python() -> Path:
    """Baixa (com cache local) o pacote oficial embeddable do Python 3.12.10 x64."""
    dl_dir = BUILD_DIR / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dl_dir / "python-3.12.10-embed-amd64.zip"
    if zip_path.is_file() and zipfile.is_zipfile(zip_path):
        return zip_path
    print(f"Baixando Python 3.12.10 oficial embutido: {EMBED_PYTHON_URL}")
    req = urllib.request.Request(EMBED_PYTHON_URL, headers={"User-Agent": "Mozilla/5.0"})
    tmp_path = zip_path.with_suffix(".tmp")
    with urllib.request.urlopen(req, timeout=60) as resp, tmp_path.open("wb") as out:
        shutil.copyfileobj(resp, out)
    if not zipfile.is_zipfile(tmp_path):
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Arquivo baixado do Python embeddable não é um ZIP válido")
    tmp_path.replace(zip_path)
    return zip_path


def _copy_pkg_files(pkg_name: str, dst_root: Path, allowed_bins: set[str], allowed_py: set[str] | None = None) -> None:
    """Copia apenas arquivos .py/py.typed e binários estritamente necessários de um pacote."""
    mod = importlib.import_module(pkg_name)
    src_dir = Path(mod.__file__).resolve().parent
    dst_dir = dst_root / pkg_name
    dst_dir.mkdir(parents=True, exist_ok=True)

    for src in src_dir.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(src_dir)
        name = src.name
        if name in allowed_bins:
            pass
        elif src.suffix == ".py" or name == "py.typed":
            if allowed_py is not None and name not in allowed_py:
                continue
        else:
            continue
        dst = dst_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def build_embedded_python() -> Path:
    """Monta o runtime oficial assinado do Python 3.12 sem .exe e sem arquivos .zip aninhados."""
    emb_zip = _download_embed_python()
    emb_dir = BUILD_DIR / "embedded_python"
    if emb_dir.exists():
        shutil.rmtree(emb_dir)
    emb_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(emb_zip) as zf:
        zf.extractall(emb_dir)

    stdlib_zip = emb_dir / "python312.zip"
    if not stdlib_zip.is_file():
        raise FileNotFoundError(f"python312.zip não encontrado em {emb_dir}")
    lib_dir = emb_dir / "Lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(stdlib_zip) as zf:
        zf.extractall(lib_dir)
    stdlib_zip.unlink()

    for item in list(emb_dir.iterdir()):
        if not item.is_file():
            continue
        suf = item.suffix.lower()
        if suf in (".exe", ".zip", ".cat") or item.name.endswith("._pth"):
            item.unlink()
        elif suf in (".dll", ".pyd") and item.name not in KEEP_RUNTIME_BINARIES:
            item.unlink()

    (emb_dir / "python312._pth").write_text("Lib\n.\nsite-packages\n..\n", encoding="utf-8")

    sp_dir = emb_dir / "site-packages"
    sp_dir.mkdir(parents=True, exist_ok=True)
    _copy_pkg_files("PIL", sp_dir, allowed_bins={"_imaging.cp312-win_amd64.pyd"})
    _copy_pkg_files(
        "zstandard",
        sp_dir,
        allowed_bins={"backend_c.cp312-win_amd64.pyd"},
        allowed_py={"__init__.py", "py.typed"},
    )
    _copy_pkg_files(
        "texture2ddecoder",
        sp_dir,
        allowed_bins={"_texture2ddecoder.pyd"},
        allowed_py={"__init__.py", "py.typed"},
    )

    for cache_dir in emb_dir.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)

    if not (emb_dir / "python312.dll").is_file():
        raise FileNotFoundError(f"python312.dll ausente em {emb_dir}")
    return emb_dir


def package_release(dll_path: Path, embedded_py_dir: Path | None) -> None:
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    pp_dir = RELEASE_DIR / "PurahPad"
    pp_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dll_path, RELEASE_DIR / "winmm.dll")

    for py_name in PY_SOURCE_FILES:
        shutil.copy2(ROOT_DIR / py_name, pp_dir / py_name)
    if embedded_py_dir is not None:
        shutil.copytree(embedded_py_dir, pp_dir / "python")

    shutil.copytree(ROOT_DIR / "web", pp_dir / "web")
    if (ROOT_DIR / "Iniciar Purah Pad.bat").is_file():
        shutil.copy2(ROOT_DIR / "Iniciar Purah Pad.bat", pp_dir / "Iniciar Purah Pad.bat")
    if (ROOT_DIR / "README.md").is_file():
        shutil.copy2(ROOT_DIR / "README.md", RELEASE_DIR / "README.md")
    if (ROOT_DIR / "LICENSE").is_file():
        shutil.copy2(ROOT_DIR / "LICENSE", RELEASE_DIR / "LICENSE")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compila winmm.dll e gera o pacote standalone embutido do Purah Pad.")
    ap.add_argument("--proxy-only", action="store_true", help="Compila apenas winmm.dll sem montar o runtime Python embutido")
    args = ap.parse_args()

    exports = parse_pe_exports(SYSTEM_WINMM)
    print(f"Exports detectados em {SYSTEM_WINMM}: {len(exports)}")
    generate_sources(exports)
    dll_path = compile_proxy()
    out_exports = parse_pe_exports(dll_path)
    print(f"winmm.dll compilada ({dll_path.stat().st_size} bytes), exports={len(out_exports)}")
    assert len(out_exports) == len(exports)

    embedded_py_dir = None if args.proxy_only else build_embedded_python()
    package_release(dll_path, embedded_py_dir)
    print(f"Pacote pronto em {RELEASE_DIR}")


if __name__ == "__main__":
    main()
