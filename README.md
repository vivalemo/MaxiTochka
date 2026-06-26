# Maxitochka

Панель управления токенами MAX: запуск, прокси, чекер, CRM, автоматизация.

## Сборка

```bat
build.bat
```

Результат: `dist\Maxitochka\Maxitochka.exe`

## Обновления

В корне лежит `version.json`:

```json
{
  "version": "1.2.8",
  "update_url": "https://raw.githubusercontent.com/USER/REPO/main/version.json",
  "url": "https://github.com/USER/REPO/releases/download/v1.2.8/Maxitochka.zip",
  "notes": "Что нового"
}
```

- В приложении: кнопка **«Обновление»** внизу окна
- При старте: автопроверка раз в сутки (можно отключить в `%APPDATA%\Maxitochka\settings.json` → `"auto_check_updates": false`)

### Публикация новой версии

1. Поднимите `version` в `version.json`
2. Укажите реальные `update_url` и `url` (ссылка на zip в Releases)
3. Соберите `build.bat`, упакуйте `dist\Maxitochka` в zip
4. Создайте GitHub Release, загрузите zip
5. Закоммитьте `version.json` в `main`

Скрипт-помощник:

```bat
scripts\make_release_zip.bat
```

## GitHub (первый раз)

```bat
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

Замените `USER/REPO` в `version.json` и в remote на свой репозиторий.

## Настройки

Файл: `%APPDATA%\Maxitochka\settings.json`

| Ключ | По умолчанию | Описание |
|------|--------------|----------|
| `browser_engine` | `selenium` | `selenium` или `playwright` |
| `auto_check_updates` | `true` | Проверка обновлений при старте |
| `crm_chat_keyword` | `ЖКХ, ключ` | Фильтр чатов CRM |

## Разработка

```bat
start.bat
```

Тесты:

```bat
.venv\Scripts\python.exe scripts\test_unit_all.py
```
