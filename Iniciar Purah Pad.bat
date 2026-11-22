@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if exist "%~dp0PurahPad.exe" (
    start "" "%~dp0PurahPad.exe" %*
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

echo PurahPad.exe not found in "%~dp0".
pause
exit /b 1
