@echo off
cd /d "%~dp0.."

if not exist "dist\Maxitochka\Maxitochka.exe" goto nobuild

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0make_release_zip.py"
if errorlevel 1 goto fail

echo.
pause
exit /b 0

:nobuild
echo Run build.bat first.
pause
exit /b 1

:fail
pause
exit /b 1
