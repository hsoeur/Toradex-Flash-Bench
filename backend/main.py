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

import json
import logging
import os
import subprocess
import threading
import time
import traceback
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

import requests as http_requests
from flask import Flask, jsonify, request as flask_request
from flask_cors import CORS
from flask_socketio import SocketIO

from log_handler import ServiceLogBuffer, SocketIOLogHandler
from monitor import ModuleStore, NginxMonitor, SerialListener
from services import ServicesManager
from vnc_proxy import VncProxyManager

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

# External traceability API
EXTERNAL_API_URL = "http://192.168.10.1:10000"
PRODUCT_UID      = "04IN00145"
MACHINE_UID      = "MO03B"
OPERATION_NUMBER = 30
UNIT_UID         = "STR"
TRACE_LABEL      = "PROG_TORADEX"

# Recovery script (Toradex Easy Installer) — update the folder name when upgrading
RECOVERY_SCRIPT_DIR  = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..",
                 "..", "Verdin-AM62_ToradexEasyInstaller_7.4.0+build.8")
)
RECOVERY_SCRIPT_PATH = os.path.join(RECOVERY_SCRIPT_DIR, "recovery-linux.sh")

# Nginx web root where Tezi images live
IMAGE_ROOT = "/var/www/html"
IMAGE_LIST_FILE = os.path.join(IMAGE_ROOT, "image_list.json")

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

# ══════════════════════════════════════════════════
# Session context (operator + order from frontend)
# ══════════════════════════════════════════════════

_session_context: dict = {"operatorId": "", "orderNumber": ""}
_session_context_lock = threading.Lock()


def get_session_context() -> dict:
    with _session_context_lock:
        return dict(_session_context)


def set_session_context(data: dict) -> None:
    with _session_context_lock:
        if "operatorId" in data:
            _session_context["operatorId"] = str(data["operatorId"])
        if "orderNumber" in data:
            _session_context["orderNumber"] = str(data["orderNumber"])
    logger.info("Session context updated: %s", _session_context)


def _on_modules_changed(snapshot: dict) -> None:
    """Called by ModuleStore whenever board state changes → push to all clients."""
    try:
        socketio.emit("modules_update", snapshot)
    except Exception:
        logger.error("Error emitting modules_update:\n%s", traceback.format_exc())


module_store.subscribe(_on_modules_changed)

# ══════════════════════════════════════════════════
# VNC proxy (websockify)
# ══════════════════════════════════════════════════

vnc_proxy = VncProxyManager()
module_store.subscribe(vnc_proxy.on_modules_changed)

# ══════════════════════════════════════════════════
# Recovery script runner
# ══════════════════════════════════════════════════


