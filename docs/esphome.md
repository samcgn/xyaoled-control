# ESPHome component (ESP32 bridge)

`esphome/components/xyao_led` turns a cheap ESP32 into a dedicated, always-connected
controller for one XYAO-LED panel. Home Assistant talks to the ESP32 over Wi-Fi (native
ESPHome API); the ESP32 holds the Bluetooth link to the panel. Text is rendered **on the
ESP32**, so no PC or Python is needed once it is flashed.

Use it when the panel is out of range of your Home Assistant Bluetooth, when you want many
panels around a site (one ESP32 per location), or when you want it to keep working without
the HACS integration.

Tested on a classic ESP32 (ESP32-D0WD-V3, `esp32dev`, ESP-IDF framework, ESPHome 2026.7)
with a **32x16** panel. 64x16 is supported via `width: 64` (same frame format as the Python
library) but has not been tested on hardware with this component yet.

## What you get in Home Assistant

| Entity / action | What it does |
|---|---|
| `text.<name>_message` | Type a message — short text is centred, longer text scrolls |
| `select.<name>_colour` | Colour used by the message box |
| `select.<name>_font` | `mono`, `sans`, `bold`, `italic`, `narrow`, `large`, `tall`, `slim`, `small` |
| `select.<name>_effect` | `none` or `flash` (flash works for text that fits without scrolling) |
| `number.<name>_brightness` | 0–100 |
| `switch.<name>_power` | Panel on/off, state read back from the panel |
| `button.<name>_clear` | Clear screen + on-device playlist |
| `esphome.<name>_display_text` | `message`, `red`, `green`, `blue`, `mode` (0 auto, 1 static, 2 scroll), `speed`, `font`, `effect` |
| `esphome.<name>_send_raw` | Raw command frames in hex, `\|`-separated |

Example automation:

```yaml
action: esphome.xyao_main_hall_display_text
data:
  message: "Supper in 10 minutes"
  red: 255
  green: 200
  blue: 0
  mode: 0
  speed: 0
  font: bold
  effect: flash
```

## Message syntax

| In the message | Result |
|---|---|
| `Dinner is ready!` | One line; centred if it fits, otherwise scrolls |
| `Genny\|ON 31%` | Two lines (`\|` or a newline) in the 8-row `small` font |
| `:battery: 71%` | Built-in icon, see list below |
| `:warning: GO~:battery: 23%` | Pages (`~`): the panel alternates them itself (`speed` sets the page time) |
| `:warning:[green]GO` | `[colour]` switches colour from that point on (`red`, `green`, `blue`, `yellow`, `white`, `cyan`, `magenta`, `orange` or `[#rrggbb]`) |
| `:santa:~[red]Merry\|[green]Xmas!~:sleigh:` | Animations play all their frames, even past the page time |
| `High UV\|[red]{warning}` | Text inside `{ }` blinks at 2 Hz (GIF mode) |
| `:battery_low!:23%` | `!` makes an icon blink at 2 Hz; the off phase uses the icon `<name>_off` if there is one (e.g. the battery's bottom bar blinks) |

If a page is wider than the panel, it is re-rendered in `narrow`, then `tall`, then `slim`, then `small`, before it is
clipped (single pages scroll instead, unless they fit in a narrower font). `mode: 2` forces
scrolling in the chosen font.

Icons (`esphome/tools/icons.txt`, edit and re-run `gen_font.py` to add your own):
`battery`, `bolt`, `drop`, `food`, `sun`, `moon`, `bell`, `warning`, `check`,
`cross`, `heart`, `clock`, `wifi`, `temp`, `home`, `gate`, `battery_empty`, `battery_low`.

Animated icons (colour, play in GIF mode): `rain` (cloud + falling drops), `uv` (blazing sun),
`dinnerbell` (swinging bell), `coffee` (steaming cup), `pot` (steaming pot), `shower` (water
falling from a shower head), `santa` (winks), `candle` (flickering flame), `sleigh` (reindeer and
sleigh riding across the whole panel, 15 frames), `fireworks` (rocket, burst, sparkles), `water`
(a bottle filling up), `bulb` (flickers and switches off), `night` (moon with twinkling stars),
`lollipop` (spinning swirl), `wind` (gusting lines), `cold` (thermometer dropping), `storm` (cloud with flashing lightning), `hot` (thermometer rising), `fog` (drifting mist), `hail` (cloud with falling hailstones), `fullmoon` (full moon with twinkling stars), `newmoon` (dark moon outline with stars), `campfire` (flickering fire on logs), `smile` (winking smiley), `broom` (sweeping broom). An icon is animated
when `icons.txt` has numbered frames `name_1`, `name_2`, … instead of `name`; a colour pair after
the name (e.g. `rain_1 white blue`) fixes the icon's top/bottom-half colours.

Plain messages are sent as a 1-bit image (one colour). Messages that use `[colour]` tags or
blinking icons are rendered on the ESP32 as a full-colour **GIF animation** (per-pixel colour,
exact frame timing; up to 7 colours per message). Example, as used for a generator alert:

```
:warning:[green]GO~:battery_low!:[white]23%
```

shows a red warning sign with a green "GO", then a red empty battery whose bottom bar blinks
twice a second beside a white "23%" (with `red: 255` as the base colour). In GIF mode `speed`
is the page time in tenths of a second (default 25 = 2.5 s).

## Setup

1. Find the panel's Bluetooth address (it advertises as `XyaoLED_xxxx`; nRF Connect or the
   ESPHome BLE tracker log will show it). Close the phone app — the panel accepts only one
   connection at a time.
