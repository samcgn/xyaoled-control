"""Power, brightness and clear-screen control.

    python -m xyaoled.ctrl --on
    python -m xyaoled.ctrl --off
    python -m xyaoled.ctrl --brightness 30
    python -m xyaoled.ctrl --clear
"""
import argparse
import asyncio

from . import core


def main(argv=None):
    ap = argparse.ArgumentParser(description="Power/brightness/clear control for a XYAO-LED panel.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true", help="panel power on")
    g.add_argument("--off", action="store_true", help="panel power off")
    g.add_argument("--brightness", type=int, metavar="LEVEL", help="brightness 0..100")
    g.add_argument("--clear", action="store_true", help="clear screen + playlist")
    ap.add_argument("--address", default=None)
    a = ap.parse_args(argv)

    if a.brightness is not None and not 0 <= a.brightness <= 100:
        ap.error("brightness must be 0..100")

    if a.clear:
        cmds = [core.clear_cmd()]
    elif a.brightness is not None:
        cmds = [core.brightness_cmd(a.brightness)]
    else:
        cmds = [core.power_cmd(a.on)]
    asyncio.run(core.send(cmds, address=a.address,
                          on_notify=lambda _, d: print("notify:", bytes(d).hex(" "))))


if __name__ == "__main__":
    main()
