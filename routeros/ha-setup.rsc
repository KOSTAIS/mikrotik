# Prepares a MikroTik router (RouterOS v7) for Home Assistant.
#
# - creates a "homeassistant" group/user with only the rights it needs
# - creates a self-signed certificate and enables the HTTPS (www-ssl)
#   service, which the RouterOS REST API runs on
# - restricts that service to the Home Assistant host
#
# Edit the variables below, then upload the file and run:
#   /import file-name=ha-setup.rsc
# Run it on the router that is the CAPsMAN controller.

:local haIP "192.168.88.10"
:local haUser "homeassistant"
:local haPass "CHANGE-ME-to-a-long-random-password"
# Addresses allowed to reach the HTTPS/REST service. Add your admin subnet
# here (comma separated) if you also use WebFig over HTTPS.
:local allowedFrom "192.168.88.10/32"

# --- user ------------------------------------------------------------------
# read+rest-api: statistics; write: enable/disable interfaces;
# api: only needed for the optional HACS "Mikrotik Router" integration.
:if ([:len [/user group find name="homeassistant"]] = 0) do={
    /user group add name="homeassistant" policy="read,write,api,rest-api" comment="Home Assistant"
}
:if ([:len [/user find name=$haUser]] = 0) do={
    /user add name=$haUser group="homeassistant" password=$haPass address=$haIP comment="Home Assistant"
} else={
    /user set [find name=$haUser] group="homeassistant" password=$haPass address=$haIP
}

# --- HTTPS certificate -----------------------------------------------------
:if ([:len [/certificate find name="ha-https"]] = 0) do={
    /certificate add name="ha-https" common-name="router" key-usage="digital-signature,key-encipherment,tls-server" days-valid=3650
    /certificate sign "ha-https"
    # signing runs in the background on slow devices
    :delay 10s
}

# --- REST API service ------------------------------------------------------
/ip service set www-ssl certificate="ha-https" address=$allowedFrom disabled=no

# Optional: plain API, only for the HACS "Mikrotik Router" integration.
# /ip service set api address=$allowedFrom disabled=no

:put "Home Assistant access ready: https://<router-ip>/rest  user=$haUser"
