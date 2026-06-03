"""
Core protocol + BLE transport for XYAO-LED style 64x16 BLE pixel matrices.

Reverse-engineered, unofficial. No affiliation with the vendor. For use with
hardware you own. See PROTOCOL.md for the wire format.
"""
import asyncio
import os

from bleak import BleakClient, BleakScanner

# Panel geometry
W, H = 64, 16

# BLE identifiers (16-bit shorts inside the standard base UUID)
NAME_PREFIX = "XyaoLED"          # advertised device-name prefix used for auto-discovery
SERVICE_PREFIX = "0000ae00"      # control service
WRITE_CHAR_PREFIX = "0000ae01"   # write commands here (write-without-response)
NOTIFY_CHAR_PREFIX = "0000ae02"  # status/ack notifications

# Every command frame starts with this constant header (magic + protocol constant).
MAGIC = bytes.fromhex("99aa002eff88")

# Known-good handshake (command type 0x0000). The device validates a token that is
# bound to the timestamp embedded in this frame, so an exact, previously-captured
# frame is required. The bundled sample works for the reference unit; if your device
# rejects it (you never get a "88 ff 00 05 ..." notify), capture your own init frame
# from the official app and provide it via the XYAO_INIT_HEX environment variable.
DEFAULT_INIT_HEX = "99aa002eff881f00000001001a06030b1a2f030100a1a9df647ff700000000"


def get_init() -> bytes:
    return bytes.fromhex(os.environ.get("XYAO_INIT_HEX", DEFAULT_INIT_HEX))


def frame(type_le: int, seq: int, params: bytes) -> bytes:
    """Build a command frame: MAGIC + total_len(u16) + type(u16) + seq + params."""
    rest = type_le.to_bytes(2, "little") + bytes([seq & 0xFF]) + bytes(params)
    total = len(MAGIC) + 2 + len(rest)
    return MAGIC + total.to_bytes(2, "little") + rest


def clear_cmd(seq: int = 1) -> bytes:
    """Clear screen + playlist (command type 0x0005)."""
    return frame(0x0005, seq, bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00]))


def checksum(data: bytes) -> int:
    """Device notification frames end with sum(of preceding bytes) mod 256."""
    return sum(data) & 0xFF


async def resolve_address(address: str | None = None) -> str:
    """Address from arg -> XYAO_ADDRESS env -> BLE scan by name prefix."""
    address = address or os.environ.get("XYAO_ADDRESS")
    if address:
        return address
    print(f"Scanning for {NAME_PREFIX}* ...")
    devices = await BleakScanner.discover(timeout=8.0)
    for d in devices:
        if d.name and d.name.startswith(NAME_PREFIX):
            print(f"Found {d.name} @ {d.address}")
            return d.address
    raise SystemExit(
        f"No '{NAME_PREFIX}*' device found. Make sure it is on and not connected to "
        f"the phone app, or set XYAO_ADDRESS / pass --address."
    )


async def send(cmds, clear_first=False, address=None, do_init=True, on_notify=None):
    """Connect, run the handshake, optionally clear, then write the given command frames.

    Large frames are split into <=512-byte ATT writes; the device reassembles them by
    the length field in each frame's header.
    """
    addr = await resolve_address(address)
    async with BleakClient(addr, timeout=20.0) as c:
        write_char = notify_char = None
        for s in c.services:
            if s.uuid.lower().startswith(SERVICE_PREFIX):
                for ch in s.characteristics:
                    if ch.uuid.lower().startswith(WRITE_CHAR_PREFIX):
                        write_char = ch
                    if ch.uuid.lower().startswith(NOTIFY_CHAR_PREFIX):
                        notify_char = ch
        if write_char is None:
            raise SystemExit("Control characteristic (ae01) not found on this device.")

        if notify_char is not None:
            await c.start_notify(notify_char, on_notify or (lambda *_: None))
            await asyncio.sleep(0.3)

        chunk = min(512, (getattr(c, "mtu_size", 515) or 515) - 3)

        if do_init:
            await c.write_gatt_char(write_char, get_init(), response=False)
            await asyncio.sleep(1.0)
        if clear_first:
            await c.write_gatt_char(write_char, clear_cmd(), response=False)
            await asyncio.sleep(0.7)

        for cmd in cmds:
            for i in range(0, len(cmd), chunk):
                await c.write_gatt_char(write_char, cmd[i:i + chunk], response=False)
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.35)
        await asyncio.sleep(1.0)
