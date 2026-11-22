"""Compila o mod drop-in winmm.dll (proxy x64) e empacota a pasta mod_release/ pronta para uso."""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = Path(__file__).resolve().parent / "build"
RELEASE_DIR = ROOT_DIR / "mod_release"
SYSTEM_WINMM = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "winmm.dll"
VCVARS64 = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat")


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
#include <wctype.h>

#define NUM_EXPORTS {n}

FARPROC g_winmm_procs[NUM_EXPORTS] = {{0}};
static HMODULE g_real_winmm = NULL;
static HANDLE g_mutex = NULL;

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

static int contains_ci(const wchar_t *hay, const wchar_t *needle) {{
    int hl = lstrlenW(hay);
    int nl = lstrlenW(needle);
    if (nl <= 0 || hl < nl) return 0;
    for (int i = 0; i <= hl - nl; ++i) {{
        if (CompareStringOrdinal(hay + i, nl, needle, nl, TRUE) == CSTR_EQUAL) return 1;
    }}
    return 0;
}}

static int file_exists(const wchar_t *path) {{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}}

static int find_pythonw(wchar_t *out, DWORD cap) {{
    if (SearchPathW(NULL, L"pythonw.exe", NULL, cap, out, NULL) > 0 && !contains_ci(out, L"WindowsApps")) return 1;
    wchar_t local[MAX_PATH];
    if (GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH) > 0) {{
        static const wchar_t *const rels[] = {{
            L"\\\\Programs\\\\Python\\\\Python313\\\\pythonw.exe",
            L"\\\\Programs\\\\Python\\\\Python312\\\\pythonw.exe",
            L"\\\\Programs\\\\Python\\\\Python311\\\\pythonw.exe",
            L"\\\\Programs\\\\Python\\\\Python310\\\\pythonw.exe",
        }};
        for (int i = 0; i < 4; ++i) {{
            swprintf_s(out, cap, L"%ls%ls", local, rels[i]);
            if (file_exists(out)) return 1;
        }}
    }}
    if (SearchPathW(NULL, L"python.exe", NULL, cap, out, NULL) > 0 && !contains_ci(out, L"WindowsApps")) return 1;
    return 0;
}}

static DWORD WINAPI launch_purah_pad_thread(LPVOID param) {{
    HMODULE hSelf = (HMODULE)param;
    wchar_t mod_path[MAX_PATH * 2];
    wchar_t game_dir[MAX_PATH * 2];
    wchar_t purah_dir[MAX_PATH * 2];
    wchar_t purah_exe[MAX_PATH * 2];
    wchar_t launcher_py[MAX_PATH * 2];
    wchar_t python_exe[MAX_PATH * 2];
    wchar_t cmd_line[MAX_PATH * 6];

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
    swprintf_s(purah_exe, MAX_PATH * 2, L"%ls\\\\PurahPad.exe", purah_dir);

    DWORD pid = GetCurrentProcessId();
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);

    if (file_exists(purah_exe)) {{
        swprintf_s(
            cmd_line,
            MAX_PATH * 6,
            L"\\"%ls\\" --game-dir \\"%ls\\" --watch-pid %lu",
            purah_exe,
            game_dir,
            (unsigned long)pid
        );
        if (CreateProcessW(purah_exe, cmd_line, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, purah_dir, &si, &pi)) {{
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
        }}
        return 0;
    }}

    swprintf_s(launcher_py, MAX_PATH * 2, L"%ls\\\\launcher.py", purah_dir);
    if (!file_exists(launcher_py)) return 0;
    if (!find_pythonw(python_exe, MAX_PATH * 2)) return 0;

    swprintf_s(
        cmd_line,
        MAX_PATH * 6,
        L"\\"%ls\\" \\"%ls\\" --game-dir \\"%ls\\" --watch-pid %lu",
        python_exe,
        launcher_py,
        game_dir,
        (unsigned long)pid
    );
    if (CreateProcessW(python_exe, cmd_line, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, purah_dir, &si, &pi)) {{
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }}
    return 0;
}}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {{
    (void)lpvReserved;
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
        if (g_mutex) {{
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


def build_standalone_exe() -> Path:
    """Empacota o Purah Pad em PurahPad.exe standalone via PyInstaller (--onedir --noconsole)."""
    dist_dir = BUILD_DIR / "dist"
    work_dir = BUILD_DIR / "work"
    for d in (dist_dir, work_dir):
        if d.exists():
            shutil.rmtree(d)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noconsole",
        "--name",
        "PurahPad",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT_DIR),
        "--collect-all",
        "texture2ddecoder",
        "--collect-all",
        "zstandard",
        "--collect-submodules",
        "PIL",
        "--hidden-import",
        "config",
        "--hidden-import",
        "totk_formats",
        "--hidden-import",
        "asset_builder",
        "--hidden-import",
        "save_reader",
        "--hidden-import",
        "live_memory",
        "--hidden-import",
        "server",
        str(ROOT_DIR / "launcher.py"),
    ]
    print("Executando PyInstaller para PurahPad.exe standalone...")
    res = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller falhou com código {res.returncode}")

    out_dir = dist_dir / "PurahPad"
    if not (out_dir / "PurahPad.exe").is_file():
        raise FileNotFoundError(f"PurahPad.exe não encontrado em {out_dir}")
    return out_dir


def package_release(dll_path: Path, standalone_dir: Path | None) -> None:
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    pp_dir = RELEASE_DIR / "PurahPad"
    shutil.copy2(dll_path, RELEASE_DIR / "winmm.dll")

    if standalone_dir is not None:
        shutil.copytree(standalone_dir, pp_dir)
    else:
        pp_dir.mkdir(parents=True, exist_ok=True)
        for py_name in ("config.py", "totk_formats.py", "asset_builder.py", "save_reader.py", "live_memory.py", "server.py", "launcher.py"):
            shutil.copy2(ROOT_DIR / py_name, pp_dir / py_name)

    shutil.copytree(ROOT_DIR / "web", pp_dir / "web")
    if (ROOT_DIR / "Iniciar Purah Pad.bat").is_file():
        shutil.copy2(ROOT_DIR / "Iniciar Purah Pad.bat", pp_dir / "Iniciar Purah Pad.bat")
    if (ROOT_DIR / "README.md").is_file():
        shutil.copy2(ROOT_DIR / "README.md", RELEASE_DIR / "README.md")
    if (ROOT_DIR / "LICENSE").is_file():
        shutil.copy2(ROOT_DIR / "LICENSE", RELEASE_DIR / "LICENSE")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compila winmm.dll e gera o pacote standalone do Purah Pad.")
    ap.add_argument("--proxy-only", action="store_true", help="Compila apenas winmm.dll sem rodar PyInstaller")
    args = ap.parse_args()

    exports = parse_pe_exports(SYSTEM_WINMM)
    print(f"Exports detectados em {SYSTEM_WINMM}: {len(exports)}")
    generate_sources(exports)
    dll_path = compile_proxy()
    out_exports = parse_pe_exports(dll_path)
    print(f"winmm.dll compilada ({dll_path.stat().st_size} bytes), exports={len(out_exports)}")
    assert len(out_exports) == len(exports)

    standalone_dir = None if args.proxy_only else build_standalone_exe()
    package_release(dll_path, standalone_dir)
    print(f"Pacote pronto em {RELEASE_DIR}")


if __name__ == "__main__":
    main()
