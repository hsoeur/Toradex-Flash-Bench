"""
session.py — Thread-safe session context (operator + order number).
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("FlashBench.Session")

_context: dict = {"operatorId": "", "orderNumber": ""}
_lock = threading.Lock()


def get() -> dict:
    """Return a snapshot of the current session context."""
    with _lock:
        return dict(_context)


def update(data: dict) -> None:
    """Merge *data* into the session context."""
    with _lock:
        if "operatorId" in data:
            _context["operatorId"] = str(data["operatorId"])
        if "orderNumber" in data:
            _context["orderNumber"] = str(data["orderNumber"])
    logger.info("Session context updated: %s", _context)
