"""Domestic Intelligence Service: notifications that reach whoever is home and in earshot."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ACTIONS,
    ATTR_ANNOUNCEMENT,
    ATTR_DATA,
    ATTR_IGNORE_QUIET,
    ATTR_MESSAGE,
    ATTR_PRIORITY,
    ATTR_PUSH_TO,
    ATTR_QUESTION,
    ATTR_RECIPIENTS,
    ATTR_REMIND_EVERY,
    ATTR_REMINDER,
    ATTR_REMOVE_AFTER,
    ATTR_SPEAKERS,
    ATTR_STORE,
    ATTR_TAG,
    ATTR_TEXT_NO,
    ATTR_TEXT_YES,
    ATTR_TIMEOUT,
    ATTR_TITLE,
    DOMAIN,
    PLATFORMS,
    PRIORITIES,
    PRIORITY_NORMAL,
    PUSH_TO_OPTIONS,
    SERVICE_ASK,
    SERVICE_CLEAR,
    SERVICE_DELIVER,
    SERVICE_REMOVE,
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
        vol.Optional(ATTR_PRIORITY, default=PRIORITY_NORMAL): vol.In(PRIORITIES),
        vol.Optional(ATTR_TAG): cv.string,
        vol.Optional(ATTR_STORE, default=True): cv.boolean,
        vol.Optional(ATTR_REMOVE_AFTER): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1440)),
        vol.Optional(ATTR_PUSH_TO): vol.In(PUSH_TO_OPTIONS),
        vol.Optional(ATTR_RECIPIENTS): cv.entity_ids,
        vol.Optional(ATTR_ANNOUNCEMENT): cv.string,
        vol.Optional(ATTR_REMINDER, default=False): cv.boolean,
        vol.Optional(ATTR_REMIND_EVERY): vol.All(vol.Coerce(float), vol.Range(min=1, max=1440)),
        vol.Optional(ATTR_ACTIONS): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("title"): cv.string,
                        vol.Optional("action"): cv.string,
                        vol.Optional("uri"): cv.string,
                    }
                )
            ],
        ),
    }
)
ASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TITLE): cv.string,
        vol.Required(ATTR_QUESTION): cv.string,
        vol.Optional(ATTR_TIMEOUT, default=15): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=240)),
        vol.Optional(ATTR_TEXT_YES): cv.string,
        vol.Optional(ATTR_TEXT_NO): cv.string,
        vol.Optional(ATTR_SPEAKERS): cv.entity_ids,
    }
)
DELIVER_SCHEMA = vol.Schema({vol.Optional(ATTR_SPEAKERS): cv.entity_ids})
REMOVE_SCHEMA = vol.Schema({vol.Required(ATTR_TAG): cv.string})


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
            data.get(ATTR_ACTIONS),
            data.get(ATTR_PRIORITY, PRIORITY_NORMAL),
            data.get(ATTR_TAG),
            data.get(ATTR_STORE, True),
            data.get(ATTR_REMOVE_AFTER),
            data.get(ATTR_PUSH_TO),
            data.get(ATTR_RECIPIENTS),
            data.get(ATTR_ANNOUNCEMENT),
            data.get(ATTR_REMINDER, False),
            data.get(ATTR_REMIND_EVERY),
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

    async def _remove(call: ServiceCall) -> None:
        await _manager(hass).async_remove(call.data[ATTR_TAG])

    hass.services.async_register(DOMAIN, SERVICE_REMOVE, _remove, schema=REMOVE_SCHEMA)

    async def _ask(call: ServiceCall) -> ServiceResponse:
        data = call.data
        return await _manager(hass).async_ask(
            data[ATTR_TITLE],
            data[ATTR_QUESTION],
            data.get(ATTR_TIMEOUT, 15),
            data.get(ATTR_TEXT_YES),
            data.get(ATTR_TEXT_NO),
            data.get(ATTR_SPEAKERS),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_ASK, _ask, schema=ASK_SCHEMA, supports_response=SupportsResponse.ONLY
    )
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
