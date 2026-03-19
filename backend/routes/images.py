"""
routes/images.py — /api/images/* endpoints.
"""

from __future__ import annotations

import logging
import traceback

from flask import Blueprint, jsonify, request as flask_request
from flask_socketio import SocketIO

import image_service

logger = logging.getLogger("FlashBench.Routes.Images")

bp = Blueprint("images", __name__, url_prefix="/api/images")

_socketio: SocketIO | None = None


def init(socketio: SocketIO) -> None:
    """Inject the SocketIO instance for live-push."""
    global _socketio
    _socketio = socketio


@bp.get("")
def list_images():
    """List all Tezi images with their autoinstall status."""
    try:
        return jsonify({"images": image_service.get_all_images()})
    except Exception:
        logger.error("Error listing images:\n%s", traceback.format_exc())
        return jsonify({"error": "Cannot read image list"}), 500


@bp.post("/autoinstall")
def set_autoinstall():
    """Set autoinstall=true for one image, false for all others."""
    try:
        body = flask_request.get_json(force=True)
        target_path = body.get("path")
        if not target_path:
            return jsonify({"error": "Missing 'path'"}), 400

        try:
            images = image_service.set_autoinstall(target_path)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

        # Push update to all connected clients
        if _socketio:
            try:
                _socketio.emit("images_update", {"images": images})
            except Exception:
                logger.error("Error emitting images_update:\n%s", traceback.format_exc())

        return jsonify({"ok": True})
    except Exception:
        logger.error("Error in set_autoinstall:\n%s", traceback.format_exc())
        return jsonify({"error": "Internal error"}), 500
