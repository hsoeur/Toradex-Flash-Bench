from __future__ import annotations

from pathlib import Path

from . import commands
from .errors import SCPIError
from .pcf8563 import PCF8563
from .usb_comm import SerialLike, USBComm


class BoardInterface:
    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout_ms: int = 10_000,
        serial_port: SerialLike | None = None,
        log_file: str | Path | None = None,
    ) -> None:
        self._comm = USBComm(port, baudrate, timeout_ms, serial_port, log_file)
        self.rtc_module = PCF8563(self._comm)

    @property
    def timeout_ms(self) -> int:
        return self._comm.timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._comm.timeout_ms = value

    @property
    def id(self) -> str:
        return self.query_scpi_command(commands.IDN)

    @property
    def fixture_outputs_mask(self) -> int:
        return int(self.query_scpi_command(commands.QUERY_FIXTURE))

    @property
    def active_target(self) -> int:
        return int(self.query_scpi_command(f"{commands.TARGET}?"))

    @active_target.setter
    def active_target(self, value: int) -> None:
        if value > 6:
            raise ValueError("6 targets maximum")
        if value < 0:
            raise ValueError("target index cannot be negative")

        self.write_scpi_command(f"{commands.TARGET} {value}")

    def init(self) -> None:
        self._comm.open()

    def close(self) -> None:
        self._comm.close()

    def enable_fixture_output(self, index: int) -> None:
        self._validate_fixture_index(index)
        self.write_scpi_command(f"{commands.FIXTURE_OUTPUT_ON} {index}")

    def disable_fixture_output(self, index: int) -> None:
        self._validate_fixture_index(index)
        self.write_scpi_command(f"{commands.FIXTURE_OUTPUT_OFF} {index}")

    def power_on(self, output_index: int) -> None:
        self.enable_fixture_output(output_index)

    def power_off(self, output_index: int) -> None:
        self.disable_fixture_output(output_index)

    def power_cycle(self, output_index: int, off_time_s: float = 1.0) -> None:
        import time

        self.power_off(output_index)
        time.sleep(off_time_s)
        self.power_on(output_index)

    def write_scpi_command(self, command: str) -> None:
        self._comm.write_scpi_command(command)

    def query_scpi_command(self, command: str) -> str:
        return self._comm.query_scpi_command(command)

    def get_error(self) -> SCPIError:
        return SCPIError(int(self.query_scpi_command(commands.QUERY_LAST_ERROR)))

    def clear_errors(self) -> None:
        self.write_scpi_command(commands.CLEAR_STATUS)

    def reset(self) -> None:
        self.write_scpi_command(commands.RESET)

    def __enter__(self) -> BoardInterface:
        self.init()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @staticmethod
    def _validate_fixture_index(index: int) -> None:
        if index < 0 or index > 7:
            raise ValueError("fixture output index must be between 0 and 7 included")


InterfaceBoard = BoardInterface

