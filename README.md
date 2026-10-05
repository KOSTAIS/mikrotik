# MikroTik + Home Assistant

Shows your MikroTik router's LAN and WAN statistics in Home Assistant, and
lets you turn the WAN interface and the Wi-Fi interfaces managed by CAPsMAN
on and off. It uses the built-in RouterOS v7 REST API, so you don't need to
install anything on the router or any custom component in Home Assistant.

## What you get

| Entity | What it shows / does |
| --- | --- |
| `sensor.mikrotik_wan_download` / `_upload` | Live WAN rate (Mbit/s, every 10 s) |
| `sensor.mikrotik_wan_downloaded` / `_uploaded` | WAN byte counters, with daily and monthly totals through `utility_meter` |
| `binary_sensor.mikrotik_wan_running` | Whether the WAN link is up |
| `sensor.mikrotik_lan_rx` / `_tx` | Live LAN (bridge) rate |
| `sensor.mikrotik_lan_received` / `_sent` | LAN byte counters |
| `sensor.mikrotik_cpu_load`, `_memory_used`, `_uptime`, `_routeros_version` | Router health |
| `sensor.mikrotik_wi_fi_clients` | Number of Wi-Fi clients across all CAPs |
| `switch.mikrotik_wan` | Turns the WAN interface on and off |
| `switch.mikrotik_wifi1`, `switch.mikrotik_wifi2` | Turns CAPsMAN Wi-Fi interfaces on and off |

## Setup

### 1. Router (on the CAPsMAN controller)

1. Edit the variables at the top of `routeros/ha-setup.rsc`: the Home
   Assistant IP and a strong password.
2. Upload the file (Winbox → Files, drag and drop) and run
   `/import file-name=ha-setup.rsc`.
3. Find the names of your interfaces:
   ```
   /interface print where type=ether or type=bridge or type=pppoe-out
   /interface wifi print        # new CAPsMAN (wifi-qcom / wifi-qcom-ac)
   /caps-man interface print    # legacy CAPsMAN (wireless package)
   ```
4. Check it from the Home Assistant host:
   ```
   curl -k -u homeassistant:PASSWORD https://192.168.88.1/rest/system/resource
   ```

### 2. Home Assistant

1. Enable packages in `configuration.yaml` if you haven't already:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. Copy `homeassistant/packages/mikrotik.yaml` into `<config>/packages/`.
3. Edit the placeholders listed at the top of that file: the router IP
   `192.168.88.1`, WAN `ether1`, LAN `bridge`, and Wi-Fi `wifi1`/`wifi2`.
   Add or remove Wi-Fi switch blocks to match your CAPs.
4. Add `mikrotik_user` and `mikrotik_password` to `secrets.yaml` (see
   `homeassistant/secrets.yaml.example`).
5. Developer tools → YAML → Check configuration, then restart.

## Notes

- **PPPoE / LTE WAN:** for the traffic sensors, point them at the logical
  interface (for example `pppoe-out1`). The WAN switch can stay on the
  physical port.
- **Disabling the WAN cuts internet access,** including Nabu Casa or any
  other remote access to Home Assistant. You won't be able to turn it back
  on from outside your home. Home Assistant on the LAN still reaches the
  router, so the switch keeps working locally.
- **Don't add a switch for the LAN interface or bridge** that Home Assistant
  uses to reach the router. If you turn it off, you lock yourself out.
- **CAPsMAN:** the switches act on the controller (`/interface/wifi
  disable`), which is how CAPsMAN-managed interfaces are meant to be
  controlled. You can't disable them on the CAP itself. For legacy
  CAPsMAN, follow the comment at the top of the package.
- **Certificate:** the router uses a self-signed certificate, so the package
  sets `verify_ssl: false`. The user is limited to the Home Assistant IP.

## Alternative: HACS "Mikrotik Router" integration

If you want everything set up through the UI, including device tracking and
per-interface entities for every port, install
[Mikrotik Router](https://github.com/tomaae/homeassistant-mikrotik_router)
from HACS. Uncomment the `api` service line in `ha-setup.rsc`, because that
integration uses the API on port 8728 rather than REST. You can keep this
package alongside it for the CAPsMAN Wi-Fi switches.
