"""
main.py — FlashBench backend entry point.

Starts and orchestrates:
  - Flask-SocketIO server  (port 5001)  ← consumed by the React frontend
  - SerialListener         (port 5000)  ← boards announce their serial numbers
  - ServicesManager                     ← monitors DB, dnsmasq, nginx

Run with:
    python main.py
"""

from __future__ import annotations

import atexit
import logging
import signal
import subprocess
import traceback

from config import FLASK_HOST, FLASK_PORT, DEBUG, SERIAL_TCP_PORT, SERIAL_TCP_HOST

# ── Logging (must be initialised first) ──────────
from logging_setup import init_logging

sio_log_handler, service_log_buffer = init_logging()

logger = logging.getLogger("FlashBench.Main")

# ── Flask + SocketIO ─────────────────────────────
from app_factory import create_app

app, socketio = create_app()

# Wire live-push objects to the socketio instance
sio_log_handler.set_socketio(socketio)
service_log_buffer.set_socketio(socketio)

# ── Core components ──────────────────────────────
from monitor import ModuleStore, SerialListener
from services import ServicesManager
from vnc_proxy import VncProxyManager
from recovery import RecoveryRunner
from power_control import PowerController

module_store = ModuleStore()


def _on_modules_changed(snapshot: dict) -> None:
    """Called by ModuleStore whenever board state changes → push to all clients."""
    try:
        socketio.emit("modules_update", snapshot)
    except Exception:
        logger.error("Error emitting modules_update:\n%s", traceback.format_exc())


# VNC proxy — subscribed FIRST so the token file is written
# before the frontend is notified (avoids a race where the VNC
# viewer connects before websockify has the token).
vnc_proxy = VncProxyManager()
module_store.subscribe(vnc_proxy.on_modules_changed)

module_store.subscribe(_on_modules_changed)

# Recovery runner
recovery_runner = RecoveryRunner(socketio)

# Power controller (Board Interface)
power_controller = PowerController()
try:
    power_controller.init()
    power_controller.reset_all_outputs()
except Exception:
    logger.warning("Board Interface not available at startup — power control disabled until reconnect")


# Serial listener
def _on_serial_listener_status_changed(_status: str) -> None:
    try:
        socketio.emit("monitor_status", serial_listener.get_status())
    except Exception:
        logger.error("Error emitting monitor_status:\n%s", traceback.format_exc())


serial_listener = SerialListener(
    store=module_store,
    on_status_changed=_on_serial_listener_status_changed,
)


# Services manager
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

# ── Register Socket.IO events ───────────────────
import sio_events

sio_events.register(
    socketio=socketio,
    module_store=module_store,
    services_manager=services_manager,
    serial_listener=serial_listener,
    vnc_proxy=vnc_proxy,
    recovery_runner=recovery_runner,
    power_controller=power_controller,
    sio_log_handler=sio_log_handler,
    service_log_buffer=service_log_buffer,
)

# ── Register REST blueprints ────────────────────
from routes import traceability, recovery_routes, images, status, manufacturing_order

traceability.init(module_store)
recovery_routes.init(recovery_runner)
images.init(socketio)
status.init(module_store, services_manager, serial_listener, vnc_proxy)

app.register_blueprint(traceability.bp)
app.register_blueprint(recovery_routes.bp)
app.register_blueprint(images.bp)
app.register_blueprint(status.bp)
app.register_blueprint(manufacturing_order.bp)


# ══════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════


# ── Stale process cleanup ────────────────────────

def _kill_stale_port_holders(*ports: int) -> None:
    """Kill any process (other than ourselves) that is listening on the given ports."""
    import os as _os
    my_pid = _os.getpid()
    for port in ports:
        try:
            out = subprocess.check_output(
                ["fuser", f"{port}/tcp"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for token in out.split():
            try:
                pid = int(token)
            except ValueError:
                continue
            if pid == my_pid:
                continue
            logger.warning("Killing stale process PID %d on port %d", pid, port)
            try:
                _os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _shutdown() -> None:
    """Graceful shutdown — stop child processes so ports are freed for the next start."""
    logger.info("Shutting down FlashBench backend…")
    try:
        power_controller.close()
    except Exception:
        logger.debug("power_controller.close failed", exc_info=True)
    try:
        vnc_proxy.stop()
    except Exception:
        logger.debug("vnc_proxy.stop failed", exc_info=True)
    logger.info("Shutdown complete")


def _start_board_interface_healthcheck() -> None:
    """Periodically check board interface connectivity and emit status."""
    import threading as _th
    import time as _time

    def _loop():
        last_state: bool | None = None
        while True:
            connected = power_controller.check_connection()
            if connected != last_state:
                last_state = connected
                try:
                    socketio.emit("board_interface_status", power_controller.get_status())
                except Exception:
                    pass
                if not connected:
                    logger.warning("Board Interface disconnected — attempting reconnect")
                    power_controller.init()
            _time.sleep(10)

    t = _th.Thread(target=_loop, name="BoardIfaceHealth", daemon=True)
    t.start()


def main() -> None:
    # Kill leftover processes from a previous unclean exit
    _kill_stale_port_holders(SERIAL_TCP_PORT, vnc_proxy.port, FLASK_PORT)

    # Register cleanup for graceful exit
    atexit.register(_shutdown)

    logger.info("═" * 60)
    logger.info("FlashBench Monitor backend starting")
    logger.info("  Flask-SocketIO : http://%s:%d", FLASK_HOST, FLASK_PORT)
    logger.info("  Serial TCP     : port %d", SERIAL_TCP_PORT)
    logger.info("  VNC proxy      : ws://0.0.0.0:%d", vnc_proxy.port)
    logger.info("  Board Iface    : %s", power_controller.get_status())
    logger.info("═" * 60)

    # Start background workers
    serial_listener.start()
    services_manager.start()
    vnc_proxy.start()
    module_store.start_timeout_watchdog()
    _start_board_interface_healthcheck()

    # Start Flask-SocketIO (blocking)
    socketio.run(
        app,
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=DEBUG,
        use_reloader=False,              # reloader breaks threading
        log_output=False,
        allow_unsafe_werkzeug=True,      # needed for systemd / production
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("FlashBench backend stopped by user")
    except Exception:
        logger.critical("Fatal exception in main:\n%s", traceback.format_exc())
        raise
