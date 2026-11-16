"""Domestic Intelligence Service: notifications that reach whoever is home and in earshot."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DATA,
    ATTR_IGNORE_QUIET,
    ATTR_MESSAGE,
    ATTR_SPEAKERS,
    ATTR_TITLE,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR,
    SERVICE_DELIVER,
    SERVICE_SEND,
)
from .manager import PresenceNotifyManager

type PresenceNotifyConfigEntry = ConfigEntry[PresenceNotifyManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SEND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TITLE): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_DATA, default={}): vol.Any(dict, None),
        vol.Optional(ATTR_SPEAKERS): cv.entity_ids,
        vol.Optional(ATTR_IGNORE_QUIET, default=False): cv.boolean,
    }
)
DELIVER_SCHEMA = vol.Schema({vol.Optional(ATTR_SPEAKERS): cv.entity_ids})


def _manager(hass: HomeAssistant) -> PresenceNotifyManager:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services once (independent of the config entry)."""

    async def _send(call: ServiceCall) -> None:
        data: dict[str, Any] = call.data
        await _manager(hass).async_send(
            data[ATTR_TITLE],
            data[ATTR_MESSAGE],
            data.get(ATTR_DATA) or {},
            data.get(ATTR_SPEAKERS),
            data.get(ATTR_IGNORE_QUIET, False),
        )

    async def _deliver(call: ServiceCall) -> None:
        await _manager(hass).async_deliver(call.data.get(ATTR_SPEAKERS))

    async def _clear(call: ServiceCall) -> None:
        await _manager(hass).async_clear()

    hass.services.async_register(DOMAIN, SERVICE_SEND, _send, schema=SEND_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_DELIVER, _deliver, schema=DELIVER_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_CLEAR, _clear)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PresenceNotifyConfigEntry) -> bool:
    manager = PresenceNotifyManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: PresenceNotifyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PresenceNotifyConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.async_unload()
    return unloaded
