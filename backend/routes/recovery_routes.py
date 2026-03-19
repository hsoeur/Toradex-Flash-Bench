"""
routes/recovery_routes.py — /api/recovery/* endpoints.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from recovery import RecoveryRunner

bp = Blueprint("recovery", __name__, url_prefix="/api/recovery")

_runner: RecoveryRunner | None = None


def init(runner: RecoveryRunner) -> None:
    """Inject the RecoveryRunner instance."""
    global _runner
    _runner = runner


@bp.post("/start")
def start():
    assert _runner is not None
    if not _runner.start():
        return jsonify({"ok": False, "error": "Already running"}), 409
    return jsonify({"ok": True})


@bp.post("/stop")
def stop():
    assert _runner is not None
    _runner.stop()
    return jsonify({"ok": True})


@bp.get("/status")
def status():
    assert _runner is not None
    return jsonify(_runner.get_status())
