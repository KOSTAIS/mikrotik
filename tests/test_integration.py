"""Home Assistant tests: config flow, entities, switches."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from librouteros.exceptions import TrapError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mikrotik_api.const import (
    CONF_LAN_INTERFACE,
    CONF_SWITCH_INTERFACES,
    CONF_WAN_INTERFACE,
    DOMAIN,
)

from .fake_routeros import FakeApi

USER_INPUT = {
    CONF_HOST: "192.168.88.1",
    CONF_USERNAME: "homeassistant",
    CONF_PASSWORD: "pw",
    CONF_SSL: True,
    CONF_VERIFY_SSL: False,
}


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="HG1234567",
        title="home-router",
        data={**USER_INPUT, CONF_PORT: 8729},
        options={
            CONF_WAN_INTERFACE: "ether1",
            CONF_LAN_INTERFACE: "bridge",
            CONF_SWITCH_INTERFACES: [],
            CONF_SCAN_INTERVAL: 10,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_config_flow(hass: HomeAssistant, mock_connect) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "interfaces"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WAN_INTERFACE: "ether1", CONF_LAN_INTERFACE: "bridge", CONF_SWITCH_INTERFACES: []},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "home-router"
    assert result["data"][CONF_PORT] == 8729  # api-ssl default
    assert result["options"][CONF_WAN_INTERFACE] == "ether1"
    assert result["result"].unique_id == "HG1234567"


async def test_config_flow_bad_login(hass: HomeAssistant, mock_connect) -> None:
    mock_connect.side_effect = TrapError(message="invalid user name or password (6)")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}

    mock_connect.side_effect = OSError("no route")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_entities(hass: HomeAssistant, entry, fake_api: FakeApi, mock_connect) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("binary_sensor.home_router_wan_connected").state == STATE_ON
    assert hass.states.get("sensor.home_router_cpu_load").state == "7"
    assert hass.states.get("sensor.home_router_memory_used").state == "25.0"
    assert hass.states.get("sensor.home_router_wi_fi_clients").state == "3"
    home = hass.states.get("sensor.home_router_home_clients")
    assert home.state == "3"
    assert [c["name"] for c in home.attributes["clients"]] == [
        "AA:BB:CC:00:00:03",
        "Kitchen plug",
        "my-phone",
    ]
    assert home.attributes["clients"][2]["mac"] == "AA:BB:CC:00:00:01"
    assert home.attributes["clients"][2]["ssid"] == "Home"
    total = hass.states.get("sensor.home_router_wi_fi_clients")
    assert len(total.attributes["clients"]) == 3
    assert hass.states.get("switch.home_router_wi_fi_home").attributes["clients"] == 3
    assert hass.states.get("sensor.home_router_guest_clients").state == "0"
    assert hass.states.get("sensor.home_router_last_boot").state not in ("unknown", "unavailable")
    # no rate until there are two polls
    assert hass.states.get("sensor.home_router_wan_download").state == "unknown"

    assert hass.states.get("switch.home_router_wan").state == STATE_ON
    assert hass.states.get("switch.home_router_wi_fi_home").state == STATE_ON
    guest = hass.states.get("switch.home_router_wi_fi_guest")
    assert guest.state == STATE_OFF
    assert guest.attributes["interfaces"] == ["guest-24", "guest-5"]

    fake_api.menus[("interface",)][0]["rx-byte"] += 10_000_000
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.home_router_wan_download").state) > 0

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert fake_api.closed


async def test_switch_wifi_network(hass: HomeAssistant, entry, fake_api: FakeApi, mock_connect) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_router_wi_fi_guest"}, blocking=True
    )
    assert hass.states.get("switch.home_router_wi_fi_guest").state == STATE_ON
    assert {c[2][".id"] for c in fake_api.calls} == {"*5", "*6"}

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_router_wi_fi_guest"}, blocking=True
    )
    assert hass.states.get("switch.home_router_wi_fi_guest").state == STATE_OFF


async def test_switch_wan(hass: HomeAssistant, entry, fake_api: FakeApi, mock_connect) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_router_wan"}, blocking=True
    )
    assert hass.states.get("switch.home_router_wan").state == STATE_OFF
    assert fake_api.calls[-1] == (("interface",), "set", {".id": "*1", "disabled": True})


async def test_switch_dynamic_network_errors(
    hass: HomeAssistant, entry, fake_api: FakeApi, mock_connect
) -> None:
    fake_api.menus[("interface", "wifi")][2]["dynamic"] = True
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="create-enabled"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.home_router_wi_fi_guest"}, blocking=True
        )


async def test_new_network_appears(hass: HomeAssistant, entry, fake_api: FakeApi, mock_connect) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.home_router_wi_fi_iot") is None

    fake_api.menus[("interface", "wifi")].append(
        {".id": "*7", "name": "iot", "configuration.ssid": "IoT", "disabled": True}
    )
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.home_router_wi_fi_iot").state == STATE_OFF


async def test_router_down_on_setup(hass: HomeAssistant, entry, mock_connect) -> None:
    mock_connect.side_effect = OSError("no route")
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_flow(hass: HomeAssistant, entry, mock_connect) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_WAN_INTERFACE: "ether1",
            CONF_SWITCH_INTERFACES: ["cap-wifi1"],
            CONF_SCAN_INTERVAL: 30,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("switch.home_router_interface_cap_wifi1").state == STATE_ON
    # LAN removed -> its sensors are gone after the reload
    assert hass.states.get("sensor.home_router_lan_received").state == "unavailable"
