"""Constants for the XYAO LED Panel integration."""

DOMAIN = "xyaoled"

CONF_INIT_HEX = "init_hex"

DEFAULT_COLOR = (255, 0, 0)
DEFAULT_TEXT_SIZE = 14
DEFAULT_SPEED = 0x3C

SERVICE_DISPLAY_TEXT = "display_text"
SERVICE_DISPLAY_IMAGE = "display_image"
SERVICE_DISPLAY_PIXEL_ART = "display_pixel_art"

ATTR_MESSAGE = "message"
ATTR_COLOR = "color"
ATTR_MODE = "mode"
ATTR_SIZE = "size"
ATTR_SPEED = "speed"
ATTR_FONT = "font"
ATTR_CLEAR = "clear"
ATTR_PATH = "path"
ATTR_FIT = "fit"
ATTR_SOURCE = "source"
ATTR_THRESHOLD = "threshold"
ATTR_INVERT = "invert"

MODE_AUTO = "auto"
MODE_STATIC = "static"
MODE_SCROLL = "scroll"
MODE_PAGES = "pages"
TEXT_MODES = [MODE_AUTO, MODE_STATIC, MODE_SCROLL, MODE_PAGES]

FIT_CONTAIN = "contain"
FIT_STRETCH = "stretch"
FIT_MODES = [FIT_CONTAIN, FIT_STRETCH]
