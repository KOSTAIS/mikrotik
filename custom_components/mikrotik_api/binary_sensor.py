"""Binary sensors for the MikroTik Router (API) integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_WAN_INTERFACE
from .coordinator import MikrotikConfigEntry, MikrotikCoordinator
from .entity import MikrotikEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MikrotikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if wan := entry.options.get(CONF_WAN_INTERFACE):
        async_add_entities([WanConnectedSensor(coordinator, wan)])


class WanConnectedSensor(MikrotikEntity, BinarySensorEntity):
    """WAN interface link is up."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "wan_connected"

    def __init__(self, coordinator: MikrotikCoordinator, interface: str) -> None:
        super().__init__(coordinator, "wan_connected")
        self._interface = interface

    @property
    def available(self) -> bool:
        return super().available and self._interface in self.coordinator.data.interfaces

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.interfaces[self._interface].running
