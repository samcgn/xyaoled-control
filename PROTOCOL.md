# XYAO-LED BLE protocol (64x16)

Reverse-engineered wire format for "XYAO-LED" style 64x16 RGB BLE pixel matrices
(advertised name `XyaoLED...`). Unofficial; documented for interoperability with
hardware you own. All multi-byte integers are little-endian.

## Transport (GATT)

- Control service: short UUID `0xae00`.
- Write characteristic `0xae01` (write-without-response): all commands go here.
- Notify characteristic `0xae02`: status / acknowledgements.

A long command value is split into ATT writes of at most `MTU-3` bytes; the device
reassembles them using the length field in the frame header. A single frame's length
field caps at `10000` bytes; larger payloads use a continuation command (see GIF/animation).

## Command frame

```
99 aa 00 2e ff 88 | LEN(u16) | TYPE(u16) | SEQ(u8) | params...
\___ 6-byte magic _/  total     command     counter
```

- `LEN` = total frame length including the magic and the length field.
- `SEQ` increments per logical operation; resets to 1 each connection.

### Connection handshake (required)

After connecting you must, in order:

1. Enable notifications on `0xae02` (write its CCCD `01 00`). Most BLE stacks do this
   automatically when you subscribe.
2. Send an **init** frame, `TYPE = 0x0000`:
   `99 aa 00 2e ff 88 1f 00 00 00 01 | 00 [YY MM DD HH MM SS WD] 01 00 [token:6] 00 00 00 00`
   - `YY`=year-2000, `WD`=ISO weekday.
   - The 6-byte `token` is validated by the device and is bound to the timestamp. A
     previously captured init frame is accepted as-is (the device tolerates a stale
     timestamp). The token cannot currently be computed offline, so reuse a captured
     frame for your device.

The device replies on `0xae02` with a status frame:
`88 ff 00 05 01 02 [W:u16][H:u16] 04 [power] [brightness] ...`, e.g. `40 00 10 00` = 64x16.

Without a valid handshake the device ignores all commands.

## Checksum

Device notification frames end with one byte equal to `sum(all preceding bytes) mod 256`.

## Commands

| TYPE     | Meaning            | params |
|----------|--------------------|--------|
| `0x0000` | init / handshake   | timestamp + token (see above) |
| `0x0011` | power              | `02 01 01` = off, `01 01 01` = on |
| `0x0012` | brightness         | `[level 0..100] ...` |
| `0x0005` | clear screen+playlist | `01 01 00 00 00 00` |
| `0x0204` | colour/prepare (sent before each image) | `ff 00` |
| `0x0207` | image / first chunk | see below |
| `0x0209` | image continuation | see below |

Each new image is appended to a looping on-device playlist; use `0x0005` to clear it.

## Image payload (TYPE `0x0207`)

```
[SUBLEN(u16) = payload_len - 13] [11-byte header] [pixel data]
```
Header byte offsets (relative to the payload start):

- offset 9  : frame count `N`
- offset 11 : mode — `0x03` 1-bit bitmap, `0x08` full-colour GIF, `0x00` scrolling bitmap

### 1-bit (single colour) — mode `0x03`

```
8c 00 00 02 00 02 01 00 00 [N] 00 03 00 00 00 00 [R G B] 00 00 ff 00 [SPEED] 00 [bitmap...]
```
- colour RGB at offsets 16..18.
- offset 22 : scroll flag (`0x01` = device scrolls a wide N*64 strip; `0x00` = static).
- offset 23 : per-frame display time / scroll speed.
- bitmap = `N * 128` bytes; each frame is `16 rows x 8 bytes` (64 columns), **LSB-first**:
  `column = byte_index*8 + bit_index`. For `N>1` and scroll off the frames are pages;
  with scroll on they form one horizontal strip the device scrolls.

### Full colour — mode `0x08`

```
[SUBLEN = len(GIF)] 00 02 00 01 01 00 00 01 00 08 00 [raw GIF89a, 64x16]
```
A standard single-frame GIF89a embedded directly.

### Animation — multi-frame GIF, split into `0x0207` + `0x0209`

A multi-frame GIF89a (the on-device animation). The header differs and the data is
**always** split across two commands, even when small (otherwise the device never
finalises the transfer):

- `0x0207`: `[SUBLEN = len(GIF)] 00 03 00 [4 bytes, value ignored] [N] 00 03 00 [GIF part 1]`
- `0x0209`: `[len(part2):u16] 00 02 00 [GIF part 2]`

`0x0207` carries up to ~9976 GIF bytes; the remainder goes in `0x0209`. The device acks
`0x0207` then `0x0209`, then sends a completion notify (`88 ff 05 01 ...`).
```
