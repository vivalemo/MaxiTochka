#!/usr/bin/env python3
"""
Run Maxitochka: оригинальная логика DotLauncher + новый дизайн.
"""
from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
EXTRACTED = os.path.join(ROOT, "DotLauncher.exe_extracted")
MAIN_PYC = os.path.join(EXTRACTED, "main.pyc")
MODULE_NAME = "dotlauncher_main"
PYZ_EXTRACTED = os.path.join(EXTRACTED, "PYZ.pyz_extracted")

# PyInstaller: библиотеки в _internal; chromedriver — в DotLauncher.exe_extracted
_BUNDLE_ROOT = ""
_RUNTIME_ROOT = ""


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _app_root() -> str:
    if _frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return ROOT


def _venv_site_packages() -> str:
    return os.path.join(ROOT, ".venv", "Lib", "site-packages")


def _runtime_dir(app_root: str) -> str:
    return os.path.join(app_root, "DotLauncher.exe_extracted")


def _add_python_max_client_path() -> None:
    """Только python_max_client: весь PYZ в path ломает setuptools (jaraco)."""
    candidates: list[str] = []
    if _frozen() and _BUNDLE_ROOT:
        candidates.append(_BUNDLE_ROOT)
    candidates.append(PYZ_EXTRACTED)
    for base in candidates:
        pkg = os.path.join(base, "python_max_client")
        if not os.path.isdir(pkg):
            continue
        if base not in sys.path:
            sys.path.append(base)
        return


def setup_runtime() -> None:
    global EXTRACTED, MAIN_PYC, _BUNDLE_ROOT, _RUNTIME_ROOT  # noqa: PLW0603

    app_root = _app_root()
    EXTRACTED = _runtime_dir(app_root)
    MAIN_PYC = os.path.join(EXTRACTED, "main.pyc")

    if not os.path.isfile(MAIN_PYC):
        raise SystemExit(
            f"Not found: {MAIN_PYC}\n"
            "For dev: extract DotLauncher with pyinstxtractor.\n"
            "For .exe: run build.bat and keep DotLauncher.exe_extracted next to Maxitochka.exe."
        )

    os.environ["PATH"] = EXTRACTED + os.pathsep + os.environ.get("PATH", "")
    os.environ["MAXITOCHKA_APP_ROOT"] = app_root
    os.environ["MAXITOCHKA_RUNTIME"] = EXTRACTED
    os.chdir(EXTRACTED)

    _RUNTIME_ROOT = EXTRACTED

    if _frozen():
        _BUNDLE_ROOT = getattr(sys, "_MEIPASS", "") or ""
        src_dir = os.path.join(_BUNDLE_ROOT, "src") if _BUNDLE_ROOT else SRC
        sys.path[:0] = [
            p for p in (src_dir, _BUNDLE_ROOT) if p and p not in sys.path
        ]
        # Не трогать sys._MEIPASS — иначе PyInstaller не находит selenium и др.
        os.environ["MAXITOCHKA_RUNTIME"] = EXTRACTED
    else:
        site_pkgs = _venv_site_packages()
        if not os.path.isdir(site_pkgs):
            raise SystemExit(f"Run start.bat first (missing venv): {site_pkgs}")
        sys.path[:0] = [site_pkgs, SRC]
        for bad in ("", EXTRACTED):
            while bad in sys.path:
                sys.path.remove(bad)
        sys._MEIPASS = EXTRACTED  # noqa: SLF001

    _add_python_max_client_path()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            _ = pw.chromium.executable_path
    except Exception as ex:
        raise SystemExit(
            "Playwright не готов.\n"
            "Выполните: pip install playwright && playwright install chrome\n"
            f"Детали: {ex}"
        ) from ex

    try:
        from seleniumwire_patch import apply_seleniumwire_patch

        apply_seleniumwire_patch()
    except Exception:
        pass


def load_app_module():
    import setuptools  # noqa: F401

    try:
        import pkg_resources  # noqa: F401
    except ImportError:
        pass

    spec = importlib.util.spec_from_file_location(MODULE_NAME, MAIN_PYC)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load {MAIN_PYC}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)

    from ui_patches import apply_theme

    apply_theme(module)
    return module


def _install_excepthook() -> None:
    import traceback

    orig = sys.excepthook

    def _hook(exc_type, exc, tb) -> None:
        try:
            from app_logger import get_logger

            get_logger("maxitochka").critical(
                "Необработанное исключение:\n%s",
                "".join(traceback.format_exception(exc_type, exc, tb)),
            )
        except Exception:
            pass
        if orig is not None:
            orig(exc_type, exc, tb)

    sys.excepthook = _hook


def main() -> None:
    setup_runtime()

    try:
        from app_logger import setup_logging

        setup_logging()
        _install_excepthook()
    except Exception:
        pass

    mod = load_app_module()

    from PyQt6.QtWidgets import QApplication

    from manager_guide import APP_NAME

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    win = mod.DotLauncher()
    win.show()

    try:
        import proxy_backend

        app.aboutToQuit.connect(proxy_backend.stop_all)
    except Exception:
        pass

    try:
        from browser_launcher import shutdown_playwright

        app.aboutToQuit.connect(shutdown_playwright)
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
