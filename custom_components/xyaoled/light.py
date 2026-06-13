"""Light entity (power + brightness) and the display_* entity services."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XyaoLedConfigEntry
from .const import (
    ATTR_CLEAR,
    ATTR_COLOR,
    ATTR_FIT,
    ATTR_FONT,
    ATTR_INVERT,
    ATTR_MESSAGE,
    ATTR_MODE,
    ATTR_PATH,
    ATTR_SIZE,
    ATTR_SOURCE,
    ATTR_SPEED,
    ATTR_THRESHOLD,
    DEFAULT_COLOR,
    DEFAULT_SPEED,
    DEFAULT_TEXT_SIZE,
    FIT_CONTAIN,
    FIT_MODES,
    MODE_AUTO,
    SERVICE_DISPLAY_IMAGE,
    SERVICE_DISPLAY_PIXEL_ART,
    SERVICE_DISPLAY_TEXT,
    TEXT_MODES,
)
from .entity import XyaoLedEntity
from .render import PATTERNS

COLOR_SCHEMA = vol.All(
    cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(min=3, max=3)
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XyaoLedConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([XyaoLedLight(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_DISPLAY_TEXT,
        {
            vol.Required(ATTR_MESSAGE): cv.string,
            vol.Optional(ATTR_COLOR, default=list(DEFAULT_COLOR)): COLOR_SCHEMA,
            vol.Optional(ATTR_MODE, default=MODE_AUTO): vol.In(TEXT_MODES),
            vol.Optional(ATTR_SIZE, default=DEFAULT_TEXT_SIZE): vol.All(
                vol.Coerce(int), vol.Range(min=6, max=16)
            ),
            vol.Optional(ATTR_SPEED, default=DEFAULT_SPEED): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=255)
            ),
            vol.Optional(ATTR_FONT): cv.string,
            vol.Optional(ATTR_CLEAR, default=True): cv.boolean,
        },
        "async_display_text",
    )
    platform.async_register_entity_service(
        SERVICE_DISPLAY_IMAGE,
        {
            vol.Required(ATTR_PATH): cv.string,
            vol.Optional(ATTR_FIT, default=FIT_CONTAIN): vol.In(FIT_MODES),
            vol.Optional(ATTR_CLEAR, default=True): cv.boolean,
        },
        "async_display_image",
    )
    platform.async_register_entity_service(
        SERVICE_DISPLAY_PIXEL_ART,
        {
            vol.Required(ATTR_SOURCE): cv.string,
            vol.Optional(ATTR_COLOR, default=list(DEFAULT_COLOR)): COLOR_SCHEMA,
            vol.Optional(ATTR_THRESHOLD, default=128): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=255)
            ),
            vol.Optional(ATTR_INVERT, default=False): cv.boolean,
            vol.Optional(ATTR_FIT, default=FIT_CONTAIN): vol.In(FIT_MODES),
            vol.Optional(ATTR_CLEAR, default=True): cv.boolean,
        },
        "async_display_pixel_art",
    )


class XyaoLedLight(XyaoLedEntity, LightEntity):
    """Power + brightness of the panel, optimistic state."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_name = None
    _attr_assumed_state = True

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._attr_unique_id = f"{panel.address}-light"

    @property
    def is_on(self) -> bool:
        return self._panel.power

    @property
    def brightness(self) -> int | None:
        if self._panel.brightness is None:
            return None
        return round(self._panel.brightness * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            await self._panel.set_brightness(round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
        if not self._panel.power or ATTR_BRIGHTNESS not in kwargs:
            await self._panel.set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._panel.set_power(False)

    # ------------------------------------------------------------ entity services

    async def async_display_text(
        self,
        message: str,
        color: list[int],
        mode: str,
        size: int,
        speed: int,
        clear: bool,
        font: str | None = None,
    ) -> None:
        await self._panel.display_text(
            message, tuple(color), mode=mode, size=size, speed=speed, font=font, clear=clear
        )

    async def async_display_image(self, path: str, fit: str, clear: bool) -> None:
        self._check_path(path)
        await self._panel.display_image(path, fit=fit, clear=clear)

    async def async_display_pixel_art(
        self,
        source: str,
        color: list[int],
        threshold: int,
        invert: bool,
        fit: str,
        clear: bool,
    ) -> None:
        if source not in PATTERNS:
            self._check_path(source)
        await self._panel.display_pixel_art(
            source, tuple(color), threshold=threshold, invert=invert, fit=fit, clear=clear
        )

    def _check_path(self, path: str) -> None:
        if not self.hass.config.is_allowed_path(path):
            raise HomeAssistantError(
                f"Path '{path}' is not allowed; add its directory to "
                "'allowlist_external_dirs' in configuration.yaml"
            )
