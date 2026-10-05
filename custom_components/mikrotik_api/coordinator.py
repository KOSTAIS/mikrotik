"""Polls the router and keeps the latest RouterData."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .router import AuthError, RouterClient, RouterData, RouterError, RouterInfo, compute_rates

_LOGGER = logging.getLogger(__name__)

type MikrotikConfigEntry = ConfigEntry[MikrotikCoordinator]


class MikrotikCoordinator(DataUpdateCoordinator[RouterData]):
    """Fetches system, interface and Wi-Fi state in one go."""

    config_entry: MikrotikConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MikrotikConfigEntry,
        client: RouterClient,
        info: RouterInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.info = info

    async def _async_update_data(self) -> RouterData:
        try:
            data = await self.hass.async_add_executor_job(self.client.fetch)
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RouterError as err:
            raise UpdateFailed(str(err)) from err
        compute_rates(self.data, data)
        return data
