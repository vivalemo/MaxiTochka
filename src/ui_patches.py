"""Monkey-patches: только новый дизайн, логика как в оригинале."""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

from manager_guide import APP_NAME
from sessions_meta import sanitize_session_js
from theme import (
    CHECKER_LOG_STYLE,
    SECTION_LABEL_STYLE,
    STYLESHEET,
    TEXT,
    WINDOW_BTN_CLOSE_STYLE,
    WINDOW_BTN_MIN_STYLE,
)

_RECOLOR_MAP = (
    ("#40E0D0", "#6366f1"),
    ("#FF7F50", "#f43f5e"),
    ("#ADFF2F", "#22c55e"),
    ("#FFD700", "#f59e0b"),
    ("#FFFFFF", "#f1f5f9"),
    ("rgba(64, 224, 208, 0.4)", "rgba(99, 102, 241, 0.4)"),
    ("rgba(64,224,208,0.4)", "rgba(99, 102, 241, 0.4)"),
)


def _recolor(style: str) -> str:
    for old, new in _RECOLOR_MAP:
        style = style.replace(old, new)
    return style


def apply_theme(module: Any) -> None:
    module.VOID_STYLE = STYLESHEET
    try:
        from checker_panel import patch_checker_class

        patch_checker_class(module.DotLauncher)
    except Exception:
        pass
    _patch_dot_launcher(module)
    _patch_void_modal(module)
    _patch_toast(module)
    _patch_license_dialog(module)
    _patch_playwright_browser(module)


def _fix_readable_text(window, module) -> None:
    cont = window.findChild(module.QFrame, "MainContainer")
    if not cont:
        return

    for lbl in cont.findChildren(module.QLabel):
        if lbl.objectName() == "Header":
            continue
        sheet = lbl.styleSheet() or ""
        if "color:" not in sheet and "Color:" not in sheet:
            lbl.setStyleSheet(sheet + f" color: {TEXT}; background: transparent;")

    for btn in cont.findChildren(module.QPushButton):
        sheet = btn.styleSheet() or ""
        if btn.objectName() in ("NavBtn", "GhostBtn", "CyanBtn", ""):
            if "color:" not in sheet:
                base = TEXT
                if btn.objectName() == "NavBtn" and not btn.isChecked():
                    base = "rgba(241, 245, 249, 0.55)"
                btn.setStyleSheet(sheet + f" color: {base};")

    if hasattr(window, "p_input"):
        window.p_input.setStyleSheet(
            "color: #f1f5f9; background: rgba(255,255,255,0.06); "
            "border: 1px solid rgba(255,255,255,0.12); border-radius: 12px;"
        )


