"""ESPHome external component for XYAO-LED and iPixel Color BLE matrix panels (32x16 and 64x16)."""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import ble_client
from esphome.const import CONF_ID, CONF_WIDTH

DEPENDENCIES = ["ble_client"]
CODEOWNERS = ["@dreyfussflip"]

CONF_INIT_FRAME = "init_frame"
CONF_FONT = "font"
CONF_PROTOCOL = "protocol"
FONTS = ["mono", "sans", "bold", "italic", "narrow", "large", "tall", "slim", "small"]
# Same sample handshake as xyaoled/core.py (DEFAULT_INIT_HEX). Capture your own if the panel ignores it.
DEFAULT_INIT = "99aa002eff881f00000001001a06030b1a2f030100a1a9df647ff700000000"

xyao_led_ns = cg.esphome_ns.namespace("xyao_led")
XyaoLED = xyao_led_ns.class_("XyaoLED", cg.Component, ble_client.BLEClientNode)


def _hex(value):
    value = cv.string_strict(value).replace(" ", "").lower()
    if len(value) % 2 or any(c not in "0123456789abcdef" for c in value):
        raise cv.Invalid("init_frame must be an even-length hex string")
    if not value.startswith("99aa002eff88"):
        raise cv.Invalid("init_frame must start with 99aa002eff88")
    return value


CONFIG_SCHEMA = cv.ensure_list(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(XyaoLED),
            cv.Optional(CONF_WIDTH, default=32): cv.one_of(32, 64, int=True),
            cv.Optional(CONF_INIT_FRAME, default=DEFAULT_INIT): _hex,
            cv.Optional(CONF_FONT, default="mono"): cv.one_of(*FONTS, lower=True),
            # xyao: XYAO-LED app panels (AE01/AE02 + handshake); ipixel: iPixel Color app panels (FA02/FA03, GIF files)
            cv.Optional(CONF_PROTOCOL, default="xyao"): cv.one_of("xyao", "ipixel", lower=True),
        }
    )
    .extend(ble_client.BLE_CLIENT_SCHEMA)
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    for conf in config:
        var = cg.new_Pvariable(conf[CONF_ID])
        await cg.register_component(var, conf)
        await ble_client.register_ble_node(var, conf)
        cg.add(var.set_width(conf[CONF_WIDTH]))
        cg.add(var.set_init_hex(conf[CONF_INIT_FRAME]))
        cg.add(var.set_default_font(conf[CONF_FONT]))
        cg.add(var.set_ipixel(conf[CONF_PROTOCOL] == "ipixel"))
