@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist "dist\Maxitochka\Maxitochka.exe" (
    echo Сначала выполните build.bat
    pause
    exit /b 1
)

for /f "tokens=2 delims=:" %%a in ('findstr /c:"\"version\"" version.json') do (
    set "VER=%%a"
)
set VER=%VER:"=%
set VER=%VER:,=%
set VER=%VER: =%

set "ZIP=dist\Maxitochka-%VER%.zip"
if exist "%ZIP%" del /f /q "%ZIP%"

powershell -NoProfile -Command "Compress-Archive -Path 'dist\Maxitochka\*' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 exit /b 1

echo.
echo Готово: %ZIP%
echo Загрузите этот файл в GitHub Releases и обновите url в version.json
echo.
pause
