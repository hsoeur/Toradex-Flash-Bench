"""
main.py — FlashBench backend entry point.

Starts and orchestrates:
  - Flask-SocketIO server  (port 5001)  ← consumed by the React frontend
  - SerialListener         (port 5000)  ← boards announce their serial numbers
  - NginxMonitor                        ← tails /var/log/nginx/access.log
  - ServicesManager                     ← lifecycle for mac_api & Docker Compose

Run with:
    python main.py
"""

from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from log_handler import ServiceLogBuffer, SocketIOLogHandler
from monitor import ModuleStore, NginxMonitor, SerialListener
from services import ServicesManager

# ══════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════

LOG_DIR      = os.path.join(os.path.dirname(__file__), "..", "logs")
FLASK_HOST   = "0.0.0.0"
FLASK_PORT   = 5001
DEBUG        = False
LOG_RETENTION_DAYS = 30

# Working directory for docker-compose / uvicorn (project root by default)
WORK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ══════════════════════════════════════════════════
# Helpers — daily log files named YYYY-MM-DD_<stem>.log
# ══════════════════════════════════════════════════

os.makedirs(LOG_DIR, exist_ok=True)


def _make_daily_handler(stem: str, level: int = logging.DEBUG) -> TimedRotatingFileHandler:
    """
    Create a TimedRotatingFileHandler that:
      - writes today's logs to  logs/YYYY-MM-DD_<stem>.log
      - rotates at midnight, keeping LOG_RETENTION_DAYS files
      - names rotated backups  logs/YYYY-MM-DD_<stem>.log  (date prefix, not suffix)
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

    # Rename rotated files to  YYYY-MM-DD_<stem>.log  instead of  <stem>.log.YYYY-MM-DD
    def _namer(default_name: str) -> str:
        # default_name = /path/YYYY-MM-DD_stem.log.YYYY-MM-DD
        base, _sep, date_suffix = default_name.rpartition(".")
        log_dir  = os.path.dirname(base)
        # strip old date prefix from the base filename, keep only the stem part
        basename = os.path.basename(base)
        # basename looks like "YYYY-MM-DD_stem.log" — extract stem
        parts = basename.split("_", 1)
        pure_stem = parts[1] if len(parts) == 2 else basename
        return os.path.join(log_dir, f"{date_suffix}_{pure_stem}")

    handler.namer = _namer
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    return handler


# ══════════════════════════════════════════════════
# Loggers setup
# ══════════════════════════════════════════════════

# — Console (INFO+, visible dans le terminal)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)

# — Fichier principal : tout (DEBUG+), tous les modules FlashBench
_main_file_handler = _make_daily_handler("flashbench", logging.DEBUG)

# Root logger
_root_logger = logging.getLogger("FlashBench")
_root_logger.setLevel(logging.DEBUG)
_root_logger.addHandler(_main_file_handler)
_root_logger.addHandler(_console_handler)

# — Fichier dédié aux events cartes (register / progress / error)
#   Uniquement le logger FlashBench.Monitor
_events_file_handler = _make_daily_handler("flash_events", logging.INFO)
_events_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)
_monitor_logger = logging.getLogger("FlashBench.Monitor")
_monitor_logger.addHandler(_events_file_handler)

logger = logging.getLogger("FlashBench.Main")

# ══════════════════════════════════════════════════
# Socket.IO log handler (in-memory buffer + push)
# ══════════════════════════════════════════════════

sio_log_handler = SocketIOLogHandler(maxlen=500)
sio_log_handler.setFormatter(logging.Formatter("%(name)s | %(message)s"))
_root_logger.addHandler(sio_log_handler)

# ══════════════════════════════════════════════════
# Service log buffer (per-source logs for ServicesPanel)
# ══════════════════════════════════════════════════

service_log_buffer = ServiceLogBuffer(maxlen=500)

# ══════════════════════════════════════════════════
# Flask + Socket.IO
# ══════════════════════════════════════════════════

app = Flask(__name__)
app.config["SECRET_KEY"] = "flashbench-secret"

CORS(app, resources={r"/*": {"origins": "*"}})

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# Inject the live socketio instance into our buffers/handlers
sio_log_handler.set_socketio(socketio)
service_log_buffer.set_socketio(socketio)

# ══════════════════════════════════════════════════
# Module store + monitors
# ══════════════════════════════════════════════════

module_store = ModuleStore()


def _on_modules_changed(snapshot: dict) -> None:
    """Called by ModuleStore whenever board state changes → push to all clients."""
    try:
        socketio.emit("modules_update", snapshot)
    except Exception:
        logger.error("Error emitting modules_update:\n%s", traceback.format_exc())


module_store.subscribe(_on_modules_changed)

def _on_serial_listener_status_changed(_status: str) -> None:
    try:
        socketio.emit("monitor_status", serial_listener.get_status())
    except Exception:
        logger.error("Error emitting monitor_status:\n%s", traceback.format_exc())


serial_listener = SerialListener(
    store=module_store,
    on_status_changed=_on_serial_listener_status_changed,
)
nginx_monitor   = NginxMonitor(store=module_store)

# ══════════════════════════════════════════════════
# Services manager
# ══════════════════════════════════════════════════


def _on_services_status_changed(status_dict: dict) -> None:
    try:
        socketio.emit("services_status", status_dict)
    except Exception:
        logger.error("Error emitting services_status:\n%s", traceback.format_exc())


def _on_service_log(entry: dict) -> None:
    service_log_buffer.append(entry)


services_manager = ServicesManager(
    on_status_changed=_on_services_status_changed,
    on_service_log=_on_service_log,
)

# ══════════════════════════════════════════════════
# Socket.IO events
# ══════════════════════════════════════════════════


@socketio.on("connect")
def handle_connect(auth=None):
    from flask import request
    from flask_socketio import emit as sio_emit

    sid = request.sid  # type: ignore[attr-defined]
    logger.info("Client connected | sid=%s", sid)

    # Replay history and current state to the new client
    sio_log_handler.on_client_connect(sid)
    service_log_buffer.on_client_connect(sid)

    sio_emit("modules_update",  module_store.snapshot())
    sio_emit("services_status", services_manager.get_status())
    sio_emit("monitor_status",  serial_listener.get_status())


@socketio.on("disconnect")
def handle_disconnect():
    from flask import request
    sid = request.sid  # type: ignore[attr-defined]
    logger.info("Client disconnected | sid=%s", sid)



# ══════════════════════════════════════════════════
# REST routes — mac_api lifecycle control
# ══════════════════════════════════════════════════


@app.post("/api/services/mac-api/start")
def mac_api_start():
    services_manager.mac_api_start()
    return jsonify({"ok": True})


@app.post("/api/services/mac-api/stop")
def mac_api_stop():
    services_manager.mac_api_stop()
    return jsonify({"ok": True})


@app.post("/api/services/mac-api/restart")
def mac_api_restart():
    services_manager.mac_api_restart()
    return jsonify({"ok": True})


@app.get("/api/status")
def get_status():
    return jsonify({
        "modules":         module_store.snapshot(),
        "services":        services_manager.get_status(),
        "serial_listener": serial_listener.get_status(),
    })


# ══════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════


def main() -> None:
    logger.info("═" * 60)
    logger.info("FlashBench Monitor backend starting")
    logger.info("  Flask-SocketIO : http://%s:%d", FLASK_HOST, FLASK_PORT)
    logger.info("  Serial TCP     : port %d", 5000)
    logger.info("  Nginx log      : /var/log/nginx/access.log")
    logger.info("═" * 60)

    # Start background workers
    serial_listener.start()
    nginx_monitor.start()
    services_manager.start()

    # Start Flask-SocketIO (blocking)
    socketio.run(
        app,
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=DEBUG,
        use_reloader=False,   # reloader breaks threading
        log_output=False,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("FlashBench backend stopped by user")
    except Exception:
        logger.critical("Fatal exception in main:\n%s", traceback.format_exc())
        raise
