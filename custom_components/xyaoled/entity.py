"""Shared entity base for the XYAO LED Panel integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import XyaoLedPanel


class XyaoLedEntity(Entity):
    """Base entity bound to one panel."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, panel: XyaoLedPanel) -> None:
        self._panel = panel
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, panel.address)},
            connections={(CONNECTION_BLUETOOTH, panel.address)},
            name="XYAO LED Panel",
            manufacturer="XYAO",
            model=f"{panel.width}x{panel.height} BLE LED matrix",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._panel.register_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        return self._panel.available
