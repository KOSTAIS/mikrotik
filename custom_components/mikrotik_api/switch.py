"""Switches for the MikroTik Router (API) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SWITCH_INTERFACES, CONF_WAN_INTERFACE
from .coordinator import MikrotikConfigEntry, MikrotikCoordinator
from .entity import MikrotikEntity
from .router import RouterError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MikrotikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    wan = entry.options.get(CONF_WAN_INTERFACE)
    if wan:
        entities.append(InterfaceSwitch(coordinator, wan, is_wan=True))
    entities.extend(
        InterfaceSwitch(coordinator, name, is_wan=False)
        for name in entry.options.get(CONF_SWITCH_INTERFACES, [])
        if name != wan
    )
    async_add_entities(entities)

    known: set[str] = set()

    @callback
    def add_new_networks() -> None:
        new = [ssid for ssid in coordinator.data.networks if ssid not in known]
        known.update(new)
        if new:
            async_add_entities(WifiNetworkSwitch(coordinator, ssid) for ssid in new)

    add_new_networks()
    entry.async_on_unload(coordinator.async_add_listener(add_new_networks))


class _RouterSwitch(MikrotikEntity, SwitchEntity):
    """Switch that runs a blocking router call, then refreshes."""

    async def _call(self, func, *args: Any) -> None:
        try:
            await self.hass.async_add_executor_job(func, *args)
        except RouterError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.coordinator.async_refresh()


class InterfaceSwitch(_RouterSwitch):
    """Enable/disable a RouterOS interface (/interface)."""

    def __init__(self, coordinator: MikrotikCoordinator, name: str, is_wan: bool) -> None:
        super().__init__(coordinator, "wan" if is_wan else f"interface_{name}")
        self._name = name
        if is_wan:
            self._attr_translation_key = "wan"
        else:
            self._attr_translation_key = "interface"
            self._attr_translation_placeholders = {"name": name}
        self._attr_extra_state_attributes = {"interface": name}

    @property
    def available(self) -> bool:
        return super().available and self._name in self.coordinator.data.interfaces

    @property
    def is_on(self) -> bool:
        return not self.coordinator.data.interfaces[self._name].disabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.set_interface_enabled, self._name, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.set_interface_enabled, self._name, False)


class WifiNetworkSwitch(_RouterSwitch):
    """Enable/disable every Wi-Fi interface broadcasting one SSID."""

    _attr_translation_key = "wifi_network"

    def __init__(self, coordinator: MikrotikCoordinator, ssid: str) -> None:
        super().__init__(coordinator, f"wifi_{ssid}")
        self._ssid = ssid
        self._attr_translation_placeholders = {"ssid": ssid}

    @property
    def available(self) -> bool:
        return super().available and self._ssid in self.coordinator.data.networks

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.networks[self._ssid].enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        network = self.coordinator.data.networks.get(self._ssid)
        if network is None:
            return {}
        return {
            "ssid": network.ssid,
            "interfaces": [i.name for i in network.interfaces],
            "running": network.running,
            "clients": network.clients,
            "switchable": network.switchable,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.set_network_enabled, self._ssid, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.set_network_enabled, self._ssid, False)
