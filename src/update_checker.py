"""Проверка и загрузка обновлений Maxitochka."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from app_logger import get_logger
from app_version import APP_VERSION, load_version_info
from settings_store import UPDATE_URL, app_data_root, load_settings, save_settings

_log = get_logger("update")

ProgressFn = Callable[[str], None]


class _UpdateBridge(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


def _parse_version(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in re.split(r"[.\-+]", str(raw or "").strip()):
        if not chunk:
            continue
        m = re.match(r"(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) if parts else (0,)


def is_newer_version(remote: str, local: str | None = None) -> bool:
    return _parse_version(remote) > _parse_version(local or APP_VERSION)


def fetch_remote_version(url: str | None = None, *, timeout: float = 12.0) -> dict | None:
    check_url = (url or UPDATE_URL or "").strip()
    if not check_url:
        return None
    try:
        req = urllib.request.Request(
            check_url,
            headers={"User-Agent": f"Maxitochka/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as ex:
        _log.warning("fetch remote version failed: %s", ex)
        return None


def _updates_dir() -> str:
    path = os.path.join(app_data_root(), "updates")
    os.makedirs(path, exist_ok=True)
    return path


def download_update(
    url: str,
    version: str,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    """Скачать zip обновления. Возвращает путь к файлу."""
    safe_ver = re.sub(r"[^\w.\-]+", "_", version or "latest")
    dest = os.path.join(_updates_dir(), f"Maxitochka-{safe_ver}.zip")
    if on_progress:
        on_progress(f"Скачивание {version}…")

    req = urllib.request.Request(url, headers={"User-Agent": f"Maxitochka/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if on_progress and total > 0:
                on_progress(f"Скачано {done * 100 // total}%")

    _log.info("update downloaded: %s", dest)
    return dest


def _open_folder(path: str) -> bool:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def _show_result(parent: Any, title: str, text: str, *, informative: str = "") -> int:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if informative:
        box.setInformativeText(informative)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return int(box.exec())


def _ask_download(parent: Any, latest: str, notes: str, url: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle("Доступно обновление")
    box.setText(f"Новая версия: {latest}\nУ вас: {APP_VERSION}")
    body = (notes or "").strip()
    if url:
        body = (body + "\n\n" if body else "") + f"Файл:\n{url}"
    if body:
        box.setInformativeText(body)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    box.button(QMessageBox.StandardButton.Yes).setText("Скачать")
    box.button(QMessageBox.StandardButton.No).setText("Позже")
    return box.exec() == QMessageBox.StandardButton.Yes


def check_updates(parent: Any, *, silent: bool = False) -> dict:
    """Проверить обновления. silent=True — без окна, если версия актуальна."""
    save_settings({"last_version_check": datetime.now().isoformat(timespec="seconds")})
    data = fetch_remote_version()
    result = {
        "ok": bool(data),
        "current": APP_VERSION,
        "latest": APP_VERSION,
        "update_available": False,
    }
    if not data:
        if not silent:
            _show_result(
                parent,
                "Обновления",
                "Не удалось проверить обновления.",
                informative=f"Текущая версия: {APP_VERSION}\n\nURL:\n{UPDATE_URL}",
            )
        return result

    latest = str(data.get("version") or APP_VERSION).strip()
    url = str(data.get("url") or "").strip()
    notes = str(data.get("notes") or "").strip()
    result["latest"] = latest
    result["update_available"] = is_newer_version(latest)

    if not result["update_available"]:
        if not silent:
            _show_result(
                parent,
                "Обновления",
                f"У вас актуальная версия ({APP_VERSION}).",
            )
        return result

    if silent:
        if hasattr(parent, "signals"):
            try:
                parent.signals.notify.emit(
                    f"Доступно обновление {latest}\nУ вас: {APP_VERSION}\n"
                    "Нажмите «Обновление» внизу окна.",
                    "#f59e0b",
                )
            except Exception:
                pass
        return result

    if not url:
        _show_result(
            parent,
            "Есть обновление",
            f"Версия {latest} опубликована, но ссылка на скачивание не указана.",
            informative=notes,
        )
        return result

    if _ask_download(parent, latest, notes, url):
        _download_and_notify(parent, url, latest)
    return result


def _download_and_notify(parent: Any, url: str, version: str) -> None:
    bridge = _UpdateBridge()

    def _worker() -> None:
        try:
            path = download_update(url, version)
            bridge.finished.emit(path)
        except Exception as ex:
            bridge.failed.emit(str(ex))

    def _ok(path: str) -> None:
        folder = os.path.dirname(path)
        _open_folder(folder)
        _show_result(
            parent,
            "Обновление скачано",
            f"Файл сохранён:\n{path}",
            informative=(
                "Распакуйте архив поверх папки с Maxitochka.exe "
                "(или замените папку dist\\Maxitochka) и перезапустите программу."
            ),
        )

    def _err(msg: str) -> None:
        _log.exception("download failed: %s", msg)
        _show_result(parent, "Ошибка загрузки", msg)

    bridge.finished.connect(_ok)
    bridge.failed.connect(_err)
    threading.Thread(target=_worker, daemon=True, name="update-download").start()


def schedule_auto_check(window: Any, *, delay_ms: int = 10000) -> None:
    """Фоновая проверка при старте (не чаще раза в сутки)."""
    settings = load_settings()
    if settings.get("auto_check_updates") is False:
        return
    last = str(settings.get("last_version_check") or "").strip()
    if last:
        try:
            dt = datetime.fromisoformat(last)
            if datetime.now() - dt < timedelta(hours=24):
                return
        except ValueError:
            pass

    def _run() -> None:
        try:
            check_updates(window, silent=True)
        except Exception:
            _log.exception("auto update check failed")

    QTimer.singleShot(max(3000, int(delay_ms)), _run)
