"""
power_control.py — Power controller wrapper for the Board Interface.

Manages USB-serial communication with the hardware interface board to
automatically power on/off Toradex boards at each fixture position.

Mapping: POS n (1-based) → fixture output index n-1 (0-based)
"""

from __future__ import annotations

import logging
import threading
import time

from board_interface import BoardInterface
from board_interface.errors import SCPICommandFailedError

from config import (
    BOARD_INTERFACE_BAUDRATE,
    BOARD_INTERFACE_PORT,
    BOARD_INTERFACE_TIMEOUT_MS,
    POSITIONS_COUNT,
    POWER_OFF_TIME_S,
)

logger = logging.getLogger("FlashBench.Power")

MAX_RETRIES = 2
RETRY_DELAY_S = 1.0


class PowerControlError(Exception):
    """Raised when a power operation fails after all retries."""


class PowerController:
    """
    Thread-safe wrapper around BoardInterface for fixture power management.

    The serial connection is opened once at init and kept alive.  If a
    communication error occurs, the controller attempts to reconnect.
    """

    def __init__(
        self,
        port: str = BOARD_INTERFACE_PORT,
        baudrate: int = BOARD_INTERFACE_BAUDRATE,
        timeout_ms: int = BOARD_INTERFACE_TIMEOUT_MS,
        positions_count: int = POSITIONS_COUNT,
        power_off_time_s: float = POWER_OFF_TIME_S,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout_ms = timeout_ms
        self._positions_count = positions_count
        self._power_off_time_s = power_off_time_s

        self._board: BoardInterface | None = None
        self._lock = threading.Lock()
        self._connected = False

    # ── Lifecycle ────────────────────────────────────

    def init(self) -> None:
        """Open the serial connection to the interface board."""
        with self._lock:
            self._connect()

    def close(self) -> None:
        """Close the serial connection gracefully."""
        with self._lock:
            if self._board is not None:
                try:
                    self._board.close()
                except Exception:
                    pass
                self._board = None
                self._connected = False
                logger.info("Board interface connection closed")

    # ── Public API ───────────────────────────────────

    def power_on(self, position: int) -> None:
        """
        Power on the fixture output for the given position (1-based).

        Raises PowerControlError after MAX_RETRIES failed attempts.
        """
        output_index = self._position_to_index(position)
        self._execute_with_retry(
            lambda board: board.power_on(output_index),
            f"power_on(POS{position}, output={output_index})",
        )
        logger.info("Power ON | position=POS%d | output_index=%d", position, output_index)

    def power_off(self, position: int) -> None:
        """
        Power off the fixture output for the given position (1-based).

        Raises PowerControlError after MAX_RETRIES failed attempts.
        """
        output_index = self._position_to_index(position)
        self._execute_with_retry(
            lambda board: board.power_off(output_index),
            f"power_off(POS{position}, output={output_index})",
        )
        logger.info("Power OFF | position=POS%d | output_index=%d", position, output_index)

    def power_cycle(self, position: int) -> None:
        """
        Power cycle (OFF → wait → ON) for the given position (1-based).

        Raises PowerControlError after MAX_RETRIES failed attempts.
        """
        output_index = self._position_to_index(position)
        self._execute_with_retry(
            lambda board: board.power_cycle(output_index, self._power_off_time_s),
            f"power_cycle(POS{position}, output={output_index})",
        )
        logger.info(
            "Power CYCLE | position=POS%d | output_index=%d | off_time=%.1fs",
            position, output_index, self._power_off_time_s,
        )

    def check_connection(self) -> bool:
        """
        Check if the board interface is reachable by querying its identity.

        Returns True if connected and responding, False otherwise.
        """
        with self._lock:
            if self._board is None:
                return False
            try:
                _ = self._board.id
                self._connected = True
                return True
            except Exception:
                self._connected = False
                return False

    @property
    def connected(self) -> bool:
        """Last known connection state (non-blocking)."""
        return self._connected

    def get_status(self) -> dict:
        """Return a status dict for services_status emission."""
        return {
            "connected": self._connected,
            "port": self._port,
        }

    def reset_all_outputs(self) -> None:
        """
        Turn OFF all fixture outputs (positions 1 to positions_count).

        Used at startup to ensure a clean state.
        """
        for pos in range(1, self._positions_count + 1):
            try:
                self.power_off(pos)
            except PowerControlError as e:
                logger.warning("Failed to reset output for POS%d: %s", pos, e)
        logger.info("All %d fixture outputs reset (OFF)", self._positions_count)

    # ── Internals ────────────────────────────────────

    def _position_to_index(self, position: int) -> int:
        """Convert 1-based position to 0-based output index with validation."""
        if position < 1 or position > self._positions_count:
            raise PowerControlError(
                f"Invalid position {position}: must be 1–{self._positions_count}"
            )
        return position - 1

    def _connect(self) -> None:
        """Open (or re-open) the serial connection."""
        # Close existing connection if any
        if self._board is not None:
            try:
                self._board.close()
            except Exception:
                pass

        try:
            self._board = BoardInterface(
                port=self._port,
                baudrate=self._baudrate,
                timeout_ms=self._timeout_ms,
            )
            self._board.init()
            board_id = self._board.id
            self._connected = True
            logger.info(
                "Board interface connected | port=%s | id=%s",
                self._port, board_id,
            )
        except Exception as e:
            self._board = None
            self._connected = False
            logger.error(
                "Failed to connect to board interface on %s: %s",
                self._port, e,
            )

    def _reconnect(self) -> bool:
        """Attempt to reconnect. Returns True on success."""
        logger.warning("Attempting to reconnect to board interface…")
        self._connect()
        return self._connected

    def _execute_with_retry(self, operation, description: str) -> None:
        """
        Execute an operation on the board with retry logic.

        If the operation fails, attempt to reconnect and retry up to
        MAX_RETRIES times.
        """
        with self._lock:
            last_error: Exception | None = None

            for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + MAX_RETRIES retries
                if self._board is None:
                    if not self._reconnect():
                        last_error = PowerControlError(
                            f"Board interface not connected (port={self._port})"
                        )
                        if attempt <= MAX_RETRIES:
                            time.sleep(RETRY_DELAY_S)
                        continue

                try:
                    operation(self._board)
                    self._connected = True
                    return
                except (SCPICommandFailedError, OSError, IOError) as e:
                    last_error = e
                    self._connected = False
                    logger.warning(
                        "Power operation failed (attempt %d/%d): %s — %s",
                        attempt, MAX_RETRIES + 1, description, e,
                    )
                    # Try to reconnect for next attempt
                    if attempt <= MAX_RETRIES:
                        time.sleep(RETRY_DELAY_S)
                        self._reconnect()
                except Exception as e:
                    last_error = e
                    self._connected = False
                    logger.error(
                        "Unexpected error in power operation: %s — %s",
                        description, e,
                    )
                    if attempt <= MAX_RETRIES:
                        time.sleep(RETRY_DELAY_S)
                        self._reconnect()

            raise PowerControlError(
                f"{description} failed after {MAX_RETRIES + 1} attempts: {last_error}"
            )
