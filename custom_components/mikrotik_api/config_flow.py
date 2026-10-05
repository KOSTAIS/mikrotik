"""UI setup for the MikroTik Router (API) integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from . import client_from_config
from .const import (
    CONF_LAN_INTERFACE,
    CONF_SWITCH_INTERFACES,
    CONF_WAN_INTERFACE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SSL_PORT,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import MikrotikConfigEntry
from .router import AuthError, Interface, RouterError, RouterInfo

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default="homeassistant"): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=True): bool,
        vol.Required(CONF_VERIFY_SSL, default=False): bool,
        vol.Optional(CONF_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    }
)


def _interfaces_schema(interfaces: list[Interface], with_interval: bool) -> vol.Schema:
    options = [
        SelectOptionDict(value=i.name, label=f"{i.name} ({i.type})" if i.type else i.name)
        for i in sorted(interfaces, key=lambda i: i.name)
    ]
    single = SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
    )
    multi = SelectSelector(
        SelectSelectorConfig(
            options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN
        )
    )
    schema: dict[Any, Any] = {
        vol.Required(CONF_WAN_INTERFACE): single,
        vol.Optional(CONF_LAN_INTERFACE): single,
        vol.Optional(CONF_SWITCH_INTERFACES, default=[]): multi,
    }
    if with_interval:
        schema[vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL)] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=300,
                    step=1,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            )
        )
    return vol.Schema(schema)


def _connect(config: dict[str, Any]) -> tuple[RouterInfo, list[Interface]]:
    """Blocking: log in, read identity and interfaces."""
    client = client_from_config(config)
    try:
        return client.get_info(), client.list_interfaces()
    finally:
        client.close()


class MikrotikConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._info: RouterInfo | None = None
        self._interfaces: list[Interface] = []

    @staticmethod
    @callback
    def async_get_options_flow(entry: MikrotikConfigEntry) -> MikrotikOptionsFlow:
        return MikrotikOptionsFlow()

    async def _try_connect(
        self, config: dict[str, Any]
    ) -> tuple[RouterInfo, list[Interface]] | str:
        try:
            return await self.hass.async_add_executor_job(_connect, config)
        except AuthError:
            return "invalid_auth"
        except RouterError:
            return "cannot_connect"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            config = dict(user_input)
            config.setdefault(
                CONF_PORT, DEFAULT_SSL_PORT if config[CONF_SSL] else DEFAULT_PORT
            )
            result = await self._try_connect(config)
            if isinstance(result, str):
                errors["base"] = result
            else:
                self._info, self._interfaces = result
                await self.async_set_unique_id(self._info.serial or config[CONF_HOST])
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: config[CONF_HOST], CONF_PORT: config[CONF_PORT]}
                )
                self._config = config
                return await self.async_step_interfaces()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_interfaces(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._info.identity,
                data=self._config,
                options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL, **user_input},
            )
        return self.async_show_form(
            step_id="interfaces",
            data_schema=_interfaces_schema(self._interfaces, with_interval=False),
            description_placeholders={"router": self._info.identity},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            config = {**entry.data, **user_input}
            result = await self._try_connect(config)
            if isinstance(result, str):
                errors["base"] = result
            else:
                return self.async_update_reload_and_abort(entry, data=config)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=entry.data[CONF_USERNAME]
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class MikrotikOptionsFlow(OptionsFlowWithReload):
    """Change interfaces and polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        entry: MikrotikConfigEntry = self.config_entry
        if not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="not_loaded")
        interfaces = list(entry.runtime_data.data.interfaces.values())
        schema = _interfaces_schema(interfaces, with_interval=True)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, entry.options),
        )
