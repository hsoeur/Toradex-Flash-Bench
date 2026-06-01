from __future__ import annotations

from datetime import datetime

from . import commands
from .usb_comm import USBComm


class PCF8563:
    SLAVE_ADDRESS = 0x51
    SECONDS_ADDRESS = 0x02
    MINUTES_ADDRESS = 0x03
    HOURS_ADDRESS = 0x04
    MONTH_DAY_ADDRESS = 0x05
    WEEK_DAY_ADDRESS = 0x06
    MONTH_ADDRESS = 0x07
    YEAR_ADDRESS = 0x08

    def __init__(self, comm: USBComm) -> None:
        self._comm = comm

    @property
    def seconds(self) -> int:
        return self._read_register(self.SECONDS_ADDRESS)

    @seconds.setter
    def seconds(self, value: int) -> None:
        self._write_register(self.SECONDS_ADDRESS, value)

    @property
    def minutes(self) -> int:
        return self._read_register(self.MINUTES_ADDRESS)

    @minutes.setter
    def minutes(self, value: int) -> None:
        self._write_register(self.MINUTES_ADDRESS, value)

    @property
    def hours(self) -> int:
        return self._read_register(self.HOURS_ADDRESS)

    @hours.setter
    def hours(self, value: int) -> None:
        self._write_register(self.HOURS_ADDRESS, value)

    @property
    def day(self) -> int:
        return self._read_register(self.MONTH_DAY_ADDRESS)

    @day.setter
    def day(self, value: int) -> None:
        self._write_register(self.MONTH_DAY_ADDRESS, value)

    @property
    def day_of_week(self) -> int:
        return self._read_register(self.WEEK_DAY_ADDRESS)

    @day_of_week.setter
    def day_of_week(self, value: int) -> None:
        self._write_register(self.WEEK_DAY_ADDRESS, value)

    @property
    def month(self) -> int:
        return self._read_register(self.MONTH_ADDRESS)

    @month.setter
    def month(self, value: int) -> None:
        self._write_register(self.MONTH_ADDRESS, value)

    @property
    def year(self) -> int:
        return self._read_register(self.YEAR_ADDRESS)

    @year.setter
    def year(self, value: int) -> None:
        self._write_register(self.YEAR_ADDRESS, value)

    def assign_to_i2c(self, scl_freq: int) -> None:
        self._comm.write_scpi_command(f"{commands.I2C_SLAVE_ADDRESS} {self.SLAVE_ADDRESS}")
        self._comm.write_scpi_command(f"{commands.I2C_SCL_FREQ} {scl_freq}")

    def start_clock(self) -> None:
        self._comm.write_scpi_command(f"{commands.I2C_WRITE_BYTE} 00,00")

    def set_datetime(self, value: datetime) -> None:
        year_to_send = value.year % 100
        data = [
            str(self.SECONDS_ADDRESS),
            f"h{value.second:02}",
            f"h{value.minute:02}",
            f"h{value.hour:02}",
            f"h{value.day:02}",
            f"{self._dotnet_day_of_week(value):02}",
            f"h{value.month:02}",
            f"h{year_to_send:02}",
        ]
        self._comm.write_scpi_command(f"{commands.I2C_WRITE_ALL_BYTES} {','.join(data)}")

    def get_datetime(self) -> datetime:
        response = self._comm.query_scpi_command(f"{commands.I2C_QUERY_N_BYTES} 2,7")
        date = response.split(",")
        if len(date) < 7:
            raise ValueError(f"Invalid PCF8563 response: {response}")

        seconds = int(date[0], 16) & 0x7F
        minutes = int(date[1], 16) & 0x7F
        hours = int(date[2], 16) & 0x3F
        day = int(date[3], 16) & 0x3F
        month = int(date[5], 16) & 0x1F
        year = int(date[6], 16) & 0xFF

        return datetime(
            self._bcd_to_dec(year) + 2000,
            self._bcd_to_dec(month),
            self._bcd_to_dec(day),
            self._bcd_to_dec(hours),
            self._bcd_to_dec(minutes),
            self._bcd_to_dec(seconds),
        )

    def _read_register(self, address: int) -> int:
        response = self._comm.query_scpi_command(f"{commands.I2C_QUERY_BYTE} {address:02}")
        return int(response)

    def _write_register(self, address: int, value: int) -> None:
        self._comm.write_scpi_command(f"{commands.I2C_WRITE_BYTE} h{address:02},{value:02}")

    @staticmethod
    def _bcd_to_dec(value: int) -> int:
        return value // 16 * 10 + value % 16

    @staticmethod
    def _dotnet_day_of_week(value: datetime) -> int:
        return (value.weekday() + 1) % 7
