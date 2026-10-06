"""Tests for the blocking RouterOS client (no Home Assistant needed)."""

from __future__ import annotations

from librouteros.exceptions import ConnectionClosed, TrapError
import pytest

from custom_components.mikrotik_api.router import (
    AuthError,
    DynamicInterfaceError,
    RouterClient,
    RouterError,
    WifiClient,
    WifiFlavor,
    compute_rates,
    group_networks,
    parse_uptime,
)

from .fake_routeros import FakeApi


def client() -> RouterClient:
    return RouterClient("192.168.88.1", 8729, "homeassistant", "pw", True, False)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("1w2d3h4m5s", 604800 + 2 * 86400 + 3 * 3600 + 4 * 60 + 5),
        ("45s", 45),
        ("2d03:04:05", 2 * 86400 + 3 * 3600 + 4 * 60 + 5),
        ("00:00:10", 10),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_uptime(value, seconds) -> None:
    assert parse_uptime(value) == seconds


def test_group_networks_by_ssid() -> None:
    networks = group_networks(
        [
            {".id": "*1", "name": "a", "configuration": "cfg-home"},
            {".id": "*2", "name": "b", "configuration": "cfg-home", "disabled": True},
            {".id": "*3", "name": "c", "configuration.ssid": "Inline"},
            {".id": "*4", "name": "d"},
            {".id": "*5", "name": 5, "dynamic": True},
        ],
        {"cfg-home": "Home"},
        {
            "a": [WifiClient(mac="M1", interface="a"), WifiClient(mac="M2", interface="a")],
            "b": [WifiClient(mac="M3", interface="b")],
        },
    )
    assert set(networks) == {"Home", "Inline", "d", "5"}
    home = networks["Home"]
    assert [i.name for i in home.interfaces] == ["a", "b"]
    assert home.enabled  # one of two still enabled
    assert [c.mac for c in home.clients] == ["M1", "M2", "M3"]
    assert {c.ssid for c in home.clients} == {"Home"}
    assert home.switchable
    assert not networks["5"].switchable


def test_fetch_and_rates(fake_api: FakeApi, mock_connect) -> None:
    c = client()
    first = c.fetch()
    assert first.wifi_flavor is WifiFlavor.WIFI
    assert set(first.networks) == {"Home", "Guest"}
    assert len(first.networks["Home"].clients) == 3
    assert not first.networks["Guest"].enabled
    assert len(first.wifi_clients) == 3
    assert first.interfaces["ether1"].rx_byte == 1000

    fake_api.menus[("interface",)][0]["rx-byte"] = 1000 + 125_000
    second = c.fetch()
    second.monotonic = first.monotonic + 1
    compute_rates(first, second)
    assert second.rates["ether1"] == (1_000_000, 0)

    # a counter reset is skipped instead of reported as a huge negative rate
    fake_api.menus[("interface",)][0]["rx-byte"] = 0
    third = c.fetch()
    third.monotonic = second.monotonic + 1
    compute_rates(second, third)
    assert "ether1" not in third.rates
    # connection is reused between calls
    assert mock_connect.call_count == 1


def test_info(mock_connect) -> None:
    info = client().get_info()
    assert info.identity == "home-router"
    assert info.serial == "HG1234567"
    assert info.version == "7.20 (stable)"


def test_info_without_routerboard(fake_api: FakeApi, mock_connect) -> None:
    del fake_api.menus[("system", "routerboard")]
    info = client().get_info()
    assert info.serial is None
    assert info.model == "hAP ax^3"


def test_enable_network_sets_every_interface(fake_api: FakeApi, mock_connect) -> None:
    c = client()
    c.set_network_enabled("Guest", True)
    assert [call[2] for call in fake_api.calls] == [
        {".id": "*5", "disabled": False},
        {".id": "*6", "disabled": False},
    ]
    assert all(call[0] == ("interface", "wifi") for call in fake_api.calls)
    assert c.fetch().networks["Guest"].enabled


