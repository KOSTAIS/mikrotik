"""MikroTik Router (API) integration."""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .coordinator import MikrotikConfigEntry, MikrotikCoordinator
from .router import AuthError, RouterClient, RouterError

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


def client_from_config(config: dict) -> RouterClient:
    return RouterClient(
        host=config[CONF_HOST],
        port=config[CONF_PORT],
        username=config[CONF_USERNAME],
        password=config[CONF_PASSWORD],
        use_ssl=config[CONF_SSL],
        verify_ssl=config[CONF_VERIFY_SSL],
    )


async def async_setup_entry(hass: HomeAssistant, entry: MikrotikConfigEntry) -> bool:
    client = client_from_config(dict(entry.data))
    try:
        info = await hass.async_add_executor_job(client.get_info)
    except AuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except RouterError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = MikrotikCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MikrotikConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded
