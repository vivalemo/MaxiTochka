"""Запуск MAX через Playwright (замена Selenium / undetected-chromedriver)."""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

from app_logger import get_logger
from browser_session import BrowserSession, PlaywrightDriverAdapter, as_driver
from browser_prefs import get_window_size
from browser_window import MAX_APP_URL, set_window_bounds
from session_token_parse import normalize_for_launch, wrap_session_js_for_inject

_log = get_logger("browser_launcher")

# Playwright sync API привязан к потоку — у каждого worker свой экземпляр.
_PW_THREADS: dict[int, Any] = {}
_PW_LOCK = threading.Lock()
_SESSIONS: dict[str, BrowserSession] = {}
_SESSIONS_LOCK = threading.Lock()

_CHROME_ARGS = (
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--disable-plugins",
    "--disable-default-apps",
    "--ignore-certificate-errors",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-hang-monitor",
    "--disable-domain-reliability",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-component-update",
    "--disable-ipc-flooding-protection",
    "--disable-renderer-backgrounding",
    "--disable-spell-checking",
    "--metrics-recording-only",
    "--renderer-process-limit=4",
    "--disk-cache-size=52428800",
    "--media-cache-size=52428800",
)

# CDN/static MAX (VK) + аватарки OneMe. Только i.oneme.ru — ws-api/api оставляем
# на прокси. Формат Chrome: «.domain» = домен и поддомены (не «*.domain»).
_BYPASS_CDN = (
    ".okcdn.ru,.vkuserphoto.ru,.vkuservideo.ru,.vkuseraudio.ru,"
    "st.max.ru,i.oneme.ru"
)
_BYPASS_MAX = f"<local>,.max.ru,{_BYPASS_CDN}"

_FINGERPRINT_INIT = """
(function() {
  function _ovr(obj, prop, val) {
    try {
      Object.defineProperty(obj, prop, {
        get: function() { return val; },
        configurable: true
      });
    } catch (e) {}
  }
  try { _ovr(navigator, 'webdriver', undefined); } catch (e) {}
  try { _ovr(navigator, 'languages', ['ru-RU', 'ru', 'en-US', 'en']); } catch (e) {}
  try { _ovr(navigator, 'deviceMemory', 8); } catch (e) {}
  try {
    window.chrome = {runtime:{}, loadTimes:function(){}, csi:function(){}, app:{}};
  } catch (e) {}
})();
"""


_SW_BACKEND_PORTS: dict[int, int] = {}
_SW_CAPTURE_INSTALLED = False


def _install_seleniumwire_port_capture() -> None:
    """Перехватить allocate_port в seleniumwire.backend.create по thread-id."""
    global _SW_CAPTURE_INSTALLED
    if _SW_CAPTURE_INSTALLED:
        return
    try:
        from seleniumwire import backend as bmod
    except Exception:
        return
    orig = bmod.create

    def create(addr: str = "127.0.0.1", port: int = 0, options=None):
        b = orig(addr=addr, port=port, options=options)
        try:
            tid = threading.get_ident()
            real_port = int(b.address()[1])
            _SW_BACKEND_PORTS[tid] = real_port
        except Exception:
            pass
        return b

    bmod.create = create
    _SW_CAPTURE_INSTALLED = True


def seleniumwire_port_of(driver: Any) -> int:
    """Локальный порт mitmproxy, который selenium-wire выдал данному драйверу."""
    tid = threading.get_ident()
    captured = _SW_BACKEND_PORTS.pop(tid, 0)
    if captured:
        return captured
    backend = getattr(driver, "backend", None)
    try:
        if backend is not None:
            addr = backend.address()
            if addr and len(addr) >= 2:
                return int(addr[1])
    except Exception:
        pass
    return 0


def _playwright():
    """Playwright для текущего потока (launch идёт из threading в main.pyc)."""
    tid = threading.get_ident()
    with _PW_LOCK:
        pw = _PW_THREADS.get(tid)
        if pw is None:
            from playwright.sync_api import sync_playwright

            pw = sync_playwright().start()
            _PW_THREADS[tid] = pw
            _log.info("Playwright started in thread %s", tid)
        return pw


