"""Notify entity: send a message in an automation and it appears on the panel."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XyaoLedConfigEntry
from .const import DEFAULT_COLOR
from .entity import XyaoLedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XyaoLedConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([XyaoLedNotify(entry.runtime_data)])


class XyaoLedNotify(XyaoLedEntity, NotifyEntity):
    _attr_translation_key = "panel"

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._attr_unique_id = f"{panel.address}-notify"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        text = f"{title}: {message}" if title else message
        await self._panel.display_text(text, DEFAULT_COLOR)
