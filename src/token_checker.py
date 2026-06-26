"""Проверка токенов MAX (как чекер в основной программе)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import requests

from session_token_parse import normalize_session_token
from tokenbase import (
    ALIVE_SUBDIR,
    alive_dir,
    default_dir as default_tokenbase_dir,
    list_txt_files,
    token_path,
)

# Обратная совместимость
normalize_for_checker = normalize_session_token

LogFn = Callable[[str], None]
Result = str  # alive | dead | error

_ALIVE_PREFIX = "ЖИВОЙ"
_ALIVE_TAG_LINE = "ЖИВОЙ"
_ALIVE_SUBDIR = ALIVE_SUBDIR

_LAUNCHER: Any = None
_QT_APP: Any = None
_LOG_HANDLERS: dict[int, LogFn] = {}
_LOG_HANDLERS_LOCK = threading.Lock()
_LAUNCHER_LOG_ROUTED = False
_DEFAULT_PARALLEL = 5
_FILE_OPS_LOCK = threading.Lock()
_LAUNCHER_INIT_LOCK = threading.Lock()
_CHECK_SUBPROCESS_TIMEOUT_SEC = 120.0


def _default_log(msg: str) -> None:
    print(msg, flush=True)


def _setup_launcher_runtime(root: str) -> None:
    global _LAUNCHER, _QT_APP
    with _LAUNCHER_INIT_LOCK:
        if _LAUNCHER is not None:
            return

        root = os.path.abspath(root)
        sys.path.insert(0, root)
        src = os.path.join(root, "src")
        if src not in sys.path:
            sys.path.insert(0, src)

        os.environ.setdefault("MAXITOCHKA_APP_ROOT", root)
        extracted = os.path.join(root, "DotLauncher.exe_extracted")
        os.chdir(extracted)

        import run_launcher

        run_launcher.setup_runtime()
        spec = importlib.util.spec_from_file_location("dotlauncher_main", run_launcher.MAIN_PYC)
        if spec is None or spec.loader is None:
            raise RuntimeError("не удалось загрузить main.pyc")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from PyQt6.QtWidgets import QApplication

        _QT_APP = QApplication.instance() or QApplication([])
        _LAUNCHER = mod.DotLauncher()
        _LAUNCHER.token_results = {}


def _launcher(root: str) -> Any:
    _setup_launcher_runtime(root)
    assert _LAUNCHER is not None
    _install_launcher_log_router(_LAUNCHER)
    return _LAUNCHER


def _install_launcher_log_router(launcher: Any) -> None:
    global _LAUNCHER_LOG_ROUTED
    if _LAUNCHER_LOG_ROUTED:
        return

    def _route(_session: str, message: str) -> None:
        line = (message or "").strip()
        if not line:
            return
        tid = threading.get_ident()
        with _LOG_HANDLERS_LOCK:
            handler = _LOG_HANDLERS.get(tid)
        if handler:
            handler(f"  {line}")

    launcher.append_check_log = _route  # type: ignore[method-assign]
    _LAUNCHER_LOG_ROUTED = True


def load_proxies_file(root: str | None = None) -> str:
    from settings_store import app_data_root, default_proxies_file, load_settings

    base = app_data_root(root)
    settings = load_settings()
    candidates = [
        str(settings.get("proxies_file") or "").strip(),
        default_proxies_file(base),
        os.path.join(base, "proxies.txt"),
        os.path.join(base, "DotLauncher.exe_extracted", "proxies.txt"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return candidates[1]


def read_proxy_lines(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    lines: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                lines.append(s)
    return lines


def _proxy_auth_prefix(parts: list[str]) -> str:
    if len(parts) > 3:
        return f"{parts[2]}:{parts[3]}@"
    return ""


def build_proxy_requests(raw: str, ptype: str = "http") -> dict[str, str]:
    parts = raw.split(":")
    auth = _proxy_auth_prefix(parts)
    url = f"{ptype}://{auth}{parts[0]}:{parts[1]}"
    return {"http": url, "https": url}


def check_proxy_line(raw: str, timeout: float = 5.0) -> dict[str, Any]:
    """Проверка прокси как в main.pyc (_worker): ipify через http/socks5."""
    for ptype in ("socks5", "http"):
        try:
            px = build_proxy_requests(raw, ptype)
            t0 = time.perf_counter()
            r = requests.get(
                "http://api.ipify.org",
                proxies=px,
                timeout=timeout,
            )
            if r.status_code == 200 and (r.text or "").strip():
                return {
                    "st": "OK",
                    "type": ptype,
                    "ms": int((time.perf_counter() - t0) * 1000),
                    "ip": r.text.strip(),
                }
        except Exception:
            continue
    return {"st": "ERR", "type": "http", "ms": None}


def build_proxy_cache(lines: list[str], log: LogFn | None = None) -> dict[str, dict]:
    log = log or _default_log
    cache: dict[str, dict] = {}
    if not lines:
        log("[!] Файл прокси пуст — проверка без прокси")
        return cache
    log(f"Проверка {len(lines)} прокси...")
    ok = 0
    for raw in lines:
        inf = check_proxy_line(raw)
        cache[raw] = inf
        host = raw.split(":")[0]
        port = raw.split(":")[1] if ":" in raw else "?"
        if inf.get("st") == "OK":
            ok += 1
            log(f"  [OK] {host}:{port} ({inf.get('type')}, {inf.get('ms')} ms)")
        else:
            log(f"  [--] {host}:{port}")
    log(f"Рабочих прокси: {ok}/{len(lines)}")
    return cache


def check_token_via_launcher(
    content: str,
    fname: str,
    *,
    proxy_cache: dict[str, dict],
    root: str,
    log: LogFn | None = None,
) -> Result:
    """Тот же _check_token_worker, что и во вкладке «Чекер» (WebSocket, без Chrome)."""
    log = log or _default_log
    launcher = _launcher(root)
    launcher.proxy_cache = proxy_cache

    tid = threading.get_ident()
    with _LOG_HANDLERS_LOCK:
        _LOG_HANDLERS[tid] = log
    try:
        prepared = normalize_session_token(content)
        launcher.token_results[fname] = "checking"
        try:
            launcher._check_token_worker(fname, prepared)
        except Exception as ex:
            log(f"  [ОШИБКА] {ex}")
            return "error"

        status = str((launcher.token_results or {}).get(fname) or "error")
        low = status.lower()
        if low == "alive":
            return "alive"
        if low == "dead":
            return "dead"
        if low == "ok":
            return "alive"
        return "error"
    finally:
        with _LOG_HANDLERS_LOCK:
            _LOG_HANDLERS.pop(tid, None)


def default_checktoken_dir(root: str | None = None) -> str:
    """Папка токенов (tokenbase) — та же, что для запуска."""
    return default_tokenbase_dir(root)


def list_token_files(folder: str, *, recursive: bool = True) -> list[str]:
    """Список .txt для очереди проверки (кроме alive/)."""
    return list_txt_files(folder, recursive=recursive, skip_subdirs=(ALIVE_SUBDIR,))


def _resolve_alive_dest(path: str, checktoken_root: str) -> str:
    dest_dir = alive_dir(checktoken_root)
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.basename(path)
    dest = os.path.join(dest_dir, name)
    if not os.path.exists(dest):
        return dest
    parent = os.path.basename(os.path.dirname(path))
    if parent and parent.casefold() not in (".", "", _ALIVE_SUBDIR):
        alt = os.path.join(dest_dir, f"{parent}__{name}")
        if not os.path.exists(alt):
            return alt
    stem, ext = os.path.splitext(name)
    n = 2
    while n < 10_000:
        alt = os.path.join(dest_dir, f"{stem}_{n}{ext}")
        if not os.path.exists(alt):
            return alt
        n += 1
    return os.path.join(dest_dir, f"{stem}_{int(time.time())}{ext}")


def mark_alive_file(
    path: str,
    *,
    checktoken_root: str | None = None,
    log: LogFn | None = None,
) -> str:
    """Подписать живой токен и перенести в tokenbase/alive/."""
    log = log or _default_log
    with _FILE_OPS_LOCK:
        with open(path, encoding="utf-8") as f:
            body = f.read()
        lines = body.splitlines()
        if not lines or lines[0].strip().upper() != _ALIVE_TAG_LINE:
            body = _ALIVE_TAG_LINE + "\n" + body.lstrip("\ufeff")
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            log("  >> подпись ЖИВОЙ в файле")

        if checktoken_root:
            dest = _resolve_alive_dest(path, checktoken_root)
            if os.path.abspath(path) != os.path.abspath(dest):
                if os.path.exists(dest):
                    os.remove(dest)
                os.rename(path, dest)
                path = dest
            log(f"  >> в папку alive: {os.path.basename(path)}")
            return path

        folder = os.path.dirname(path)
        name = os.path.basename(path)
        if not name.upper().startswith(_ALIVE_PREFIX):
            new_name = f"{_ALIVE_PREFIX}_{name}"
            new_path = os.path.join(folder, new_name)
            if os.path.exists(new_path):
                os.remove(new_path)
            os.rename(path, new_path)
            path = new_path
            log(f"  >> переименован: {new_name}")
    return path


def delete_dead_file(path: str, log: LogFn | None = None) -> None:
    log = log or _default_log
    with _FILE_OPS_LOCK:
        try:
            os.remove(path)
            log(f"  >> удален мертвый: {os.path.basename(path)}")
        except OSError as ex:
            log(f"  ! не удалось удалить {path}: {ex}")


def _apply_token_result(
    path: str,
    result: Result,
    stats: dict[str, int],
    log: LogFn,
    *,
    checktoken_root: str | None = None,
) -> None:
    if result == "alive":
        log("  => ЖИВОЙ")
        mark_alive_file(path, checktoken_root=checktoken_root, log=log)
        stats["alive"] += 1
    elif result == "dead":
        log("  => МЕРТВЫЙ")
        delete_dead_file(path, log=log)
        stats["dead"] += 1
    else:
        log("  => ОШИБКА")
        stats["error"] += 1


def _check_one_token_file(
    folder: str,
    fname: str,
    *,
    index: int,
    total: int,
    root: str,
    proxy_cache: dict[str, dict],
    log: LogFn,
    log_lock: threading.Lock | None,
) -> Result:
    path = token_path(folder, fname)

    def _emit(msg: str) -> None:
        if log_lock:
            with log_lock:
                log(msg)
        else:
            log(msg)

    _emit("")
    _emit(f"[{index}/{total}] {fname}")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as ex:
        _emit(f"  [ERR] не прочитан: {ex}")
        return "error"

    return check_token_via_launcher(
        content,
        fname,
        proxy_cache=proxy_cache,
        root=root,
        log=_emit,
    )


def _checktoken_one_script(root: str) -> str:
    return os.path.join(root, "scripts", "checktoken_one.py")


def _check_one_token_subprocess(
    path: str,
    fname: str,
    *,
    root: str,
    proxy_file: str,
) -> Result:
    """Проверка в отдельном процессе — Qt не ломается при параллельном запуске."""
    script = _checktoken_one_script(root)
    if not os.path.isfile(script):
        return "error"
    cmd = [
        sys.executable,
        script,
        "--path",
        os.path.abspath(path),
        "--fname",
        fname,
        "--root",
        root,
        "-p",
        proxy_file,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CHECK_SUBPROCESS_TIMEOUT_SEC,
            cwd=root,
        )
    except subprocess.TimeoutExpired:
        return "error"
    except OSError:
        return "error"

    lines = [ln.strip().lower() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    result = lines[-1] if lines else "error"
    if result in ("alive", "dead", "error"):
        return result
    return "error"


def run_checktoken_folder(
    folder: str | None = None,
    *,
    root: str | None = None,
    proxies_path: str | None = None,
    delay_sec: float = 1.5,
    recursive: bool = True,
    parallel: int = _DEFAULT_PARALLEL,
    log: LogFn | None = None,
) -> dict[str, int]:
    """Проверить все .txt в tokenbase. Мёртвые удаляются, живые → tokenbase/alive/."""
    log = log or _default_log
    root = os.path.abspath(
        root or os.environ.get("MAXITOCHKA_APP_ROOT") or os.path.join(os.path.dirname(__file__), "..")
    )
    folder = folder or default_checktoken_dir(root)
    os.makedirs(folder, exist_ok=True)
    try:
        from tokenbase import migrate_legacy_dirs

        migrate_legacy_dirs(root, folder)
    except Exception:
        pass

    files = list_token_files(folder, recursive=recursive)
    stats = {"total": len(files), "alive": 0, "dead": 0, "error": 0}

    log("=" * 56)
    log("Maxitochka — проверка токенов (tokenbase)")
    log(f"Папка: {folder}")
    log(f"Живые → {alive_dir(folder)}")
    if recursive:
        log("Режим: корень + все подпапки")
    else:
        log("Режим: только корень папки")
    workers = max(1, min(int(parallel or 1), 16))
    if workers > 1:
        log(f"Параллельно: до {workers} токенов (отдельный процесс на каждый)")
    else:
        log("Параллельно: 1 (последовательно)")
    log("=" * 56)

    if not files:
        log("Нет .txt файлов в tokenbase (включая подпапки)")
        return stats

    proxy_file = proxies_path or load_proxies_file(root)
    log(f"Прокси: {proxy_file}")
    proxy_lines = read_proxy_lines(proxy_file)
    proxy_cache = build_proxy_cache(proxy_lines, log=log)

    if proxy_lines and not any(v.get("st") == "OK" for v in proxy_cache.values()):
        log("[ERR] Нет рабочих прокси — остановка")
        stats["error"] = len(files)
        return stats

    if workers <= 1:
        log("Инициализация чекера…")
        _launcher(root)
        for i, fname in enumerate(files, 1):
            path = token_path(folder, fname)
            result = _check_one_token_file(
                folder,
                fname,
                index=i,
                total=len(files),
                root=root,
                proxy_cache=proxy_cache,
                log=log,
                log_lock=None,
            )
            _apply_token_result(path, result, stats, log, checktoken_root=folder)
            if i < len(files) and delay_sec > 0:
                time.sleep(delay_sec)
    else:
        log_lock = threading.Lock()
        stats_lock = threading.Lock()

        def _worker(fname: str, index: int) -> None:
            path = token_path(folder, fname)

            def locked_log(msg: str) -> None:
                with log_lock:
                    log(msg)

            locked_log("")
            locked_log(f"[{index}/{len(files)}] {fname}")
            result = _check_one_token_subprocess(
                path,
                fname,
                root=root,
                proxy_file=proxy_file,
            )
            if result == "alive":
                locked_log("  => ЖИВОЙ")
                mark_alive_file(path, checktoken_root=folder, log=locked_log)
                with stats_lock:
                    stats["alive"] += 1
            elif result == "dead":
                locked_log("  => МЕРТВЫЙ")
                delete_dead_file(path, log=locked_log)
                with stats_lock:
                    stats["dead"] += 1
            else:
                locked_log("  => ОШИБКА")
                with stats_lock:
                    stats["error"] += 1

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i, fname in enumerate(files, 1):
                futures.append(pool.submit(_worker, fname, i))
                if i < len(files) and delay_sec > 0:
                    time.sleep(delay_sec)
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as ex:
                    with stats_lock:
                        stats["error"] += 1
                    with log_lock:
                        log(f"  [ERR] поток: {ex}")

    log("")
    log("=" * 56)
    log(
        f"Итого: живых {stats['alive']} | мертвых удалено {stats['dead']} | "
        f"ошибок {stats['error']}"
    )
    if stats["alive"]:
        log(f"Живые токены: {alive_dir(folder)}")
    log("=" * 56)
    return stats
