import unittest

from board_interface import BoardInterface


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


class BoardInterfaceTests(unittest.TestCase):
    def test_power_cycle_uses_fixture_output_commands(self) -> None:
        serial = FakeSerial(["1", "1"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        board.power_cycle(3, off_time_s=0)

        self.assertEqual(serial.commands, ["FIXT:OFF 3", "FIXT:ON 3"])

    def test_id_and_fixture_outputs_mask_query_board(self) -> None:
        serial = FakeSerial(['HORIZON-TELECOM,61SP00091,"1.0","1.0"', "20"])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        self.assertEqual(board.id, 'HORIZON-TELECOM,61SP00091,"1.0","1.0"')
        self.assertEqual(board.fixture_outputs_mask, 20)
        self.assertEqual(serial.commands, ["*IDN?", "FIXT?"])

    def test_rejects_invalid_fixture_output(self) -> None:
        serial = FakeSerial([])
        board = BoardInterface("COM_TEST", 115200, serial_port=serial)

        with self.assertRaises(ValueError):
            board.power_on(8)


if __name__ == "__main__":
    unittest.main()