def parse_playwright_proxy(raw: str) -> dict[str, str] | None:
    s = (raw or "").strip()
    if not s:
        return None
    if "://" in s:
        u = urlparse(s)
        scheme = (u.scheme or "http").lower()
        host = (u.hostname or "").strip()
        if not host:
            return None
        port = u.port or (1080 if "socks" in scheme else 8080)
        out: dict[str, str] = {"server": f"{scheme}://{host}:{port}"}
        if u.username:
            out["username"] = u.username
            out["password"] = u.password or ""
        return out
    parts = s.split(":")
    if len(parts) < 2:
        return None
    host = parts[0].strip()
    try:
        port = int(parts[1].strip())
    except ValueError:
        return None
    # Формат DotLauncher: host:port:user:pass — это HTTP-прокси (не SOCKS).
    scheme = "http"
    low = s.casefold()
    if low.startswith("socks") or "socks5" in low or "socks4" in low:
        scheme = "socks5"
    out = {"server": f"{scheme}://{host}:{port}"}
    if len(parts) >= 4:
        out["username"] = parts[2].strip()
        out["password"] = parts[3].strip()
    return out


def _proxy_bypass_mode() -> str:
    try:
        from settings_store import load_settings

        raw = load_settings().get("proxy_media_bypass", "max")
    except Exception:
        raw = "max"
    if raw in (False, 0, "0", "off", "false", "none", "no"):
        return "off"
    if raw in (True, 1, "1", "true", "yes", "max", "all"):
        return "max"
    if str(raw).strip().lower() == "cdn":
        return "cdn"
    return "max"


def _apply_proxy_media_bypass(proxy: dict[str, str]) -> dict[str, str]:
    """MAX/CDN/аватарки в обход прокси — иначе картинки и upload часто не работают через datacenter proxy."""
    mode = _proxy_bypass_mode()
    if mode == "off":
        return proxy
    try:
        from settings_store import load_settings

        extra = str(load_settings().get("proxy_bypass_extra") or "").strip()
    except Exception:
        extra = ""
    bypass = _BYPASS_MAX if mode == "max" else f"<local>,{_BYPASS_CDN}"
    if extra:
        bypass = f"{bypass},{extra}"
    out = dict(proxy)
    out["bypass"] = bypass
    return out


def _proxy_bypass_chrome_args(proxy: dict[str, str] | None) -> list[str]:
    """bypass ТОЛЬКО через флаг (запятые). Playwright-овский proxy.bypass через «;»
    в этом Chrome не срабатывает — поэтому в Playwright bypass не передаём."""
    if not proxy:
        return []
    bypass = str(proxy.get("bypass") or "").strip()
    if not bypass:
        return []
    return [f"--proxy-bypass-list={bypass}"]


def _prepare_browser_proxy(proxy_raw: str) -> tuple[dict[str, str] | None, int]:
    """Playwright: весь трафик через локальный selenium-wire (как Selenium).

    Datacenter-прокси напрямую ломает картинки/фото в MAX; mitmproxy из
    selenium-wire проксирует всё стабильно — тот же путь, что у рабочего Selenium.
    """
    p = (proxy_raw or "").strip()
    if not p:
        return None, 0

    try:
        import proxy_backend
    except Exception:
        _log.exception("proxy_backend недоступен")
        proxy = parse_playwright_proxy(p)
        return (_apply_proxy_media_bypass(proxy) if proxy else None), 0

    port = proxy_backend.allocate_relay_port()
    if not port:
        _log.error("не удалось выделить порт для selenium-wire relay")
        proxy = parse_playwright_proxy(p)
        return (_apply_proxy_media_bypass(proxy) if proxy else None), 0

    if not proxy_backend.start_backend(port, p):
        _log.error("не удалось поднять selenium-wire relay на %s", port)
        proxy = parse_playwright_proxy(p)
        return (_apply_proxy_media_bypass(proxy) if proxy else None), 0

    _log.info(
        "Playwright → selenium-wire relay http://127.0.0.1:%s upstream=%s",
        port,
        p[:60],
    )
    return {"server": f"http://127.0.0.1:{port}"}, port


