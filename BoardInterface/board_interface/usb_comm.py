from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from .errors import SCPICommandFailedError


COMMAND_FAILED = "-1"
COMMAND_SUCCESS = "1"


class SerialLike(Protocol):
    dtr: bool
    in_waiting: int

    def open(self) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> int | None: ...
    def readline(self) -> bytes: ...


class USBComm:
    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout_ms: int = 10_000,
        serial_port: SerialLike | None = None,
        log_file: str | Path | None = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.log_file = Path(log_file) if log_file else None

        if serial_port is not None:
            self._serial_port = serial_port
            return

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is required for InterfaceBoard. Install it with: pip install pyserial"
            ) from exc

        self._serial_port = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            timeout=10,
            write_timeout=1,
            rtscts=False,
        )
        self._serial_port.dtr = False

    def open(self) -> None:
        if hasattr(self._serial_port, "is_open") and self._serial_port.is_open:
            return

        self._serial_port.open()
        if self.log_file is not None:
            self.log_file.touch(exist_ok=True)

    def close(self) -> None:
        self._serial_port.close()

    def write_scpi_command(self, command: str) -> None:
        response = self.query_scpi_command(command)
        if response != COMMAND_SUCCESS:
            raise SCPICommandFailedError(command)

    def query_scpi_command(self, command: str) -> str:
        command = command.rstrip()
        self._serial_port.dtr = True
        self._serial_port.write(f"{command}\n".encode("ascii"))
        self._log("SEND", command)

        deadline = time.monotonic() + (self.timeout_ms / 1000)
        while self._serial_port.in_waiting == 0 and time.monotonic() < deadline:
            time.sleep(0.001)

        if self._serial_port.in_waiting == 0:
            raise TimeoutError("Interface board has not responded in time")

        raw_response = self._serial_port.readline()
        self._serial_port.dtr = False

        response = raw_response.decode("ascii", errors="replace").strip()
        self._log("RECEIVED", response)

        if response == COMMAND_FAILED:
            raise SCPICommandFailedError(command)

        return response

    def _log(self, direction: str, data: str) -> None:
        if self.log_file is None:
            return

        timestamp = time.strftime("%c")
        with self.log_file.open("a", encoding="utf-8") as stream:
            stream.write(f"<{timestamp}> [Carte interface] {direction} {data}\n")
