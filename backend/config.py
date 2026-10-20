"""
config.py — Centralised configuration for the FlashBench backend.
"""

from __future__ import annotations

import os

# ── Paths ────────────────────────────────────────

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR  = os.path.join(BASE_DIR, "logs")

# ── Flask / SocketIO ─────────────────────────────

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5001
SECRET_KEY = "flashbench-secret"
DEBUG      = False

# ── Logging ──────────────────────────────────────

LOG_RETENTION_DAYS = 30
LOG_BUFFER_MAXLEN  = 500

# ── External traceability API ────────────────────

EXTERNAL_API_URL   = "http://localhost:10000"
PRODUCT_UID        = "04IN00145"
MACHINE_UID        = "MO03B"
OPERATION_NUMBER   = 30
UNIT_UID           = "STR"
TRACE_LABEL        = "PROG_TORADEX"
TRACE_LABEL_IMAGE  = "IMAGE_TORADEX"

# ── Recovery script (Toradex Easy Installer) ─────

RECOVERY_SCRIPT_DIR = os.path.abspath(
    os.path.join(BASE_DIR, "..",
                 "Verdin-AM62_ToradexEasyInstaller_7.4.0+build.8")
)
RECOVERY_SCRIPT_PATH = os.path.join(RECOVERY_SCRIPT_DIR, "recovery-linux.sh")

# ── Nginx / Tezi images ─────────────────────────

IMAGE_ROOT      = "/var/www/html"
IMAGE_LIST_FILE = os.path.join(IMAGE_ROOT, "image_list.json")

# ── Board Interface (power control) ──────────────

BOARD_INTERFACE_PORT       = os.environ.get("BOARD_INTERFACE_PORT", "/dev/ttyACM0")
BOARD_INTERFACE_BAUDRATE   = int(os.environ.get("BOARD_INTERFACE_BAUDRATE", "115200"))
BOARD_INTERFACE_TIMEOUT_MS = int(os.environ.get("BOARD_INTERFACE_TIMEOUT_MS", "10000"))
POWER_OFF_TIME_S           = float(os.environ.get("POWER_OFF_TIME_S", "1.0"))
POSITIONS_COUNT            = 5   # POS1→output0 … POS5→output4

# ── Flash timeout ────────────────────────────────
# If a board stays in WAITING or FLASHING for longer than this
# duration (seconds) it is automatically marked as ERROR.
# Default: 20 minutes = 1200 s
FLASH_TIMEOUT_S = int(os.environ.get("FLASH_TIMEOUT_S", "1200"))

# ── Network ports ────────────────────────────────

SERIAL_TCP_HOST = "0.0.0.0"
SERIAL_TCP_PORT = 5000