def test_dynamic_network_is_refused(fake_api: FakeApi, mock_connect) -> None:
    fake_api.menus[("interface", "wifi")][2]["dynamic"] = True
    with pytest.raises(DynamicInterfaceError, match="create-enabled"):
        client().set_network_enabled("Guest", True)
    assert fake_api.calls == []


def test_unknown_network(mock_connect) -> None:
    with pytest.raises(RouterError, match="Nope"):
        client().set_network_enabled("Nope", True)


def test_interface_switch(fake_api: FakeApi, mock_connect) -> None:
    client().set_interface_enabled("ether1", False)
    assert fake_api.calls == [(("interface",), "set", {".id": "*1", "disabled": True})]
    with pytest.raises(RouterError, match="not found"):
        client().set_interface_enabled("ether9", False)


def test_legacy_capsman_detected(fake_api: FakeApi, mock_connect) -> None:
    menus = fake_api.menus
    del menus[("interface", "wifi")]
    del menus[("interface", "wifi", "configuration")]
    del menus[("interface", "wifi", "registration-table")]
    menus[("caps-man", "interface")] = [
        {".id": "*10", "name": "cap1", "configuration": "guest", "disabled": False, "dynamic": False},
    ]
    menus[("caps-man", "configuration")] = [{".id": "*C", "name": "guest", "ssid": "Guest"}]
    menus[("caps-man", "registration-table")] = []

    c = client()
    data = c.fetch()
    assert data.wifi_flavor is WifiFlavor.CAPSMAN
    assert data.networks["Guest"].enabled
    c.set_network_enabled("Guest", False)
    assert fake_api.calls == [(("caps-man", "interface"), "set", {".id": "*10", "disabled": True})]


def test_no_wifi(fake_api: FakeApi, mock_connect) -> None:
    for menu in [m for m in fake_api.menus if m[:2] == ("interface", "wifi")]:
        del fake_api.menus[menu]
    data = client().fetch()
    assert data.wifi_flavor is WifiFlavor.NONE
    assert data.networks == {}


def test_login_rejected(mock_connect) -> None:
    mock_connect.side_effect = TrapError(message="invalid user name or password (6)")
    with pytest.raises(AuthError):
        client().fetch()


def test_unreachable(mock_connect) -> None:
    mock_connect.side_effect = OSError("timed out")
    with pytest.raises(RouterError) as err:
        client().fetch()
    assert not isinstance(err.value, AuthError)


def test_reconnects_after_dropped_connection(fake_api: FakeApi, mock_connect) -> None:
    c = client()
    c.fetch()
    broken = FakeApi({})
    broken.path = lambda *p: (_ for _ in ()).throw(ConnectionClosed("gone"))  # type: ignore[method-assign]
    c._api = broken  # simulate the socket dying between polls
    data = c.fetch()
    assert data.interfaces
    assert mock_connect.call_count == 2
    assert broken.closed


def test_clients_get_host_name_and_ip(mock_connect) -> None:
    clients = {c.mac: c for c in client().fetch().wifi_clients}
    phone = clients["AA:BB:CC:00:00:01"]  # MAC case differs between tables
    assert phone.as_dict() == {
        "name": "my-phone",
        "host_name": "my-phone",
        "mac": "AA:BB:CC:00:00:01",
        "ip": "192.168.88.21",
        "ssid": "Home",
        "interface": "cap-wifi1",
        "signal": -52,
        "uptime": "1h2m3s",
    }
    plug = clients["AA:BB:CC:00:00:02"]
    assert plug.name == "Kitchen plug"  # lease comment wins over host name
    assert plug.ip == "192.168.88.22"  # bound lease, not the stale one
    unknown = clients["AA:BB:CC:00:00:03"]
    assert unknown.host_name is None and unknown.name == "AA:BB:CC:00:00:03"


def test_clients_without_dhcp_server(fake_api: FakeApi, mock_connect) -> None:
    del fake_api.menus[("ip", "dhcp-server", "lease")]
    clients = client().fetch().wifi_clients
    assert len(clients) == 3
    assert all(c.host_name is None and c.ssid == "Home" for c in clients)
