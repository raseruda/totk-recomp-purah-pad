@echo off
cd /d "%~dp0"
set PYW=
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if defined PYW (
    start "" "%PYW%" "%~dp0launcher.py" %*
) else (
    python "%~dp0launcher.py" %*
    if errorlevel 1 pause
)
