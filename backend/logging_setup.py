"""
logging_setup.py — Logger configuration for FlashBench.

Creates:
  - Root FlashBench logger with console + daily file handlers
  - Dedicated flash_events file handler for FlashBench.Monitor
  - SocketIOLogHandler for live push to the frontend
  - ServiceLogBuffer for per-service log panels
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from config import LOG_DIR, LOG_RETENTION_DAYS, LOG_BUFFER_MAXLEN
from log_handler import ServiceLogBuffer, SocketIOLogHandler

os.makedirs(LOG_DIR, exist_ok=True)


# ── Helpers ──────────────────────────────────────

def _make_daily_handler(stem: str, level: int = logging.DEBUG) -> TimedRotatingFileHandler:
    """
    TimedRotatingFileHandler that writes to ``logs/YYYY-MM-DD_<stem>.log``
    and rotates at midnight, keeping *LOG_RETENTION_DAYS* backups.
    """
    today    = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(LOG_DIR, f"{today}_{stem}.log")

    handler = TimedRotatingFileHandler(
        filepath,
        when="midnight",
        interval=1,
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )

    def _namer(default_name: str) -> str:
        base, _sep, date_suffix = default_name.rpartition(".")
        log_dir  = os.path.dirname(base)
        basename = os.path.basename(base)
        parts    = basename.split("_", 1)
        pure_stem = parts[1] if len(parts) == 2 else basename
        return os.path.join(log_dir, f"{date_suffix}_{pure_stem}")

    handler.namer = _namer
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    return handler


# ── Public setup function ────────────────────────

def init_logging() -> tuple[SocketIOLogHandler, ServiceLogBuffer]:
    """
    Configure all FlashBench loggers and return the live-push objects
    that need a ``socketio`` instance injected later.
    """
    # Console handler (INFO+)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))

    # Main file handler (DEBUG+)
    main_file = _make_daily_handler("flashbench", logging.DEBUG)

    # Root FlashBench logger
    root = logging.getLogger("FlashBench")
    root.setLevel(logging.DEBUG)
    root.addHandler(main_file)
    root.addHandler(console)

    # Dedicated flash-events file for FlashBench.Monitor
    events_file = _make_daily_handler("flash_events", logging.INFO)
    events_file.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    )
    logging.getLogger("FlashBench.Monitor").addHandler(events_file)

    # Socket.IO live-push handler
    sio_handler = SocketIOLogHandler(maxlen=LOG_BUFFER_MAXLEN)
    sio_handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
    root.addHandler(sio_handler)

    # Per-service log buffer
    svc_buffer = ServiceLogBuffer(maxlen=LOG_BUFFER_MAXLEN)

    return sio_handler, svc_buffer
