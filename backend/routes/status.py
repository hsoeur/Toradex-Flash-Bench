"""
routes/status.py — GET /api/status
"""

from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("status", __name__, url_prefix="/api")

# Injected at startup via init()
_deps: dict | None = None


def init(module_store, services_manager, serial_listener, vnc_proxy) -> None:  # noqa: ANN001
    """Inject runtime dependencies."""
    global _deps
    _deps = {
        "module_store":     module_store,
        "services_manager": services_manager,
        "serial_listener":  serial_listener,
        "vnc_proxy":        vnc_proxy,
    }


@bp.get("/status")
def get_status():
    assert _deps is not None
    return jsonify({
        "modules":         _deps["module_store"].snapshot(),
        "services":        _deps["services_manager"].get_status(),
        "serial_listener": _deps["serial_listener"].get_status(),
        "vnc_ws_port":     _deps["vnc_proxy"].port,
    })
