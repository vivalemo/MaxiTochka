"""Лог Maxitochka: ротация ~10MB, доступен команде для отправки разработчику."""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

_LOG_DIR_NAME = "Maxitochka"
_LOG_FILE_NAME = "maxitochka.log"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 1

_installed = False
_logger: logging.Logger | None = None


def log_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, _LOG_DIR_NAME, "logs")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.join(os.path.expanduser("~"), _LOG_DIR_NAME, "logs")
        os.makedirs(folder, exist_ok=True)
    return folder


def log_path() -> str:
    return os.path.join(log_dir(), _LOG_FILE_NAME)


def setup_logging() -> logging.Logger:
    global _installed, _logger

    logger = logging.getLogger("maxitochka")
    if _installed:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        handler = RotatingFileHandler(
            log_path(),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(fmt)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    except Exception:
        pass

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    logger.addHandler(sh)

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error(
            "Необработанное исключение:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        logger.error(
            "Исключение в потоке %s:\n%s",
            getattr(args.thread, "name", "?"),
            "".join(
                traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            ),
        )

    try:
        threading.excepthook = _thread_excepthook
    except Exception:
        pass

    _installed = True
    _logger = logger
    logger.info("=" * 60)
    logger.info("Maxitochka запущена | %s %s", platform.system(), platform.release())
    logger.info("Лог: %s", log_path())
    return logger


def get_logger(name: str = "") -> logging.Logger:
    if not _installed:
        setup_logging()
    if not name or name == "maxitochka":
        return logging.getLogger("maxitochka")
    return logging.getLogger(f"maxitochka.{name}")


def open_log_folder() -> bool:
    """Открыть папку с логом в проводнике."""
    folder = log_dir()
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: SIM115
            return True
        if sys.platform == "darwin":
            os.system(f'open "{folder}"')
            return True
        os.system(f'xdg-open "{folder}"')
        return True
    except Exception:
        return False
