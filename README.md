# xyaoled-control

Unofficial Python library and CLI to drive **"XYAO-LED" style 64x16 RGB BLE pixel
matrices** (the kind controlled by the *XYAO LED* phone app, advertised name
`XyaoLED...`) directly over Bluetooth Low Energy — no app required.

It can show static text, paginated and **hardware-scrolling** text, single-colour
pixel art, **full-colour images**, and **animations** (multi-frame GIF / video clips).

The BLE wire format was reverse-engineered for interoperability with hardware you own.
This project is not affiliated with or endorsed by the device vendor.

## Features

- Static text, multi-page text, smooth device-side scrolling text (any colour, any font)
- Single-colour pixel art from an image file or built-in patterns
- Full-colour images (any picture, fitted to 64x16)
- Animations from an animated GIF
- Power, brightness, clear-screen/playlist
- A capture parser for inspecting your own device's BLE traffic
- A **Home Assistant integration** (HACS-installable) — see below

## Requirements

- Python 3.10+
- [`bleak`](https://github.com/hbldh/bleak) (cross-platform BLE) and `Pillow`

```bash
pip install -r requirements.txt
```

## Quick start

The device must be powered on and **not** connected to the phone app (only one BLE
central can be connected at a time). The address is auto-discovered by name; you can
override it with `--address` or the `XYAO_ADDRESS` environment variable.

```bash
# text
python -m xyaoled.text "HELLO" --color 0,255,0
python -m xyaoled.text "a long running message" --scroll --color 255,0,0
python -m xyaoled.text "HELLO WORLD 123" --pages

# single-colour pixel art (image file or a built-in pattern)
python -m xyaoled.image heart --color 255,0,0
python -m xyaoled.image mylogo.png --color 0,128,255 --clear

# full colour + animation
python -m xyaoled.gif photo.jpg --clear
python -m xyaoled.gif animation.gif --clear

# power / brightness / clear
python -m xyaoled.ctrl --off
python -m xyaoled.ctrl --brightness 30
python -m xyaoled.ctrl --clear

# utilities
python -m xyaoled.text "CLEAR" --dry-run          # render without sending
python tools/parse_capture.py capture.pklg        # inspect a BLE capture
```

Add `--dry-run` to any command to preview the ASCII/command without connecting.
Add `--clear` to wipe the looping playlist first (each send is otherwise appended to it).

## The handshake / init frame

Every session starts with an init handshake. The device validates a small token bound
to a timestamp; it accepts a previously-captured init frame as-is. A sample frame is
bundled and works for the reference unit. **If your device does not respond** (you never
see a `88 ff 00 05 ...` notification), capture your own init frame from the official app
and provide it:

```bash
export XYAO_INIT_HEX=99aa002eff881f0000000100....   # your captured TYPE=0x0000 frame
```

`tools/parse_capture.py` helps you find it in a PacketLogger `.pklg` capture (look for
the first write whose value starts `99 aa 00 2e ff 88 1f 00 00 00 01`).

## Platform notes (BLE permissions)

- **macOS**: the terminal/app you run Python from needs the *Bluetooth* privacy
  permission (System Settings → Privacy & Security → Bluetooth). On recent macOS you
  may also need the developer "Bluetooth" logging profile to capture HCI traffic with
  PacketLogger. The BLE peripheral address is a per-machine CoreBluetooth UUID, so it is
  auto-discovered rather than hard-coded.
- **Linux**: needs BlueZ; the address is the BD_ADDR (`AA:BB:...`).
- **Windows**: works via the WinRT backend.

## Home Assistant

The repo doubles as a HACS custom repository: the
[`custom_components/xyaoled`](custom_components/xyaoled) integration exposes the panel
in Home Assistant as a light (power/brightness), a clear-screen button, a notify
entity, and `xyaoled.display_text` / `display_image` / `display_pixel_art` services.
It works with a local Bluetooth adapter or ESPHome Bluetooth proxies and auto-discovers
the panel. See [docs/home_assistant.md](docs/home_assistant.md) for install and
automation examples.

## Protocol

See [PROTOCOL.md](PROTOCOL.md) for the full reverse-engineered wire format (frame
layout, commands, 1-bit/full-colour/animation image formats, checksum).

## Disclaimer

For personal, interoperability use with your own hardware. No warranty. Sending
malformed data to embedded hardware is at your own risk. Not affiliated with the vendor.

## License

MIT — see [LICENSE](LICENSE).
