"""Выбор движка браузера: Selenium (по умолчанию) или Playwright."""

from __future__ import annotations

from settings_store import load_settings

ENGINE_SELENIUM = "selenium"
ENGINE_PLAYWRIGHT = "playwright"
_DEFAULT = ENGINE_SELENIUM


def get_browser_engine() -> str:
    raw = str(load_settings().get("browser_engine") or _DEFAULT).strip().lower()
    if raw in (ENGINE_PLAYWRIGHT, "pw", "playwright"):
        return ENGINE_PLAYWRIGHT
    return ENGINE_SELENIUM


def use_playwright() -> bool:
    return get_browser_engine() == ENGINE_PLAYWRIGHT


def engine_label() -> str:
    return "Playwright" if use_playwright() else "Selenium"
