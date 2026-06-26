"""Автоматический chromedriver под установленный Google Chrome (любая актуальная версия)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from typing import Callable
from urllib.request import urlopen

from app_logger import get_logger

_log = get_logger("chromedriver")

_LOCK = threading.Lock()
# runtime_dir -> (chrome_major, path)
_READY: dict[str, tuple[int | None, str]] = {}


def _chrome_paths() -> list[str]:
    paths: list[str] = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (pf, pf86):
        if base:
            paths.append(
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            )
    return paths


def get_chrome_major_version() -> int | None:
    """Мажорная версия установленного Chrome (149, 150, …)."""
    if sys.platform == "win32":
        try:
            import winreg

            for hive, key in (
                (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
                ),
            ):
                try:
                    with winreg.OpenKey(hive, key) as reg:
                        ver, _ = winreg.QueryValueEx(reg, "version")
                    m = re.search(r"(\d+)", str(ver))
                    if m:
                        return int(m.group(1))
                except OSError:
                    continue
        except Exception:
            pass

    for chrome in _chrome_paths():
        if not os.path.isfile(chrome):
            continue
        try:
            out = subprocess.check_output(
                [chrome, "--version"],
                stderr=subprocess.STDOUT,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = out.decode("utf-8", errors="replace")
            m = re.search(r"(\d+)\.", text)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def get_bundled_chromedriver_version(path: str) -> int | None:
    if not os.path.isfile(path):
        return None
    try:
        out = subprocess.check_output(
            [path, "--version"],
            stderr=subprocess.STDOUT,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = out.decode("utf-8", errors="replace")
        m = re.search(r"ChromeDriver\s+(\d+)", text, re.I)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def is_version_mismatch_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "only supports chrome version" in text
        or "session not created" in text
        and "chrome version" in text
        or "this version of chromedriver" in text
    )


def _copy_driver_to_target(src: str, target: str) -> bool:
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".download"
        shutil.copy2(src, tmp)
        try:
            os.replace(tmp, target)
        except OSError:
            if os.path.isfile(target):
                os.remove(target)
            os.rename(tmp, target)
        return os.path.isfile(target)
    except Exception:
        _log.exception("chromedriver: не удалось скопировать %s -> %s", src, target)
        return False


def _download_via_uc_cache(target: str, chrome_major: int | None, *, force: bool) -> bool:
    """Скачать в кэш undetected_chromedriver, затем скопировать в runtime."""
    from undetected_chromedriver import Patcher

    patcher = Patcher(
        version_main=int(chrome_major or 0),
        force=bool(force),
    )
    patcher.auto()
    src = patcher.executable_path
    if not src or not os.path.isfile(src):
        _log.error("chromedriver: uc Patcher не вернул файл (%s)", src)
        return False
    _log.info("chromedriver: скачан uc -> %s", src)
    return _copy_driver_to_target(src, target)


def _download_via_cft_api(target: str, chrome_major: int) -> bool:
    """Запасной способ: Chrome for Testing (если uc не сработал)."""
    url = (
        "https://googlechromelabs.github.io/chrome-for-testing/"
        "latest-versions-per-milestone-with-downloads.json"
    )
    try:
        with urlopen(url, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        _log.exception("chromedriver: CFT JSON недоступен")
        return False

    milestone = data.get("milestones", {}).get(str(chrome_major))
    if not milestone:
        _log.error("chromedriver: в CFT нет milestone для Chrome %s", chrome_major)
        return False

    zip_url = None
    for item in milestone.get("downloads", {}).get("chromedriver", []):
        if item.get("platform") == "win64":
            zip_url = item.get("url")
            break
    if not zip_url:
        _log.error("chromedriver: нет win64 chromedriver для Chrome %s", chrome_major)
        return False

    _log.info("chromedriver: CFT загрузка %s", zip_url)
    try:
        with urlopen(zip_url, timeout=120) as resp:
            zdata = resp.read()
    except Exception:
        _log.exception("chromedriver: не скачался zip")
        return False

    tmpdir = tempfile.mkdtemp(prefix="mx-cft-")
    try:
        zpath = os.path.join(tmpdir, "chromedriver.zip")
        with open(zpath, "wb") as f:
            f.write(zdata)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmpdir)
        exe_src = None
        for root, _dirs, files in os.walk(tmpdir):
            if "chromedriver.exe" in files:
                exe_src = os.path.join(root, "chromedriver.exe")
                break
        if not exe_src:
            return False
        return _copy_driver_to_target(exe_src, target)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _download_chromedriver(target: str, chrome_major: int | None, *, force: bool) -> bool:
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)

    if _download_via_uc_cache(target, chrome_major, force=force):
        return True

    if chrome_major and _download_via_cft_api(target, chrome_major):
        return True

    _log.error("chromedriver: все способы скачивания не удались")
    return False


def ensure_chromedriver(runtime_dir: str, *, force: bool = False) -> str:
    """
    Положить в runtime_dir/chromedriver.exe драйвер под текущий Chrome.
    При смене версии Chrome (после автообновления) — подтягивает заново.
    """
    runtime_dir = os.path.abspath(runtime_dir or "")
    if not runtime_dir:
        return ""

    target = os.path.join(runtime_dir, "chromedriver.exe")
    chrome_major = get_chrome_major_version()

    with _LOCK:
        cached = _READY.get(runtime_dir)
        if not force and cached:
            cached_major, cached_path = cached
            if cached_path and os.path.isfile(cached_path):
                drv = get_bundled_chromedriver_version(cached_path)
                if chrome_major and drv and drv == chrome_major:
                    return cached_path
                if chrome_major and cached_major == chrome_major and drv == chrome_major:
                    return cached_path

        bundled_major = get_bundled_chromedriver_version(target)
        need_update = force or not os.path.isfile(target)
        if chrome_major and bundled_major and chrome_major != bundled_major:
            need_update = True

        if not need_update and os.path.isfile(target):
            _READY[runtime_dir] = (chrome_major, target)
            return target

        if chrome_major:
            _log.info(
                "chromedriver: Chrome %s, в папке %s — обновление…",
                chrome_major,
                bundled_major or "нет",
            )
        else:
            _log.warning("chromedriver: версия Chrome не определена, пробую авто-скачивание")

        if _download_chromedriver(target, chrome_major, force=need_update or force):
            _READY[runtime_dir] = (chrome_major, target)
            _log.info(
                "chromedriver: готов для Chrome %s (driver %s)",
                chrome_major,
                get_bundled_chromedriver_version(target),
            )
            return target

        if os.path.isfile(target):
            _READY[runtime_dir] = (chrome_major, target)
            return target

    return ""


def mismatch_message(runtime_dir: str) -> str | None:
    target = os.path.join(os.path.abspath(runtime_dir or ""), "chromedriver.exe")
    chrome = get_chrome_major_version()
    driver = get_bundled_chromedriver_version(target)
    if chrome and driver and chrome != driver:
        return (
            f"Chrome {chrome}, chromedriver {driver}.\n"
            "Подбираю драйвер под вашу версию Chrome…"
        )
    return None


def prepare_runtime_async(runtime_dir: str) -> None:
    """Фоном при старте — чтобы окно открылось быстрее."""

    def worker() -> None:
        try:
            ensure_chromedriver(runtime_dir)
        except Exception:
            _log.exception("chromedriver background prepare failed")

    threading.Thread(target=worker, daemon=True, name="ChromedriverPrepare").start()


def prepare_before_browser_launch(
    runtime_dir: str,
    notify: Callable[[str, str], None] | None = None,
) -> bool:
    """Перед запуском токена. True — драйвер на месте."""
    runtime_dir = os.path.abspath(runtime_dir or "")
    if not runtime_dir:
        return False

    hint = mismatch_message(runtime_dir)
    if hint and notify:
        try:
            notify(hint, "#f59e0b")
        except Exception:
            pass

    path = ensure_chromedriver(runtime_dir)
    if path and os.path.isfile(path):
        return True

    if notify:
        try:
            notify(
                "Не удалось подготовить chromedriver.\n"
                "Проверьте интернет и Google Chrome.",
                "#f43f5e",
            )
        except Exception:
            pass
    return False


def retry_after_mismatch(runtime_dir: str) -> bool:
    """Повторная попытка после ошибки «version 147 / browser 149»."""
    _READY.pop(os.path.abspath(runtime_dir or ""), None)
    return bool(ensure_chromedriver(runtime_dir, force=True))
