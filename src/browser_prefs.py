"""Размер окна браузера и заголовок вкладки для токена."""

from __future__ import annotations

import json
from typing import Any

from browser_window import browser_window_title, get_window_bounds, set_window_bounds
from settings_store import load_settings, save_settings

_DEFAULT_W = 800
_DEFAULT_H = 600
_MIN_SIZE = 400
_MAX_SIZE = 3840

# В Chrome имя на вкладке = document.title (отдельного API нет).
_TITLE_HOOK_INSTALLED = "_maxitochka_title_hook"


def get_window_size() -> tuple[int, int]:
    s = load_settings()
    try:
        w = int(s.get("browser_width") or _DEFAULT_W)
        h = int(s.get("browser_height") or _DEFAULT_H)
    except (TypeError, ValueError):
        w, h = _DEFAULT_W, _DEFAULT_H
    w = max(_MIN_SIZE, min(_MAX_SIZE, w))
    h = max(_MIN_SIZE, min(_MAX_SIZE, h))
    return w, h


def save_window_size(width: int, height: int) -> None:
    try:
        w = max(_MIN_SIZE, min(_MAX_SIZE, int(width)))
        h = max(_MIN_SIZE, min(_MAX_SIZE, int(height)))
    except (TypeError, ValueError):
        return
    data = load_settings()
    if data.get("browser_width") == w and data.get("browser_height") == h:
        return
    data["browser_width"] = w
    data["browser_height"] = h
    save_settings(data)


def token_tab_title(session_dir: str, fname: str) -> str:
    """Заголовок окна браузера — только MAX."""
    return browser_window_title(session_dir, fname)


def _title_persist_script(title: str) -> str:
    """Вешается на каждую страницу: сайт часто меняет <title> после загрузки."""
    t = json.dumps(title, ensure_ascii=False)
    return f"""
(function() {{
  var T = {t};
  function apply() {{
    try {{
      if (document.title !== T) document.title = T;
      var el = document.querySelector("title");
      if (el && el.textContent !== T) el.textContent = T;
    }} catch (e) {{}}
  }}
  apply();
  if (window.__maxitochkaTitleTimer) clearInterval(window.__maxitochkaTitleTimer);
  window.__maxitochkaTitleTimer = setInterval(apply, 1200);
  if (!window.__maxitochkaTitleObs) {{
    window.__maxitochkaTitleObs = new MutationObserver(apply);
    var root = document.documentElement || document;
    window.__maxitochkaTitleObs.observe(root, {{
      subtree: true, childList: true, characterData: true
    }});
  }}
}})();
"""


def install_tab_title_hook(driver: Any, session_dir: str, fname: str) -> None:
    """Один раз на сессию: скрипт на все будущие страницы."""
    if driver is None or getattr(driver, _TITLE_HOOK_INSTALLED, False):
        return
    title = token_tab_title(session_dir, fname)
    script = _title_persist_script(title)
    sess = getattr(driver, "_mx_playwright_session", None)
    if sess is not None:
        try:
            sess.context.add_init_script(script)
            setattr(driver, _TITLE_HOOK_INSTALLED, True)
        except Exception:
            pass
        return
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": script},
        )
        setattr(driver, _TITLE_HOOK_INSTALLED, True)
    except Exception:
        pass


def refresh_tab_title(driver: Any, session_dir: str, fname: str) -> None:
    """Повторно выставить document.title (сайт мог перезаписать)."""
    if driver is None:
        return
    title = token_tab_title(session_dir, fname)
    try:
        driver.execute_script(
            """
            var t = arguments[0];
            try {
              if (document.title !== t) document.title = t;
              var el = document.querySelector('title');
              if (el && el.textContent !== t) el.textContent = t;
            } catch (e) {}
            """,
            title,
        )
    except Exception:
        pass


def apply_browser_prefs(driver: Any, session_dir: str, fname: str) -> None:
    """Размер окна + заголовок MAX при появлении драйвера."""
    if driver is None:
        return
    w, h = get_window_size()
    sess = getattr(driver, "_mx_playwright_session", None)
    page = getattr(sess, "page", None) if sess is not None else None
    if page is not None:
        set_window_bounds(page, w, h)
    else:
        try:
            driver.set_window_size(w, h)
        except Exception:
            pass
    install_tab_title_hook(driver, session_dir, fname)
    refresh_tab_title(driver, session_dir, fname)


def capture_window_size_from_driver(driver: Any) -> None:
    """Запомнить текущий размер окна перед закрытием."""
    if driver is None:
        return
    try:
        sess = getattr(driver, "_mx_playwright_session", None)
        page = getattr(sess, "page", None) if sess is not None else None
        bounds = get_window_bounds(page) if page is not None else None
        if bounds:
            save_window_size(bounds.get("width", _DEFAULT_W), bounds.get("height", _DEFAULT_H))
            return
        size = driver.get_window_size()
        save_window_size(size.get("width", _DEFAULT_W), size.get("height", _DEFAULT_H))
    except Exception:
        pass


def patch_chrome_options_window_size() -> Any:
    """Legacy Selenium hook — для Playwright не используется."""
    return None


def restore_chrome_options_window_size(orig_add_argument: Any) -> None:
    if orig_add_argument is None:
        return
    try:
        import undetected_chromedriver as uc

        uc.ChromeOptions.add_argument = orig_add_argument
    except Exception:
        pass