class RecoveryRunner:
    """Runs recovery-linux.sh in a background thread and streams output via Socket.IO."""

    def __init__(self) -> None:
        self._proc:   subprocess.Popen | None = None
        self._thread: threading.Thread  | None = None
        self._lock   = threading.Lock()
        self.status  = "idle"   # idle | running | success | error

    def start(self) -> bool:
        """Start the recovery script. Returns False if already running."""
        with self._lock:
            if self.status == "running":
                return False
            self.status = "running"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Terminate the running recovery script."""
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def get_status(self) -> dict:
        return {"status": self.status}

    def _emit_log(self, line: str, level: str = "info") -> None:
        try:
            socketio.emit("recovery_log", {
                "ts":      time.time(),
                "level":   level,
                "message": line,
            })
        except Exception:
            pass

    def _emit_status(self) -> None:
        try:
            socketio.emit("recovery_status", self.get_status())
        except Exception:
            pass

    def _run(self) -> None:
        self._emit_status()

        if not os.path.isfile(RECOVERY_SCRIPT_PATH):
            self._emit_log(f"Script introuvable : {RECOVERY_SCRIPT_PATH}", "error")
            with self._lock:
                self.status = "error"
            self._emit_status()
            return

        self._emit_log(f"Lancement : {RECOVERY_SCRIPT_PATH}", "info")
        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(
                ["bash", RECOVERY_SCRIPT_PATH],
                cwd=RECOVERY_SCRIPT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._proc = proc

            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                if line:
                    self._emit_log(line)

            proc.wait()
            with self._lock:
                self._proc = None

            if proc.returncode == 0:
                with self._lock:
                    self.status = "success"
                self._emit_log("Script terminé avec succès.", "info")
            else:
                with self._lock:
                    self.status = "error"
                self._emit_log(f"Script terminé avec le code {proc.returncode}.", "error")

        except Exception as exc:
            logger.error("RecoveryRunner error: %s", traceback.format_exc())
            self._emit_log(f"Erreur : {exc}", "error")
            with self._lock:
                self._proc  = None
                self.status = "error"

        self._emit_status()


recovery_runner = RecoveryRunner()

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

    sio_emit("modules_update",   module_store.snapshot())
    sio_emit("services_status",  services_manager.get_status())
    sio_emit("monitor_status",   serial_listener.get_status())
    sio_emit("vnc_config",       {"ws_port": vnc_proxy.port})
    sio_emit("recovery_status",  recovery_runner.get_status())

    # Send current images list
    try:
        images_paths = _read_image_list()
        images = []
        for rel_path in images_paths:
            try:
                img = _read_image_json(rel_path)
                folder = rel_path.rsplit("/", 1)[0] if "/" in rel_path else rel_path
                autoinstall_raw = img.get("autoinstall", False)
                autoinstall = autoinstall_raw is True or autoinstall_raw == "true"
                images.append({
                    "path":         rel_path,
                    "folder":       folder,
                    "name":         img.get("name", folder),
                    "description":  img.get("description", ""),
                    "version":      img.get("version", ""),
                    "release_date": img.get("release_date", ""),
                    "autoinstall":  autoinstall,
                })
            except Exception:
                pass
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
    """Receive operator + order context from the frontend."""
    if data and isinstance(data, dict):
        set_session_context(data)
        logger.info("Session context received: %s", data)


@socketio.on("reset_boards")
def handle_reset_boards(data=None):
    """Clear finished (done/error) boards, or all boards if mode='all'."""
    mode = (data or {}).get("mode", "done")
    if mode == "all":
        logger.info("Client requested full board reset")
        module_store.clear_all()
    else:
        logger.info("Client requested clearing finished boards")
        module_store.clear_done()



# ══════════════════════════════════════════════════
# REST route — Traceability notification (called by board script)
# ══════════════════════════════════════════════════


@app.post("/api/traceability/notify")
def traceability_notify():
    """
    Called by the on-board script (prepare.sh) after MAC injection.
    Enriches the board data with the session context (operator, order)
    and forwards the traceability record to the external API.
    """
    try:
        body = flask_request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    # Required fields from the board script
    required = ["serialNumber", "macId", "clientMac", "factoryMac"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # Session context from the frontend
    ctx = get_session_context()
    if not ctx["operatorId"] or not ctx["orderNumber"]:
        logger.warning(
            "Traceability notify received but session context incomplete: %s", ctx
        )
        return jsonify({
            "error": "Session context incomplete — no operator/order set on the dashboard"
        }), 400

    # Build the payload for the external traceability API
    creation_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    trace_payload = {
        "productUid":            PRODUCT_UID,
        "serialNumber":          int(body["serialNumber"]),
        "label":                 TRACE_LABEL,
        "value":                 body["clientMac"],
        "classification":        "OK",
        "creationDate":          creation_date,
        "operationNumber":       OPERATION_NUMBER,
        "unitUid":               UNIT_UID,
        "userUid":               ctx["operatorId"],
        "machineUid":            MACHINE_UID,
        "manufacturingOrderUid": int(ctx["orderNumber"]),
    }

    ext_url = f"{EXTERNAL_API_URL}/api/MeasurementTraceability/create-with-mac"

    logger.info(
        "Traceability notify | serial=%s | MAC=%s | operator=%s | order=%s",
        body["serialNumber"], body["clientMac"],
        ctx["operatorId"], ctx["orderNumber"],
    )
    logger.debug(
        "Traceability request | URL=%s | payload=%s",
        ext_url, json.dumps(trace_payload, indent=2),
    )

    try:
        resp = http_requests.post(
            ext_url,
            json=trace_payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=10,
        )
    except http_requests.RequestException as exc:
        logger.error("External traceability API unreachable: %s", exc)
        return jsonify({"error": "External traceability API unreachable", "detail": str(exc)}), 502

    if resp.status_code != 200:
        logger.error(
            "External traceability API error | HTTP %d | %s", resp.status_code, resp.text
        )
        return jsonify({
            "error": "External traceability API returned an error",
            "httpCode": resp.status_code,
            "detail": resp.text,
        }), 502

    # Mark the board as done in the real-time monitor
    board_ip = flask_request.remote_addr
    module_store.mark_done(board_ip)

    logger.info(
        "Traceability OK | serial=%s | MAC=%s | ip=%s",
        body["serialNumber"], body["clientMac"], board_ip,
    )

    return jsonify({"ok": True, "message": "Traceability recorded"})


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


# ══════════════════════════════════════════════════
# REST routes — Recovery script
# ══════════════════════════════════════════════════


@app.post("/api/recovery/start")
def recovery_start():
    started = recovery_runner.start()
    if not started:
        return jsonify({"ok": False, "error": "Already running"}), 409
    return jsonify({"ok": True})


@app.post("/api/recovery/stop")
def recovery_stop():
    recovery_runner.stop()
    return jsonify({"ok": True})


@app.get("/api/recovery/status")
def get_recovery_status():
    return jsonify(recovery_runner.get_status())


@app.get("/api/status")
def get_status():
    return jsonify({
        "modules":         module_store.snapshot(),
        "services":        services_manager.get_status(),
        "serial_listener": serial_listener.get_status(),
        "vnc_ws_port":     vnc_proxy.port,
    })


# ══════════════════════════════════════════════════
# REST routes — Tezi image autoinstall switcher
# ══════════════════════════════════════════════════


def _read_image_list() -> list[str]:
    """Return list of relative image.json paths from image_list.json."""
    with open(IMAGE_LIST_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("images", [])


def _read_image_json(relative_path: str) -> dict:
    """Read and return a single image.json."""
    full_path = os.path.join(IMAGE_ROOT, relative_path)
    with open(full_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_image_json(relative_path: str, data: dict) -> None:
    """Write data back to an image.json file."""
    full_path = os.path.join(IMAGE_ROOT, relative_path)
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


@app.get("/api/images")
def get_images():
    """List all Tezi images with their autoinstall status."""
    try:
        paths = _read_image_list()
        images = []
        for rel_path in paths:
            try:
                img = _read_image_json(rel_path)
                # Derive folder name from path (e.g. "Verdin-AM62_DEV/image.json" → "Verdin-AM62_DEV")
                folder = rel_path.rsplit("/", 1)[0] if "/" in rel_path else rel_path
                autoinstall_raw = img.get("autoinstall", False)
                autoinstall = autoinstall_raw is True or autoinstall_raw == "true"
                images.append({
                    "path":         rel_path,
                    "folder":       folder,
                    "name":         img.get("name", folder),
                    "description":  img.get("description", ""),
                    "version":      img.get("version", ""),
                    "release_date": img.get("release_date", ""),
                    "autoinstall":  autoinstall,
                })
            except Exception:
                logger.warning("Cannot read image %s:\n%s", rel_path, traceback.format_exc())
        return jsonify({"images": images})
    except Exception:
        logger.error("Error listing images:\n%s", traceback.format_exc())
        return jsonify({"error": "Cannot read image list"}), 500


@app.post("/api/images/autoinstall")
def set_autoinstall():
    """Set autoinstall=true for one image, false for all others."""
    try:
        body = flask_request.get_json(force=True)
        target_path = body.get("path")
        if not target_path:
            return jsonify({"error": "Missing 'path'"}), 400

        paths = _read_image_list()
        if target_path not in paths:
            return jsonify({"error": f"Unknown image path: {target_path}"}), 404

        for rel_path in paths:
            try:
                img = _read_image_json(rel_path)
                should_be_active = (rel_path == target_path)
                img["autoinstall"] = should_be_active
                _write_image_json(rel_path, img)
                logger.info(
                    "Image %s → autoinstall=%s",
                    rel_path, should_be_active,
                )
            except Exception:
                logger.error("Error updating %s:\n%s", rel_path, traceback.format_exc())

        # Push update to all connected clients
        try:
            # Re-read to send fresh state
            from flask import url_for
            resp = get_images()
            socketio.emit("images_update", resp.get_json())
        except Exception:
            logger.error("Error emitting images_update:\n%s", traceback.format_exc())

        return jsonify({"ok": True})
    except Exception:
        logger.error("Error in set_autoinstall:\n%s", traceback.format_exc())
        return jsonify({"error": "Internal error"}), 500


# ══════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════


def main() -> None:
    logger.info("═" * 60)
    logger.info("FlashBench Monitor backend starting")
    logger.info("  Flask-SocketIO : http://%s:%d", FLASK_HOST, FLASK_PORT)
    logger.info("  Serial TCP     : port %d", 5000)
    logger.info("  VNC proxy      : ws://0.0.0.0:%d", vnc_proxy.port)
    logger.info("  Nginx log      : /var/log/nginx/access.log")
    logger.info("═" * 60)

    # Start background workers
    serial_listener.start()
    nginx_monitor.start()
    services_manager.start()
    vnc_proxy.start()

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