def _is_local_relay_proxy(proxy: dict[str, str] | None) -> bool:
    if not proxy:
        return False
    server = (proxy.get("server") or "").lower()
    return "127.0.0.1" in server or "localhost" in server


def _proxy_timezone(proxy_raw: str) -> str:
    ep = parse_playwright_proxy(proxy_raw)
    host = ""
    if ep:
        u = urlparse(ep["server"])
        host = u.hostname or ""
    if not host:
        return "Europe/Moscow"
    try:
        r = requests.get(
            f"http://ip-api.com/json/{host}",
            params={"fields": "status,timezone"},
            timeout=8,
        )
        data = r.json()
        if data.get("status") == "success" and data.get("timezone"):
            return str(data["timezone"])
    except Exception:
        pass
    return "Europe/Moscow"


def _chrome_major() -> str:
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
        ):
            try:
                with winreg.OpenKey(hive, key) as reg:
                    ver, _ = winreg.QueryValueEx(reg, "version")
                m = re.search(r"(\d+)", str(ver))
                if m:
                    return m.group(1)
            except OSError:
                continue
    except Exception:
        pass
    return "131"


def _build_user_agent() -> str:
    major = _chrome_major()
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )


def _inject_timezone(page: Any, tz: str) -> None:
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setTimezoneOverride", {"timezoneId": tz})
    except Exception:
        _log.debug("timezone override failed", exc_info=True)


def _page_alive(page: Any) -> bool:
    try:
        return page is not None and not page.is_closed()
    except Exception:
        return False


_GOTO_RETRYABLE = (
    "err_tunnel",
    "err_aborted",
    "timeout",
    "timed out",
    "err_connection",
    "err_proxy",
    "err_network",
)

_UNREGISTER_SW_JS = """
async () => {
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const r of regs) await r.unregister();
    }
    if (window.caches) {
      const keys = await caches.keys();
      for (const k of keys) await caches.delete(k);
    }
  } catch (e) {}
}
"""

_MAX_UI_STATE_JS = """
() => {
  const t = (document.body && document.body.innerText) || '';
  if (t.includes('Обновление') && t.length < 120) return 'updating';
  if (t.length > 100) return 'ready';
  try {
    const raw = localStorage.getItem('__oneme_auth');
    if (raw && raw !== 'null') {
      const o = JSON.parse(raw);
      if (o && o.token) return 'auth';
    }
  } catch (e) {}
  return 'wait';
}
"""


def _navigate_to_max(page: Any, session_name: str) -> bool:
    url = "https://web.max.ru"
    for attempt in range(4):
        if not _page_alive(page):
            _log.error("страница закрыта до goto (%s), попытка %s", session_name, attempt + 1)
            return False
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            return True
        except Exception as ex:
            msg = str(ex).casefold()
            _log.warning(
                "goto %s failed (%s), attempt %s: %s",
                session_name,
                url,
                attempt + 1,
                ex,
            )
            if "closed" in msg:
                return False
            if attempt < 3 and any(x in msg for x in _GOTO_RETRYABLE):
                time.sleep(3.0)
                continue
            return False
    return False


def _clear_pwa_caches(page: Any) -> None:
    try:
        page.evaluate(_UNREGISTER_SW_JS)
    except Exception:
        _log.debug("unregister service worker failed", exc_info=True)


_MAX_AUTH_CHECK_JS = """
() => {
  try {
    const raw = localStorage.getItem('__oneme_auth');
    if (!raw || raw === 'null') return false;
    const o = JSON.parse(raw);
    return !!(o && o.token);
  } catch (e) { return false; }
}
"""


def _apply_session_token(page: Any, raw_js: str) -> None:
    """Вставка токена как в Selenium: clear + setItem + reload из .txt."""
    from session_token_parse import prepare_js_for_selenium

    body = prepare_js_for_selenium(raw_js)
    if not body.strip():
        return
    page.evaluate(wrap_session_js_for_inject(body))
    if "reload" in body.casefold():
        try:
            page.wait_for_load_state("domcontentloaded", timeout=90000)
        except Exception:
            _reload_after_token(page)
    else:
        _reload_after_token(page)


