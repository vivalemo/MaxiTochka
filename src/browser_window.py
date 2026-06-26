"""Отдельное окно Chrome для MAX: без адресной строки, с изменением размера."""

from __future__ import annotations

from typing import Any

from app_logger import get_logger

_log = get_logger("browser_window")

MAX_APP_URL = "https://web.max.ru"
BROWSER_WINDOW_TITLE = "MAX"


def browser_window_title(_session_dir: str = "", _fname: str = "") -> str:
    """Заголовок окна браузера — только MAX, без имён файлов."""
    return BROWSER_WINDOW_TITLE


def set_window_bounds(page: Any, width: int, height: int) -> None:
    """Размер внешнего окна Chrome (работает с no_viewport)."""
    if page is None:
        return
    try:
        cdp = page.context.new_cdp_session(page)
        info = cdp.send("Browser.getWindowForTarget")
        window_id = info.get("windowId")
        if not window_id:
            return
        cdp.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {
                    "width": max(400, int(width)),
                    "height": max(400, int(height)),
                    "windowState": "normal",
                },
            },
        )
    except Exception:
        _log.debug("Browser.setWindowBounds failed", exc_info=True)


def get_window_bounds(page: Any) -> dict[str, int] | None:
    if page is None:
        return None
    try:
        cdp = page.context.new_cdp_session(page)
        info = cdp.send("Browser.getWindowForTarget")
        window_id = info.get("windowId")
        if not window_id:
            return None
        data = cdp.send("Browser.getWindowBounds", {"windowId": window_id})
        bounds = data.get("bounds") or {}
        w = int(bounds.get("width") or 0)
        h = int(bounds.get("height") or 0)
        if w > 0 and h > 0:
            return {"width": w, "height": h}
    except Exception:
        _log.debug("Browser.getWindowBounds failed", exc_info=True)
    return None