2. Copy [`esphome/xyaoled-display.yaml`](../esphome/xyaoled-display.yaml), set `name`,
   `panel_mac` and `panel_width`, and add `wifi_ssid` / `wifi_password` to `secrets.yaml`.
3. Flash it (`esphome run xyaoled-display.yaml`) and adopt the device in Home Assistant.

On every (re)connect the component enables notifications on `AE02`, waits for the CCCD
write, then sends the init handshake. If your panel never reports a status in the log
(`status: 32x16 power=ON`) and ignores commands, capture your own `TYPE=0x0000` frame
(see the main README) and set `init_frame:`.

### iPixel Color panels

Some identical-looking 32x16 boards (e.g. marked `TR231HII9-07 16*32`) ship with the **iPixel Color**
app instead and advertise as `LED_BLE_xxxxxxxx`. They also expose `AE01`/`AE02` but ignore the XYAO
handshake; set `protocol: ipixel` for them:

```yaml
xyao_led:
  - id: panel2
    ble_client_id: panel2_ble
    protocol: ipixel
```

The component then writes GIF files to `FA02` (acknowledged writes, 244-byte chunks) and listens on
`FA03`; no handshake is needed. Everything else — fonts, icons, colours, blinking, animations — works the
same, because every message is rendered as a GIF. Power and brightness use the iPixel commands.
Long single-colour text does not scroll on these panels yet (it is fitted with the narrowest font).
Protocol details come from [lucagoc/pypixelcolor](https://github.com/lucagoc/pypixelcolor).

### Several panels on one ESP32

See [`esphome/xyaoled-multi.yaml`](../esphome/xyaoled-multi.yaml) for a complete example (one XYAO + two iPixel panels).

Add one `ble_client` and one `xyao_led` entry per panel (each with its own `id`) and an API action per
panel calling `id(panelN).display_text(...)`. Each panel keeps its own last message and resends it after
reconnecting, staggered 6 s apart.

## Notes

- **One BLE connection per panel.** While the ESP32 is connected the phone app cannot connect.
- **Many panels.** ESPHome allows up to 9 BLE connections per ESP32 (`esp32_ble: max_connections`),
  but with Wi-Fi active 3–4 is a realistic maximum, and BLE range (≈10–30 m indoors) usually
  decides it. For panels spread over a site, use one ESP32 per location and give each a
  descriptive `name`.
- **Reconnects.** The panel forgets its content when it loses power; the ESP32 re-sends the last
  message automatically after it reconnects (the message is kept in flash, so this also works after
  the ESP32 itself restarts).
- **Playlist.** Each image is appended to the panel's looping playlist, so `display_text`
  always clears first.
- **Fonts.** `xyao_font.h` holds nine bitmap fonts generated from the DejaVu family by
  [`esphome/tools/gen_font.py`](../esphome/tools/gen_font.py): `mono`, `sans` (proportional, fits
  more), `bold`, `italic`, `narrow`, `tall` (narrow letters with hand-drawn 13-row digits from
  `esphome/tools/tall_digits.txt`, good for numbers next to an icon), `slim` (DejaVu Sans Condensed
  15 px squeezed to 70 % width: tall letters at ~5 px wide, for words next to an icon), `large` (16 px, ~2 characters on a 32-wide panel) and `small` (8 rows, used for
  two-line messages, ~6 characters per line on a 32-wide panel).
  ASCII 32–126; other characters render as `?`. Set the default with `font:` on `xyao_led`.
- **Flash.** `effect: flash` sends a two-frame animation (text, blank) that the panel loops
  itself; `speed` sets the blink rate (default 20).
- **Don't use the same ESP32 as a Bluetooth proxy for this panel** if Home Assistant's own
  `xyaoled` integration is also installed — both would compete for the single connection.

## 32x16 panels

The 32x16 variant uses the same `99 aa 00 2e ff 88` command frames, handshake and image
format as the 64x16 panel. Differences seen so far:

- Status notify after the handshake starts `88 ff 00 03 01 01 20 00 10 00 04 …`
  (type `00 03` instead of `00 05`, width `0x20` = 32). Byte 11 is power: `01` on, `00` off.
- 1-bit bitmaps are 16 rows × 4 bytes = 64 bytes per frame (LSB = leftmost pixel), and the
  payload's `SUBLEN` is `12 + n*64`.
- Other notifies observed while uploading: `88 ff 03 00 …`, `88 ff 03 01 …` (per-command acks)
  and `88 ff 05 01 …` (image complete), as on the 64x16 panel.
- The bundled sample handshake was accepted by a 32x16 panel unchanged.