def _reload_after_token(page: Any) -> None:
    """Перезагрузить MAX после вставки токена; ERR_ABORTED — страница уже ушла в навигацию."""
    try:
        page.reload(wait_until="domcontentloaded", timeout=90000)
        return
    except Exception as ex:
        msg = str(ex).casefold()
        if not any(x in msg for x in ("err_aborted", "detached", "closed", "crashed")):
            raise
        _log.debug("reload after token: %s — ждём навигацию", ex)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception:
        page.goto("https://web.max.ru", wait_until="domcontentloaded", timeout=90000)


def _page_has_auth_token(page: Any) -> bool:
    try:
        return bool(page.evaluate(_MAX_AUTH_CHECK_JS))
    except Exception:
        return False


def _wait_for_max_ready(page: Any, session_name: str, timeout: float = 90.0) -> bool:
    """Дождаться интерфейса MAX (не экрана «Обновление…»)."""
    deadline = time.time() + timeout
    updating_since = 0.0
    recovered = False

    while time.time() < deadline:
        if not _page_alive(page):
            return False
        try:
            state = page.evaluate(_MAX_UI_STATE_JS)
        except Exception:
            time.sleep(0.5)
            continue

        if state == "ready":
            _log.info("MAX UI ready: %s", session_name)
            return True

        if state == "auth":
            try:
                n = page.evaluate("document.body?.innerText?.length || 0")
                if int(n) > 100:
                    _log.info("MAX UI ready (auth): %s", session_name)
                    return True
            except Exception:
                pass

        if state == "updating":
            if not updating_since:
                updating_since = time.time()
            elif not recovered and time.time() - updating_since > 20:
                _log.warning("MAX застрял на «Обновление» — сброс PWA: %s", session_name)
                try:
                    _clear_pwa_caches(page)
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                except Exception:
                    _log.debug("PWA recovery reload failed", exc_info=True)
                updating_since = 0.0
                recovered = True
        else:
            updating_since = 0.0

        time.sleep(1.0)

    _log.warning("таймаут ожидания UI MAX: %s", session_name)
    return _page_alive(page)


def _inject_user_agent(page: Any, ua: str) -> None:
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Network.setUserAgentOverride",
            {"userAgent": ua, "platform": "Win32"},
        )
    except Exception:
        _log.debug("UA override failed", exc_info=True)


def _stop_relay(relay_port: int) -> None:
    if not relay_port:
        return
    try:
        import proxy_backend

        proxy_backend.stop_backend(relay_port)
    except Exception:
        pass


