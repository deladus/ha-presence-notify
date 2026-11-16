"""Sensors for Presence Notify."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import PresenceNotifyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([PendingSensor(entry, "pending"), LastDeliverySensor(entry, "last_delivery")])


class PendingSensor(PresenceNotifyEntity, SensorEntity):
    """Number of stored messages, with the list as attribute."""

    _attr_icon = "mdi:bell-badge"

    @property
    def native_value(self) -> int:
        return len(self.manager.pending)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"items": self.manager.pending}


class LastDeliverySensor(PresenceNotifyEntity, SensorEntity):
    """When stored messages were last delivered."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.manager.last_delivery
