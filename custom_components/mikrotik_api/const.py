"""Constants for the MikroTik Router (API) integration."""

from typing import Final

DOMAIN: Final = "mikrotik_api"

CONF_WAN_INTERFACE: Final = "wan_interface"
CONF_LAN_INTERFACE: Final = "lan_interface"
CONF_SWITCH_INTERFACES: Final = "switch_interfaces"

DEFAULT_PORT: Final = 8728
DEFAULT_SSL_PORT: Final = 8729
DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5