def launch_session(
    *,
    profiles_dir: str,
    session_name: str,
    proxy_raw: str,
    js: str,
    cdp_port: int,
    init_scripts: list[str] | None = None,
    require_ready: bool = True,
) -> PlaywrightDriverAdapter | None:
    """Открыть persistent Chrome с токеном и прокси."""
    profile_dir = os.path.join(profiles_dir, session_name)
    os.makedirs(profile_dir, exist_ok=True)
    try:
        from browser_profile_prefs import ensure_profile_media_enabled

        ensure_profile_media_enabled(profile_dir)
    except Exception:
        _log.debug("ensure_profile_media_enabled failed", exc_info=True)

    w, h = get_window_size()
    proxy, relay_port = _prepare_browser_proxy(proxy_raw)
    tz = _proxy_timezone(proxy_raw)
    ua = _build_user_agent()

    args = list(_CHROME_ARGS)
    args.append(f"--app={MAX_APP_URL}")
    args.append(f"--window-size={w},{h}")
    if cdp_port:
        args.append(f"--remote-debugging-port={int(cdp_port)}")
    use_relay = _is_local_relay_proxy(proxy)
    if proxy and not use_relay:
        args.extend(_proxy_bypass_chrome_args(proxy))

    pw = _playwright()
    launch_kwargs: dict[str, Any] = {
        "user_data_dir": profile_dir,
        "channel": "chrome",
        "headless": False,
        "args": args,
        "no_viewport": True,
        "ignore_default_args": ["--enable-automation"],
        "ignore_https_errors": True,
        "locale": "ru-RU",
    }
    if proxy:
        launch_kwargs["proxy"] = dict(proxy)
        if use_relay:
            _log.info(
                "browser proxy: selenium-wire relay=%s upstream=%s",
                relay_port,
                str(proxy_raw or "")[:80],
            )
        else:
            mode = _proxy_bypass_mode()
            _log.info(
                "browser proxy: server=%s auth=%s relay=%s bypass_mode=%s bypass=%s",
                proxy.get("server"),
                bool(proxy.get("username")),
                relay_port,
                mode,
                (proxy.get("bypass") or "")[:160],
            )

    try:
        context = pw.chromium.launch_persistent_context(**launch_kwargs)
    except Exception as ex:
        _log.exception("Playwright launch failed: %s", session_name)
        _stop_relay(relay_port)
        if "socks5" in str(ex).lower():
            _log.error(
                "Для socks5 с логином нужен selenium-wire. "
                "Выполните: pip install selenium-wire"
            )
        return None

    page = context.pages[0] if context.pages else context.new_page()
    set_window_bounds(page, w, h)
    try:
        from browser_profile_prefs import (
            apply_network_media_cdp,
            attach_media_failure_logger,
        )

        apply_network_media_cdp(page)
        attach_media_failure_logger(page, session_name)
    except Exception:
        _log.debug("media CDP setup failed", exc_info=True)
    context.add_init_script(_FINGERPRINT_INIT)
    for extra in init_scripts or []:
        if extra and extra.strip():
            context.add_init_script(extra)
    token_js = (js or "").strip()

    _inject_user_agent(page, ua)
    _inject_timezone(page, tz)

    if not _navigate_to_max(page, session_name):
        _log.error("не удалось открыть web.max.ru для %s", session_name)
        try:
            context.close()
        except Exception:
            pass
        _stop_relay(relay_port)
        return None

    if token_js:
        try:
            _apply_session_token(page, token_js)
        except Exception:
            _log.warning("token inject failed for %s", session_name, exc_info=True)

    if not _wait_for_max_ready(page, session_name) and require_ready:
        _log.error("интерфейс MAX не загрузился: %s", session_name)
        try:
            context.close()
        except Exception:
            pass
        _stop_relay(relay_port)
        return None

    # SW активируется уже после загрузки — повторно включаем обход, чтобы
    # картинки/аватарки и отправка фото не ломались через несколько секунд.
    if _page_alive(page):
        try:
            from browser_profile_prefs import apply_network_media_cdp

            apply_network_media_cdp(page)
        except Exception:
            _log.debug("re-apply media CDP failed", exc_info=True)

    if not _page_alive(page):
        _log.error("браузер закрылся после запуска: %s", session_name)
        try:
            context.close()
        except Exception:
            pass
        _stop_relay(relay_port)
        return None

    session = BrowserSession(
        session_name=session_name,
        profile_dir=profile_dir,
        cdp_port=int(cdp_port or 0),
        proxy_raw=str(proxy_raw or ""),
        context=context,
        page=page,
        playwright=pw,
        owner_thread_id=threading.get_ident(),
    )
    session.relay_port = relay_port  # type: ignore[attr-defined]

    with _SESSIONS_LOCK:
        old = _SESSIONS.pop(session_name, None)
        if old and not old.closed:
            _close_session_inner(old)
        _SESSIONS[session_name] = session

    _log.info(
        "Playwright session started: %s cdp=%s relay=%s proxy=%s",
        session_name,
        cdp_port,
        relay_port,
        str(proxy_raw or "")[:80],
    )
    return as_driver(session)


def get_session(session_name: str) -> BrowserSession | None:
    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_name)


def _close_session_inner(session: BrowserSession) -> None:
    if session.closed:
        return
    session.closed = True
    clear_thread_adapters(session.session_name)
    relay = int(getattr(session, "relay_port", 0) or 0)
    try:
        session.context.close()
    except Exception:
        _log.debug("context.close failed", exc_info=True)
    if relay:
        try:
            import proxy_backend

            proxy_backend.stop_backend(relay)
        except Exception:
            pass


