"""Base entity for the MikroTik Router (API) integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MikrotikCoordinator


class MikrotikEntity(CoordinatorEntity[MikrotikCoordinator]):
    """Entity attached to the router device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MikrotikCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.entry_id
        info = coordinator.info
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=info.identity,
            manufacturer="MikroTik",
            model=info.model,
            sw_version=info.version,
            serial_number=info.serial,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )
