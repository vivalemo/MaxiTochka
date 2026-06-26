@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem PYZ.pyz_extracted/logging перекрывает stdlib, если cwd в PATH
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
        pause
        exit /b 1
    )
)

echo [setup] Installing dependencies...
"%VENV_PY%" -m pip install -q --upgrade pip
"%VENV_PY%" -m pip install -q -r "%~dp0requirements.txt"
"%VENV_PY%" -m pip install -q "pyinstaller>=6.0"

if not exist "%~dp0DotLauncher.exe_extracted\main.pyc" (
    echo ERROR: DotLauncher.exe_extracted\main.pyc not found.
    echo Extract the original DotLauncher .exe with pyinstxtractor first.
    pause
    exit /b 1
)

echo [build] Killing running Maxitochka / chromedriver instances...
taskkill /f /im Maxitochka.exe >nul 2>&1
taskkill /f /im chromedriver.exe >nul 2>&1
timeout /t 1 /nobreak >nul

if exist "%~dp0dist\Maxitochka" (
    echo [build] Removing previous dist folder...
    rmdir /s /q "%~dp0dist\Maxitochka" 2>nul
    if exist "%~dp0dist\Maxitochka" (
        echo ERROR: cannot remove dist\Maxitochka - close all instances and retry.
        pause
        exit /b 1
    )
)

echo [build] Preparing runtime data...
"%VENV_PY%" "%~dp0prepare_runtime.py"
if errorlevel 1 exit /b 1

echo [build] Running PyInstaller...
"%VENV_PY%" -m PyInstaller --noconfirm "%~dp0maxitochka.spec"
if errorlevel 1 exit /b 1

set "DIST=%~dp0dist\Maxitochka"
set "RT_SRC=%~dp0build\runtime\DotLauncher.exe_extracted"
set "RT_DST=%DIST%\DotLauncher.exe_extracted"

echo [build] Copying runtime next to Maxitochka.exe...
if exist "%RT_DST%" rmdir /s /q "%RT_DST%"
xcopy /e /i /q "%RT_SRC%" "%RT_DST%" >nul
copy /y "%~dp0version.json" "%DIST%\version.json" >nul

echo.
echo Done: %DIST%\Maxitochka.exe
echo Data folder: %RT_DST%
echo.
pause
