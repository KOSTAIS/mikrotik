"""RouterOS API client. Blocking; Home Assistant runs it in the executor.

Kept free of Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import functools
import re
import ssl
import threading
import time
from typing import Any

import librouteros
from librouteros.exceptions import LibRouterosError, TrapError


class RouterError(Exception):
    """Router unreachable or returned an error."""


class AuthError(RouterError):
    """Login rejected."""


class DynamicInterfaceError(RouterError):
    """Tried to enable/disable an interface RouterOS manages dynamically."""


class WifiFlavor(StrEnum):
    """Which Wi-Fi/CAPsMAN menu the router uses."""

    WIFI = "wifi"  # RouterOS 7 wifi package (wifi-qcom, wifi-qcom-ac), new CAPsMAN
    CAPSMAN = "caps-man"  # legacy wireless package CAPsMAN
    NONE = "none"


WIFI_MENUS: dict[WifiFlavor, dict[str, tuple[str, ...]]] = {
    WifiFlavor.WIFI: {
        "interface": ("interface", "wifi"),
        "configuration": ("interface", "wifi", "configuration"),
        "registration": ("interface", "wifi", "registration-table"),
    },
    WifiFlavor.CAPSMAN: {
        "interface": ("caps-man", "interface"),
        "configuration": ("caps-man", "configuration"),
        "registration": ("caps-man", "registration-table"),
    },
}


@dataclass(slots=True)
class Interface:
    """Row from /interface."""

    id: str
    name: str
    type: str
    disabled: bool
    running: bool
    rx_byte: int
    tx_byte: int
    comment: str | None = None


@dataclass(slots=True)
class WifiInterface:
    """Row from the Wi-Fi/CAPsMAN interface menu."""

    id: str
    name: str
    disabled: bool
    dynamic: bool
    running: bool
    clients: int = 0


@dataclass(slots=True)
class WifiNetwork:
    """All Wi-Fi interfaces broadcasting the same SSID, across every CAP."""

    ssid: str
    interfaces: list[WifiInterface] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return any(not i.disabled for i in self.interfaces)

    @property
    def running(self) -> bool:
        return any(i.running for i in self.interfaces)

    @property
    def clients(self) -> int:
        return sum(i.clients for i in self.interfaces)

    @property
    def switchable(self) -> bool:
        return all(not i.dynamic for i in self.interfaces)


@dataclass(slots=True)
class RouterInfo:
    """Static facts about the router, read once."""

    identity: str
    serial: str | None
    model: str | None
    version: str | None


@dataclass(slots=True)
class RouterData:
    """One poll's worth of state."""

    resource: dict[str, Any]
    interfaces: dict[str, Interface]
    wifi_flavor: WifiFlavor
    networks: dict[str, WifiNetwork]
    monotonic: float
    # bits per second, filled in by compute_rates()
    rates: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def wifi_clients(self) -> int:
        return sum(n.clients for n in self.networks.values())


_UPTIME_RE = re.compile(r"(\d+)([wdhms])")
_UPTIME_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_uptime(value: str | None) -> int | None:
    """Turn RouterOS uptime ("2w3d04:05:06" or "2w3d4h5m6s") into seconds."""
    if not value:
        return None
    seconds = 0
    rest = value
    # some versions print the h:m:s part as a clock
    if clock := re.search(r"(\d+):(\d+):(\d+)$", value):
        h, m, s = (int(x) for x in clock.groups())
        seconds += h * 3600 + m * 60 + s
        rest = value[: clock.start()]
    matches = _UPTIME_RE.findall(rest)
    if not matches and not clock:
        return None
    seconds += sum(int(n) * _UPTIME_UNITS[unit] for n, unit in matches)
    return seconds