def close_session(session: BrowserSession | str | None) -> None:
    if session is None:
        return
    if isinstance(session, str):
        with _SESSIONS_LOCK:
            obj = _SESSIONS.pop(session, None)
        if obj:
            _close_session_inner(obj)
        return
    name = session.session_name
    with _SESSIONS_LOCK:
        _SESSIONS.pop(name, None)
    _close_session_inner(session)


_THREAD_ADAPTERS: dict[tuple[str, int], PlaywrightDriverAdapter] = {}
_ATTACH_LOCK = threading.Lock()


def resolve_driver(driver: PlaywrightDriverAdapter | None) -> PlaywrightDriverAdapter | None:
    """Playwright sync API — только в потоке-владельце; иначе CDP attach."""
    if driver is None:
        return None
    sess = getattr(driver, "_mx_playwright_session", None)
    if sess is None or sess.closed:
        return None
    owner = int(getattr(sess, "owner_thread_id", 0) or 0)
    tid = threading.get_ident()
    if owner and owner == tid:
        return driver
    name = str(sess.session_name or "")
    port = int(sess.cdp_port or 0)
    if not port:
        _log.warning("resolve_driver: нет CDP порта для %s", name)
        return driver
    key = (name, tid)
    with _ATTACH_LOCK:
        cached = _THREAD_ADAPTERS.get(key)
        if cached is not None:
            cs = getattr(cached, "_mx_playwright_session", None)
            if cs is not None and not cs.closed:
                try:
                    if not cs.page.is_closed():
                        return cached
                except Exception:
                    pass
            _THREAD_ADAPTERS.pop(key, None)
    attached = attach_over_cdp(port)
    if attached is None:
        _log.error("resolve_driver: CDP attach failed port=%s %s", port, name)
        return None
    attached_sess = attached._mx_playwright_session
    attached_sess.session_name = name
    attached_sess.owner_thread_id = tid
    attached_sess.cdp_port = port
    with _ATTACH_LOCK:
        _THREAD_ADAPTERS[key] = attached
    _log.debug("resolve_driver: CDP attach ok %s thread=%s", name, tid)
    return attached


def clear_thread_adapters(session_name: str = "") -> None:
    with _ATTACH_LOCK:
        if not session_name:
            _THREAD_ADAPTERS.clear()
            return
        for key in list(_THREAD_ADAPTERS):
            if key[0] == session_name:
                _THREAD_ADAPTERS.pop(key, None)


def _pick_max_context_page(browser: Any) -> tuple[Any, Any] | None:
    """Найти вкладку web.max.ru (не about:blank / service worker)."""
    best: tuple[Any, Any] | None = None
    for context in browser.contexts:
        for page in context.pages:
            try:
                if page.is_closed():
                    continue
                url = (page.url or "").lower()
                if "web.max.ru" in url:
                    return context, page
                if url and url not in ("about:blank", "") and best is None:
                    best = (context, page)
            except Exception:
                continue
    if best:
        return best
    if browser.contexts:
        ctx = browser.contexts[0]
        if ctx.pages:
            return ctx, ctx.pages[0]
        return ctx, ctx.new_page()
    return None


def attach_over_cdp(cdp_port: int) -> PlaywrightDriverAdapter | None:
    if not cdp_port:
        return None
    pw = _playwright()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{int(cdp_port)}")
        picked = _pick_max_context_page(browser)
        if not picked:
            return None
        context, page = picked
        session = BrowserSession(
            session_name="",
            profile_dir="",
            cdp_port=int(cdp_port),
            proxy_raw="",
            context=context,
            page=page,
            playwright=pw,
            owner_thread_id=threading.get_ident(),
        )
        return as_driver(session)
    except Exception:
        _log.exception("CDP attach failed on port %s", cdp_port)
        return None


def shutdown_playwright() -> None:
    with _SESSIONS_LOCK:
        for sess in list(_SESSIONS.values()):
            _close_session_inner(sess)
        _SESSIONS.clear()
    with _PW_LOCK:
        for tid, pw in list(_PW_THREADS.items()):
            try:
                pw.stop()
            except Exception:
                pass
            _PW_THREADS.pop(tid, None)
    try:
        import proxy_backend

        proxy_backend.stop_all()
    except Exception:
        pass
    _log.info("Playwright stopped")


