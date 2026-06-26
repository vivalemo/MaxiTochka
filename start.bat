@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem PYZ extract folder must not be on PYTHONPATH
set "PYTHONPATH="
set "PYTHONSAFEPATH=1"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PY313=%LocalAppData%\Programs\Python\Python313\python.exe"

if not exist "%VENV_PY%" (
    echo [setup] Creating virtual environment...
    if exist "%PY313%" (
        "%PY313%" -m venv "%~dp0.venv"
    ) else (
        echo ERROR: Python 3.13 not found.
        echo Install from https://www.python.org/downloads/ or fix path in start.bat
        pause
        exit /b 1
    )
)

if exist "%~dp0.venv\Lib\site-packages\~ip" (
    echo [setup] Repairing broken pip in venv...
    rmdir /s /q "%~dp0.venv\Lib\site-packages\~ip" 2>nul
    rmdir /s /q "%~dp0.venv\Lib\site-packages\~ip-24.3.1.dist-info" 2>nul
    "%VENV_PY%" -m pip install -q --force-reinstall pip
)

if not exist "%~dp0.venv\Scripts\pip.exe" (
    echo [setup] Upgrading pip...
    "%VENV_PY%" -m pip install -q --upgrade pip
)

echo [setup] Checking dependencies...
"%VENV_PY%" -m pip install -q -r "%~dp0requirements.txt"

echo [setup] Playwright browser (Chrome)...
"%VENV_PY%" -m playwright install chrome 2>nul

echo [run] Starting Maxitochka...
"%VENV_PY%" "%~dp0run_launcher.py"
set "ERR=%ERRORLEVEL%"
if %ERR% neq 0 (
    echo.
    echo Exit code: %ERR%
    pause
)
exit /b %ERR%