def compute_rates(previous: RouterData | None, current: RouterData) -> None:
    """Fill current.rates from the byte counters of two polls."""
    if previous is None:
        return
    elapsed = current.monotonic - previous.monotonic
    if elapsed <= 0:
        return
    for name, iface in current.interfaces.items():
        old = previous.interfaces.get(name)
        if old is None:
            continue
        drx = iface.rx_byte - old.rx_byte
        dtx = iface.tx_byte - old.tx_byte
        if drx < 0 or dtx < 0:  # counters reset (reboot, interface re-created)
            continue
        current.rates[name] = (drx * 8 / elapsed, dtx * 8 / elapsed)


def group_networks(
    interfaces: list[dict[str, Any]],
    configurations: dict[str, str | None],
    clients_per_interface: dict[str, int],
) -> dict[str, WifiNetwork]:
    """Group Wi-Fi interfaces by the SSID they broadcast."""
    networks: dict[str, WifiNetwork] = {}
    for row in interfaces:
        if row.get("name") in (None, ""):
            continue
        name = str(row["name"])
        config_name = str(row["configuration"]) if "configuration" in row else None
        ssid = (
            row.get("configuration.ssid")
            or (configurations.get(config_name) if config_name else None)
            or row.get("ssid")
            or name
        )
        ssid = str(ssid)
        networks.setdefault(ssid, WifiNetwork(ssid=ssid)).interfaces.append(
            WifiInterface(
                id=row[".id"],
                name=name,
                disabled=bool(row.get("disabled", False)),
                dynamic=bool(row.get("dynamic", False)),
                running=bool(row.get("running", False)),
                clients=clients_per_interface.get(name, 0),
            )
        )
    return networks


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class RouterClient:
    """Thread-safe wrapper around one librouteros connection."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool,
        verify_ssl: bool,
        timeout: float = 10,
    ) -> None:
        self.host = host
        self.port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._api: librouteros.Api | None = None
        self._lock = threading.Lock()
        self._flavor: WifiFlavor | None = None

    # -- connection -------------------------------------------------------

    def _connect(self) -> librouteros.Api:
        kwargs: dict[str, Any] = {
            "port": self.port,
            "timeout": self._timeout,
            "encoding": "utf-8",
        }
        if self._use_ssl:
            ctx = ssl.create_default_context()
            if not self._verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_wrapper"] = functools.partial(
                ctx.wrap_socket, server_hostname=self.host
            )
        try:
            return librouteros.connect(
                self.host, self._username, self._password, **kwargs
            )
        except TrapError as err:
            # a trap during login means the credentials were refused
            raise AuthError(str(err)) from err
        except (LibRouterosError, OSError) as err:
            raise RouterError(f"Cannot connect to {self.host}:{self.port}: {err}") from err

    def _run(self, func):
        """Run func(api) with a live connection; reconnect once if it dropped."""
        with self._lock:
            for attempt in (1, 2):
                if self._api is None:
                    self._api = self._connect()
                try:
                    return func(self._api)
                except TrapError as err:
                    # command-level error; the connection is still fine
                    raise RouterError(str(err)) from err
                except (LibRouterosError, OSError) as err:
                    self._close_locked()
                    if attempt == 2:
                        raise RouterError(str(err)) from err
        raise AssertionError("unreachable")

    def _close_locked(self) -> None:
        if self._api is not None:
            try:
                self._api.close()
            except Exception:  # noqa: BLE001 - socket already gone
                pass
            self._api = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    # -- reads ------------------------------------------------------------

    def get_info(self) -> RouterInfo:
        def read(api: librouteros.Api) -> RouterInfo:
            identity = _first(api.path("system", "identity")).get("name", self.host)
            resource = _first(api.path("system", "resource"))
            try:
                board = _first(api.path("system", "routerboard"))
            except TrapError:  # CHR / x86 have no routerboard menu
                board = {}
            return RouterInfo(
                identity=str(identity),
                serial=board.get("serial-number"),
                model=board.get("model") or resource.get("board-name"),
                version=resource.get("version"),
            )

        return self._run(read)

    def list_interfaces(self) -> list[Interface]:
        return self._run(_read_interfaces)

    def fetch(self) -> RouterData:
        def read(api: librouteros.Api) -> RouterData:
            resource = _first(api.path("system", "resource"))
            interfaces = {i.name: i for i in _read_interfaces(api)}
            if self._flavor is None:
                self._flavor = _detect_flavor(api)
            networks = _read_networks(api, self._flavor)
            return RouterData(
                resource=resource,
                interfaces=interfaces,
                wifi_flavor=self._flavor,
                networks=networks,
                monotonic=time.monotonic(),
            )

        return self._run(read)

    # -- writes -----------------------------------------------------------

    def set_interface_enabled(self, name: str, enabled: bool) -> None:
        def write(api: librouteros.Api) -> None:
            path = api.path("interface")
            row = next((r for r in path if str(r.get("name")) == name), None)
            if row is None:
                raise RouterError(f"Interface {name} not found")
            if row.get("dynamic"):
                raise DynamicInterfaceError(
                    f"{name} is a dynamic interface and cannot be enabled/disabled"
                )
            path.update(**{".id": row[".id"], "disabled": not enabled})

        self._run(write)

    def set_network_enabled(self, ssid: str, enabled: bool) -> None:
        def write(api: librouteros.Api) -> None:
            if self._flavor is None:
                self._flavor = _detect_flavor(api)
            if self._flavor is WifiFlavor.NONE:
                raise RouterError("Router has no Wi-Fi or CAPsMAN menu")
            network = _read_networks(api, self._flavor).get(ssid)
            if network is None:
                raise RouterError(f"No Wi-Fi interfaces broadcast SSID {ssid!r}")
            if dynamic := [i.name for i in network.interfaces if i.dynamic]:
                raise DynamicInterfaceError(
                    f"{ssid!r} is on dynamic CAPsMAN interfaces ({', '.join(dynamic)}). "
                    "Use action=create-enabled in the provisioning rule so they "
                    "become static, then they can be switched."
                )
            path = api.path(*WIFI_MENUS[self._flavor]["interface"])
            for iface in network.interfaces:
                path.update(**{".id": iface.id, "disabled": not enabled})

        self._run(write)


def _first(rows) -> dict[str, Any]:
    return next(iter(tuple(rows)), {})


def _read_interfaces(api: librouteros.Api) -> list[Interface]:
    return [
        Interface(
            id=row[".id"],
            name=str(row["name"]),
            type=str(row.get("type", "")),
            disabled=bool(row.get("disabled", False)),
            running=bool(row.get("running", False)),
            rx_byte=_as_int(row.get("rx-byte")),
            tx_byte=_as_int(row.get("tx-byte")),
            comment=row.get("comment"),
        )
        for row in api.path("interface")
        if "name" in row
    ]


def _detect_flavor(api: librouteros.Api) -> WifiFlavor:
    found = WifiFlavor.NONE
    for flavor in (WifiFlavor.WIFI, WifiFlavor.CAPSMAN):
        try:
            rows = tuple(api.path(*WIFI_MENUS[flavor]["interface"]))
        except TrapError:  # menu doesn't exist (package not installed)
            continue
        if rows:
            return flavor
        if found is WifiFlavor.NONE:
            found = flavor
    return found


def _read_networks(api: librouteros.Api, flavor: WifiFlavor) -> dict[str, WifiNetwork]:
    if flavor is WifiFlavor.NONE:
        return {}
    menus = WIFI_MENUS[flavor]
    interfaces = list(api.path(*menus["interface"]))
    configurations = {
        str(row["name"]): row.get("ssid")
        for row in api.path(*menus["configuration"])
        if "name" in row
    }
    clients: dict[str, int] = {}
    for row in api.path(*menus["registration"]):
        if (iface := row.get("interface")) is not None:
            clients[str(iface)] = clients.get(str(iface), 0) + 1
    return group_networks(interfaces, configurations, clients)
