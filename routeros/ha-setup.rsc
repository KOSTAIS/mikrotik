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
# A small local CA signs the API certificate (RouterOS won't self-sign a
# certificate that lacks key-cert-sign: "CA not found").
# First drop unsigned leftovers from an earlier failed run.
:foreach c in=[/certificate find where (name="ha-ca" or name="ha-https")] do={
    :if ([:len [/certificate get $c fingerprint]] = 0) do={ /certificate remove $c }
}
:if ([:len [/certificate find name="ha-ca"]] = 0) do={
    /certificate add name="ha-ca" common-name="ha-ca" key-usage="key-cert-sign,crl-sign" days-valid=3650
    /certificate sign "ha-ca"
    # signing runs in the background on slow devices
    :delay 10s
}
:if ([:len [/certificate find name="ha-https"]] = 0) do={
    /certificate add name="ha-https" common-name="router" key-usage="digital-signature,key-encipherment,tls-server" days-valid=3650
    /certificate sign "ha-https" ca="ha-ca"
    :delay 10s
}

# --- API service (custom integration) --------------------------------------
# Services to enable. Add "www-ssl" only for homeassistant/packages/mikrotik.yaml
# (REST), or "api" (port 8728) only if you untick "Use API-SSL".
:local haServices {"api-ssl"}

# RouterOS 7.24 renamed "address" to "available-from". The command is built
# with :parse so older versions fall back to "address" instead of failing.
:foreach svc in=$haServices do={
    :local cmd "/ip service set $svc certificate=ha-https disabled=no"
    :do {
        :local f [:parse "$cmd available-from=\"$allowedFrom\""]
        $f
    } on-error={
        :local f [:parse "$cmd address=\"$allowedFrom\""]
        $f
    }
}

:put "Home Assistant access ready: api-ssl port 8729, user=$haUser"
