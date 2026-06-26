@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "GIT=git -c safe.directory=%CD%"

echo === Maxitochka: публикация на GitHub ===
echo.

%GIT% status --short 2>nul | findstr /r "." >nul
if errorlevel 1 (
    echo Нет изменений для коммита.
) else (
    echo Коммит...
    %GIT% add -A
    %GIT% commit -m "Maxitochka: автообновление, Selenium по умолчанию, CRM"
    if errorlevel 1 (
        echo Коммит не выполнен.
        pause
        exit /b 1
    )
)

echo.
set /p REPO=URL репозитория GitHub (https://github.com/USER/REPO.git): 
if "%REPO%"=="" (
    echo Укажите URL репозитория.
    pause
    exit /b 1
)

%GIT% branch -M main 2>nul
%GIT% remote remove origin 2>nul
%GIT% remote add origin "%REPO%"
echo.
echo Отправка на GitHub...
%GIT% push -u origin main
if errorlevel 1 (
    echo.
    echo Если репозиторий ещё не создан — создайте его на github.com
    echo Затем снова запустите этот скрипт.
    pause
    exit /b 1
)

echo.
echo Готово. Не забудьте в version.json заменить USER/REPO на свой репозиторий.
pause
