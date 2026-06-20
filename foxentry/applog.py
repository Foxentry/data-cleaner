# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AVANTRO s.r.o.
"""
Application log (human-readable) for debugging the app run.

Writes to logs/app.log (and to the stderr console). Unlike
logs/requests-*.jsonl (pure API calls), this captures the whole app flow:
server start, run start/end, progress heartbeat, retries on 429,
errors with traceback. The goal is to see where validation might get stuck.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

_LOCK = threading.Lock()
_log = logging.getLogger("foxentry.app")
_configured = False


def set_value(log_dir: Path, enabled: bool = True) -> None:
    """Configure the logger (once). Safe to call repeatedly."""
    global _configured
    with _LOCK:
        if _configured:
            return
        _log.setLevel(logging.DEBUG)
        _log.propagate = False
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
        if enabled:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                from logging.handlers import RotatingFileHandler
                fh = RotatingFileHandler(log_dir / "app.log", encoding="utf-8",
                                         maxBytes=2_000_000, backupCount=3)
                fh.setFormatter(fmt)
                _log.addHandler(fh)
            except OSError:
                pass
        try:
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("[foxentry] %(message)s"))
            _log.addHandler(sh)
        except Exception:
            pass
        _configured = True


def info(msg, *a) -> None:
    _log.info(msg, *a)


def warn(msg, *a) -> None:
    _log.warning(msg, *a)


def error(msg, *a) -> None:
    _log.error(msg, *a)


def exception(msg, *a) -> None:
    """Zaloguje chybu i s tracebackem (volat v except bloku)."""
    _log.exception(msg, *a)
