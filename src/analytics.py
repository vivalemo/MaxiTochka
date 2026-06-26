"""Статистика для дашборда и учёт запусков."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import date, datetime, timedelta

from sessions_meta import format_seconds, load as load_meta, sync_from_disk

STATS_FILE = "maxitochka_stats.json"

_lock = threading.RLock()
_DEFAULT = {"daily": {}, "checker": {}, "launches_log": []}
_stats_cache: dict[str, tuple[float, dict]] = {}


def _stats_path(session_dir: str) -> str:
    base = os.path.dirname(os.path.abspath(session_dir))
    return os.path.join(base, STATS_FILE)


def load_stats(session_dir: str) -> dict:
    """Прочитать статистику. Кэш по mtime — без лишних чтений с диска."""
    path = _stats_path(session_dir)
    with _lock:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _stats_cache.pop(path, None)
            return {k: ({} if isinstance(v, dict) else list(v)) for k, v in _DEFAULT.items()}
        cached = _stats_cache.get(path)
        if cached and cached[0] == mtime:
            import copy

            return copy.deepcopy(cached[1])
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data.setdefault("daily", {})
        data.setdefault("checker", {})
        data.setdefault("launches_log", [])
        import copy

        _stats_cache[path] = (mtime, copy.deepcopy(data))
        return data


def save_stats(session_dir: str, data: dict) -> None:
    path = _stats_path(session_dir)
    folder = os.path.dirname(path) or "."
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return
    with _lock:
        tmp_path = ""
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=".stats_", suffix=".tmp", dir=folder
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            try:
                import copy

                _stats_cache[path] = (os.path.getmtime(path), copy.deepcopy(data))
            except OSError:
                _stats_cache.pop(path, None)
        except Exception:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def _today() -> str:
    return date.today().isoformat()


def _day_bucket(data: dict, day: str | None = None) -> dict:
    day = day or _today()
    daily = data.setdefault("daily", {})
    if day not in daily:
        daily[day] = {
            "launches": 0,
            "unique_tokens": [],
            "new_tokens": 0,
            "run_seconds": 0,
            "no_proxy_launches": 0,
        }
    return daily[day]


def record_launch(
    session_dir: str,
    fname: str,
    *,
    had_proxy: bool,
) -> None:
    data = load_stats(session_dir)
    bucket = _day_bucket(data)
    bucket["launches"] = int(bucket.get("launches", 0)) + 1
    uniq = list(bucket.get("unique_tokens") or [])
    if fname not in uniq:
        uniq.append(fname)
    bucket["unique_tokens"] = uniq
    if not had_proxy:
        bucket["no_proxy_launches"] = int(bucket.get("no_proxy_launches", 0)) + 1

    log = data.setdefault("launches_log", [])
    log.append({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "token": fname})
    data["launches_log"] = log[-500:]
    save_stats(session_dir, data)

    m = load_meta(session_dir)
    e = m.setdefault(fname, {})
    e["launch_count"] = int(e.get("launch_count", 0)) + 1
    e["last_launch_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    from sessions_meta import save

    save(session_dir, m)


def record_new_token(session_dir: str, fname: str) -> None:
    data = load_stats(session_dir)
    bucket = _day_bucket(data)
    bucket["new_tokens"] = int(bucket.get("new_tokens", 0)) + 1
    save_stats(session_dir, data)


def record_run_seconds(session_dir: str, seconds: float, day: str | None = None) -> None:
    if seconds <= 0:
        return
    data = load_stats(session_dir)
    bucket = _day_bucket(data, day)
    bucket["run_seconds"] = float(bucket.get("run_seconds", 0)) + seconds
    save_stats(session_dir, data)


def record_checker(session_dir: str, alive: int, dead: int) -> None:
    data = load_stats(session_dir)
    data["checker"] = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "alive": alive,
        "dead": dead,
    }
    save_stats(session_dir, data)


def _proxy_key(proxy_raw: str) -> str:
    return (proxy_raw or "").strip()


def top_countries(session_dir: str, limit: int = 10) -> list[tuple[str, int, float]]:
    """(country, launches, run_seconds)"""
    meta = load_meta(session_dir)
    agg: dict[str, dict] = {}
    for fname, entry in meta.items():
        if not fname.endswith(".txt"):
            continue
        country = str(entry.get("connection_country") or "").strip() or "—"
        if country not in agg:
            agg[country] = {"launches": 0, "seconds": 0.0}
        agg[country]["launches"] += int(entry.get("launch_count", 0))
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        agg[country]["seconds"] += sec
    rows = [(c, v["launches"], v["seconds"]) for c, v in agg.items()]
    rows.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return rows[:limit]


def top_proxies(session_dir: str, limit: int = 10) -> list[tuple[str, float]]:
    meta = load_meta(session_dir)
    agg: dict[str, float] = {}
    for entry in meta.values():
        proxy = _proxy_key(str(entry.get("connection_proxy", "")))
        if not proxy:
            continue
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        agg[proxy] = agg.get(proxy, 0.0) + sec
    rows = sorted(agg.items(), key=lambda x: x[1], reverse=True)
    return [(p, s) for p, s in rows[:limit]]


def country_changes_week(session_dir: str) -> list[tuple[str, list[str]]]:
    """Токены с 2+ странами за 7 дней."""
    meta = load_meta(session_dir)
    cutoff = datetime.now().astimezone() - timedelta(days=7)
    out: list[tuple[str, list[str]]] = []
    for fname, entry in meta.items():
        if not fname.endswith(".txt"):
            continue
        hist = entry.get("ip_history") or []
        countries: list[str] = []
        for h in hist:
            if not isinstance(h, dict):
                continue
            try:
                at = datetime.fromisoformat(str(h.get("at", "")))
            except Exception:
                continue
            if at < cutoff:
                continue
            c = str(h.get("country") or "").strip()
            if c and c not in countries:
                countries.append(c)
        cur = str(entry.get("connection_country") or "").strip()
        if cur and cur not in countries:
            countries.append(cur)
        if len(countries) >= 2:
            out.append((fname, countries))
    return out


def build_nav_kpi(
    session_dir: str,
    proxy_cache: dict,
    active_drivers: dict,
    checker_results: dict | None = None,
) -> dict:
    """Только цифры для шапки. Один проход по meta — без top/longest/geo."""
    meta = load_meta(session_dir)
    stats = load_stats(session_dir)
    bucket = stats.get("daily", {}).get(_today(), {})
    now = datetime.now().astimezone()

    def _extra(entry: dict) -> float:
        started = entry.get("run_started_at")
        if not started:
            return 0.0
        try:
            return (now - datetime.fromisoformat(str(started))).total_seconds()
        except Exception:
            return 0.0

    total_tokens = 0
    for fname, entry in meta.items():
        if fname.endswith(".txt"):
            total_tokens += 1

    today_seconds = float(bucket.get("run_seconds", 0))
    for fname in active_drivers:
        today_seconds += _extra(meta.get(fname, {}))

    proxy_ok = sum(1 for v in proxy_cache.values() if v.get("st") == "OK")
    checker = stats.get("checker", {})
    if checker_results:
        checker_alive = checker_results.get("alive", checker.get("alive", 0))
    else:
        checker_alive = checker.get("alive", 0)

    return {
        "total_tokens": total_tokens,
        "active_count": len(active_drivers),
        "time_today": format_seconds(today_seconds),
        "launches_today": int(bucket.get("launches", 0)),
        "checker_alive": checker_alive,
        "proxy_ok": proxy_ok,
        "proxy_total": len(proxy_cache),
    }


def build_dashboard(
    session_dir: str,
    proxy_cache: dict,
    active_drivers: dict,
    checker_results: dict | None = None,
) -> dict:
    meta = load_meta(session_dir)
    stats = load_stats(session_dir)
    today = _today()
    bucket = stats.get("daily", {}).get(today, {})

    total_tokens = 0
    if os.path.isdir(session_dir):
        try:
            total_tokens = sum(
                1 for f in os.listdir(session_dir) if f.endswith(".txt")
            )
        except OSError:
            total_tokens = 0

    active_list = []
    for fname in active_drivers:
        entry = meta.get(fname, {})
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        active_list.append({"name": fname, "runtime": format_seconds(sec)})

    # longest session all time
    longest_name = ""
    longest_sec = 0.0
    for fname, entry in meta.items():
        if not fname.endswith(".txt"):
            continue
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        if sec > longest_sec:
            longest_sec = sec
            longest_name = fname

    top_tokens = []
    ranked = []
    for fname, entry in meta.items():
        if not fname.endswith(".txt"):
            continue
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        ranked.append((fname, sec))
    ranked.sort(key=lambda x: x[1], reverse=True)
    for fname, sec in ranked[:10]:
        top_tokens.append({"name": fname, "time": format_seconds(sec)})

    proxy_ok = sum(1 for v in proxy_cache.values() if v.get("st") == "OK")
    proxy_total = len(proxy_cache)

    checker = stats.get("checker", {})
    if checker_results:
        checker_alive = checker_results.get("alive", checker.get("alive", 0))
        checker_dead = checker_results.get("dead", checker.get("dead", 0))
    else:
        checker_alive = checker.get("alive", 0)
        checker_dead = checker.get("dead", 0)

    today_seconds = float(bucket.get("run_seconds", 0))
    for fname in active_drivers:
        entry = meta.get(fname, {})
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                today_seconds += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass

    total_runtime_sec = 0.0
    for fname, entry in meta.items():
        if not fname.endswith(".txt"):
            continue
        sec = float(entry.get("run_seconds", 0))
        if entry.get("run_started_at"):
            try:
                dt = datetime.fromisoformat(str(entry["run_started_at"]))
                sec += (datetime.now().astimezone() - dt).total_seconds()
            except Exception:
                pass
        total_runtime_sec += sec

    return {
        "total_runtime": format_seconds(total_runtime_sec),
        "kpi": {
            "total_tokens": total_tokens,
            "active_count": len(active_drivers),
            "time_today": format_seconds(today_seconds),
            "launches_today": int(bucket.get("launches", 0)),
            "checker_alive": checker_alive,
            "proxy_ok": proxy_ok,
            "proxy_total": proxy_total,
        },
        "today": {
            "new_tokens": int(bucket.get("new_tokens", 0)),
            "unique_tokens": len(bucket.get("unique_tokens") or []),
            "no_proxy_launches": int(bucket.get("no_proxy_launches", 0)),
        },
        "longest": {
            "name": longest_name or "—",
            "time": format_seconds(longest_sec) if longest_sec else "—",
        },
        "active_list": active_list,
        "top_tokens": top_tokens,
        "top_countries": [
            {"country": c, "launches": n, "time": format_seconds(s)}
            for c, n, s in top_countries(session_dir)
        ],
        "top_proxies": [
            {"proxy": p[:48], "time": format_seconds(s)} for p, s in top_proxies(session_dir)
        ],
        "country_changes": [
            {"name": n, "countries": ", ".join(cs)} for n, cs in country_changes_week(session_dir)
        ],
    }
