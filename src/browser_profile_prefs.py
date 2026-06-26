"""Настройки Chrome-профиля: картинки, медиа, обход service worker."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app_logger import get_logger

_log = get_logger("browser_profile")

# 1 = разрешено, 2 = заблокировано (Chrome content settings)
_ALLOW = 1


def ensure_profile_media_enabled(profile_dir: str) -> None:
    """
    Гарантировать, что в профиле не отключены картинки и загрузки.
    Вызывать до старта Chrome (профиль не должен быть занят).
    """
    if not profile_dir:
        return
    default_dir = os.path.join(profile_dir, "Default")
    os.makedirs(default_dir, exist_ok=True)
    prefs_path = os.path.join(default_dir, "Preferences")

    data: dict = {}
    if os.path.isfile(prefs_path):
        try:
            with open(prefs_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            _log.debug("read Preferences failed: %s", prefs_path, exc_info=True)

    profile = data.setdefault("profile", {})
    dcv = profile.setdefault("default_content_setting_values", {})
    for key in ("images", "automatic_downloads", "plugins", "media_stream"):
        dcv[key] = _ALLOW

    mdc = profile.setdefault("managed_default_content_settings", {})
    mdc["images"] = _ALLOW

    # Снять точечные блокировки картинок по сайтам.
    cs = profile.setdefault("content_settings", {})
    if not isinstance(cs, dict):
        cs = {}
        profile["content_settings"] = cs
    exc = cs.get("exceptions")
    if isinstance(exc, dict):
        for key in ("images", "automatic_downloads", "plugins"):
            if key in exc and isinstance(exc[key], dict) and exc[key]:
                exc[key] = {}
                _log.info("profile %s: cleared %s blocks", profile_dir, key)

    # Экономия трафика / lite mode иногда ломает медиа в PWA.
    net = data.get("net")
    if isinstance(net, dict) and net.get("network_prediction_options") == 2:
        net["network_prediction_options"] = 0
    dr = profile.get("data_reduction")
    if isinstance(dr, dict) and dr.get("enabled"):
        dr["enabled"] = False

    try:
        fd, tmp = tempfile.mkstemp(
            prefix=".prefs_", suffix=".tmp", dir=default_dir
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, prefs_path)
    except Exception:
        _log.exception("write Preferences failed: %s", prefs_path)


def apply_network_media_cdp(page: Any) -> Any:
    """CDP: ничего не блокировать на уровне сети. Service worker НЕ трогаем.

    Важно: в MAX именно service worker подгружает медиа (аватарки/фото
    скачиваются и превращаются в blob:). Если SW отключить/обойти —
    картинки ломаются после навигации, а фото не отправляется. Поэтому
    мы только снимаем возможные блокировки URL и НЕ включаем
    setBypassServiceWorker.
    """
    if page is None:
        return None
    cdp = getattr(page, "_mx_media_cdp", None)
    if cdp is None:
        try:
            cdp = page.context.new_cdp_session(page)
        except Exception:
            return None
        try:
            page._mx_media_cdp = cdp  # держим ссылку живой
        except Exception:
            pass
    for method, params in (
        ("Network.enable", {}),
        ("Network.setBlockedURLs", {"urls": []}),
    ):
        try:
            cdp.send(method, params)
        except Exception:
            _log.debug("CDP %s failed", method, exc_info=True)
    return cdp


_MEDIA_HINTS = ("oneme.ru", "okcdn.ru", "vkuser", "st.max.ru", "max.ru")


def attach_media_failure_logger(page: Any, session_name: str, *, cap: int = 40) -> None:
    """Логировать упавшие запросы картинок/медиа — чтобы видеть, какой домен блокируется."""
    if page is None:
        return
    state = {"n": 0}

    def _is_media(req: Any) -> bool:
        try:
            if req.resource_type in ("image", "media", "font"):
                return True
            url = (req.url or "").lower()
            return any(h in url for h in _MEDIA_HINTS)
        except Exception:
            return False

    def _on_failed(req: Any) -> None:
        if state["n"] >= cap or not _is_media(req):
            return
        state["n"] += 1
        try:
            _log.warning(
                "media FAIL [%s] %s :: %s",
                session_name,
                (req.url or "")[:140],
                req.failure,
            )
        except Exception:
            pass

    def _on_response(resp: Any) -> None:
        if state["n"] >= cap:
            return
        try:
            if resp.status >= 400 and _is_media(resp.request):
                state["n"] += 1
                _log.warning(
                    "media HTTP %s [%s] %s",
                    resp.status,
                    session_name,
                    (resp.url or "")[:140],
                )
        except Exception:
            pass

    try:
        page.on("requestfailed", _on_failed)
        page.on("response", _on_response)
    except Exception:
        _log.debug("attach media logger failed", exc_info=True)
