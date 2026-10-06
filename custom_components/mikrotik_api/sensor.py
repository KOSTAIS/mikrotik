"""Sensors for the MikroTik Router (API) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_LAN_INTERFACE, CONF_WAN_INTERFACE
from .coordinator import MikrotikConfigEntry, MikrotikCoordinator
from .entity import MikrotikEntity
from .router import RouterData, WifiClient, parse_uptime

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RouterSensorDescription(SensorEntityDescription):
    """Sensor computed from the whole RouterData."""

    value_fn: Callable[[RouterData], Any]
    attributes_fn: Callable[[RouterData], dict[str, Any]] | None = None


def _clients_attributes(clients: list[WifiClient]) -> dict[str, Any]:
    return {"clients": [c.as_dict() for c in sorted(clients, key=lambda c: c.name.lower())]}


def _memory_used(data: RouterData) -> float | None:
    total = int(data.resource.get("total-memory") or 0)
    free = int(data.resource.get("free-memory") or 0)
    return round((total - free) / total * 100, 1) if total else None


SYSTEM_SENSORS: tuple[RouterSensorDescription, ...] = (
    RouterSensorDescription(
        key="cpu_load",
        translation_key="cpu_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.resource.get("cpu-load"),
    ),
    RouterSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_memory_used,
    ),
    RouterSensorDescription(
        key="wifi_clients",
        translation_key="wifi_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.wifi_clients),
        attributes_fn=lambda d: _clients_attributes(d.wifi_clients),
    ),
)


@dataclass(frozen=True, kw_only=True)
class InterfaceSensorDescription(SensorEntityDescription):
    """Sensor for one configured interface (WAN or LAN)."""

    value_fn: Callable[[RouterData, str], Any]


def _rate(index: int) -> Callable[[RouterData, str], float | None]:
    def value(data: RouterData, name: str) -> float | None:
        rates = data.rates.get(name)
        return round(rates[index]) if rates else None

    return value


def _bytes(attr: str) -> Callable[[RouterData, str], int | None]:
    def value(data: RouterData, name: str) -> int | None:
        iface = data.interfaces.get(name)
        return getattr(iface, attr) if iface else None

    return value


def _interface_sensors(role: str) -> tuple[InterfaceSensorDescription, ...]:
    rate = {
        "device_class": SensorDeviceClass.DATA_RATE,
        "native_unit_of_measurement": UnitOfDataRate.BITS_PER_SECOND,
        "suggested_unit_of_measurement": UnitOfDataRate.MEGABITS_PER_SECOND,
        "suggested_display_precision": 2,
        "state_class": SensorStateClass.MEASUREMENT,
    }
    size = {
        "device_class": SensorDeviceClass.DATA_SIZE,
        "native_unit_of_measurement": UnitOfInformation.BYTES,
        "suggested_unit_of_measurement": UnitOfInformation.GIGABYTES,
        "suggested_display_precision": 2,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    }
    return (
        InterfaceSensorDescription(
            key=f"{role}_rx_rate", translation_key=f"{role}_rx_rate", value_fn=_rate(0), **rate
        ),
        InterfaceSensorDescription(
            key=f"{role}_tx_rate", translation_key=f"{role}_tx_rate", value_fn=_rate(1), **rate
        ),
        InterfaceSensorDescription(
            key=f"{role}_rx_bytes", translation_key=f"{role}_rx_bytes", value_fn=_bytes("rx_byte"), **size
        ),
        InterfaceSensorDescription(
            key=f"{role}_tx_bytes", translation_key=f"{role}_tx_bytes", value_fn=_bytes("tx_byte"), **size
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MikrotikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        RouterSensor(coordinator, description) for description in SYSTEM_SENSORS
    ]
    entities.append(BootTimeSensor(coordinator))
    for role, option in (("wan", CONF_WAN_INTERFACE), ("lan", CONF_LAN_INTERFACE)):
        if interface := entry.options.get(option):
            entities.extend(
                InterfaceSensor(coordinator, description, interface)
                for description in _interface_sensors(role)
            )
    async_add_entities(entities)

    known: set[str] = set()

    @callback
    def add_new_networks() -> None:
        new = [ssid for ssid in coordinator.data.networks if ssid not in known]
        known.update(new)
        if new:
            async_add_entities(NetworkClientsSensor(coordinator, ssid) for ssid in new)

    add_new_networks()
    entry.async_on_unload(coordinator.async_add_listener(add_new_networks))


class RouterSensor(MikrotikEntity, SensorEntity):
    """System-level sensor."""

    entity_description: RouterSensorDescription
    # the client list changes constantly; keep it out of the history database
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(
        self, coordinator: MikrotikCoordinator, description: RouterSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


class InterfaceSensor(MikrotikEntity, SensorEntity):
    """Traffic sensor for the WAN or LAN interface."""

    entity_description: InterfaceSensorDescription

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        description: InterfaceSensorDescription,
        interface: str,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._interface = interface
        self._attr_extra_state_attributes = {"interface": interface}

    @property
    def available(self) -> bool:
        return super().available and self._interface in self.coordinator.data.interfaces

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data, self._interface)


class BootTimeSensor(MikrotikEntity, SensorEntity):
    """When the router last booted (derived from uptime)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_boot"

    def __init__(self, coordinator: MikrotikCoordinator) -> None:
        super().__init__(coordinator, "last_boot")
        self._boot: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        uptime = parse_uptime(self.coordinator.data.resource.get("uptime"))
        if uptime is None:
            return None
        boot = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(microsecond=0)
        # uptime is sampled with some delay; ignore jitter so the state is stable
        if self._boot is None or abs(boot - self._boot) > timedelta(seconds=60):
            self._boot = boot
        return self._boot


class NetworkClientsSensor(MikrotikEntity, SensorEntity):
    """Clients connected to one SSID across all CAPs."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "network_clients"
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(self, coordinator: MikrotikCoordinator, ssid: str) -> None:
        super().__init__(coordinator, f"wifi_{ssid}_clients")
        self._ssid = ssid
        self._attr_translation_placeholders = {"ssid": ssid}

    @property
    def available(self) -> bool:
        return super().available and self._ssid in self.coordinator.data.networks

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.networks[self._ssid].clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        network = self.coordinator.data.networks.get(self._ssid)
        return _clients_attributes(network.clients if network else [])
