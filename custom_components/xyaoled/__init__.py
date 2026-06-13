"""XYAO LED Panel - control 64x16 BLE pixel matrices from Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_INIT_HEX
from .device import XyaoLedPanel

PLATFORMS = [Platform.BUTTON, Platform.LIGHT, Platform.NOTIFY]

XyaoLedConfigEntry = ConfigEntry[XyaoLedPanel]


async def async_setup_entry(hass: HomeAssistant, entry: XyaoLedConfigEntry) -> bool:
    panel = XyaoLedPanel(
        hass,
        entry.data[CONF_ADDRESS],
        entry.options.get(CONF_INIT_HEX) or None,
    )
    entry.runtime_data = panel
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: XyaoLedConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: XyaoLedConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.disconnect()
    return unload_ok
