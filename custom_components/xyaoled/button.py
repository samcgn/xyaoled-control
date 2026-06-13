"""Button that clears the panel screen and its looping playlist."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XyaoLedConfigEntry
from .entity import XyaoLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XyaoLedConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([XyaoLedClearButton(entry.runtime_data)])


class XyaoLedClearButton(XyaoLedEntity, ButtonEntity):
    _attr_translation_key = "clear"

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._attr_unique_id = f"{panel.address}-clear"

    async def async_press(self) -> None:
        await self._panel.clear()
