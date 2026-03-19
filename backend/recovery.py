"""
recovery.py — Background runner for the Toradex recovery-linux.sh script.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import traceback

from flask_socketio import SocketIO

from config import RECOVERY_SCRIPT_DIR, RECOVERY_SCRIPT_PATH

logger = logging.getLogger("FlashBench.Recovery")


class RecoveryRunner:
    """Runs recovery-linux.sh in a background thread and streams output via Socket.IO."""

    def __init__(self, socketio: SocketIO) -> None:
        self._socketio = socketio
        self._proc:   subprocess.Popen | None = None
        self._thread: threading.Thread  | None = None
        self._lock   = threading.Lock()
        self.status  = "idle"  # idle | running | success | error

    # ── Public API ───────────────────────────────

    def start(self) -> bool:
        """Start the recovery script. Returns ``False`` if already running."""
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

    # ── Internals ────────────────────────────────

    def _emit_log(self, line: str, level: str = "info") -> None:
        try:
            self._socketio.emit("recovery_log", {
                "ts":      time.time(),
                "level":   level,
                "message": line,
            })
        except Exception:
            pass

    def _emit_status(self) -> None:
        try:
            self._socketio.emit("recovery_status", self.get_status())
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
                self._emit_log(
                    f"Script terminé avec le code {proc.returncode}.", "error"
                )

        except Exception as exc:
            logger.error("RecoveryRunner error: %s", traceback.format_exc())
            self._emit_log(f"Erreur : {exc}", "error")
            with self._lock:
                self._proc  = None
                self.status = "error"

        self._emit_status()
