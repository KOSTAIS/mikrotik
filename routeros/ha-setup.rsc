# Prepares a MikroTik router (RouterOS v7) for Home Assistant.
#
# - creates a "homeassistant" group/user with only the rights it needs
# - creates a self-signed certificate and enables the encrypted API service
#   (api-ssl, port 8729) used by the mikrotik_api custom integration
# - restricts that service to the Home Assistant host
#
# Edit the variables below, then upload the file and run:
#   /import file-name=ha-setup.rsc
# Run it on the router that is the CAPsMAN controller.

:local haIP "192.168.88.10"
:local haUser "homeassistant"
:local haPass "CHANGE-ME-to-a-long-random-password"
# Addresses allowed to reach the API (and, if enabled below, HTTPS/REST).
# Add your admin subnet here (comma separated) if you also use WebFig over HTTPS.
:local allowedFrom "192.168.88.10/32"

# --- user ------------------------------------------------------------------
# read: statistics; write: enable/disable interfaces and Wi-Fi networks;
# api: the custom integration; rest-api: only for the YAML/REST package.
:if ([:len [/user group find name="homeassistant"]] = 0) do={
    /user group add name="homeassistant" policy="read,write,api,rest-api" comment="Home Assistant"
}
:if ([:len [/user find name=$haUser]] = 0) do={
    /user add name=$haUser group="homeassistant" password=$haPass address=$haIP comment="Home Assistant"
} else={
    /user set [find name=$haUser] group="homeassistant" password=$haPass address=$haIP
}

# --- TLS certificate -------------------------------------------------------
:if ([:len [/certificate find name="ha-https"]] = 0) do={
    /certificate add name="ha-https" common-name="router" key-usage="digital-signature,key-encipherment,tls-server" days-valid=3650
    /certificate sign "ha-https"
    # signing runs in the background on slow devices
    :delay 10s
}

# --- API service (custom integration) --------------------------------------
/ip service set api-ssl certificate="ha-https" address=$allowedFrom disabled=no

# Optional: REST API, only for homeassistant/packages/mikrotik.yaml.
# /ip service set www-ssl certificate="ha-https" address=$allowedFrom disabled=no

# Optional: unencrypted API on 8728. Only if you untick "Use API-SSL".
# /ip service set api address=$allowedFrom disabled=no

:put "Home Assistant access ready: api-ssl port 8729, user=$haUser"
