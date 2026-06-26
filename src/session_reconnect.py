"""Переподключение к Chrome, оставшемуся открытым после перезапуска Maxitochka.

После старта программы:
1. Поднимаем mitmproxy seleniumwire на тех же портах с теми же upstream-прокси,
   что были до закрытия (Chrome продолжает их использовать → интернет возвращается).
2. Подключаемся к каждому Chrome-окну через CDP.
3. Актуализируем мета: время работы, IP/страну (через прокси), токен из localStorage.
4. Перерисовываем «Запуск» и «Чекер».
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import proxy_backend
from app_logger import get_logger
from session_registry import (
    find_fname_by_session_id,
    get_or_create_session_id,
    is_debug_port_alive,
    list_registered,
    parse_tab_title,
    port_for_registered,
    profile_looks_running,
    read_profile_debug_port,
    register_session,
    update_session_proxy,
)

_log = get_logger("reconnect")


def _chromedriver_path() -> str:
    runtime = os.environ.get("MAXITOCHKA_RUNTIME", "")
    if runtime:
        try:
            from chromedriver_compat import ensure_chromedriver

            p = ensure_chromedriver(runtime)
            if p:
                return p
        except Exception:
            pass
        p = os.path.join(runtime, "chromedriver.exe")
        if os.path.isfile(p):
            return p
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        p = os.path.join(meipass, "chromedriver.exe")
        if os.path.isfile(p):
            return p
    return "chromedriver.exe"


def attach_to_debug_port(port: int, module: Any) -> Any | None:
    if not is_debug_port_alive(port):
        return None
    try:
        from browser_launcher import attach_over_cdp

        driver = attach_over_cdp(port)
        if driver is not None:
            _ = driver.window_handles
        return driver
    except Exception:
        _log.exception("attach_to_debug_port(%s) failed", port)
        return None


def _abs_dir(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    return os.path.abspath(p)


def _fname_from_profile(session_dir: str, profile_name: str) -> str | None:
    if not session_dir or not profile_name:
        return None
    base = profile_name
    if base.lower().endswith(".txt"):
        base = base[:-4]
    candidates = (
        f"{profile_name}.txt"
        if not profile_name.lower().endswith(".txt")
        else profile_name,
        f"{base}.txt",
    )
    for fname in candidates:
        if os.path.isfile(os.path.join(session_dir, fname)):
            return fname
    try:
        import sessions_meta as meta

        for fname in meta.load(session_dir):
            if not fname.endswith(".txt"):
                continue
            if os.path.splitext(fname)[0] == base:
                return fname
    except Exception:
        pass
    if base.upper().startswith("MANUAL-"):
        return f"{base}.txt" if not base.lower().endswith(".txt") else base
    return None


def _resolve_fname(
    driver: Any, session_dir: str, profiles_dir: str, profile_name: str
) -> str | None:
    try:
        title = (driver.title or "").strip()
    except Exception:
        title = ""
    sid, _ = parse_tab_title(title)
    if sid and session_dir:
        found = find_fname_by_session_id(session_dir, sid)
        if found:
            return found

    found = _fname_from_profile(session_dir, profile_name)
    if found:
        return found

    fname = f"{profile_name}.txt"
    if session_dir and os.path.isfile(os.path.join(session_dir, fname)):
        return fname
    return None


def _read_localstorage_token(driver: Any) -> str:
    """Прочитать __oneme_auth.token из localStorage MAX через CDP."""
    js = (
        "try { const r = localStorage.getItem('__oneme_auth'); "
        "if (!r) return ''; const o = JSON.parse(r); return o && o.token || ''; }"
        " catch(e){ return ''; }"
    )
    try:
        return str(driver.execute_script(f"return (function(){{{js}}})();") or "").strip()
    except Exception:
        return ""


def _refresh_session_meta(window: Any, fname: str, driver: Any, proxy_raw: str) -> None:
    """После переподключения — освежить IP, токен и счётчик времени."""
    sd = getattr(window, "session_dir", "") or ""
    if not sd:
        return
    try:
        import sessions_meta as meta
    except Exception:
        return

    try:
        if (proxy_raw or "").strip():
            meta.set_connection_proxy(sd, fname, proxy_raw)
    except Exception:
        _log.exception("set_connection_proxy на reconnect: %s", fname)

    try:
        meta.start_run(sd, fname)
    except Exception:
        pass

    try:
        token = _read_localstorage_token(driver)
        if token:
            data = meta.load(sd)
            entry = data.get(fname)
            if isinstance(entry, dict):
                if entry.get("live_token") != token:
                    entry["live_token"] = token
                    entry["live_token_at"] = meta._now_iso()
                    meta.save(sd, data)
    except Exception:
        _log.debug("refresh live_token failed: %s", fname, exc_info=True)


def _after_attach(
    window: Any, module: Any, fname: str, driver: Any, proxy_raw: str
) -> None:
    import browser_prefs

    sd = getattr(window, "session_dir", "")
    applied = getattr(window, "_browser_prefs_applied", set())
    if isinstance(applied, set):
        applied.discard(fname)
    window._browser_prefs_applied = applied
    try:
        browser_prefs.apply_browser_prefs(driver, sd, fname)
    except Exception:
        pass
    try:
        import launch_panel as lp

        lp._begin_session_watch(window, fname, proxy_raw or None)
    except Exception:
        _log.exception("begin_session_watch on reconnect: %s", fname)

    _refresh_session_meta(window, fname, driver, proxy_raw or "")


def _restore_proxy_for(rec: dict, session_dir: str, fname: str) -> tuple[int, str]:
    """Поднять mitmproxy на сохранённом порту с сохранённым upstream.
    Возвращает (proxy_port, proxy_raw) для последующей записи в registry.
    Fallback: если в реестре нет proxy_raw, берём connection_proxy из meta.
    """
    proxy_raw = str(rec.get("proxy_raw") or "")
    proxy_port = int(rec.get("proxy_port") or 0)

    if not proxy_raw and session_dir and fname:
        try:
            import sessions_meta as meta

            entry = meta.load(session_dir).get(fname, {})
            if isinstance(entry, dict):
                proxy_raw = str(entry.get("connection_proxy") or "")
        except Exception:
            proxy_raw = ""

    if proxy_port and proxy_raw:
        proxy_backend.start_backend(proxy_port, proxy_raw)
    elif proxy_raw and not proxy_port:
        _log.warning(
            "reconnect: для %s есть upstream, но порт mitmproxy неизвестен — интернет в окне не восстановится. Перезапустите токен.",
            fname,
        )
    return proxy_port, proxy_raw


def reconnect_orphan_browsers(window: Any, module: Any) -> int:
    profiles_dir = _abs_dir(getattr(window, "profiles_dir", "") or "")
    session_dir = _abs_dir(getattr(window, "session_dir", "") or "")
    if not profiles_dir or not os.path.isdir(profiles_dir):
        _log.warning(
            "reconnect skip: profiles_dir missing (%r)",
            getattr(window, "profiles_dir", ""),
        )
        return 0

    active: dict = getattr(window, "active_drivers", None)
    if active is None:
        window.active_drivers = {}
        active = window.active_drivers

    reconnected = 0
    live_seen = 0
    used_ports: set[int] = set()
    used_proxy_ports: set[int] = set()
    registered = list_registered()
    _log.info(
        "reconnect: registry=%s profiles_dir=%s session_dir=%s",
        len(registered),
        profiles_dir,
        session_dir,
    )

    for fname, rec in registered.items():
        if active.get(fname):
            continue
        cdp_port = port_for_registered(rec)
        if not cdp_port or cdp_port in used_ports:
            continue
        proxy_port, proxy_raw = _restore_proxy_for(rec, session_dir, fname)
        if proxy_port:
            used_proxy_ports.add(proxy_port)

        if not is_debug_port_alive(cdp_port):
            _log.debug("registry CDP-port %s dead for %s", cdp_port, fname)
            continue

        live_seen += 1
        # Дать Chrome секунду «увидеть» поднятый mitmproxy
        if proxy_port:
            time.sleep(0.4)

        driver = attach_to_debug_port(cdp_port, module)
        if not driver:
            continue

        used_ports.add(cdp_port)
        active[fname] = driver
        reconnected += 1
        _after_attach(window, module, fname, driver, proxy_raw)
        _log.info(
            "reconnected via registry: %s cdp=%s sw=%s",
            fname,
            cdp_port,
            proxy_port,
        )

    stale_profiles: list[str] = []
    for profile_name in os.listdir(profiles_dir):
        prof_path = os.path.join(profiles_dir, profile_name)
        if not os.path.isdir(prof_path):
            continue
        if not profile_looks_running(profiles_dir, profile_name):
            continue
        cdp_port = read_profile_debug_port(profiles_dir, profile_name)
        if not cdp_port:
            _log.debug(
                "profile %s: DevToolsActivePort отсутствует/неверный — Chrome мёртв?",
                profile_name,
            )
            stale_profiles.append(profile_name)
            continue
        if cdp_port in used_ports:
            continue
        if not is_debug_port_alive(cdp_port):
            _log.debug(
                "profile %s: порт %s в DevToolsActivePort не отвечает — Chrome закрыт",
                profile_name,
                cdp_port,
            )
            stale_profiles.append(profile_name)
            continue

        live_seen += 1

        # Может быть, профиль уже был в registry? (попробуем восстановить прокси)
        rec = registered.get(f"{profile_name}.txt") or {}
        guess_fname = f"{profile_name}.txt"
        proxy_port, proxy_raw = _restore_proxy_for(rec, session_dir, guess_fname)
        if proxy_port:
            used_proxy_ports.add(proxy_port)

        driver = attach_to_debug_port(cdp_port, module)
        if not driver:
            _log.warning(
                "profile %s: cdp=%s — attach_to_debug_port вернул None",
                profile_name,
                cdp_port,
            )
            continue
        fname = _resolve_fname(driver, session_dir, profiles_dir, profile_name)
        if not fname:
            _log.warning(
                "reconnect: chrome on port %s profile %s — нет совпадения с .txt",
                cdp_port,
                profile_name,
            )
            try:
                driver.quit()
            except Exception:
                pass
            continue
        if active.get(fname):
            try:
                driver.quit()
            except Exception:
                pass
            continue
        used_ports.add(cdp_port)

        sid = get_or_create_session_id(session_dir, fname)
        register_session(
            fname,
            port=cdp_port,
            session_id=sid,
            profile_dir=prof_path,
            proxy_raw=proxy_raw,
            proxy_port=proxy_port,
        )

        active[fname] = driver
        reconnected += 1
        _after_attach(window, module, fname, driver, proxy_raw)
        _log.info("reconnected via profile: %s cdp=%s sw=%s", fname, cdp_port, proxy_port)

    try:
        window._reconnect_live_candidates = int(live_seen)
    except Exception:
        pass

    if stale_profiles and live_seen:
        _log.info(
            "reconnect: пропущено мёртвых профилей=%s",
            len(stale_profiles),
        )
    elif stale_profiles:
        _log.info(
            "reconnect: все профили Chrome (%s) закрыты — нечего подключать",
            len(stale_profiles),
        )

    if reconnected:
        try:
            if session_dir:
                import sessions_meta as meta

                meta.sync_run_state(session_dir, set(active.keys()))
        except Exception:
            pass
    else:
        running = sum(
            1
            for name in os.listdir(profiles_dir)
            if profile_looks_running(profiles_dir, name)
        )
        if (running or registered) and live_seen:
            _log.warning(
                "reconnect: 0 attached (registry=%s running_profiles=%s)",
                len(registered),
                running,
            )

    return reconnected
