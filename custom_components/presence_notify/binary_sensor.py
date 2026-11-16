"""Binary sensor: waiting for someone to enter a return room."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import PresenceNotifyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([WaitingSensor(entry, "waiting")])


class WaitingSensor(PresenceNotifyEntity, BinarySensorEntity):
    _attr_icon = "mdi:account-clock"

    @property
    def is_on(self) -> bool:
        return self.manager.waiting

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"phase": self.manager.wait_phase}
