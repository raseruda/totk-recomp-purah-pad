@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

tasklist /FI "IMAGENAME eq totk.exe" 2>nul | find /I "totk.exe" >nul
if not errorlevel 1 (
    set "URL=http://127.0.0.1:8765"
    for %%B in (
        "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
        "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
        "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
        "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
        "%LocalAppData%\Google\Chrome\Application\chrome.exe"
        "%LocalAppData%\Microsoft\Edge\Application\msedge.exe"
    ) do (
        if exist %%~B (
            start "" %%~B --app=%URL% --new-window
            exit /b 0
        )
    )
    start "" "%URL%"
    exit /b 0
)

set "PYEXE="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    echo "%%i" | findstr /I "WindowsApps" >nul
    if errorlevel 1 if not defined PYEXE set "PYEXE=%%i"
)
if defined PYEXE (
    start "" "%PYEXE%" "%~dp0launcher.py" %*
    exit /b 0
)

for /f "delims=" %%i in ('where python 2^>nul') do (
    echo "%%i" | findstr /I "WindowsApps" >nul
    if errorlevel 1 if not defined PYEXE set "PYEXE=%%i"
)
if defined PYEXE (
    "%PYEXE%" "%~dp0launcher.py" %*
    if errorlevel 1 pause
    exit /b 0
)

echo.
echo [EN] Python is NOT required! Simply open totk.exe and Purah Pad starts automatically on Monitor 2.
echo      (Run this .bat while the game is open to reopen the Purah Pad window if you closed it.)
echo.
echo [PT-BR] Python NAO e necessario! Basta abrir o totk.exe e o Purah Pad abre sozinho no Monitor 2.
echo         (Execute este .bat com o jogo aberto caso tenha fechado a janela do Purah Pad.)
echo.
pause
exit /b 0
