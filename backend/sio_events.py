"""
sio_events.py — Socket.IO event handlers.
"""

from __future__ import annotations

import logging
import traceback

from flask_socketio import SocketIO

import image_service
import session
from log_handler import ServiceLogBuffer, SocketIOLogHandler
from monitor import ModuleStore
from recovery import RecoveryRunner
from services import ServicesManager
from vnc_proxy import VncProxyManager


logger = logging.getLogger("FlashBench.SIO")


def register(
    socketio:           SocketIO,
    module_store:       ModuleStore,
    services_manager:   ServicesManager,
    serial_listener,                        # SerialListener (avoid circular import typing)
    vnc_proxy:          VncProxyManager,
    recovery_runner:    RecoveryRunner,
    sio_log_handler:    SocketIOLogHandler,
    service_log_buffer: ServiceLogBuffer,
) -> None:
    """Bind all Socket.IO event handlers."""

    @socketio.on("connect")
    def handle_connect(auth=None):
        from flask import request
        from flask_socketio import emit as sio_emit

        sid = request.sid  # type: ignore[attr-defined]
        logger.info("Client connected | sid=%s", sid)

        # Replay history to the new client
        sio_log_handler.on_client_connect(sid)
        service_log_buffer.on_client_connect(sid)

        sio_emit("modules_update",  module_store.snapshot())
        sio_emit("services_status", services_manager.get_status())
        sio_emit("monitor_status",  serial_listener.get_status())
        sio_emit("vnc_config",      {"ws_port": vnc_proxy.port})
        sio_emit("recovery_status", recovery_runner.get_status())

        # Send current images list
        try:
            images = image_service.get_all_images()
            sio_emit("images_update", {"images": images})
        except Exception:
            logger.warning("Could not send images on connect: %s", traceback.format_exc())

    @socketio.on("disconnect")
    def handle_disconnect():
        from flask import request
        sid = request.sid  # type: ignore[attr-defined]
        logger.info("Client disconnected | sid=%s", sid)

    @socketio.on("set_session_context")
    def handle_set_session_context(data=None):
        if data and isinstance(data, dict):
            session.update(data)
            logger.info("Session context received: %s", data)

    @socketio.on("reset_boards")
    def handle_reset_boards(data=None):
        mode = (data or {}).get("mode", "done")
        if mode == "all":
            logger.info("Client requested full board reset")
            module_store.clear_all()
        else:
            logger.info("Client requested clearing finished boards")
            module_store.clear_done()

    @socketio.on("reset_board")
    def handle_reset_board(data=None):
        """Reset a single board by IP (used when an operator re-scans a position)."""
        ip = (data or {}).get("ip")
        if not ip:
            logger.warning("reset_board called without IP")
            return
        logger.info("Client requested single board reset | ip=%s", ip)
        module_store.clear_one(ip)