def _patch_dot_launcher(module: Any) -> None:
    DotLauncher = module.DotLauncher
    orig_init = DotLauncher.__init__
    orig_init_ui = DotLauncher.init_ui

    def __init__(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        self.setWindowTitle(APP_NAME)
        from window_chrome import apply_resizable_window

        apply_resizable_window(self, module)

    def init_ui(self):
        try:
            from modern_gui import build_modern_ui

            build_modern_ui(self, module)
            self._modern_gui_enabled = True
        except Exception:
            orig_init_ui(self)
            self._modern_gui_enabled = False
        if not getattr(self, "_modern_gui_enabled", False):
            self.setStyleSheet(STYLESHEET)
        from window_chrome import apply_resizable_layout

        apply_resizable_layout(self, module)

        for child in self.findChildren(module.QLabel):
            if child.objectName() == "Header":
                child.setText(APP_NAME)
                child.setStyleSheet(
                    f"font-size: 24px; font-weight: 800; letter-spacing: 1px; "
                    f"border: none; color: {TEXT}; background: transparent;"
                )

        if hasattr(self, "c_log"):
            self.c_log.setStyleSheet(CHECKER_LOG_STYLE)

        for lbl in self.findChildren(module.QLabel):
            t = lbl.text()
            if t.startswith("//"):
                lbl.setStyleSheet(SECTION_LABEL_STYLE)

        for btn in self.findChildren(module.QPushButton):
            txt = btn.text()
            if txt in ("─", "–", "-"):
                btn.setText("—")
                btn.setStyleSheet(WINDOW_BTN_MIN_STYLE)
                btn.setFixedSize(40, 40)
            elif txt in ("✕", "×", "x"):
                btn.setText("✕")
                btn.setStyleSheet(WINDOW_BTN_CLOSE_STYLE)
                btn.setFixedSize(40, 40)

        for btn_attr in ("btn_p", "btn_l"):
            btn = getattr(self, btn_attr, None)
            if btn:
                btn.setObjectName("NavBtn")
                btn.setCursor(module.Qt.CursorShape.PointingHandCursor)

        _fix_readable_text(self, module)
        from app_logger import get_logger

        log = get_logger("ui")
        _log_startup_environment(self, log)
        _patch_notify_logging(self, module, log)

        for mod_name, fn_name in (
            ("launch_panel", "install_launch_panel"),
            ("proxy_panel", "install_proxy_panel"),
            ("checker_panel", "install_checker_panel"),
            ("dashboard_panel", "install_dashboard"),
            ("automation_panel", "install_automation_panel"),
            ("crm_panel", "install_crm_panel"),
            ("automation_runner", "install_automation_handlers"),
            ("maxitochka_features", "install"),
        ):
            try:
                mod_obj = __import__(mod_name)
                getattr(mod_obj, fn_name)(self, module)
            except Exception:
                log.exception("Install %s.%s failed", mod_name, fn_name)

        def _deferred_first_render() -> None:
            for name in ("render_proxies", "render_sessions", "render_checker"):
                try:
                    getattr(self, name)()
                except Exception:
                    log.exception("Initial %s failed", name)

        module.QTimer.singleShot(0, _deferred_first_render)

    DotLauncher.__init__ = __init__
    DotLauncher.init_ui = init_ui


def _patch_void_modal(module: Any) -> None:
    orig = module.VoidModal.__init__

    def __init__(self, *args, **kwargs):
        orig(self, *args, **kwargs)
        self.setStyleSheet(STYLESHEET)

    module.VoidModal.__init__ = __init__


def _patch_toast(module: Any) -> None:
    from toast_ui import install_toast

    install_toast(module)


_ERR_TOAST_COLORS = frozenset({"#f43f5e", "#FF7F50", "#ff7f50"})


def _toast_is_real_error(msg: str, color: str) -> bool:
    """Не путать предупреждения и «Ошибок: 0» с настоящими сбоями."""
    if color in _ERR_TOAST_COLORS:
        return True
    low = msg.lower()
    if "не найден" in low or "errno" in low:
        return True
    if "traceback" in low or "exception" in low or "filenotfound" in low:
        return True
    if "ошибок: 0" in low or "ошибок:0" in low:
        return False
    if "ошибка" in low or "ошибки:" in low or "с ошибк" in low:
        return True
    if low.startswith("error") or " error:" in low:
        return True
    return False


def _log_toast_message(text: Any, color: Any) -> None:
    """Toast — в лог: ERROR только для реальных проблем, остальное INFO."""
    try:
        from app_logger import get_logger

        msg = str(text).strip()
        c = str(color).lower()
        log = get_logger("ui")
        if _toast_is_real_error(msg, c):
            log.error("Toast: %s", msg)
        else:
            log.info("Toast: %s", msg)
    except Exception:
        pass


def _patch_notify_logging(window: Any, module: Any, log) -> None:
    """Лог toast-ошибок — в patched show_toast (notify.connect(show_toast) в main.pyc)."""
    _ = window, module, log  # show_toast уже вызывает _log_toast_message


def _log_startup_environment(window: Any, log) -> None:
    """Записать в лог пути и наличие Chrome — для диагностики на чужих ПК."""
    try:
        log.info("---- старт диагностики окружения ----")
        try:
            from app_version import load_version_info, version_display

            vinfo = load_version_info()
            log.info(
                "Maxitochka %s build=%s file=%s",
                version_display(),
                vinfo.get("build", "—"),
                vinfo.get("_path", "—"),
            )
        except Exception:
            log.exception("version info failed")
        log.info("frozen=%s exe=%s", bool(getattr(sys, "frozen", False)), sys.executable)
        log.info("cwd=%s", os.getcwd())
        log.info("MAXITOCHKA_RUNTIME=%s", os.environ.get("MAXITOCHKA_RUNTIME", ""))
        log.info("_MEIPASS=%s", getattr(sys, "_MEIPASS", ""))

        for attr in ("session_dir", "profiles_dir", "db_path", "hist_path", "stats_path"):
            val = getattr(window, attr, None)
            if val is None:
                log.warning("attr %s = None", attr)
                continue
            exists = os.path.exists(val) if isinstance(val, str) else False
            log.info("attr %s=%s exists=%s", attr, val, exists)
            if isinstance(val, str) and val and not exists:
                if attr.endswith("_dir"):
                    try:
                        os.makedirs(val, exist_ok=True)
                        log.info("  -> создана папка %s", val)
                    except Exception:
                        log.exception("  -> не смог создать %s", val)

        runtime = os.environ.get("MAXITOCHKA_RUNTIME") or getattr(sys, "_MEIPASS", "")
        if runtime:
            cd = os.path.join(runtime, "chromedriver.exe")
            log.info("chromedriver.exe=%s exists=%s", cd, os.path.isfile(cd))
            try:
                from chromedriver_compat import (
                    ensure_chromedriver,
                    get_bundled_chromedriver_version,
                    get_chrome_major_version,
                )

                chrome_v = get_chrome_major_version()
                drv_v = get_bundled_chromedriver_version(cd)
                log.info("Chrome major=%s chromedriver major=%s", chrome_v, drv_v)
                if chrome_v and drv_v and chrome_v != drv_v:
                    log.warning(
                        "chromedriver mismatch: Chrome %s vs driver %s — updating",
                        chrome_v,
                        drv_v,
                    )
                from chromedriver_compat import prepare_runtime_async

                prepare_runtime_async(runtime)
            except Exception:
                log.exception("chromedriver ensure at startup failed")

        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        found = [p for p in chrome_paths if os.path.isfile(p)]
        if found:
            log.info("Chrome installed: %s", found[0])
        else:
            log.error("Chrome НЕ найден ни в одном из стандартных путей: %s", chrome_paths)
            if hasattr(window, "signals"):
                window.signals.notify.emit(
                    "Chrome не найден.\nУстановите Google Chrome.", "#f43f5e"
                )
        try:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            try:
                exe = pw.chromium.executable_path
                log.info("Playwright Chromium: %s exists=%s", exe, os.path.isfile(exe))
            finally:
                pw.stop()
        except Exception as ex:
            log.error("Playwright check failed: %s", ex)
            if hasattr(window, "signals"):
                window.signals.notify.emit(
                    "Playwright не установлен.\n"
                    "Выполните: pip install playwright && playwright install chrome",
                    "#f43f5e",
                )

        log.info("---- конец диагностики ----")
    except Exception:
        log.exception("startup diagnostics failed")


def _patch_playwright_browser(module: Any) -> None:
    """Роутер Selenium / Playwright (по умолчанию Selenium)."""
    from browser_launcher import patch_dot_launcher

    patch_dot_launcher(module.DotLauncher)


def _patch_license_dialog(module: Any) -> None:
    if not hasattr(module, "LicenseDialog"):
        return
    orig = module.LicenseDialog.__init__

    def __init__(self, *args, **kwargs):
        orig(self, *args, **kwargs)
        self.setStyleSheet(STYLESHEET)
        self.setWindowTitle(f"{APP_NAME} — активация")

    module.LicenseDialog.__init__ = __init__


def _patch_render_methods(DotLauncher: type, module: Any) -> None:
    for name in ("render_proxies", "render_checker"):
        fn = getattr(DotLauncher, name, None)
        if fn:
            setattr(DotLauncher, name, _wrap_recolor(fn, module))


def _walk_widgets(root):
    from PyQt6.QtWidgets import QWidget

    seen = set()
    stack = [root]
    while stack:
        w = stack.pop()
        wid = id(w)
        if wid in seen:
            continue
        seen.add(wid)
        yield w
        for child in w.children():
            if isinstance(child, QWidget):
                stack.append(child)


def _wrap_recolor(fn: Callable, module: Any) -> Callable:
    def wrapper(self, *args, **kwargs):
        result = fn(self, *args, **kwargs)
        for w in _walk_widgets(self):
            try:
                sheet = w.styleSheet()
                if sheet:
                    w.setStyleSheet(_recolor(sheet))
            except Exception:
                pass
        _fix_readable_text(self, module)
        return result

    return wrapper
