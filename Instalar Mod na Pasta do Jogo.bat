@echo off
setlocal
set "SRC=%~dp0mod_release"
set "DST=C:\Games\The Legend of Zelda - Tears of the Kingdom"
if not exist "%SRC%\winmm.dll" (
    python "%~dp0mod_native\build_proxy.py"
    if errorlevel 1 (
        echo Falha ao compilar winmm.dll
        pause
        exit /b 1
    )
)
echo Instalando mod auto-start do Purah Pad em:
echo   %DST%
copy /Y "%SRC%\winmm.dll" "%DST%\winmm.dll" >nul
robocopy "%SRC%\PurahPad" "%DST%\PurahPad" /E /NFL /NDL /NJH /NJS /NC /NS /NP >nul
if exist "%~dp0cache" (
    robocopy "%~dp0cache" "%DST%\PurahPad\cache" /E /XD edge_profile /NFL /NDL /NJH /NJS /NC /NS /NP >nul
)
if exist "%~dp0data" (
    robocopy "%~dp0data" "%DST%\PurahPad\data" /E /NFL /NDL /NJH /NJS /NC /NS /NP >nul
)
echo Mod instalado com sucesso! Abra totk.exe para iniciar automaticamente no Monitor 2.
pause
