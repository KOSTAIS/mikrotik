# MikroTik + Home Assistant

A Home Assistant custom integration that talks to a MikroTik router over the
RouterOS API. It gives you:

- **WAN and LAN statistics:** live download/upload rates and byte counters,
  plus whether the WAN link is up.
- **Router health:** CPU, memory and last boot time.
- **WAN switch:** turns the WAN interface on and off.
- **A switch for each Wi-Fi network (SSID):** Wi-Fi networks managed by
  CAPsMAN are found automatically, one switch per SSID. A switch turns that
  SSID on or off on every CAP and band at once, which makes it handy for
  guest or IoT networks you only turn on when needed. Each SSID also gets a
  connected-clients sensor.
- **Optional switches** for any other interfaces you pick.

It works with the new CAPsMAN (RouterOS 7 `wifi` package: `wifi-qcom`,
`wifi-qcom-ac`) and with legacy CAPsMAN (`/caps-man`). It detects which one
you use on its own.

## 1. Prepare the router

Run this on the CAPsMAN controller.

1. Edit the variables at the top of `routeros/ha-setup.rsc`: the Home
   Assistant IP and a strong password.
2. Upload the file (Winbox → Files) and run `/import file-name=ha-setup.rsc`.

   The script creates a `homeassistant` user that can only log in from the
   Home Assistant IP. It also enables **api-ssl** (port 8729) with a
   self-signed certificate.

### Make your on-demand Wi-Fi networks switchable

RouterOS only lets you enable or disable **static** Wi-Fi interfaces.
Interfaces that CAPsMAN creates dynamically can't be switched, and the
switch shows an error if you try. Check yours:

```
/interface wifi print         # new CAPsMAN: a "D" flag means dynamic
/caps-man interface print     # legacy CAPsMAN
```

If they show `D`, change the provisioning rule so it creates static
interfaces, then provision again:

```
# new CAPsMAN
/interface wifi provisioning set [find] action=create-enabled
/interface wifi radio provision [find]

# legacy CAPsMAN
/caps-man provisioning set [find] action=create-enabled
/caps-man remote-cap provision [find]
```

Your guest/IoT SSIDs stay in `slave-configurations` as before. After
provisioning, each SSID gets its own static interface on every CAP, and the
integration groups them under one switch per SSID.

## 2. Install the integration

**HACS:** add this repository as a custom repository (category
*Integration*), install **MikroTik Router (API)**, and restart Home
Assistant.

**Manually:** copy `custom_components/mikrotik_api` into
`<config>/custom_components/` and restart Home Assistant.

## 3. Add it in Home Assistant

Go to Settings → Devices & services → Add integration → **MikroTik Router
(API)**.

1. Enter the router IP and the `homeassistant` user and password. Keep
   *Use API-SSL* on and *Verify SSL* off, because the certificate is
   self-signed.
2. Pick the **WAN interface** (`ether1`, or `pppoe-out1` for PPPoE), the
   **LAN interface** (usually `bridge`), and any extra interfaces you want
   switches for.

To change the interfaces or the update interval (10 s by default), open the
integration's **Configure** menu.

## Entities

Entity IDs start with your router's identity, for example `home_router`.

| Entity | What it is |
| --- | --- |
| `sensor.*_wan_download` / `_wan_upload` | WAN rate, averaged over the update interval |
| `sensor.*_wan_downloaded` / `_wan_uploaded` | WAN byte counters. Feed them to `utility_meter` for daily or monthly usage. |
| `binary_sensor.*_wan_connected` | WAN link up |
| `sensor.*_lan_receive_rate` / `_lan_transmit_rate`, `_lan_received` / `_lan_sent` | LAN interface traffic |
| `sensor.*_cpu_load`, `_memory_used`, `_last_boot` | Router health |
| `sensor.*_wi_fi_clients` | Number of Wi-Fi clients. Its `clients` attribute lists every client (see below). |
| `sensor.*_<ssid>_clients` | Number of clients on one SSID, with the same `clients` list for that SSID |
| `switch.*_wan` | WAN interface on/off |
| `switch.*_wi_fi_<ssid>` | Turns that SSID on/off on every CAP. Attributes list the interfaces, clients, and whether the SSID is actually broadcasting. |
| `switch.*_interface_<name>` | Extra interfaces you selected |

New SSIDs show up automatically. You don't need to restart anything.

### Connected clients

Each client in the `clients` attribute has:

| Field | Source |
| --- | --- |
| `name` | DHCP lease comment if you set one, otherwise the host name, otherwise the MAC |
| `host_name` | Host name the device sent to the DHCP server |
| `mac`, `signal`, `uptime`, `interface` | Wi-Fi registration table on the CAPsMAN controller |
| `ssid` | Network the device is connected to |
| `ip` | DHCP lease |

Host names and IPs come from the DHCP server on the same router. Devices that
don't send a host name show their MAC. To give one a readable name, add a
comment to its lease (`/ip dhcp-server lease set [find mac-address=...]
comment="Kitchen plug"`). The list isn't saved to history, to keep the
database small.

Dashboard card (Markdown card) showing all clients:

```yaml
type: markdown
title: Wi-Fi clients
content: |
  | Name | SSID | MAC | IP | Signal |
  |---|---|---|---|---|
  {% for c in state_attr('sensor.mikrotik_router_wi_fi_clients', 'clients') or [] -%}
  | {{ c.name }} | {{ c.ssid }} | {{ c.mac }} | {{ c.ip or '-' }} | {{ c.signal or '-' }} |
  {% endfor %}
```

Replace `mikrotik_router` with your router's entity prefix. For one SSID
only, use `sensor.mikrotik_router_old_wifi_clients` instead.

### Example: guest Wi-Fi for 3 hours

```yaml
script:
  guest_wifi_3h:
    sequence:
      - action: switch.turn_on
        target: { entity_id: switch.home_router_wi_fi_guest }
      - delay: "03:00:00"
      - action: switch.turn_off
        target: { entity_id: switch.home_router_wi_fi_guest }
```

## Cautions

- **Turning the WAN off cuts internet access,** including Nabu Casa or any
  other remote access to Home Assistant. You won't be able to turn it back
  on from outside your home.
- **Don't add a switch for the interface Home Assistant uses to reach the
  router,** such as the LAN bridge. If you turn it off, you lock yourself
  out.

## Without a custom integration

`homeassistant/packages/mikrotik.yaml` is a YAML-only alternative that uses
the REST API (`www-ssl`) instead of the API. To use it, uncomment the
`www-ssl` line in `ha-setup.rsc`. Use either the package or the
integration, not both.

## Development

```
uv venv -p 3.13 && uv pip install -r requirements_test.txt
.venv/bin/pytest
```

The tests use an in-memory fake of the RouterOS API (`tests/fake_routeros.py`).
