#!/usr/bin/env python3
"""Interactively probe the parameter layout of the brightness command (TYPE 0x0012).

Preparation:
  1. With the phone app: set brightness to 100% and put something bright on the
     panel (or run: python -m xyaoled.text "########" --color 255,255,255).
  2. Disconnect the app (the panel accepts only one BLE central).
  3. Run from the repo root:  python tools/brightness_probe.py

The script connects once, then sends one candidate parameter layout per step,
each targeting ~50% brightness. Watch the panel and note for each step whether
it visibly dims to about half (correct layout!), goes black, or nothing changes.
Press Enter to advance; type q to quit. The last step restores 100% using the
layout you confirmed.
"""
import asyncio
import sys

sys.path.insert(0, ".")  # allow running from the repo root

from xyaoled import core  # noqa: E402
from xyaoled.core import frame  # noqa: E402

LEVEL = 50  # probe target: ~50% so both "black" and "no change" are distinguishable

CANDIDATES = [
    ("01 [level]",                bytes([0x01, LEVEL])),
    ("01 [level] 01",             bytes([0x01, LEVEL, 0x01])),
    ("[level]",                   bytes([LEVEL])),
    ("[level] 01",                bytes([LEVEL, 0x01])),
    ("[level] 01 01  (the old, wrong guess - goes black)",
                                  bytes([LEVEL, 0x01, 0x01])),
    ("01 01 [level]",             bytes([0x01, 0x01, LEVEL])),
    ("01 [level*2.55] (0-255 scale)", bytes([0x01, round(LEVEL * 2.55)])),
    ("[level*2.55] (0-255 scale)",    bytes([round(LEVEL * 2.55)])),
]


async def main() -> None:
    from bleak import BleakClient

    addr = await core.resolve_address()
    async with BleakClient(addr, timeout=20.0) as c:
        write_char = notify_char = None
        for s in c.services:
            if s.uuid.lower().startswith(core.SERVICE_PREFIX):
                for ch in s.characteristics:
                    if ch.uuid.lower().startswith(core.WRITE_CHAR_PREFIX):
                        write_char = ch
                    if ch.uuid.lower().startswith(core.NOTIFY_CHAR_PREFIX):
                        notify_char = ch
        if write_char is None:
            raise SystemExit("Control characteristic (ae01) not found.")
        if notify_char is not None:
            await c.start_notify(
                notify_char, lambda _, d: print(f"    <- notify: {bytes(d).hex(' ')}")
            )
            await asyncio.sleep(0.3)

        print("-> init handshake")
        await c.write_gatt_char(write_char, core.get_init(), response=False)
        await asyncio.sleep(1.0)

        print(f"\nProbing TYPE 0x0012 with target level {LEVEL} (~50%).")
        print("After each step check the panel: ~half brightness = correct layout.\n")

        confirmed = None
        for i, (desc, params) in enumerate(CANDIDATES, 1):
            cmd = frame(0x0012, 1, params)
            print(f"[{i}/{len(CANDIDATES)}] params: {params.hex(' '):12} ({desc})")
            print(f"          full frame: {cmd.hex(' ')}")
            await c.write_gatt_char(write_char, cmd, response=False)
            await asyncio.sleep(0.5)
            ans = await asyncio.to_thread(
                input, "          panel now? [Enter=next, y=this one works, q=quit] "
            )
            if ans.strip().lower() == "y":
                confirmed = (desc, params)
                break
            if ans.strip().lower() == "q":
                break

        if confirmed:
            desc, params = confirmed
            restore = bytearray(params)
            # replace the probe level byte with 100% on the confirmed layout
            for j, b in enumerate(params):
                if b in (LEVEL, round(LEVEL * 2.55)):
                    restore[j] = 100 if b == LEVEL else 255
            print(f"\nConfirmed layout: {desc}")
            print(f"Restoring 100%: {bytes(restore).hex(' ')}")
            await c.write_gatt_char(
                write_char, frame(0x0012, 1, bytes(restore)), response=False
            )
            await asyncio.sleep(0.5)
            print("\n>>> Please report the confirmed layout so the Home Assistant")
            print(">>> integration and PROTOCOL.md can be fixed.")
        else:
            print("\nNo candidate confirmed. Restore 100% with the phone app and")
            print("consider capturing the app's brightness slider with PacketLogger,")
            print("then: python tools/parse_capture.py capture.pklg | grep '12 00'")


if __name__ == "__main__":
    asyncio.run(main())
