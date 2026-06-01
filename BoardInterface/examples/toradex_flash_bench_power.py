from __future__ import annotations

import argparse
import time

from board_interface import BoardInterface


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Control Toradex board power with the InterfaceBoard."
    )
    parser.add_argument("--port", required=True, help="Serial port, for example COM3")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument(
        "--power-output",
        type=int,
        required=True,
        help="Fixture output wired to the Toradex board power relay, from 0 to 7",
    )
    parser.add_argument("--off-time", type=float, default=1.0)
    parser.add_argument(
        "--action",
        choices=["on", "off", "cycle"],
        default="cycle",
    )
    args = parser.parse_args()

    with BoardInterface(args.port, args.baudrate) as board:
        print(f"BoardInterface: {board.id}")

        if args.action == "on":
            board.power_on(args.power_output)
        elif args.action == "off":
            board.power_off(args.power_output)
        else:
            board.power_cycle(args.power_output, args.off_time)

        time.sleep(0.1)
        print(f"Fixture outputs mask: {board.fixture_outputs_mask}")


if __name__ == "__main__":
    main()