def patch_dot_launcher(DotLauncher: type) -> None:
    """Роутер Selenium / Playwright по настройке browser_engine."""
    if getattr(DotLauncher, "_mx_browser_router_patched", False):
        return

    if not hasattr(DotLauncher, "_mx_selenium_antidetect"):
        DotLauncher._mx_selenium_antidetect = DotLauncher.antidetect_browser
    if not hasattr(DotLauncher, "_mx_selenium_stop_session"):
        DotLauncher._mx_selenium_stop_session = DotLauncher.stop_session
    if not hasattr(DotLauncher, "_mx_selenium_quit_driver"):
        DotLauncher._mx_selenium_quit_driver = DotLauncher._quit_driver

    def _launch_playwright(self, proxy_raw, js, session_name, *args, **kwargs):
        from session_registry import (
            patch_chrome_options_debug_port,
            restore_chrome_options_debug_port,
        )

        profiles_dir = getattr(self, "profiles_dir", "") or ""
        if not profiles_dir:
            _log.error("profiles_dir missing")
            return None

        for need_dir in ("profiles_dir", "session_dir"):
            p = getattr(self, need_dir, "")
            if p:
                try:
                    os.makedirs(p, exist_ok=True)
                except Exception:
                    _log.exception("Cannot mkdir %s", need_dir)

        port = 0
        try:
            from session_registry import allocate_debug_port

            port = allocate_debug_port()
            ports = getattr(self, "_mx_debug_ports", None) or {}
            ports[session_name] = port
            self._mx_debug_ports = ports
        except Exception:
            pass

        orig_port = patch_chrome_options_debug_port(port) if port else None
        try:
            driver = launch_session(
                profiles_dir=profiles_dir,
                session_name=session_name,
                proxy_raw=str(proxy_raw or ""),
                js=str(js or ""),
                cdp_port=port,
            )
        finally:
            if orig_port is not None:
                restore_chrome_options_debug_port(orig_port)

        if driver and hasattr(self, "active_drivers"):
            self.active_drivers[session_name] = driver
            if hasattr(self, "signals"):
                try:
                    self.signals.update_status.emit()
                except Exception:
                    pass
        return driver

    def _launch_selenium(self, proxy_raw, js, session_name, *args, **kwargs):
        from session_token_parse import prepare_js_for_selenium

        _install_seleniumwire_port_capture()
        return DotLauncher._mx_selenium_antidetect(
            self,
            proxy_raw,
            prepare_js_for_selenium(str(js or "")),
            session_name,
            *args,
            **kwargs,
        )

    def antidetect_browser(self, proxy_raw, js, session_name, *args, **kwargs):
        from browser_engine import engine_label, use_playwright

        _log.info(
            "browser engine: %s session=%s",
            engine_label(),
            session_name,
        )
        if use_playwright():
            return _launch_playwright(self, proxy_raw, js, session_name, *args, **kwargs)
        return _launch_selenium(self, proxy_raw, js, session_name, *args, **kwargs)

    def _quit_driver(self, driver) -> None:
        if driver is None:
            return
        sess = getattr(driver, "_mx_playwright_session", None)
        if sess is not None:
            close_session(sess)
            return
        try:
            DotLauncher._mx_selenium_quit_driver(self, driver)
        except Exception:
            try:
                driver.quit()
            except Exception:
                pass

    def stop_session(self, fname):
        drivers = getattr(self, "active_drivers", {}) or {}
        driver = drivers.pop(fname, None)
        if driver is not None:
            _quit_driver(self, driver)
        try:
            DotLauncher._mx_selenium_stop_session(self, fname)
        except Exception:
            pass

    DotLauncher.antidetect_browser = antidetect_browser
    DotLauncher._quit_driver = _quit_driver
    DotLauncher.stop_session = stop_session
    DotLauncher._mx_browser_router_patched = True  # noqa: SLF001
    DotLauncher._maxitochka_playwright_patched = True  # noqa: SLF001 — совместимость
    _log.info("DotLauncher browser router installed (default: Selenium)")
