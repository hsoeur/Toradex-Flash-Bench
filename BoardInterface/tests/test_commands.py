import unittest
from datetime import datetime

from board_interface import BoardInterface, SCPICommandFailedError


class FakeSerial:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.commands: list[str] = []
        self.dtr = False
        self.is_open = False

    @property
    def in_waiting(self) -> int:
        return 1 if self.responses else 0

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> int:
        self.commands.append(data.decode("ascii").strip())
        return len(data)

    def readline(self) -> bytes:
        return f"{self.responses.pop(0)}\n".encode("ascii")


class BoardInterfaceCommandTests(unittest.TestCase):
    def test_open_and_close_serial_port(self) -> None:
        serial = FakeSerial([])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.init()
        self.assertTrue(serial.is_open)

        board.close()
        self.assertFalse(serial.is_open)

    def test_context_manager_opens_and_closes_serial_port(self) -> None:
        serial = FakeSerial([])

        with BoardInterface("COM_TEST", 115200, serial_port=serial):
            self.assertTrue(serial.is_open)

        self.assertFalse(serial.is_open)

    def test_id_command(self) -> None:
        serial = FakeSerial(['HORIZON-TELECOM,61SP00091,"1.0","1.0"'])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.id, 'HORIZON-TELECOM,61SP00091,"1.0","1.0"')
        self.assertEqual(serial.commands, ["*IDN?"])

    def test_reset_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.reset()

        self.assertEqual(serial.commands, ["*RST"])

    def test_clear_errors_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.clear_errors()

        self.assertEqual(serial.commands, ["*CLS"])

    def test_get_error_command(self) -> None:
        serial = FakeSerial(["-102"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        error = board.get_error()

        self.assertEqual(error.error_code, -102)
        self.assertEqual(error.message, "Syntax error")
        self.assertEqual(serial.commands, ["SYST:ERR?"])

    def test_fixture_outputs_mask_command(self) -> None:
        serial = FakeSerial(["20"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.fixture_outputs_mask, 20)
        self.assertEqual(serial.commands, ["FIXT?"])

    def test_enable_fixture_output_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.enable_fixture_output(3)

        self.assertEqual(serial.commands, ["FIXT:ON 3"])

    def test_disable_fixture_output_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.disable_fixture_output(3)

        self.assertEqual(serial.commands, ["FIXT:OFF 3"])

    def test_power_helpers_use_fixture_commands(self) -> None:
        serial = FakeSerial(["1", "1", "1", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.power_on(0)
        board.power_off(0)
        board.power_cycle(0, off_time_s=0)

        self.assertEqual(
            serial.commands,
            ["FIXT:ON 0", "FIXT:OFF 0", "FIXT:OFF 0", "FIXT:ON 0"],
        )

    def test_active_target_get_and_set_commands(self) -> None:
        serial = FakeSerial(["4", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.active_target, 4)
        board.active_target = 2

        self.assertEqual(serial.commands, ["TARG?", "TARG 2"])

    def test_invalid_active_target_is_rejected_before_serial_write(self) -> None:
        serial = FakeSerial([])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        with self.assertRaises(ValueError):
            board.active_target = 7

        self.assertEqual(serial.commands, [])

    def test_invalid_fixture_output_is_rejected_before_serial_write(self) -> None:
        serial = FakeSerial([])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        with self.assertRaises(ValueError):
            board.enable_fixture_output(8)

        self.assertEqual(serial.commands, [])

    def test_command_failure_raises_exception(self) -> None:
        serial = FakeSerial(["-1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        with self.assertRaises(SCPICommandFailedError):
            board.reset()

        self.assertEqual(serial.commands, ["*RST"])

    def test_raw_query_and_write_commands(self) -> None:
        serial = FakeSerial(["custom response", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.query_scpi_command("CUSTOM?"), "custom response")
        board.write_scpi_command("CUSTOM 1")

        self.assertEqual(serial.commands, ["CUSTOM?", "CUSTOM 1"])

    def test_rtc_assign_to_i2c_commands(self) -> None:
        serial = FakeSerial(["1", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.rtc_module.assign_to_i2c(100000)

        self.assertEqual(serial.commands, ["I2C:SLAV 81", "I2C:FREQ 100000"])

    def test_rtc_start_clock_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.rtc_module.start_clock()

        self.assertEqual(serial.commands, ["I2C:WRIT 00,00"])

    def test_rtc_register_properties_commands(self) -> None:
        serial = FakeSerial(["12", "1", "34", "1", "22", "1", "29", "1", "3", "1", "4", "1", "26", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)
        rtc = board.rtc_module

        self.assertEqual(rtc.seconds, 12)
        rtc.seconds = 13
        self.assertEqual(rtc.minutes, 34)
        rtc.minutes = 35
        self.assertEqual(rtc.hours, 22)
        rtc.hours = 23
        self.assertEqual(rtc.day, 29)
        rtc.day = 30
        self.assertEqual(rtc.day_of_week, 3)
        rtc.day_of_week = 4
        self.assertEqual(rtc.month, 4)
        rtc.month = 5
        self.assertEqual(rtc.year, 26)
        rtc.year = 27

        self.assertEqual(
            serial.commands,
            [
                "I2C:READ? 02",
                "I2C:WRIT h02,13",
                "I2C:READ? 03",
                "I2C:WRIT h03,35",
                "I2C:READ? 04",
                "I2C:WRIT h04,23",
                "I2C:READ? 05",
                "I2C:WRIT h05,30",
                "I2C:READ? 06",
                "I2C:WRIT h06,04",
                "I2C:READ? 07",
                "I2C:WRIT h07,05",
                "I2C:READ? 08",
                "I2C:WRIT h08,27",
            ],
        )

    def test_rtc_set_datetime_command(self) -> None:
        serial = FakeSerial(["1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.rtc_module.set_datetime(datetime(2026, 4, 29, 16, 5, 7))

        self.assertEqual(serial.commands, ["I2C:WRIT:ALL 2,h07,h05,h16,h29,03,h04,h26"])

    def test_rtc_get_datetime_command(self) -> None:
        serial = FakeSerial(["07,05,16,29,03,04,26"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.rtc_module.get_datetime(), datetime(2026, 4, 29, 16, 5, 7))
        self.assertEqual(serial.commands, ["I2C:READ:ALL? 2,7"])


if __name__ == "__main__":
    unittest.main()
