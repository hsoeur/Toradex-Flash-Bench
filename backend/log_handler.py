"""
log_handler.py — Socket.IO-aware Python logging handler and service log buffer.

Two components:

  SocketIOLogHandler
    A standard `logging.Handler` subclass.  Attach it to any Python logger to
    capture records and:
      - keep a circular in-memory buffer (last 500 entries, for `log_history`)
      - emit a `log_line` Socket.IO event to all connected clients in real time

  ServiceLogBuffer
    Receives structured service-log entries (dict with keys ts / level /
    message / source) from ServicesManager and:
      - keeps per-source circular buffers
      - emits `service_log` Socket.IO events in real time

Both objects expose an `on_client_connect(sid)` method that replays history
to a freshly connected client.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import deque
from typing import Any, Optional

# Maximum number of lines kept in memory per buffer
MAX_LOG_LINES = 500

# Mapping from Python logging levels to the frontend's level strings
_PYTHON_TO_FRONTEND: dict[int, str] = {
    logging.DEBUG:    "debug",
    logging.INFO:     "info",
    logging.WARNING:  "warning",
    logging.ERROR:    "error",
    logging.CRITICAL: "critical",
}


def _level_name(record: logging.LogRecord) -> str:
    return _PYTHON_TO_FRONTEND.get(record.levelno, "info")


# ──────────────────────────────────────────────────
# SocketIOLogHandler
# ──────────────────────────────────────────────────

class SocketIOLogHandler(logging.Handler):
    """
    Logging handler that stores records in a circular buffer and pushes
    them to Socket.IO clients as `log_line` events.

    Attach to the root logger (or any specific logger) **after** creating
    the Flask-SocketIO instance:

        handler = SocketIOLogHandler()
        logging.getLogger("FlashBench").addHandler(handler)
        handler.set_socketio(socketio)
    """

    def __init__(self, maxlen: int = MAX_LOG_LINES) -> None:
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=maxlen)
        self._sio: Optional[Any]  = None   # flask_socketio.SocketIO instance
        self._lock = threading.Lock()

    def set_socketio(self, sio: Any) -> None:
        self._sio = sio

    # ── logging.Handler interface ─────────────────

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts":      time.time(),
                "level":   _level_name(record),
                "message": self.format(record),
            }
            with self._lock:
                self._buffer.append(entry)

            if self._sio is not None:
                try:
                    self._sio.emit("log_line", entry)
                except Exception:
                    pass  # never let logger raise
        except Exception:
            self.handleError(record)

    # ── client connect replay ─────────────────────

    def on_client_connect(self, sid: str) -> None:
        """Send buffered history to a newly connected client."""
        if self._sio is None:
            return
        with self._lock:
            history = list(self._buffer)
        try:
            self._sio.emit("log_history", history, to=sid)
        except Exception:
            pass

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self._buffer)


# ──────────────────────────────────────────────────
# ServiceLogBuffer
# ──────────────────────────────────────────────────

_ALL_SOURCES = ("dhcp", "nginx", "mac_api", "docker")


class ServiceLogBuffer:
    """
    Stores per-source service log entries and pushes them to the frontend
    as `service_log` events.

    Call `append(entry)` from ServicesManager callbacks or any other producer.
    """

    def __init__(self, maxlen: int = MAX_LOG_LINES) -> None:
        self._buffers: dict[str, deque[dict]] = {
            src: deque(maxlen=maxlen) for src in _ALL_SOURCES
        }
        self._sio: Optional[Any] = None
        self._lock = threading.Lock()

    def set_socketio(self, sio: Any) -> None:
        self._sio = sio

    def append(self, entry: dict) -> None:
        """
        Add a service log entry.
        entry must contain at least: ts, level, message, source.
        """
        source = entry.get("source")
        if source not in self._buffers:
            return

        with self._lock:
            self._buffers[source].append(entry)

        if self._sio is not None:
            try:
                self._sio.emit("service_log", entry)
            except Exception:
                pass

    def on_client_connect(self, sid: str) -> None:
        """Send full per-source history to a freshly connected client."""
        if self._sio is None:
            return
        with self._lock:
            history = {src: list(buf) for src, buf in self._buffers.items()}
        try:
            self._sio.emit("service_log_history", history, to=sid)
        except Exception:
            pass

    def get_history(self) -> dict[str, list[dict]]:
        with self._lock:
            return {src: list(buf) for src, buf in self._buffers.items()}

    # ── convenience: log directly into this buffer ────────────────────

    def log(self, level: str, message: str, source: str) -> None:
        self.append({
            "ts":      time.time(),
            "level":   level,
            "message": message,
            "source":  source,
        })
