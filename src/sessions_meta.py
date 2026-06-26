"""Метаданные сессий: комментарий менеджера, время, IP/страна, история."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime
from urllib.parse import urlparse

META_FILENAME = "sessions_meta.json"

_lock = threading.RLock()
_cache: dict[str, tuple[float, dict]] = {}
_GEO_SEM = threading.Semaphore(2)
_GEO_INFLIGHT: set[tuple[str, str]] = set()


from session_token_parse import (
    strip_session_preamble,
    strip_session_reload,
    strip_storage_clear,
)


def sanitize_session_js(raw: str) -> str:
    """Убрать PASSWORD / 2FA, reload и storage.clear — ломают запуск."""
    return strip_storage_clear(strip_session_reload(strip_session_preamble(raw)))


def _path(session_dir: str) -> str:
    return os.path.join(session_dir, META_FILENAME)


def load(session_dir: str) -> dict:
    """Прочитать meta. Кэш по mtime — без лишних чтений с диска."""
    if not session_dir:
        return {}
    p = _path(session_dir)
    with _lock:
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            _cache.pop(p, None)
            return {}
        cached = _cache.get(p)
        if cached and cached[0] == mtime:
            return copy.deepcopy(cached[1])
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        _cache[p] = (mtime, copy.deepcopy(data))
        return copy.deepcopy(data)


def save(session_dir: str, data: dict) -> None:
    """Атомарная запись через tempfile + replace."""
    if not session_dir:
        return
    p = _path(session_dir)
    try:
        os.makedirs(session_dir, exist_ok=True)
    except OSError:
        return
    with _lock:
        tmp_path = ""
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=".meta_", suffix=".tmp", dir=session_dir
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, p)
            try:
                _cache[p] = (os.path.getmtime(p), copy.deepcopy(data))
            except OSError:
                _cache.pop(p, None)
        except Exception:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _format_display(iso_or_mtime: str | float) -> str:
    try:
        if isinstance(iso_or_mtime, (int, float)):
            dt = datetime.fromtimestamp(iso_or_mtime)
        else:
            dt = datetime.fromisoformat(str(iso_or_mtime))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def sync_from_disk(session_dir: str) -> None:
    """Добавить записи для .txt без метаданных. Вызывать только на ререндер."""
    if not session_dir or not os.path.isdir(session_dir):
        return
    try:
        from tokenbase import list_gui_files

        names = list_gui_files(session_dir)
    except OSError:
        return
    data = load(session_dir)
    changed = False
    for name in names:
        if name in data:
            continue
        path = os.path.join(session_dir, name.replace("/", os.sep))
        if not os.path.isfile(path):
            continue
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        data[name] = {
            "comment": "",
            "added_at": datetime.fromtimestamp(mt).isoformat(timespec="seconds"),
            "run_seconds": 0,
        }
        changed = True
    if changed:
        save(session_dir, data)


def touch_new(session_dir: str, fname: str) -> None:
    data = load(session_dir)
    if fname not in data:
        data[fname] = {"comment": "", "added_at": _now_iso(), "run_seconds": 0}
        save(session_dir, data)


def _entry(data: dict, fname: str) -> dict:
    return data.setdefault(
        fname,
        {"comment": "", "added_at": _now_iso(), "run_seconds": 0},
    )


def format_seconds(seconds: float) -> str:
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec} сек"
    minutes, s = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes} мин" + (f" {s} сек" if s else "")
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes} мин"


def _total_run_seconds(entry: dict) -> float:
    total = float(entry.get("run_seconds") or 0)
    started = entry.get("run_started_at")
    if started:
        try:
            dt = datetime.fromisoformat(str(started))
            total += (datetime.now().astimezone() - dt).total_seconds()
        except Exception:
            pass
    return max(0.0, total)


def start_run(session_dir: str, fname: str) -> None:
    data = load(session_dir)
    entry = _entry(data, fname)
    if not entry.get("run_started_at"):
        entry["run_started_at"] = _now_iso()
        save(session_dir, data)


def _record_stopped(entry: dict) -> None:
    """Зафиксировать момент остановки сессии."""
    entry["stopped_at"] = _now_iso()


def stop_run(session_dir: str, fname: str) -> None:
    data = load(session_dir)
    entry = data.get(fname)
    if not entry:
        return
    started = entry.get("run_started_at")
    if started:
        try:
            dt = datetime.fromisoformat(str(started))
            entry["run_seconds"] = float(entry.get("run_seconds") or 0) + (
                datetime.now().astimezone() - dt
            ).total_seconds()
        except Exception:
            pass
        entry.pop("run_started_at", None)
    _record_stopped(entry)
    save(session_dir, data)


def sync_run_state(session_dir: str, active_names: set[str]) -> None:
    """Синхронизировать таймер с active_drivers."""
    if not session_dir:
        return
    data = load(session_dir)
    changed = False
    for fname, entry in list(data.items()):
        if not fname.endswith(".txt"):
            continue
        started = bool(entry.get("run_started_at"))
        active = fname in active_names
        if started and not active:
            started_at = entry.get("run_started_at")
            if started_at:
                try:
                    dt = datetime.fromisoformat(str(started_at))
                    entry["run_seconds"] = float(entry.get("run_seconds") or 0) + (
                        datetime.now().astimezone() - dt
                    ).total_seconds()
                except Exception:
                    pass
            entry.pop("run_started_at", None)
            _record_stopped(entry)
            changed = True
        elif active and not started:
            entry["run_started_at"] = _now_iso()
            changed = True
    if changed:
        save(session_dir, data)


def get_entry(session_dir: str, fname: str) -> dict:
    return load(session_dir).get(fname, {})


def get_runtime_display(session_dir: str, fname: str, is_active: bool) -> str:
    entry = load(session_dir).get(fname, {})
    total = _total_run_seconds(entry)
    if is_active:
        return format_seconds(total) + " ▶"
    if total > 0:
        return format_seconds(total)
    return "—"


def get_stopped_display(session_dir: str, fname: str, is_active: bool = False) -> str:
    """Время последней остановки (для вкладок Запуск и Чекер)."""
    if is_active:
        return "—"
    entry = load(session_dir).get(fname, {})
    if not isinstance(entry, dict):
        return "—"
    stopped = entry.get("stopped_at")
    if not stopped:
        return "—"
    return _format_display(stopped)


def set_comment(session_dir: str, fname: str, comment: str) -> None:
    data = load(session_dir)
    entry = _entry(data, fname)
    if entry.get("comment") == comment:
        return
    entry["comment"] = comment
    save(session_dir, data)


def get_comment(session_dir: str, fname: str) -> str:
    return str(load(session_dir).get(fname, {}).get("comment", ""))


def get_last_launch_display(session_dir: str, fname: str) -> str:
    """Время последнего запуска токена (last_launch_at)."""
    entry = load(session_dir).get(fname, {})
    if not isinstance(entry, dict):
        return "—"
    last = entry.get("last_launch_at")
    if not last:
        return "—"
    return _format_display(last)


def get_added_display(session_dir: str, fname: str) -> str:
    entry = load(session_dir).get(fname, {})
    if entry.get("added_at"):
        return _format_display(entry["added_at"])
    path = os.path.join(session_dir, fname)
    if os.path.isfile(path):
        try:
            return _format_display(os.path.getmtime(path))
        except OSError:
            pass
    return "—"


def remove(session_dir: str, fname: str) -> None:
    data = load(session_dir)
    if fname in data:
        del data[fname]
        save(session_dir, data)


def _parse_proxy_host(proxy_raw: str) -> str:
    if not proxy_raw:
        return ""
    s = proxy_raw.strip()
    if "://" in s:
        try:
            return (urlparse(s).hostname or "").strip()
        except Exception:
            pass
    parts = s.split(":")
    if len(parts) >= 2 and parts[0]:
        return parts[0].strip()
    return s


def set_connection_proxy(session_dir: str, fname: str, proxy_raw: str | None) -> None:
    raw = (proxy_raw or "").strip()
    data = load(session_dir)
    entry = _entry(data, fname)
    prev = str(entry.get("connection_proxy") or "")
    entry["connection_proxy"] = raw
    if raw != prev:
        entry.pop("connection_ip", None)
        entry.pop("connection_country", None)
    save(session_dir, data)
    if not raw or raw == prev:
        return
    key = (session_dir, fname)
    with _lock:
        if key in _GEO_INFLIGHT:
            return
        _GEO_INFLIGHT.add(key)
    threading.Thread(
        target=_resolve_connection_geo_safe,
        args=(session_dir, fname, raw),
        daemon=True,
    ).start()


def _resolve_connection_geo_safe(session_dir: str, fname: str, proxy_raw: str) -> None:
    try:
        with _GEO_SEM:
            _resolve_connection_geo(session_dir, fname, proxy_raw)
    finally:
        with _lock:
            _GEO_INFLIGHT.discard((session_dir, fname))


def _resolve_connection_geo(session_dir: str, fname: str, proxy_raw: str) -> None:
    host = _parse_proxy_host(proxy_raw)
    ip, country = "—", "—"
    if not host:
        _save_connection(session_dir, fname, ip, country)
        return
    try:
        import requests

        r = requests.get(
            f"http://ip-api.com/json/{host}",
            params={"fields": "status,query,country"},
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if data.get("status") == "success":
                ip = str(data.get("query") or host)
                country = str(data.get("country") or "—")
            else:
                ip = host
    except Exception:
        ip = host
    _save_connection(session_dir, fname, ip, country)


def _save_connection(session_dir: str, fname: str, ip: str, country: str) -> None:
    data = load(session_dir)
    entry = data.get(fname)
    if not entry:
        return
    prev_ip = str(entry.get("connection_ip") or "").strip()
    entry["connection_ip"] = ip
    entry["connection_country"] = country
    if ip and ip != "—" and ip != prev_ip:
        hist = list(entry.get("ip_history") or [])
        hist.append(
            {
                "at": _now_iso(),
                "ip": ip,
                "country": country,
                "proxy": str(entry.get("connection_proxy") or ""),
            }
        )
        entry["ip_history"] = hist[-30:]
    save(session_dir, data)


def get_ip_history_display(session_dir: str, fname: str) -> str:
    entry = load(session_dir).get(fname, {})
    hist = entry.get("ip_history") or []
    if not hist:
        ip = str(entry.get("connection_ip") or "").strip()
        return ip or "—"
    parts: list[str] = []
    for h in hist[-5:]:
        if isinstance(h, dict):
            parts.append(str(h.get("ip", "?")))
    cur = str(entry.get("connection_ip") or "").strip()
    if cur and (not parts or parts[-1] != cur):
        parts.append(cur)
    return " → ".join(parts) if parts else "—"


def get_connection_display(session_dir: str, fname: str) -> str:
    entry = load(session_dir).get(fname, {})
    ip = str(entry.get("connection_ip") or "").strip()
    country = str(entry.get("connection_country") or "").strip()
    if ip and country and country != "—":
        return f"{ip} · {country}"
    if ip:
        return ip
    proxy = str(entry.get("connection_proxy") or "").strip()
    if proxy:
        host = _parse_proxy_host(proxy)
        return host or "…"
    return "—"


_LOGGED_OUT_JS = """
try {
  const raw = localStorage.getItem('__oneme_auth');
  if (!raw || raw === 'null') return true;
  const o = JSON.parse(raw);
  return !o || !o.token;
} catch (e) { return true; }
"""


def is_max_logged_out(driver) -> bool | None:
    """True = нет токена; None = не удалось проверить."""
    try:
        return bool(driver.execute_script(_LOGGED_OUT_JS))
    except Exception:
        return None


def is_max_landing_url(url: str) -> bool:
    if not url:
        return False
    u = url.strip().split("?")[0].split("#")[0].rstrip("/").lower()
    return u in ("https://web.max.ru", "http://web.max.ru")
