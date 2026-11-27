# Custom screen vs stock firmware (audit, 2026-11-25)

> **Status: finished 2026-11-25.** Every item in sections 1-4 was done, except **firmware install**, which Holden decided to skip (the screen shows the firmware notice and
> points to the admin panel or the stock screen for installing). Also still stock-only: profile management on the eSIM page, SIM data limits/reset, APN, lock operator / lock tower,
> Multi-WAN, tethering, Tor, VLAN, bridge, DPI, captive-portal sign-in. Wi-Fi writes (`wifi_rpc`) still run through the detached stand-in rather than `gl_call`, on purpose (hang handling). This
> work is in the published repo. **Later the same day Holden had text *sending* removed** (it wasn't working); section 4j (and the resend part of 4k) describe code that no longer exists.

Rule from Holden: before building anything, find out how the stock firmware does it and copy that.
Sources: the stock screen's labels (`/etc/gl_screen/language/text/default`) and strings (`strings /usr/bin/gl_screen`), the stock
web UI (`/www/views/gl-sdk4-ui-*.common.js.gz`), the system modules (`/usr/lib/oui-httpd/rpc/*`), and read-only
`ubus call gl-session call` probes. The stock screen is a compiled binary: what it does for each page is inferred from
its labels and call names, not from running it.

## 1. How my screen calls the router

Stock entry point: `ubus call gl-session call '{"module","func","params"}'` (`lib.gl_call`). It runs GL's modules in their own
service environment and also reaches the C modules (modem). Every module below answered a read-only probe through it.

| Feature | Module call | How mine runs it | Status |
|---|---|---|---|
| VPN | `vpn-client` | `gl_call` | stock path (done) |
| Mobile data, SIM switch, roaming | `modem` (C) | `gl_c_rpc` (the `glc` CGI nginx uses) | stock path |
| Airplane mode | `system.get/set_airplane_mode` | `gl_lua_rpc` stand-in | **migrate** |
| AdGuard Home | `adguardhome.get/set_config` | stand-in | **migrate** |
| Power & USB | `lpm`, `otg` `get/set_config` | stand-in | **migrate** |
| Ethernet port | `cable.get_ports_config / set_port_config` | stand-in | **migrate** |
| Block a client | `black_white_list.set_single_mac` | stand-in | **migrate** |
| Wi-Fi | `wifi.get_config / set_config` | stand-in + my hang handling | **migrate last** (riskiest) |

The stand-in is what made the VPN misbehave (wrong server, dropped tunnel). Same risk, so same fix.

**Update:** step 1 done for everything except Wi-Fi writes: `lib.gl_lua_rpc` now uses `gl_call`; reads verified identical to the old
path, writes untested on the device. The "migrate" marks above now read: airplane, AdGuard, Power & USB, Ethernet, Clients =
migrated (writes pending a device test); Wi-Fi = still the stand-in.

## 2. Settings the two screens do not share

Stock keeps its screen settings in `uci gl_screen.generic`: `BRIGHTNESS` (percent), `AUTO_LOCK_TIME`, `ALWAYS_ON`,
`ENABLE_PASSCODE`, `PASSCODE`, `HOUR_FORMAT`, `WAKE_DISPLAY_STYLE` (4 styles), `WALLPAPER_PAIR`. Mine keeps its own copies in
`/root/e5ui/config.json`. Effects: a passcode set on one screen does not exist on the other; brightness is written straight
to the backlight, so switching back to stock re-applies stock's saved value; time format and auto lock differ per screen.
Time zone: stock uses the router's (`system.get/set_timezone_config`); mine has its own in config.json.

**Update (step 2):** shared now: time zone (follows the router) and Screen always on / Auto lock 30 s-5 min (both written to
`gl_screen.generic`). Still separate: passcode (unknown encoding), brightness, time format, wake style, wallpaper.

## 3. Power

Stock: `system.reboot` and `system.poweroff`, with a "Slide to reboot / Slide to power off" panel and a
"Power Off Disabled" state. Mine runs `/sbin/reboot` and `/sbin/poweroff` directly, so it skips whatever GL's modules do
around them and ignores "power off disabled".

**Update (step 3):** reboot and power off now go through `system.reboot` / `system.poweroff`, with the `/sbin` command as backup.
Not done: "Power Off Disabled" and the slide-to-confirm panel.

## 4. Stock has it, mine doesn't

- **SIM:** SIM failover (auto switch, scheduled switch to preferred SIM, priority), SIM PIN unlock, per-SIM details and
  configuration, slot type, eSIM information.
- **Wi-Fi:** password, channel, TX power, hidden SSID, security type, band (radio bands), indoor/outdoor, Add Guest / IoT Wi-Fi, MLO.
- **Repeater:** Known Networks list with delete, change password, band auto-switch, BSSID details, username + password networks.
- **Clients:** connection type, traffic statistics, blocked-clients list.
- **SMS:** delete, send.
- **Network:** router IP address, subnet, guest and IoT gateways, IPv6 settings.
- **Internet:** Multi-WAN (failover / load balancing), tethering, USB Ethernet, Ethernet protocol / PPPoE.
- **Other:** network acceleration, firmware update check and install, captive-portal authentication, DPI / data statistics
  on the lock screen, Tor, VLAN, bridge, reset, 4 wake styles.

**Update (step 4a):** repeater Known Networks with delete is done (Wi-Fi tab -> Saved networks). Still missing from this list: SIM
failover / PIN unlock, SMS delete/send, firmware update notice, Wi-Fi password / channel, change repeater password.

**Update (step 4b):** text delete done (one text, or all read texts) and the read state now goes to the router. Still missing: send text,
delete all received / sent.

**Update (step 4c):** SIM failover done (enable, priority, scheduled switch). Still missing: SIM PIN unlock, SIM details, firmware update
notice, Wi-Fi password / channel, repeater password, send text.

**Update (step 4d):** firmware update notice done (More -> Firmware: version, release note, skip, check again; dot on More). Install is left to the
stock screen / admin panel on purpose. Still missing: SIM PIN unlock, SIM details, Wi-Fi password / channel, repeater password, send text.

**Update (step 4e):** Wi-Fi password change done for main and guest bands (stock rules: secured networks only, 8-63 characters). Still missing:
SIM PIN unlock, SIM details, Wi-Fi channel / TX power / hidden SSID, repeater password, send text.

**Update (step 4f):** Wi-Fi channel (Auto or a valid channel, locked while the repeater uses the radio) and hidden network name done. Still missing: SIM PIN
unlock, SIM details, Wi-Fi TX power, repeater password, send text.

**Update (step 4g):** repeater password change done (network in use; re-join with rollback). Still missing: SIM PIN unlock, SIM details, Wi-Fi TX power, send text,
repeater band auto-switch, firmware install.

**Update (step 4h):** Wi-Fi TX power done (Max / High / Medium / Low per radio). Still missing: SIM PIN unlock, SIM details, send text, repeater band auto-switch,
firmware install.

**Update (step 4i):** SIM PIN unlock done (with attempts-left display and safeguards; a PUK-locked SIM points to a phone, like stock). Still missing: SIM details, send text,
repeater band auto-switch, firmware install.

**Update (step 4j):** sending a text done (New text, Reply, confirm before sending, 160 characters). Still missing: SIM details, repeater band auto-switch, firmware install, a list of sent texts.

**Update (step 4k):** sent texts list done (state, resend, delete). Still missing: SIM details, repeater band auto-switch, firmware install.

**Update (step 4l):** SIM details done, read-only (SIM, network, cellular and modem information; the stock max bit rate is left out, its unit is unknown). Still missing: eSIM information,
repeater band auto-switch, firmware install.

**Update (step 4m):** Wi-Fi band (5 GHz / 6 GHz / Auto, the stock repeater "band auto-switch") done. Still missing: eSIM information, firmware install.

**Update (step 4n):** eSIM information done, read-only (EID, ICCID, IMSI, OS version, storage, profiles). Profile management is left to the admin panel. Remaining difference: firmware install
(left out on purpose).

**Update (step 4o):** network type (Auto / 5G / 4G) and band masking done (SIM -> tap the SIM -> Network & bands), copied from the stock *web UI*: the stock touchscreen has no band lock.
The write was tested on the live modem (all bands, a partial mask, a mask dropping the serving band, 4G only, 5G only; all reverted). Lock operator and lock tower are still admin-panel only.
Text *sending* (step 4j) was later removed because it wasn't working.

## 5. Mine has it, stock doesn't

Weather, currency (with a main-currency and a compare-with picker), speed test and monitor, two clocks, monthly data cap per SIM, quick panel, own wallpapers, accent color (5 presets + your own).

## 6. Matches stock

Mobile data on/off, SIM switch, roaming, airplane mode (RPC and glconfig flag), AdGuard (RPC), Clients block
(`set_single_mac`), Ethernet port mode (`set_port_config`), VPN (as of today).

## Suggested order

1. Move the stand-in calls to `gl_call` (airplane, AdGuard, Power & USB, Ethernet, Clients), then Wi-Fi.
2. Share screen settings through `gl_screen.generic` (and the router time zone).
3. Reboot / power off via `system.reboot` / `system.poweroff`.
4. Missing features by usefulness: repeater known networks + forget, SIM failover and PIN unlock, SMS delete, firmware update
   notice, Wi-Fi password / channel.
