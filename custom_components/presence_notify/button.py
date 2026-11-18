"""Buttons: deliver now / clear stored messages / acknowledge emergency."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import PresenceNotifyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        [
            DeliverButton(entry, "deliver"),
            ClearButton(entry, "clear"),
            AckEmergencyButton(entry, "acknowledge_emergency"),
        ]
    )


class DeliverButton(PresenceNotifyEntity, ButtonEntity):
    _attr_icon = "mdi:bell-ring"

    async def async_press(self) -> None:
        await self.manager.async_deliver()


class ClearButton(PresenceNotifyEntity, ButtonEntity):
    _attr_icon = "mdi:bell-remove"

    async def async_press(self) -> None:
        await self.manager.async_clear()


class AckEmergencyButton(PresenceNotifyEntity, ButtonEntity):
    """Ends a running emergency (e.g. from a dashboard or an Alexa routine)."""

    _attr_icon = "mdi:alarm-light-off"

    async def async_press(self) -> None:
        self.manager.async_acknowledge(self._context.user_id if self._context else None)
