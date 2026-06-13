# Home Assistant integration

This repository ships a Home Assistant **custom integration** under
[`custom_components/xyaoled`](../custom_components/xyaoled) that exposes the panel
as a device with:

- a **light** entity — panel power on/off and brightness,
- a **button** entity — clear the screen and the on-device playlist,
- a **notify** entity — `notify.send_message` shows the message as text on the panel
  (auto-scrolls when it is wider than 64px),
- three services: `xyaoled.display_text`, `xyaoled.display_image` (full colour,
  animated GIFs supported), `xyaoled.display_pixel_art` (built-in patterns or 1-bit
  images in any colour).

It uses Home Assistant's Bluetooth stack, so it works with a local adapter **or any
ESPHome Bluetooth proxy**. Requires Home Assistant 2024.11 or newer.

## Install

### HACS (recommended)

1. HACS → three-dot menu → *Custom repositories* → add
   `https://github.com/samcgn/xyaoled-control` as type *Integration*.
2. Install **XYAO LED Panel**, restart Home Assistant.

### Manual

Copy `custom_components/xyaoled/` into your config's `custom_components/` directory
and restart.

## Setup

With Bluetooth working in Home Assistant, the panel is **auto-discovered** (it
advertises as `XyaoLED...`) and shows up under *Settings → Devices & services*.
Otherwise add it manually via *Add integration → XYAO LED Panel*.

The panel accepts only one BLE connection at a time: it must not be connected to the
phone app. The integration disconnects ~30 s after the last command so the app can be
used in between.

### Handshake / init frame

Every BLE session starts with an init handshake the device validates (see
[PROTOCOL.md](../PROTOCOL.md)). The bundled frame works for the reference unit. If
your panel ignores all commands, capture your own `TYPE=0x0000` frame from the
official app and paste it (hex) into the integration's **options**.

## Examples

Doorbell notification:

```yaml
automation:
  - alias: Doorbell on LED panel
    triggers:
      - trigger: state
        entity_id: binary_sensor.doorbell
        to: "on"
    actions:
      - action: notify.send_message
        target:
          entity_id: notify.xyao_led_panel_panel
        data:
          message: "DING DONG!"
```

Scrolling text in a specific colour:

```yaml
- action: xyaoled.display_text
  target:
    entity_id: light.xyao_led_panel
  data:
    message: "Fenster offen im Bad!"
    color: [0, 128, 255]
    mode: scroll
```

An animated GIF (the file must be inside `allowlist_external_dirs`):

```yaml
- action: xyaoled.display_image
  target:
    entity_id: light.xyao_led_panel
  data:
    path: /config/www/nyan.gif
```

Pixel art pattern:

```yaml
- action: xyaoled.display_pixel_art
  target:
    entity_id: light.xyao_led_panel
  data:
    source: heart
    color: [255, 0, 0]
```

## Notes

- Image/font paths used in service calls must be readable by Home Assistant and
  whitelisted via `allowlist_external_dirs`.
- The light's brightness is tracked optimistically (the device's status frame does
  not report it at a stable offset), so it shows the last value set by Home
  Assistant, not changes made in the phone app.
- Each displayed item is appended to the device's looping playlist; the services
  default to clearing it first (`clear: true`).
