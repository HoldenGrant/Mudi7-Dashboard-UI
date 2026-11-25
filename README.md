# Mudi7 Dashboard UI

A replacement touchscreen UI for the GL.iNet GL-E5800's 240×320 display, running on the router at
`10.10.1.1` (`/root/e5ui`, service `e5ui`).

- **Tabs**: Home, SIM, Wi-Fi, VPN and More, plus a lock screen with an optional passcode.
- **Mobile**: SIM1 / SIM2 / eSIM switching, mobile data, roaming and per-SIM data caps.
- **Wi-Fi**: repeater join with an on-screen keyboard, band switches, and QR codes for the main and
  guest networks.
- **Other features**: WireGuard VPN with a location picker, texts (read and delete), weather with worldwide city search,
  a monitor with a speed test, currency (pick your main and compare-with currencies), network type and band masking
  (SIM → Network & bands), and an accent color (5 presets or your own).
- **Router settings**, matching the stock More menu: clients and blocking, guest Wi-Fi (on/off and
  rename), Ethernet port WAN/LAN, display and wallpaper, security, power & USB, AdGuard Home, and more.

## Docs

- **[User guide](docs/USER_GUIDE.md)**: every screen and setting, status icons, the power button, and
  switching back to the stock screen.
- **[Developer guide](docs/DEVELOPER.md)**: how the app works, the router API calls behind each feature,
  config keys, deploying, preview and screen capture, fresh install, and troubleshooting.

## Quick reference

```sh
# deploy a change
scp -O router/app.py root@10.10.1.1:/root/e5ui/ && ssh root@10.10.1.1 /etc/init.d/e5ui restart

# render every screen to PNGs without touching the display
ssh root@10.10.1.1 'cd /root/e5ui && python3 app.py --preview /tmp/e5pv'

# back to the stock screen (and "on" to return)
ssh root@10.10.1.1 /root/e5ui/toggle.sh off
```

## Layout

| Path | Contents |
|---|---|
| `router/` | Everything installed on the router: `app.py` (UI), `lib.py` (router helpers), service scripts, `init.d/` |
| `tools/` | `extract.py` and the upstream plugin source it reads to regenerate `lib.py` |
| `prototype/` | The clickable design prototype ([canvas](https://claude.ai/artifact/KszmJnj8Cw5w1Nw6EciauN)) |
| `docs/` | User and developer guides |

Based on [gl-e5800-dashboard](https://github.com/GLiNet-Community-Scripts/gl-e5800-dashboard) (MIT, see
`LICENSE-upstream`).
