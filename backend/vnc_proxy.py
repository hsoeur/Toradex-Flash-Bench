"""
vnc_proxy.py — Manages a websockify process that proxies
WebSocket connections from the browser to VNC servers on the boards.

Uses a single websockify instance with the TokenFile plugin (re-reads the
token configuration file on every incoming connection).
Each flashing board gets a token entry mapping its IP to its VNC port (5900).

The frontend connects via:
    ws://<backend_host>:6080/?token=<board_ip>

and websockify forwards that to:
    <board_ip>:5900
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading

logger = logging.getLogger("FlashBench.VncProxy")

VNC_PORT = 5900
WEBSOCKIFY_PORT = 6080
TOKEN_FILE = "/tmp/flashbench_vnc_tokens.cfg"


class VncProxyManager:
    """Manages a single websockify process with dynamic token file updates."""

    def __init__(self, websockify_port: int = WEBSOCKIFY_PORT) -> None:
        self._port = websockify_port
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._active_ips: set[str] = set()
        self._running = False

    # ── lifecycle ─────────────────────────────────

    def start(self) -> None:
        """Start the websockify proxy process.

        Any pre-existing websockify that kept port occupied from a
        previous unclean shutdown is killed first.
        """
        self._kill_process()           # clean up leftover child
        self._write_token_file(set())
        self._start_process()
        self._running = True

    def stop(self) -> None:
        """Stop the websockify proxy process."""
        self._running = False
        self._kill_process()
        try:
            os.unlink(TOKEN_FILE)
        except OSError:
            pass

    def _start_process(self) -> None:
        """Launch the websockify subprocess."""
        python = sys.executable

        # Use --token-plugin=TokenFile so the file is re-read on every
        # incoming connection (unlike --target-config which caches).
        cmd = [
            python, "-m", "websockify",
            f"0.0.0.0:{self._port}",
            "--token-plugin", "TokenFile",
            "--token-source", TOKEN_FILE,
            "-v",
        ]

        logger.info("websockify cmd: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            logger.info(
                "websockify started on port %d (pid=%d)",
                self._port,
                self._process.pid,
            )

            # Background thread to drain and log websockify output
            t = threading.Thread(
                target=self._log_output,
                daemon=True,
                name="websockify-logger",
            )
            t.start()

        except Exception:
            logger.exception("Failed to start websockify")

    def _kill_process(self) -> None:
        """Terminate the websockify subprocess."""
        if self._process and self._process.poll() is None:
            try:
                self._process.send_signal(signal.SIGTERM)
                self._process.wait(timeout=5)
                logger.info("websockify stopped")
            except subprocess.TimeoutExpired:
                self._process.kill()
                logger.warning("websockify killed (didn't stop gracefully)")
            except Exception:
                logger.exception("Error stopping websockify")
        self._process = None

    def _log_output(self) -> None:
        """Background thread that reads websockify stdout/stderr."""
        proc = self._process
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.debug("websockify: %s", line)
        except Exception:
            pass

    # ── module store callback ─────────────────────

    def on_modules_changed(self, snapshot: dict) -> None:
        """
        Called whenever the module store changes.
        Updates the token file with IPs of all active boards.
        websockify re-reads the file on each new WS connection (TokenFile plugin).

        Tokens are kept for **all** board statuses (waiting, flashing, done,
        error) so the VNC viewer can connect at any point during the lifecycle
        — in particular, this avoids a race between the token-file write and
        the first VNC connection attempt that systematically failed for the
        first board of a session.
        """
        active_ips = {
            ip
            for ip, data in snapshot.items()
            if data.get("status") in ("waiting", "flashing", "done", "error")
        }

        with self._lock:
            if active_ips != self._active_ips:
                self._active_ips = set(active_ips)
                self._write_token_file(active_ips)
                logger.info(
                    "VNC targets updated: %s",
                    sorted(active_ips) if active_ips else "(none)",
                )

        # Restart websockify if it died unexpectedly
        if self._running and self._process and self._process.poll() is not None:
            logger.warning(
                "websockify died (exit code %d) — restarting",
                self._process.returncode,
            )
            self._start_process()

    # ── token file management ─────────────────────

    @staticmethod
    def _write_token_file(ips: set[str]) -> None:
        """Write the websockify token file.  Format: ``token: host:port``."""
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                for ip in sorted(ips):
                    f.write(f"{ip}: {ip}:{VNC_PORT}\n")
        except Exception:
            logger.exception("Failed to write token file %s", TOKEN_FILE)

    @property
    def port(self) -> int:
        return self._port

    @property
    def active_ips(self) -> set[str]:
        with self._lock:
            return set(self._active_ips)
