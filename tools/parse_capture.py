#!/usr/bin/env python3
"""
Parse an Apple PacketLogger (.pklg) BLE capture and print the ATT writes/notifies
on the control characteristics. Useful for inspecting your own device's traffic.

    python tools/parse_capture.py capture.pklg
    python tools/parse_capture.py capture.pklg --all   # include notifications

Note: PacketLogger files are little-endian on Apple-silicon hosts; this reader
handles that layout. It reassembles L2CAP fragments and frames split by length.
"""
import struct
import sys

ATT_OPS = {0x12: "WriteReq", 0x52: "WriteCmd", 0x1B: "Notify", 0x1D: "Indicate", 0x0B: "ReadResp"}


def read_records(path):
    data = open(path, "rb").read()
    off = 0
    while off + 13 <= len(data):
        length = struct.unpack_from("<I", data, off)[0]
        if length < 9 or off + 4 + length > len(data):
            break
        ts = struct.unpack_from("<I", data, off + 4)[0] + struct.unpack_from("<I", data, off + 8)[0] / 1e6
        yield ts, data[off + 12], data[off + 13:off + 4 + length]
        off += 4 + length


def reassemble(records, direction_type):
    out, cur = [], None
    for ts, t, p in records:
        if t != direction_type:
            continue
        pb = (struct.unpack_from("<H", p, 0)[0] >> 12) & 3
        acl = p[4:]
        if pb in (0, 2):
            l2len, cid = struct.unpack_from("<HH", acl, 0)
            body = acl[4:]
            if len(body) >= l2len:
                out.append((ts, cid, body[:l2len]))
            else:
                cur = [ts, cid, bytearray(body), l2len]
        elif pb == 1 and cur:
            cur[2] += acl
            if len(cur[2]) >= cur[3]:
                out.append((cur[0], cur[1], bytes(cur[2][:cur[3]])))
                cur = None
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    show_all = "--all" in sys.argv
    records = list(read_records(sys.argv[1]))
    t0 = None
    for tag, dt in (("APP->DEV", 0x02), ("DEV->APP", 0x03)):
        for ts, cid, a in reassemble(records, dt):
            if cid != 0x0004 or not a:
                continue
            op = a[0]
            if op not in (0x12, 0x52, 0x1B, 0x1D, 0x0B):
                continue
            if not show_all and op in (0x1B, 0x1D):
                continue
            handle = struct.unpack_from("<H", a, 1)[0] if len(a) >= 3 else 0
            val = a[3:]
            if t0 is None:
                t0 = ts
            print(f"[{ts - t0:8.3f}s] {tag} {ATT_OPS.get(op, hex(op)):9} h=0x{handle:04x} "
                  f"len={len(val):4}  {val.hex(' ')}")


if __name__ == "__main__":
    main()
