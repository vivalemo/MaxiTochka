"""Обёртка Playwright-сессии с совместимостью с WebDriver API (legacy patches)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app_logger import get_logger

_log = get_logger("browser_session")

_TITLE_HOOK_INSTALLED = "_maxitochka_title_hook"


@dataclass
class BrowserSession:
    """Одна открытая сессия MAX в Playwright."""

    session_name: str
    profile_dir: str
    cdp_port: int
    proxy_raw: str
    context: Any
    page: Any
    playwright: Any = None
    closed: bool = False
    owner_thread_id: int = 0


class PlaywrightDriverAdapter:
    """Минимальный WebDriver-совместимый фасад для launch_panel / sessions_meta."""

    backend = None

    def __init__(self, session: BrowserSession) -> None:
        self._session = session
        self._mx_playwright_session = session

    @property
    def current_url(self) -> str:
        try:
            return self._session.page.url or ""
        except Exception:
            return ""

    @property
    def window_handles(self) -> list[str]:
        if self._session.closed:
            return []
        try:
            if self._session.page.is_closed():
                return []
        except Exception:
            return []
        return ["main"]

    def execute_script(self, script: str, *args: Any) -> Any:
        page = self._session.page
        body = (script or "").strip()
        if not body:
            return None
        try:
            if args:
                if body.startswith("return "):
                    expr = body[7:].strip()
                    return page.evaluate(f"(args) => {{ return ({expr}); }}", list(args))
                return page.evaluate(
                    f"(args) => {{ {body} }}",
                    list(args),
                )
            if body.startswith("return "):
                return page.evaluate(body[7:].strip())
            if body.startswith("(") or body.startswith("function"):
                return page.evaluate(body)
            return page.evaluate(f"(() => {{ {body} }})()")
        except Exception:
            _log.debug("execute_script failed for %s", self._session.session_name, exc_info=True)
            raise

    def execute_cdp_cmd(self, cmd: str, params: dict | None = None) -> Any:
        cdp = self._session.context.new_cdp_session(self._session.page)
        return cdp.send(cmd, params or {})

    def set_window_size(self, width: int, height: int) -> None:
        from browser_window import set_window_bounds

        set_window_bounds(self._session.page, int(width), int(height))

    def get_window_size(self) -> dict[str, int]:
        from browser_window import get_window_bounds

        bounds = get_window_bounds(self._session.page)
        if bounds:
            return bounds
        vp = self._session.page.viewport_size
        if vp:
            return {"width": vp["width"], "height": vp["height"]}
        return {"width": 800, "height": 600}

    def quit(self) -> None:
        from browser_launcher import close_session

        close_session(self._session)

    def close(self) -> None:
        self.quit()


def is_session_alive(session: BrowserSession | None) -> bool:
    if session is None or session.closed:
        return False
    port = int(session.cdp_port or 0)
    if port:
        from session_registry import is_browser_window_alive

        return is_browser_window_alive(port)
    try:
        if session.page.is_closed():
            return False
        return any(not p.is_closed() for p in session.context.pages)
    except Exception:
        return False


def install_browser_close_handler(
    driver: PlaywrightDriverAdapter | None,
    on_close: Callable[[], None],
) -> None:
    """Сразу остановить сессию, когда пользователь закрыл окно Chrome."""
    sess = getattr(driver, "_mx_playwright_session", None) if driver else None
    if sess is None or sess.closed:
        return
    fired = {"done": False}

    def _fire(*_args: Any) -> None:
        if fired["done"]:
            return
        fired["done"] = True
        try:
            on_close()
        except Exception:
            _log.debug("browser close handler failed", exc_info=True)

    try:
        sess.page.on("close", _fire)
    except Exception:
        _log.debug("page.on(close) failed", exc_info=True)
    try:
        sess.context.on("close", _fire)
    except Exception:
        _log.debug("context.on(close) failed", exc_info=True)


def as_driver(session: BrowserSession | None) -> PlaywrightDriverAdapter | None:
    if session is None:
        return None
    return PlaywrightDriverAdapter(session)
