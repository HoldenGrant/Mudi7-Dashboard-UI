# Handoff: E5800 screen UI

State as of **2026-11-25, evening (Manila)**. Read this first, then [docs/DEVELOPER.md](docs/DEVELOPER.md)
for how the app works and [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for what each screen does.

> **2026-11-27 (latest):** released as **v1.0.3** (package 1.0.3, identical to `router/`, installed on the router). Everything below dated 2026-11-25 to 2026-11-27 is in that release;
> older "not committed" remarks in the dated sections are history. See the newest dated sections at the end for the critique work (Home uplink, VPN status, legibility, QR pages, More regroup, polish) and scroll fixes.
>
> **2026-11-25 (final state, evening):** after the audit: text **sending was removed** (it wasn't working; reading, delete and the Sent list stay), a **main + compare currency**
> picker was added, **Network & bands** (stock web UI's network type + band masking; write tested live), and an **accent color** option (5 presets + custom). The router runs
> package **gl-e5800-touch-ui 1.0.2** (identical to `router/` that evening). Sections below that describe sending a text (step 4j / "Send a text") are history.
>
> **2026-11-25 (end of session): stock comparison finished.** See `docs/STOCK_COMPARISON.md` and the dated sections below (VPN rebuild, stock-path migration, shared settings, power, saved networks, text
> delete/send/sent list, SIM failover/PIN/details/eSIM, firmware notice, Wi-Fi password/channel/hidden/TX power/band, repeater password). Rule from Holden: before building anything, check how the stock firmware does it
> and copy that. Skipped on purpose: firmware install. (Committed and published later: see 2026-11-27.) Many real writes were never tried on the device (listed per section: Wi-Fi changes, sending a text, SIM PIN, band change, reboot via GL).

> **2026-11-25 ~04:05: firmware updated to 4.10.4; custom UI reinstalled.** The update wiped `/root/e5ui`, the init
> scripts and python3/Pillow. Reinstalled per docs/DEVELOPER.md "Fresh install" (opkg: python3, libtiff6, qrencode,
> zoneinfo-*, python3-pillow --nodeps), copied `router/*` and `init.d/*`, ran `toggle.sh on`. `FONT_BUMP` is now 3
> (was 2). Cosmetic cost: long Wi-Fi names are shortened on Join (band chip takes width); SIM rows say "SIM1"
> not "SIM1 · physical". 4.10.4 has the same qcacld32.sh and driver ini, so the Wi-Fi findings below still hold.
> **Swipe-down quick panel (2026-11-25):** `draw_panel()` / `close_panel()`, state `panel_open` + `panel_drag`
> (live extent while dragging). Opens by dragging down from y < 28 (status bar), closes by tap outside or drag up;
> never on the lock screen. 3×3 tiles: Data, Wi-Fi (`panel_wifi_toggle`: both main bands via `bg_wifi`, remembers the
> bands in `cfg["wifi_last"]`), VPN (`panel_vpn_toggle` = `vpn_switch()`, the tunnel's Use switch; opens the location list if no server is set; see Round 3 below) / Ad block (`set_agh(True, not blocking)` behind the same confirm as More →
> AdGuard Home), Airplane, Network (opens the Wi-Fi tab) / Screen off, Reboot, Shut down (same confirm sheets as
> More). The Lock tile was removed at Holden's request. Holden confirmed the panel and Ad block work on the device
> (swipe thresholds: 6 px to start dragging, opens past 40% of PANEL_H = 242).
> **Faster drawing (2026-11-25):** `App.t()` caches rasterized text masks per (text, font, anchor) and pastes them
> (RGB surfaces only). Renders went from 40–55 ms to 9–17 ms (home/sim/wifi/more); idle CPU ~1% of a core.
> Output matches the old path except sub-pixel shifts in a few small chips (positions are now rounded).
> Passcode keypad keys enlarged to 68×44 (was 56×34), digits 20 px; both the lock pad and Security → Change passcode.

## What this is

A custom 240×320 touchscreen UI for Holden's GL.iNet GL-E5800 travel router (`10.10.1.1`, SSH `root`
with key auth from this Mac). It replaced both the stock screen and the community
[gl-e5800-dashboard](https://github.com/GLiNet-Community-Scripts/gl-e5800-dashboard) plugin, which has
been uninstalled (with numpy) at Holden's request.

- **Source of truth:** `~/Documents/e5800-screen/router/` (`app.py` UI, `lib.py` router helpers, service
  scripts).
- **On the router:** `/root/e5ui`, services `e5ui` (boot order S13) and `homebutton` (S14). The stock
  `gl_screen` is disabled.
- **Design prototype:** <https://claude.ai/artifact/KszmJnj8Cw5w1Nw6EciauN> (behind the current build
  in places; the router is the reference now).

## Current state

The UI is live and matches every section of the stock More menu. Holden uses it daily: changed the
weather city to Cebu City, set the wallpaper to Lock + Home, turned on AdGuard blocking, read texts, and
renamed the guest Wi-Fi.

Router settings right now:

| Setting | Value |
|---|---|
| Internet | Wi-Fi repeater "Space Rice"; mobile data off; SIM1 Smart in slot 1, physical DITO in slot 2 (slot type physical), eSIM unused |
| AdGuard Home | On, blocking |
| Guest Wi-Fi | Both bands **off**. SSIDs are mismatched: `guest2g` = "Guest-A", `guest5g` = "GL-E5800-xxx-Guest" (a rename stopped halfway; see below) |
| Ethernet port | LAN mode, no cable |
| Data roaming | On (saved SIM setting; no data in use) |

## Recent work: not yet in the docs

These changes are deployed and in `router/app.py`, but `docs/` doesn't describe them yet:

- **Mobile screen:** the *Mobile data* toggle moved to the top and *Data roaming* to the bottom. With
  data off, no SIM card is selected, and tapping a SIM asks to turn data on with it (`ask_data_with`).
  Home's SIM card says "data off".
- **Lock screen status card** (`lock_info`), in both lock styles: Internet / Mobile / VPN / AdGuard.
  The "VPN on" chip was removed.
- **Keyboard:** keys are 34 px tall (30 px on city search), and touch targets extend into the gaps.
- **Guest Wi-Fi rename:** More → Network → Name (`rename_guest` → `rename_wifi`). It renames both
  bands and keeps encryption and key.
- **Wi-Fi changes run in the background:** a spinner shows in the toggle row (`bg_wifi`, `self.pending`,
  `wifi_lock`) instead of blocking the screen.
- **Wi-Fi RPC rewrite** (`wifi_rpc`): see the incident below.
- **Boot:** `e5ui` moved from S95 to S13, with `warm_up()` retries. *This one is already in DEVELOPER.md.*
- **Bug pass (2026-11-24):**
  - Text wrapping is cached (`wrap()`). Settings screens draw in ~50 ms instead of 190–270 ms.
  - Holding the power button no longer unlocks the screen: the stock-screen prompt now appears over the
    lock screen.
  - SIM switch, mobile data, AdGuard and VPN now show "Failed: …" when the router doesn't apply the
    change.
  - The wallpaper cache keeps both the lock and home versions.
  - Recent cities are de-duplicated by name plus location.
  - **Boot progress bar over the UI:** GL's `screen_boot` (started in `/lib/preinit/02_screen_boot`) keeps
    drawing until stock `gl_screen` takes over. With `gl_screen` disabled it ran forever, drawing over the
    UI and using CPU. `run.sh` now runs `killall screen_boot` before starting the app.
  - **Mobile data switch** now shows the saved setting (`get_dial()`: `dial_status == 0` for the SIM in use
    in `cellular.network status`, the same rule as the stock web UI's `cellular.lua`), not whether
    `modem_cpu` happens to be up. For about a minute after boot the modem reports "off" before it redials,
    so the last real setting is kept in `config.json` (`data_last`) and shown until about 3 minutes of
    uptime (`boot_until`). `warm_up()` re-polls `sims`/`sim` every 5 s in that window.
  - **Monthly data per SIM** (`Usage`, `cache/usage.json`, keyed by ICCID): adds the increase in the modem's
    `traffic_total`, which is cumulative and never resets monthly. 0 readings are ignored, a drop is
    treated as a counter reset, and the total restarts on the 1st. Saved every 10 MB or 10 min, and on
    exit. November started from the full modem counter.
  - **SIM tab showed 0.0 GB for the other SIM:** `cellular.network status {"bus":"cpu"}` returns only the
    SIM in use. `get_sims` now calls it without a bus filter. The SIM tab also shows each SIM's phone number.
  - **Wi-Fi tab per band** (2.4 GHz / 5 GHz sections): Network, Name (`name_row` → `rename_net` → `rename_wifi`
    on one iface, confirm first) and Network mode (`mode_row` → `set_wifi_mode`). The mode payload copies the
    stock Modify Wi-Fi drawer: iface form + device/txpower/hwmode/htmode/channel, plus `usemode` from
    `bandmode` for bands in `band_mutex` (5G+6G). htmode is kept when valid for the new mode, else the widest.
    `get_config` reports 5 GHz `channel` 36 while uci says `auto`, so channel is sent as 0 when uci is auto.
    Radios come from the `radios` job. Guest Wi-Fi moved from More → Network to the Wi-Fi tab, behind a fixed Main / Guest switch (`sel["wifi_tab"]`), with the same rows
    (`toggle_guest`, `name_row`, `mode_row`; guest bands map to the same radio in `BAND_RADIO`). More → Network
    now holds only Ethernet and the router IP. Neither rename
    nor mode change has run on the router yet.
  - **Join a network** shows a band tag (2.4 GHz / 5 GHz / 2.4/5 GHz) from `scan_nets()`.

## Incident: guest Wi-Fi stuck turning on (2026-11-25; fixed, guest 2.4 GHz verified)

**Cause (firmware bug):** for a network with no `ifname` in uci (both guest bands), GL's `wifi.set_config` runs
`/sbin/wifi multi_up wifi0` with no `wlanX` after it. `multi_radio_wifi_updown` in `/lib/wifi/qcacld32.sh`
only advances its outer `device_idx` loop inside the per-interface loop, so with no interface it spins
forever (shell in `pipe_read`, load ~5, `qcacld32_commands.txt` logs only the "multi_up wifi0" line). uci
says enabled, but no guest interface exists. The stock web UI sends the same call. The old 5-minute
"hung" cut-off in `wifi_reloading()` then let a second guest band's reload start on top.

**Fix (in `router/app.py`, deployed):**
- `wifi_stuck(args)` spots the bad call; `wifi_reloading()` ignores stuck reloads; `wifi_rpc` watches its own
  lua's children and, on a stuck one, ends only its own tree (`end_tree`) and raises `WifiStuck`, so the toast
  says "Couldn't…" instead of waiting forever.
- `set_wifi_enabled` refuses to turn on a network with no uci `ifname`.
- **A full `/sbin/wifi up` fallback was tried and removed: never use it.** The 02:27 boot (guest still enabled)
  ran `assign_vif_ifname`, which auto-assigned guest2g `wlan1`, already the main 5 GHz interface (its
  per-radio name pool assumes wifi0 = wlan0/1, but GL pins wifi5g to wlan1). Afterwards uci held
  `guest2g.ifname=wlan3` and `guest5g.ifname=wlan4` (wlan4 = the repeater sta). Both guest APs kept
  broadcasting (wlan3, and wlan2 on 5 GHz) while uci said `disabled=1`. The 5 GHz radio then had sta + 2 APs
  while the firmware's concurrency mode counted guest5g as off, and **the repeater couldn't join anything**
  ("connect timeout" every ~40 s).
- After Holden's 03:04 reboot the guest ifnames were gone again (guests off, repeater joined fine).
- **Current fix:** `name_iface()` writes a fixed, unused uci `ifname` before turning a guest band on
  (`GUEST_IFNAME`: guest2g `wlan3`, guest5g `wlan5`; refuses if the name is in use). GL's reload is then
  called as `multi_up wifi0 wlan3`, and boot keeps the name ("manual-used").
- **Verified live 03:11:** guest 2.4 GHz on, "Guest-A" broadcasting after ~5 s, reload finished in ~35 s,
  repeater stayed connected.
- **Guest 5 GHz while the repeater is on 5 GHz: refused by the driver** (03:12, `policy_mgr_allow_concurrency:
  disallow connection`; `vif_is_started wlan5` failed after 60 retries). uci says on, `wlan5` exists as an AP
  with no SSID, repeater unaffected. Firmware limit (main 5 GHz was off at the time). The screen now checks
  `broadcasting()` after turning a band on and says so. Guest toggles show `guest_on()` (uci on AND an SSID up).
- **Cause: a driver concurrency rule, not a fixed count.** `policy_mgr_get_pcl_4_port: Can't find index for 4th
  port pcl table` means the policy manager has no entry for that particular 4-connection combination (at the
  time: main 2.4 + guest 2.4 on ch 1, sta on 5 GHz ch 36, plus guest 5 GHz). The ini allows 6
  (`gNumVdevs=6`, `gMaxConcurrentActiveSessions=6` in /etc/misc/wifi/WCNSS_qcom_cfg.ini). Holden says the stock
  UI can run all networks; unverified which combination or start order. A brief "max 3" pre-check was
  removed. Now a refusal is found after the reload (`broadcasting()`) and shown on a sheet.
- **Confirmed 03:35: with the repeater joined, the driver runs the sta + 2 APs, and refuses a 4th interface**
  (any band; both 5 GHz networks were refused with main 2.4 + guest 2.4 + sta up). Turning guest 2.4 off then
  guest 5 on worked: "Guest-B" broadcast, no refusal. Holden says stock UI runs all four, probably on mobile data
  (no sta); not tested. If asked: test all four on mobile data.
- **CONFIRMED by Holden (03:50): on mobile data (no repeater sta) all four networks run on the stock UI.** So the
  limit is sta + 2 own networks only while the router is joined to Wi-Fi. The custom UI's `room_for()` already
  only offers a swap when `joined_to_wifi()`; on mobile data it just tries.
- **UI handling of the limit (deployed 03:4x):** switches show `net_on()` (saved on AND broadcasting) for all four
  networks; a refused turn-on is saved back as off; while joined to Wi-Fi with 2 own networks running,
  `room_for()` opens a "Make room: turn off" picker and `bg_swap()` turns one off then the other on (two reloads).
  The limit itself (driver, 4th interface) is not fixable in software; firmware 4.10.4 has the same scripts/ini.
- **Main 5 GHz start hung forever (03:19):** after a repeater connect GL moved `wlan4` from `wireless.sta.ifname`
  to `guest5g.ifname`, leaving the sta nameless. `hostapd_setup_vif` (qcacld32.sh ~1651) then ran
  `hostapd_cli -i $pri_ifname status` with an empty name = `hostapd_cli -i status`, which never returns.
  Fix in app.py: `fix_ifnames()` before every Wi-Fi change (restore `sta.ifname=wlan4`, move guest5g to
  wlan5) and `unstick_hostapd_cli()` (ends only that exact process, if a /sbin/wifi reload started it).
  The live router still had the stuck reload (pids ~1392-1532) when this was written; ending it needs
  Holden's OK, or a reboot.
- **GL rewrites `guest5g.ifname` to `wlan4` (= the repeater sta) after a repeater connect** (seen at 03:19 when
  Holden rejoined the home network; guests were also switched off then). So `set_wifi_enabled` always calls
  `name_iface()` for guest bands, which resets the name to `GUEST_IFNAME` before the reload. Main 5 GHz
  (`wifi5g`) is off in uci, which Holden presumably did.

## Incident: VPN wouldn't connect (2026-11-25; rebuilt on GL's real API, needs a live connect test)

- **First cause:** on firmware 4.10.4 `route_policy` has no `rule` section until a tunnel exists, and the update
  wiped it. The old code edited that rule, found none, did nothing, and reported "VPN didn't connect".
- **Second round (connected but wrong server, couldn't turn off, dropped seconds later):** my first rebuild ran GL's
  `vpn-client` Lua module through `lib.gl_lua_rpc`, a stand-in for GL's service environment. It created the tunnel,
  but the screen could not see the active server (the rule has no `peer_id`; the tunnel's server is in GL's tunnel
  config), so it showed "Off" while on and offered connect instead of disconnect. The tunnel also ended up with
  server 1535 (Seattle) instead of the chosen 1559 (Singapore), and the log showed `ifup wgclient1` then
  `ifdown ... cause=iface_disabled` 4-8 s later; the shim is the main suspect for both, not proven.
- **Now:** everything goes through `lib.gl_call(module, func, params)` = `ubus call gl-session call {module,func,params}`,
  the entry point the stock touchscreen and web UI use, run in GL's own environment. Errors come back as a top-level
  `error` or `result.err_msg`. Calls are the stock UI's (read from `/www/views/gl-sdk4-ui-vpn-client.common.js.gz`):
  `get_tunnel`; `add_tunnel {from:{type:default}, to:{type:default}, via:{type:wireguard, configs:[{group_id,
  id_list:[peer]}]}, name:"Tunnel 1", enabled:true}` when none exists; `set_tunnel {enabled:true, tunnel_id, via}`
  when one does; `stop {group_id, peer_id, type}` to disconnect (backup: `set_tunnel enabled:false`, then rule off +
  vpn-client restart, `lib.force_wireguard_off`). `group_id`/`peer_id` are numbers from the uci section
  (`peer_1559` is peer 1559, group 10007).
- **Status** comes from `get_status().status_list` like the stock UI: each entry has `peer_id`, `peer_name`,
  `group_id`, `tunnel_id`, `enabled` and (while running) a numeric `status` (1 connected, 2 connecting). The first
  look after a change waits 2 s (stock waits 5 s). `vpn_set` fails with "Joined a different server" if GL connects
  a peer other than the one asked for.
- **Not verified:** a real connect. It reroutes every device and the permission check blocked my own test, so the
  `status` field while connected is still unseen (the code also accepts `enabled` + interface up). Read-only calls
  (`get_tunnel`, `get_status`, error handling) were checked against the live router. The router was left with
  "Tunnel 1" present but disabled, saved to server 1535.
- `wg-client` is a native `.so`; `gl_call` can reach it too if ever needed.
- **Crash found 2026-11-25 08:52 (fixed):** a comment had swallowed the first argument of the "Switch to the stock
  screen?" `confirm(...)` in `tick()`, so holding the power button raised TypeError three times and `run.sh` fell back
  to the stock screen. Re-enable with `toggle.sh on`.
- **VPN tracing:** every `add_tunnel`/`set_tunnel`/`stop` (with reply), every change of the `get_status` entry, and every
  VPN tap is logged under the tag `e5vpn`: `ssh root@10.10.1.1 'logread | grep e5vpn'`. Seen twice before this: the
  tunnel comes up and `ifdown ... iface_disabled` follows 4-8 s later, cause unknown; the log should show whether a
  tap or a call did it.

- **Round 3 (Holden: copy how the stock works): VPN page rebuilt on the stock model.** The stock dashboard/screen has a
  tunnel with a **Use** switch, a **Via** (server) and **Settings**. Stock's switch is `set_tunnel {tunnel_id, enabled}`
  only; my `stop {group_id,peer_id,type}` (the VPN-client-page call) also clears the tunnel's server, which is why the
  location kept changing. Now: `lib.get_vpn_tunnel()` (job `vpnt`), `set_vpn_enabled`, `set_vpn_location`
  (`set_tunnel {tunnel_id, via}`; `add_tunnel ... enabled:false` when no tunnel), `set_vpn_options` (`set_options`);
  screens `v_vpn` (switch, Location, Settings), `v_vpn_loc`, `v_vpn_opts` (kill switch, remote LAN access, masquerading,
  services use VPN); `cfg["vpn_peer"]` is no longer used. `vpn_switch()` serves the page and the panel tile.
  `add_tunnel` with `enabled:false` is unverified. Live router: tunnel 24 exists, off, **no server saved** (the old `stop`
  cleared it), so the first step is choosing a location. Screens previewed with live data; no real connect run.

- **Round 3b (works, "cannot turn it off"):** the router switched off fine (`set_tunnel enabled:false` accepted, `ifdown wgclient1`),
  but the screen kept showing connected. Cause: `lib.Refresher` never published a `None` result (`if value is not None`),
  so "no VPN connected" (None) left the last connected peer in place and each tap sent another "off". Fix:
  `Refresher.add(..., none_ok=True)` publishes None as a real answer (a *raised* error still keeps the old value);
  `wga` and `vpnt` use it, their reads are `strict` (raise on a failed ubus call), and `App.vpn_refresh` publishes both
  right after every VPN change. Anything else that legitimately returns None has the same trap.
  Connected status as seen: `status` 2 while connecting, 1 connected (with `ipv4`, `rx_bytes`), key absent when off.

## Stock-path migration (2026-11-25, step 1 of docs/STOCK_COMPARISON.md)

`lib.gl_lua_rpc(path, method, params)` now calls `gl_call(basename(path), ...)` (`ubus call gl-session call`, the stock entry
point) instead of the Lua stand-in. That moves airplane mode (`system`), AdGuard Home, Power & USB (`lpm`, `otg`), Ethernet
port (`cable`), Clients block (`black_white_list`), and every `gl_get` read (including `wifi.get_config`) onto the stock path.
Read parity was checked on the router: all 8 read calls return identical JSON through both paths. **Writes are not yet
exercised on the device**; test airplane, AdGuard, a Power & USB toggle, block/unblock a client, Ethernet mode.
**Still on the stand-in on purpose:** Wi-Fi writes (`lib.gl_wifi_call` -> `gl_lua_shim_rpc`, and `app.wifi_rpc`, which runs
`wifi set_config` detached and has the firmware-hang handling). Migrating that is the last step and needs live testing,
because `wifi.set_config` can run for minutes and hits the qcacld32 loop bug.

## Shared screen settings (2026-11-25, step 2 of docs/STOCK_COMPARISON.md)

- **Time zone:** the clocks now follow the router's zone (`lib.get_router_zone()`, job `tzr`, 300 s), like the stock screen;
  `cfg["tz"]` is only the fallback. `app.zone(name)` turns a name into a tzinfo: exact name, then without `Etc/` (the router
  has `GMT-8` but no `Etc/` directory), then a fixed offset (Etc/GMT-8 = UTC+8), else None. Second clock still uses its own city.
- **Screen always on / Auto lock:** read from `uci gl_screen.generic` (`ALWAYS_ON` 0/1, `AUTO_LOCK_TIME` seconds) at start-up
  (`App.sync_from_stock`) and written there on every change (`lib.stock_set`). Auto lock "Never" is NOT written: its stock
  encoding is unconfirmed (and values outside 30/60/300 are ignored on read).
- **Not shared yet, and why:** `PASSCODE` is stored as 6 characters that are not base64/hex/digits, so I can't translate it and a
  wrong write could lock the stock screen: passcodes stay separate. `BRIGHTNESS` (stock 75 = backlight 95/120) and `HOUR_FORMAT`
  (0 or 1, meaning unconfirmed; stock default 0, router now 1) need a calibration on the stock screen. `WAKE_DISPLAY_STYLE`
  has 4 stock styles vs my 2, `WALLPAPER_PAIR` uses stock images.
- `Refresher` result `tzr` is published only when non-empty (a failed read keeps the old zone).

## Reboot / power off via GL (2026-11-25, step 3 of docs/STOCK_COMPARISON.md)

`lib.reboot_router` / `lib.shutdown_router` now call `system.reboot` / `system.poweroff` through `gl_call` (stock screen tasks `reboot`
/ `poweroff`; the web UI sends `{delay: 1}` for reboot), on a thread. If GL refuses, or the router is still up after 30 s, the plain
`/sbin/reboot` / `/sbin/poweroff` runs, so the button always acts. Fallback logic unit-tested with stand-ins; **a real reboot and
power-off through GL are not yet tried on the device**, and `poweroff` taking `{delay: 1}` is a guess copied from reboot (a refusal
just triggers the fallback). Not done: the stock "Power Off Disabled" state (rule unknown; its task is `check_poweroff_enable`) and
the "Slide to power off" panel.

## Saved Wi-Fi networks (2026-11-25, step 4a of docs/STOCK_COMPARISON.md)

Wi-Fi tab (Main) -> **Saved networks** (`v_saved`) lists the stock "Known Networks": `repeater.get_saved_ap_list` (job `savedap`,
120 s; only SSIDs are kept, never the keys), the one in use marked; tapping one asks to forget it: `repeater.remove_saved_ap {ssid}`
(payload copied from the stock web UI), then `savedap` and `rep` refresh. Rendered with live data (2 networks); **forgetting not
tried on the device** (it would delete a real saved network). Still to do from the stock list: SIM failover and PIN unlock, SMS
delete, firmware update notice, Wi-Fi password/channel/TX power/hidden SSID, repeater change password / band auto-switch.
Stock screen task names worth reusing (from `strings gl_screen`): `remove_saved_ap`, `set_repeater_portal`, `set_cloud_services`,
`task_remove_sms`, `task_set_sms_read`, `task_cellular_set_band_config`, `task_check_usb_mode_selection`.

## Delete texts (2026-11-25, step 4b of docs/STOCK_COMPARISON.md)

Copied from the stock web UI (`gl-sdk4-ui-sms`) and stock screen task names (`remove_sms`, `set_sms`, `get_sms_list`): `modem.remove_sms
{bus:"cpu", name, scope:10}` deletes one text, `scope:1` all read texts (12 / 13 = all received / sent, unused); `modem.set_sms
{bus, name, status:1}` marks one read. Verified read-only that stock's message `name` is the spool file name and status 0 is a file
in `/etc/spool/sms/incoming`, so the existing spool reader stays and `lib.get_sms_messages` now adds `name` and `status`
(0 in `incoming`, else 1). Texts screen: open an unread text -> also `set_sms` (background thread), so the stock screen shows it
read; `App.is_unread` = status 0 and not opened here; text view has **Delete this text**, list has **Delete read texts**
(both confirm first). **Delete and mark-read not tried on the device**: the only text on the router is a real one. Whether
`set_sms status:1` moves the file out of `incoming` is assumed from the status values, not seen. Still missing: send text,
delete all received/sent, SIM failover / PIN unlock, firmware update notice, Wi-Fi password/channel, repeater password.

## SIM failover (2026-11-25, step 4c of docs/STOCK_COMPARISON.md)

SIM tab -> **SIM failover** (`v_failover`, last row under Data roaming; scroll). Copied from the stock web dialog (`ModemSim` in
`gl-sdk4-ui-internet`) and the stock screen's "SIM Failover" page: `modem.get_slot_failover_config {bus:"cpu"}` (job `failover`, 60 s,
raises on failure) and `modem.set_slot_failover_config`. Payload exactly as the stock dialog: off = `{bus, enable_switch:false}` only; on =
`{bus, enable_switch:true, slot_priority:[...], enable_timing, hour:"HH", min:"MM"}` (`lib.set_failover`, checked against stand-ins).
Screen: Enable, Priority 1 / 2 + Swap priority, Scheduled switch (to the preferred SIM) + Execution time (30-min steps via the picker).
`failover_interval` (300 s) is shown, not editable (stock doesn't either). Manual SIM switching is a different call
(`set_slot_failover_config {current_sim}`) and is unchanged. **Not tried on the device**: enabling failover could move the SIM
(live config: off, priority [2,1] = eSIM first, current SIM1). `failover_on` preview uses example values and sends nothing.
Still missing: SIM PIN unlock, firmware update notice, Wi-Fi password/channel/TX power/hidden SSID, repeater password, send text.

## Firmware update notice (2026-11-25, step 4d of docs/STOCK_COMPARISON.md)

Copied from the stock web UI (`gl-sdk4-ui-home`: `upgrade.check_firmware_online {}`; `hasUpgrade` = `version_new` present; the prompt shows
when `version_new` and `prompt`; "Ignore" = `upgrade.set_config {prompt:false}`) and the stock screen's "Upgrade Available / Go to Upgrade
/ Skip This Version". Answer seen when up to date: `{current_version, current_type, current_compile_time}`; the update shape
(`version_new`, `prompt`, `release_note`, `publishing_channel`) is from the web UI code, **not seen live**. `lib.get_firmware_update()`
(job `fw`, run at start then every 6 h; a failed check raises and keeps the last answer) -> `{current, new, prompt, note}`.
UI: More -> **Firmware** row ("Up to date" / "X available"), `v_firmware` (installed, available, release note cleaned by `App.fw_note`,
**Skip this version**, **Check again**), orange dot on the More tab when `new` and `prompt` (`App.fw_prompt`). **Installing is
deliberately not built** (the screen points to the admin panel or the stock screen). The check makes the router contact GL's server, same as
stock (the router also checks by itself: `upgrade.get_config.upgrade_enable`). Router state: 4.10.4 installed = latest in `/tmp/firmware_list`;
`uci upgrade.general.ignore_gray_version=4.10.4`. The `firmware_new` preview uses an invented 4.10.5.
Still missing: SIM PIN unlock, Wi-Fi password/channel/TX power/hidden SSID, repeater password, send text, firmware install.

## Wi-Fi password (2026-11-25, step 4e of docs/STOCK_COMPARISON.md)

Wi-Fi tab -> each band (Main and Guest) has a **Password** row under Name. Rules copied from the stock web page (`gl-sdk4-ui-wireless`
`key` validator): only on a secured network (open -> "None (open)", no field), 8-63 printable characters (64 hex digits is also valid on
stock but the on-screen keyboard stops at 63), and WPA3 (`sae`) can't exceed 63. Change = `wifi.set_config` with the whole stock form and
only `key` replaced (`set_wifi_key`, same shape as `rename_wifi`, via `wifi_rpc`, i.e. still the detached stand-in path with the hang
handling), one reload at a time (`wifi_lock`), confirm sheet on main bands (devices disconnect), none on guest (like rename). The
current password is shown only as dots; the keyboard opens pre-filled with it. Read via the `wsec` job (`wifi_security`, 120 s, raises on a
failed read). Form logic unit-tested with stand-ins; **a real change not tried on the device** (the Wi-Fi reload drops devices, possibly
the Mac). Wi-Fi writes are still the last item to move to the stock path (`gl_call`).
Still missing: SIM PIN unlock, Wi-Fi channel / TX power / hidden SSID, repeater password, send text, firmware install.

## Wi-Fi channel and hidden name (2026-11-25, step 4f of docs/STOCK_COMPARISON.md)

From the stock web page (`gl-sdk4-ui-wireless`): **Channel** = Auto (0) + the channels valid for the radio's bandwidth. 2.4 GHz lists all offered channels; 5 GHz
is grouped into bandwidth-sized blocks of `CHANNELS_5G` (80 MHz = blocks of 4 within the first 24 channels, 160 = blocks of 8 within the first 16, 40 = pairs;
`BLOCKS_5G`), keeping only whole blocks the router offers, DFS channels only if `dfs_support` (`channel_options`). The stock page **disables the
channel while the repeater uses that radio**; so do we ("Auto · locked": today the router uses wifi1 = 5 GHz, so only 2.4 GHz is editable). DFS (or 160 MHz)
adds a warning to the confirm sheet (stock shows `enable_dfs_tips`). The change is the same stock form as the Network mode change:
`set_wifi_radio(device, hwmode=None, channel=None)` (`set_wifi_mode` now calls it; it also now keeps a pinned channel from the saved uci value, not get_config's live
one). `radios` job -> `wifi_radios()` (band, modes, bandwidth, offered channels, saved channel from uci, `dfs_support`, `repeater`; raises on a failed read).
**Hide network name** = stock "SSID Visibility" as a switch (`set_wifi_hidden`: whole form with `hidden` flipped; `hidden` added to the `wsec` job), confirm on main
bands. Both rows are on every band, main and guest (channel is shared like the mode). Form logic and channel lists checked against the live radio data and
stand-ins; **real changes not tried on the device** (each reloads the radio and drops devices). Wi-Fi writes are still on `wifi_rpc` (detached stand-in).
Still missing: SIM PIN unlock, Wi-Fi TX power, repeater password, send text, firmware install.

## Repeater password (2026-11-25, step 4g of docs/STOCK_COMPARISON.md)

Stock: changing the password of the network in use is a re-join, `repeater.connect {ssid, remember:true, key, ...saved record}` (web UI `joinApFn`; the stock screen
uses the same keys: key, identity, remember, bssid, macaddr) and only the connected network can be edited ("Change Password" on the stock repeater page).
Wi-Fi tab -> Saved networks -> tap a network = `v_saved_net` (no longer straight to the forget sheet): Status, **Password** (only for the network in use; open networks
show "None (open)"; a network not in use says to connect first), **Forget this network**. Change = confirm, then `lib.repeater_set_key(rec, key)` (`gl_call repeater.connect`
with the saved record minus key, falling back to the direct `ubus call repeater connect` that Join uses), wait up to 45 s for the network to be connected; **if it
doesn't connect, reconnect with the old key** ("Wrong password. Old one restored.") so a typo can't strand the router. The saved record (with its key) is fetched
only inside the action (`lib.get_saved_ap`), the prefill uses `get_remembered_repeater_keys`. Flow and rollback unit-tested with stand-ins; **not tried against the real network**
(it re-joins the uplink the router uses now). `gl_call repeater.connect` with the saved record is unverified; the fallback covers a refusal.
Still missing: SIM PIN unlock, Wi-Fi TX power, send text, firmware install, repeater band auto-switch / 802.1X username.

## Wi-Fi TX power (2026-11-25, step 4h of docs/STOCK_COMPARISON.md)

Stock (`gl-sdk4-ui-wireless`): TX power is one of **Max / High / Medium / Low** (`txpowerList`), per radio, sent inside the same `wifi.set_config` radio form as mode and
channel (`txpower` key). The web UI also defines `wifi.set_txpower` but never calls it, so it is not used here. `set_wifi_radio(device, hwmode=None, channel=None, txpower=None)`
now takes `txpower` (anything not given keeps its current value; the completion check waits for `get_config` to report the new level). `wifi_radios()` carries `txpower`.
Each band (main and guest, shared radio) has a **TX power** row (`txpower_row`) with the four levels via the picker; confirm sheet (radio restarts; Medium/Low add a signal
warning). Unlike Channel it is not locked while the repeater uses the radio (the stock page doesn't lock it). Form logic checked with stand-ins (power change keeps mode and
channel; mode/channel changes keep the power); **real change not tried on the device**.
Still missing: SIM PIN unlock, send text, firmware install, repeater band auto-switch, SIM details.

## SIM PIN unlock (2026-11-25, step 4i of docs/STOCK_COMPARISON.md)

Copied from the stock web UI (`UnlockPinCode` / `ModemGuidePin` in `gl-sdk4-ui-internet`), the stock screen's "SIM n Unlock" texts, and the stock websocket module
(`/usr/share/gl-ngx/websocket/cellular.lua`, which copies `status` and `pin_counter` from `cellular.sim status`): call = `modem.set_sim_pin_code {bus, iccid, pin_code}` (PIN 4-8
digits; wrong PIN = error 20002022; the error also carries the new `pin_counter`). `cellular.sim status` per slot: **status 3 = asks for the PIN (pin_counter = attempts
left), 4 = locked out (PUK, which stock sends to a phone), 2/6/7/8 ready, 0/5 no SIM**. Both SIMs read 6 now, so `pin_counter` has never been seen on this router.
UI: SIM tab shows a **Locked ›** chip on a SIM in status 3/4 and opens `v_sim_unlock` (attempts left, **Enter PIN** via the keyboard in `pin` mode: digits only, shown as dots,
starts in number mode); a confirm sheet shows the attempts (extra warning on the last one); the home SIM card says "· locked". Status 4 shows only the PUK text, no input.
**Safety rules in `run_unlock`** (they exist because a wrong PIN can lock a SIM for good): re-read the state first and refuse unless status is 3 with an ICCID; exactly one
`set_sim_pin_code` per tap, never retried automatically; after a failure re-read `cellular.sim status` and report attempts left (or "locked"). Verified with a stand-in SIM
(ready / already PUK / no ICCID refuse without calling; wrong PIN x3 -> 2, 1, locked; correct PIN unlocks; one call each). **No PIN has ever been sent to a real SIM.**
Note: the PIN is an argument of `ubus call`, so it is visible in the process list for about a second (root only); it is never logged or stored. The `sim_locked`/`sim_unlock`/`sim_puk`
previews use invented lock states.
Still missing: send text, firmware install, repeater band auto-switch, SIM details.

## Send a text (2026-11-25, step 4j of docs/STOCK_COMPARISON.md)

**REMOVED later the same day** (Holden: it wasn't working); see "Sending texts removed". Kept below as a record of what stock does.

From the stock web Texts page (`gl-sdk4-ui-sms`): `modem.send_sms {slot, bus, phone_number, body, timeout: 0, sender?}` (`timeout: 0` = the router queues it and sends in the background;
`sender` = the sending SIM's own number when known; `type` is only passed for replies and left out here). Stock rules: number is digits (optionally a country code first; here a
leading + or plain digits, 3-15), body max 160 characters (70 for non-Latin text; this keyboard only types Latin, so 160), reply is offered on received texts. The send error
codes stock maps to messages are 20002001/03/38/39/41/42; their wording is not on the router, so the screen shows "Couldn't send (code N)". Sent-side statuses in `modem.get_sms_list`:
3/4 sending, 5 failed, others (2) sent, 0/1 received.
UI: Texts -> **New text** (`v_compose`: To, Message, From = the SIM in use, character count, **Send** behind a confirm sheet that names the number and SIM and says it may cost money),
**Reply** on a text whose sender is a real number (not a name like "DITO"). Airplane mode blocks it. `run_send` snapshots matching sent-side messages first, queues the text, then
polls up to 45 s for a *new* message: sent -> "Text sent", failed -> raises (compose keeps the text to retry), still sending -> "Text queued". Keyboard targets: `smsto` (digits,
optional leading +) and `sms` (counter). Flow verified with a stand-in router (accepted/refused with and without code, failed, still sending, an old identical failed text ignored, one send each).
**No text has ever been sent from this code to a real number.** Unverified: that status 2 means "sent", and what `type`/`sender` the router insists on. Sent texts are not listed in the
Texts screen (it only reads received ones).
Still missing: SIM details, repeater band auto-switch, firmware install, listing sent texts.

## Sent texts list (2026-11-25, step 4k of docs/STOCK_COMPARISON.md)

Stock web Texts page: one `modem.get_sms_list {bus}`; messages with status 0/1 are received, **everything else is the Sent list** (3/4 sending with a spinner, 5 failed with a warning
icon and **Resend**, otherwise sent). Resend = `remove_sms {bus, name, scope:10}` then send again. `lib.get_sent_sms()` (job `smssent`, 30 s; a failed read raises) builds the list from that
same call (`phone_number` = recipient, `date` = `yy-mm-dd HH:MM:SS`, newest first, bad dates tolerated, nameless entries skipped). The router keeps them in `/etc/spool/sms/{outgoing,sent,failed}`
(all empty now) but the stock call is used instead of guessing those file formats. UI: Texts -> **Sent texts** row (count) -> `v_sent` (To number, state + start of message, date, orange dot on failed)
-> `v_sent_text` (full text, **Edit and resend** for a failed one / **Send again** for others, **Delete this text** via `delete_sms`). Resend opens the compose screen prefilled and, unlike stock
(which deletes first), removes the old failed text only AFTER the new one is accepted (`run_send(..., replace=name)`), so a failed resend never loses it. `run_send` also refreshes `smssent`.
Parsing, ordering, tolerance and the resend/replace rules verified with stand-ins and example data; **no real sent text exists yet, so the live list has only been seen empty**.
Still missing: SIM details, repeater band auto-switch, firmware install.

## SIM details (2026-11-25, step 4l of docs/STOCK_COMPARISON.md)

Stock "SIM n Details & Configs" (labels from the stock screen): SIM (phone number, ICCID, network operator), network (network type, data roaming, APN, IP, gateway, primary/secondary DNS,
max bit rate), cellular (mode, band, ARFCN, cell ID, TAC, PCI, RSRP, RSSI, RSRQ, SINR), plus Modem Information and eSIM Information pages. Read-only here: `lib.get_sim_details()` (job
`siminfo`, 60 s, requested when the screen opens; raises if `cellular.modem status` is empty) reads `cellular.sim info/status`, `cellular.network info` (per slot: `network_mode` = the
configured type AUTO, apn, ipv4 ip/gateway/dns[]) and `cell_info` (the `signal` list: primary carrier = lowest `ca` with band != 0; `tac`, `cell_id`), `cellular.modem info` (vendor, name,
version, `imei[]` per slot) and `get_roaming_config`; placeholders (-32768, band 0) come out blank. UI: SIM tab -> tap the SIM in use -> **Details & info** (top of `v_sim_detail`) ->
`v_sim_info`, grouped SIM / Network / Cellular / Modem. Long values step down in font (ICCID), very long ones wrap as notes (modem firmware, 45 chars). **Left out:** the stock max bit rate (AMBR:
`ambr_dl/ul` read 2008/1008/508 with no known unit), writes (network type, custom APN, band masking, data used reset/limit), and the **eSIM Information** page (EID, profile list; needs eSIM
calls not found). Verified live: every field comes back filled (checked by presence only, values not printed: they include the ICCID, IMEI, phone number and IP); previews use invented values.
Still missing: eSIM information, repeater band auto-switch, firmware install.

## Wi-Fi band / repeater band auto-switch (2026-11-25, step 4m of docs/STOCK_COMPARISON.md)

Stock labels: "Band Auto-Switch", "5G/Mixed", "6G/Mixed", reminder "Wi-Fi is set to X only. Repeating a X network will switch it to Auto Band automatically", and "5GHz preferred. If repeating Wi-Fi, band will follow repeater".
Mechanism (stock web `gl-sdk4-ui-wireless`, same keys in the stock screen's strings): `wifi.get_config` `bandmode {band_mutex:"5G+6G", useband, usemode}`; the choice (`usemode` = 5g / 6g / auto) is sent inside the
normal radio `set_config` form of the chosen band's radio (`useModeChange`). Router state: `wireless.autoparam.usemode=5g, useband=5g`; radios wifi0 2g, wifi1 5g, wifi2 6g (ready) but **get_config lists only wifi0/wifi1**
because `wifi.get_environment_config` is `use_environment: 0` = **Outdoor** (stock: 1 = Indoor, 0 = Outdoor; 6 GHz unavailable outdoors), and the repeater uses 5 GHz. Rules copied from stock's `modeList` (`band_options`): a band is offered only if its radio is in
get_config, not 6 GHz when use_environment is 0, and while the repeater uses one of the shared bands no other fixed band; Auto always. Today that leaves **5 GHz and Auto**.
`wifi_bandmode()` (job `wband`, 120 s, raises on a failed read; {} if no shared band) reads it; `set_wifi_radio(device, ..., usemode=)` sends the form with `usemode` (device = the chosen band's radio, or the
`useband` radio for Auto; completion = `uci wireless.autoparam.usemode` matches). UI: Wi-Fi tab, Main -> **5 / 6 GHz band** (picker, confirm sheet in stock's wording; a note says 6 GHz is off because of Outdoor). The usage environment
itself (indoor/outdoor, a regulatory choice) is only shown, not changeable here. Rules and the form verified against the real band config and stand-ins; **no real band change tried** (the radio restarts). Still missing: eSIM information, firmware install.

## eSIM information (2026-11-25, step 4n of docs/STOCK_COMPARISON.md)

Stock "eSIM Information" (web `esim-management` in `gl-sdk4-ui-internet`, stock screen tasks `get esim info` / `task_get_esim_status`): EID, ICCID, IMSI, eSIM OS version, storage (remain / 360 KB), profile
count and list. Sources: `modem.get_profile_info {bus}` -> `eid, iccid, imsi, profile_list[{iccid, sp_name (supplier), nk_name (nickname), state 1 = enabled}], seed_profile_list[]`;
`modem.get_cos_version {eid}` -> `cos`; storage = POST `{txId, method:"info2", env:1}` to the local eSIM helper `lpa_rg650` on 127.0.0.1:3456 (`/etc/nginx/gl-conf.d/esim.conf` proxies the web UI's `/sdk/v1` there)
-> `data.extCardResource` (JSON text) `.non_volatile_mem` bytes -> `ceil(/1024)` KB free. `lib.get_esim_info()` (raises `EsimUnavailable` with a readable reason; `20002057` = "Curl request failed" = the helper didn't
answer) is called only when the screen opens (`App.open_esim` / `load_esim`, background thread, spinner, Try again), **never polled** (each failed call blocks ~15 s). UI: SIM tab -> **eSIM information**
(last row), `v_esim`; needs slot 2 set to eSIM, else it says to switch. Read-only: the stock page also enables/disables/renames/deletes profiles and *sets the eSIM slot when opened*; none of that is copied.
**Verified:** parsing and every error path with stand-ins and invented data (previews). **Live today the helper answers `401 get EID fail: cpin is not READY`** (via the modem call it surfaces as 20002057 after
15 s), although both SIMs report status 6 and the eSIM (slot 2) is the active line, so a real successful read has not been seen. The log also shows something else (not this screen: probably an admin page) asking
`get_profile_info` every 15 s. Note: the router's active slot changed to 2 (eSIM) during this session without any action from this code.
Still missing: firmware install (deliberately), profile management.

## Installable package (2026-11-25)

`packages/build.sh [version]` builds `packages/dist/gl-e5800-touch-ui_<version>_all.ipk` (dist/ is gitignored) from `router/`; scripts in `packages/control/`; `packages/README.md` documents install,
the scripts and the format gotchas (gzip tar of `debian-binary`, `data.tar.gz`, `control.tar.gz`; no opkg calls in scripts; Pillow only checked for because it needs `--nodeps`; files only, no `/etc` `/root` dirs).
Depends: python3, libtiff6, qrencode, 5 zoneinfo packages; Conflicts: gl-e5800-dashboard. Install does not swap the screen (restarts it if already showing); prerm hands the screen back to stock; an upgrade restores
the custom screen if it was active within 5 minutes; config.json and cache/ are kept on removal. **Verified:** built and inspected; `opkg install --noaction` on the router exits 0 and changes nothing; a truncated copy is rejected
(exit 255); `sh -n` passes for the 3 scripts on the router. **Real install done** later the same day on the router, over the working manual install: exit 0, postinst ran, the package owns the 8 files (byte-identical to the manual copy), screen stayed active, config.json and cache/ untouched, no errors. **Never done:** remove (prerm/postrm), upgrade over an installed copy, a fresh router with no manual install, and no check that the package survives a firmware update (it does not:
`upgrade.general.keep_package=0`, reinstall the file). The version stays 1.0.0 until it changes; rebuild after every change to `router/`.
**Upgrade 1.0.0 -> 1.0.1 done on the router (2026-11-25 19:3x, Holden's OK):** `opkg install --noaction --nodeps` first (clean), then the real install: exit 0; prerm handed the screen to
stock ("dashboard OFF", plus a harmless "ubus service delete homebutton: Not found" line), postinst turned the custom screen back on straight away ("Custom screen restored"), no stock
screen left running. Afterwards: opkg says 1.0.1 `install user installed`, the 8 files are byte-identical to `router/`, `config.json` unchanged (same md5), 4 cache files kept,
e5ui + homebutton running and enabled, no marker file, no errors in the log. So the upgrade path and the 5-minute restore are verified; `opkg remove` and a fresh-router install still are not.

## Sending texts removed (2026-11-25)

Holden: "lets just remove the messaging cause its not working", then clarified: only the **sending** ("the sending of text message").
Removed: New text, Reply, Send again / Edit and resend, the compose page, `run_send`, the `sms`/`smsto` keyboard targets, and
`lib.send_sms` / `lib.sent_sms_matches`. Kept: the received list, reading, mark-read, delete (one / all read), the Sent texts list
(read and delete only), unread dots, Home/More tiles, lock-screen chip. (I first removed all of Texts by mistake; restored from a
backup and re-trimmed.) Older sections of this file describing send (stock-comparison steps 4j, and the resend part of 4k) are history.
Deployed and the UI restarted; not committed. The package 1.0.1 was installed on the router later the same evening (see "Installable package"), so the opkg version now matches the files. The `tiles` row now sizes itself to 1 or 2 tiles (unused for now).

## Main currency (2026-11-25)

Holden: "update the currency conversion so user can change main currency". New `home_fx` setting (default PHP) with a picker (Currency -> My currency,
`v_fx_home`, about 30 currencies in `FX_NAMES`). "Compare with" is a picker too (`v_fx_cmp`, same list, the main currency left out; it replaced the 5-button row after Holden asked
why only 5). The page and the More tile follow it. Rates per 100/1,000 are chosen from the size of the rate, not just for yen. Own feature, so there is no stock equivalent.
Deployed, UI restarted, not committed. Docs also corrected: the rate source is open.er-api.com, not Frankfurter/ECB.

## Network type and band masking (2026-11-25)

Holden: "can we do band locking on mobile data? does the stock firmware not have it?" The stock **touchscreen** has no band lock (only a "network mode
changed" notice); the stock **web UI** has it (`gl-sdk4-ui-cellular-detail`, BandLockControls): `modem.get_band_config {bus, slot}` ->
`{band_enable, network_mode, band_list, supports_band, band_filter_mode}` and `modem.set_band_config {bus, slot, band_enable, network_mode, band_list?}`
(band_list only when masking is on; 5G lists empty in 4G mode). Supported bands come from `cellular.modem info` -> `band {LTE, NR-NSA, NR-SA}` (this modem,
RG650V-EU: LTE 1,3,5,7,8,20,28,32,38,40,41,42,43; NR 1,3,5,7,8,20,26,28,38,40,41,75-78). Network types: AUTO / NR5G / LTE. The checked bands are the
*allowed* ones. The i18n file also has "Block" mode strings and the call returns `band_filter_mode: 0`, but no shipped UI uses them, so they are ignored.
Built: SIM -> SIM detail -> "Network & bands" (`v_bands`, `lib.get_band_state` / `set_band_config` / `band_warnings` = the stock `bandsWarning`; new
row kind `bands`). Edits a copy, Apply asks first. Stock extras left out: Lock operator and Lock tower.
**Verified:** reads on the live router (slot 2, masking off, Auto), warning logic, preview renders, deployed. **Write tested with Holden's OK (2026-11-25 19:11):**
masking on + Auto + every band ticked through `lib.set_band_config` -> accepted, read back as enabled with 15 / 15 / 13 bands; then masking off + Auto ->
accepted, read back as disabled. Internet was up right after the first write and down for a few seconds after the revert (the modem reconnecting), up again at
the next check. After masking is switched off the router still returns the last band list (15 / 15 / 13), so a disabled state can carry a full list: harmless
(the screen ignores the list while masking is off). **Partial mask tested too (19:20, Holden's OK):** masking on + Auto with LTE B32/B42/B43 and n75/n76 (SA and NSA) unticked, the serving band (B28) kept ->
accepted, read back exactly as requested (13 / 13 / 10), internet stayed up, still on B28; reverted to masking off, internet up. After the revert the router
kept that last list (13 / 13 / 10), so the next "masking on" starts from it, like the stock UI. **4G only tested (19:22, Holden's OK):** network type 4G, masking off -> accepted, read back as LTE; internet was
down for about 25 s while the modem re-attached, then up on B8 (10 MHz) as plain 4G LTE; reverted to Auto -> read back AUTO, 4G+ on B28 + B3, internet up. So a
network type change interrupts data for longer than a band change (the Apply confirm already warns). **5G only tested (19:24, Holden's OK):** network type 5G, masking off -> accepted, read back as NR5G, `net_type` "Nr5G", internet pings stayed up for the
45 s hold. **But** the radio / band readout (`get_sim_details`: `radio`, `band`) was blank in 5G-only mode, so I could not confirm from the screen's own data that
a 5G cell was attached (the signal parser may not read an NR-only `cell_info`; unchecked: re-run 5G only and dump `cellular.network cell_info`). Reverted to
Auto -> AUTO again, internet down for ~30 s while re-attaching, up by 45 s, on 4G B8. **Mask without the serving band tested (19:26, Holden's OK):** serving band B8 unticked, everything else ticked (LTE 12, NR 15 / 15) -> accepted and read back as
requested; the modem moved off B8 within 15 s (5G NSA B28 + n41, then 4G B3), internet stayed up throughout; reverted to masking off -> back on B28, internet up.
So a mask that drops only the serving band is safe: the modem re-attaches on another allowed band. **Still not tested:** a mask that leaves NO usable band at all
(the screen blocks this with the red "pick one" flags); don't try it. Side effect: the router keeps the last list while masking is off, so it now holds LTE
without B8 (12 bands); switching masking on next starts from that list (stock behaves the same).
Reset the same evening (19:29, Holden's OK): masking on with every band, then off -> the stored list is all bands again (15 / 15 / 13), masking off, Auto; internet
was up after the first write, down for a few seconds after the second, up at the next check. (The only way to change the stored list is to switch masking on with it.) The test ran as a detached script on the router so the revert would happen even if the connection dropped. Not committed.

## Accent color (2026-11-25)

Holden: "last one can we add a color accent option? 5 preselected colors and 1 custom". Own feature (no stock equivalent). More -> Display -> Accent color
(`v_accent`): Teal (the original, exact old shades), Blue, Purple, Pink, Lime, and "Your color" (`v_accent_custom`: tap a hue bar and a strength bar, or type a hex code
through the keyboard target `hex`). Settings `accent` / `accent_custom` in config.json. `apply_accent()` reassigns the accent globals (they are read at draw time; the text
cache stores glyph masks only, so it needs no flush); `ON_ACCENT` (text on filled buttons) flips between dark and white by luminance; dark custom colors are lightened
(`accent_fix`). WARN orange and the danger red are not themed. New row kind `swatch`. Checked with preview renders (Teal, Blue, Pink, a custom orange) and deployed;
not tapped on the physical screen. Not committed. Package 1.0.2 (with this feature) was built and installed on the router the same evening (upgrade from 1.0.1: dry run clean, exit 0, custom screen restored by postinst, files identical to `router/`, `config.json` unchanged, services running).

## Signature moved on Home (2026-11-27)

Holden sent a photo of the Home screen: with two clocks on, the signature (third line under the big time, y=88) was clipped by the SIM card (top at y=100). Moved it to the
empty strip above the tab bar (centered at y=260, teal, up to the screen width minus 30 px; `v_home`), which also gives the date and second clock more room. The lock screen
and the Status wake view are unchanged. Checked with a preview render (two clocks + a 23-character signature) and deployed to the router; not tapped on the screen. The router
now runs a newer `app.py` than package 1.0.2 and than the published release / commit (not committed, not repackaged: Holden hasn't asked).

## Tailscale switch (2026-11-27)

Holden: "can we add tailscale off/on" (then "check the firmware?": do what stock does). Stock: the VPN dashboard / `gl-sdk4-ui-tailscaleview`, module `tailscale` through
`gl_call`: `get_config {}` -> `{enabled, wan_enabled, lan_enabled, exit_node_ip, run_exit_node, masq, lan_ip}`; `get_status {}` (only meaningful while enabled) -> `{status: 1 not bound / needs
login, 2 needs mandate, 3 connected, 4 connecting, login_name, address_v4, dns}`; `set_config`: off = `{enabled: false}`, on = `{enabled: true, exit_node_ip, run_exit_node, wan_enabled,
lan_enabled, masq}` with the saved values (the stock UI waits 5 s then re-reads); also `get_auth_url`, `logout`, `get_exit_node_list` (not used here). The stock touchscreen has no
Tailscale page. Built: a third card on the VPN tab (`v_vpn`, `tailscale_switch`, `lib.get_tailscale` / `set_tailscale_enabled`, job `ts`); the big circle was made slightly smaller
and the cards tightened to fit above the tab bar (content is drawn 8 px lower than the y values in `v_*`, so ~268 is the usable bottom). The account name is not kept or shown. When connected, the state is a chip beside the name and the address has the whole second line (a full address like 100.101.202.233 was cut by the switch on one line).
Router state when built: Tailscale installed (1.92.5) but disabled, `tailscaled` not running, never signed in (get_status returned only dns). **Verified:** the reads on the live router,
preview renders (off / connected / not signed in with example data), deployed. **Never run on the router: the switch itself (`set_config`).** Switching it on with no account only
makes the service start and ask for sign-in; ask Holden before testing. Signing in (`get_auth_url`) is left to the admin panel. Not committed; the router runs a newer `app.py` /
`lib.py` than package 1.0.2 and the GitHub release.

## Home as a status board, step 1 of the critique plan (2026-11-27)

`/impeccable critique` of the whole UI scored 27/40 (snapshot in `.impeccable/critique/`, untracked). Its top issue: Home led with the SIM data allowance ("data off") and never said what the
router was connected through. Holden chose: Home = a glanceable status board, uplink first, fix everything in the plan (steps: 1 Home uplink card, 2 one VPN status covering WireGuard
and Tailscale, 3 legibility on the glass, 4 dead ends/QR/waits, 5 More + bands restructure, 6 polish). **Step 1 done and deployed:** `v_home`'s first card is now the uplink: title =
Wi-Fi name (repeater) / carrier name (mobile) / Ethernet / Offline (amber); chip = `Wi-Fi · Strong|Fair|Weak` (dBm > -60 / > -72, the same cut-offs as the Wi-Fi tab), `4G · Strong|Fair|Weak`
(modem bars 3-4 / 2 / 0-1) or `Wired`; second line = the SIM (`data off`, or `used of cap`); the usage bar shows only with data on and a cap. The "Repeater" chip is gone. The card opens
the Wi-Fi tab / SIM tab / Internet settings by uplink. The four tiles share one label-over-value structure and a 9 px inset (this also fixed the Texts label that sat at x=141): Devices,
Speed ("SPEED  Mbps"), VPN (Off in grey, or the country in the accent color), Texts (`All read` / `N new` amber). The tile rows are 160-204 and 208-244. Preview states added to the
`--preview` run (`home_up_*`; they patch `lib.get_wan_conn_type` / `get_cell_signal` and `app.data_on`, then restore them). **Not yet judged on the glass** (that is step 3); the Home VPN
tile still reads only the WireGuard tunnel (step 2 fixes that). Not committed; the router runs a newer `app.py` than package 1.0.2 and the GitHub release.

## One truthful VPN status, step 2 of the critique plan (2026-11-27)

Critique issue: the Home tile, lock row, status-bar shield and quick-panel tile read only the WireGuard tunnel (`wga`), so with Tailscale up they said "VPN off" while the VPN tab's Tailscale
card said "Connected". Fix (deployed): new `App.ts_connected()` (Tailscale status 3 from the `ts` job) and `App.vpn_text(wga)`. Status-bar shield = WireGuard or Tailscale connected. Home VPN tile
= WireGuard state (Off / country, accent when on) plus a teal "Tailscale" chip beside the label when it is connected. Lock row = `Off` / the server / `Tailscale on` / `Philippines + Tailscale`; the
lock rows' value width now comes from each row's own label (the VPN row had been clipping "...+ Tailsc…"). VPN tab caption names the service: "WireGuard is on. All devices go through X." / "WireGuard is off.
Devices use your normal connection." / "Choose a WireGuard location to set up the tunnel." Quick-panel tile stays "VPN" (it toggles the WireGuard tunnel, as before) with the state line "WireGuard" when on
(the label "WireGuard" did not fit the tile). Tailscale that is on but not yet connected (sign in / approve / connecting) is shown only on the VPN tab card, not on Home or lock: the shield and chips mean
connected. The preview run renders all four combinations on the lock, Home, VPN and panel (`vpnst_*`, example states). Not committed; not packaged.

## Legibility on the glass, step 3 of the critique plan (2026-11-27)

From the critique and Holden's photo of the real screen: the date, city and weather sat on the bright planet edge, and the smallest text was 11-12 px (`F(8)` / `F(9)` after `FONT_BUMP`). Changes (deployed): **`MIN_PX = 13`** in `F()`: nothing is drawn smaller
(53 text draws were affected); **chips 15 -> 17 px tall** (`chip()`); **note rows** use a 16 px line height (`row_h` + `draw_row`); **wallpaper scrim**: `wallpaper(choice, dim, scrim)` adds an eased black gradient over the top 130 px (0.75 on
Home and on the lock screen; cache key includes it). Knock-on fixes found by rendering all 109 preview screens before/after (side-by-side sheets): quick-panel tiles widened to 72 px (gap 4, margins 8) so "Shut down" and the Wi-Fi name fit;
currency card taller (spacing under the big number); Wi-Fi tab header card 58-116 with the Main/Guest switch and rows moved down 8 px; Ethernet segment "WAN · internet in" shortened to "WAN · internet"; the Home VPN tile no longer has a Tailscale chip
(it could not fit beside the label at 13 px): its value is `Off` / the country / `Tailscale` / `2 connected`. **Verified in previews only; not yet judged on the real glass** (the scrim strength and the 13 px floor should be checked on a new photo). Not
committed; not packaged.

## Dead ends and waits, step 4 of the critique plan (2026-11-27)

Critique issue: "use the admin panel" notices were dead ends on a 240x320 screen, and the Switching screen was a silent spinner. Done (deployed): **admin-panel QR** (`v_admin_qr`: `http://<lan ip>`, reached from About device > Admin panel, the firmware page
"Open admin panel" row when an update exists, and the Tailscale error page); **Tailscale sign-in** (`lib.get_tailscale_auth_url` = the stock `tailscale.get_auth_url {}` -> `{auth_url}`; `v_ts_login` shows it as a QR; when status is 1 the Tailscale card text is "Tap to sign in (QR code)" and
the left part of the card opens the page while the switch stays a switch; the link is never logged); **busy overlay** (`v_busy`): job name, `N s so far`, an estimate only where measured/stated (`BUSY_HINTS`: SIM switch "Up to a minute", Applying "Usually 10-45 s" from the band tests,
Tailscale "About 5 s"), and **Hide** (`busy_hidden`, small pill above the tab bar; `work()` now runs one job at a time and says "Still working" otherwise; `power()` jobs can't be hidden); `draw_qr` factored out of Share Wi-Fi and now keeps a 4-module quiet zone when modules stay >= 3 px
(was ~2.4 modules; the long Wi-Fi codes keep the old tight fit). **Verified:** preview renders of every new state, and the drawn admin and sign-in QR modules read back from the PNG match the encoder output exactly (0 wrong modules; quiet zone 5.8 / 8 modules). **Not verified:** a phone scanning the
real glass (modules are 4 px / 3 px), and `get_auth_url` on the live router (Tailscale is off and not signed in: turning it on, then tapping the card, would test it; ask Holden first). Not committed; not packaged.

## More regrouped and the band chips moved down, step 5 of the critique plan (2026-11-27)

Critique issue: More was one run of 15 rows (+4 tiles), the SIM tab opened a page called "Mobile", and the bands page showed 13+15+15 chips at once. Done (deployed): **More** now has four labeled groups, none over four rows: Tools (the Texts/Weather/Monitor/Currency tiles),
Connections (Clients, Internet, Network, AdGuard Home), Device (Display, Security, Power & USB, Dashboard), Router (Firmware, GL.iNet Account, About device); Airplane mode on top, Screen off / Reboot / Shut down at the end; the Monitor tile subtitle is now "Speed test" (it was cut off). **SIM page title**
"Mobile" -> "SIM & data" (matches its tab). **Network & bands**: the main page keeps Network type, Band masking and Apply; with masking on, an "Allowed bands" row ("9 of 43" / "Pick at least one") opens `v_bands_pick` with the chips (same `bands` row kind, same edit copy via `bands_ctx()`; Apply stays on the main page).
Not built, on purpose: "Auto / 5G only / Custom" presets: the critique conflated network type (Auto / 5G / 4G, already the first control) with band masking (all bands vs a chosen set); the Allowed bands page is the "Custom" part. Checked with preview renders (More at four scroll positions, the three band pages); not tapped on the glass. Not committed; not packaged.

## Incident: Wi-Fi reload pile-up (fixed; fix needs a live test)

**Symptom:** turning on guest Wi-Fi never took effect, renaming only did one band, the Share guest QR was
empty, and the router's load average reached about 7.5.

**Cause:** GL's `wifi.set_config` runs `/sbin/wifi multi_up <radio>` synchronously. On this firmware that
can take several minutes. The old code called it through `lib.gl_lua_rpc` with a 90 s timeout, which killed
the Lua process midway. That left orphaned `wifi multi_up` shells running, and later changes stacked more
on top. They were slow, not permanently hung: two finished on their own after about 6 and 12 minutes.

**Fix (deployed):**
- `wifi_rpc()` starts the Lua RPC **detached and never kills it**.
- Before starting, it waits for any `/sbin/wifi` reload younger than 5 minutes to finish (`wifi_reloading()`).
  Older ones are treated as hung and ignored.
- It reports done only when uci shows the requested state (`set_wifi_enabled`, `rename_wifi`).
- Holden rebooted the router afterwards, which cleared the leftovers.

**Not yet verified on the device.** Next time Holden toggles guest Wi-Fi or renames it, check that it
completes:

```sh
ssh root@10.10.1.1 'pgrep -f "sh /sbin/wifi" | wc -l; cat /proc/loadavg; uci show wireless | grep -E "guest(2g|5g)\.(disabled|ssid)"'
```

A single reload taking a minute or more is the firmware's normal speed; there is no faster stock path.

**Permissions:** killing the stuck reload processes was blocked by the auto-mode safety check as
destructive. Ask Holden before ending processes on the router, or suggest a reboot (More → Reboot).

## Critique step 6: polish (2026-11-27)

- **One selection mark.** New row kind `pick` (`("pick", label, selected, fn[, detail])`): a ✓ on the chosen item and nothing on the others. Before, picker lists
  showed a "✓" in the value slot *and* a chevron on every row (so the chosen row read "✓ ›"), the accent list swapped ✓/chevron, and clock times were prefixed with "✓ ".
  Converted: data cap, VPN location, both currency pickers, second clock, and the generic option lists (Wi-Fi idle timeout etc.). The accent swatch rows show ✓ or nothing; only
  "Your color" keeps a chevron because it opens an editor. The city list's ✓ (own layout) was already the same glyph.
- **Accent can't mimic a warning.** `WARN_HUE = (0.04, 0.16)` (about 15-58 degrees): `accent_fix` moves any strong color in that band to its nearer edge (orange becomes red-orange,
  amber becomes yellow). Checked: #FF8C42 -> #FF6F42, #FFA524 -> #FF5924, #F5C26B -> #F5EF6B; teal, blue, purple, pink, lime and greys are untouched. `set_accent` now stores the
  adjusted color so the hex shown in the list matches the screen. The red danger color is not reserved.
- Deployed (UI service restarted, no errors, `config.json` unchanged). Checked with preview renders only, not on the glass.

### SIM page note clipped (2026-11-27)

The line under the three SIM cards ("Mobile data is off. Tap a SIM to use it.") was cut off: since the 13 px text floor it is taller than the 13 px gap it was given, and
the rows below were drawn over it. Note moved 2 px down, the rows below start 7 px lower, and both versions of the text are shorter ("Data is off. Tap a SIM to use it." /
"SIM2 and eSIM share one slot.") so they fit on one line. Preview-checked and deployed. Other one-off `self.t(..., F(9), ...)` lines placed by hand were not audited.

### SIM page scrolls as one list (2026-11-27)

Holden: "I can barely scroll Data roaming, SIM failover, eSIM info." The Mobile data switch, the three SIM cards and the note were fixed on screen, and only the last three rows
scrolled in the ~40 px left over. Now `v_sim` builds one `rows()` list (scroll key `sim_rows`): switch, three cards, note, Data roaming, SIM failover, eSIM information. The card
drawing moved to `sim_card()` and is used through a new row kind `("simcard", draw(y) -> tap action)` (height 41), so it draws on the scrolling layer. The note is now an ordinary
`note` row. Preview shots `sim_mid` / `sim_end` added. Deployed; checked in renders only.

### Scroll-area audit of every page (2026-11-27)

After the SIM page, every screen was checked: a temporary print in `rows()` during `--preview` logged each scroll area's visible height and content height (not kept in the code).
Result: only **Wi-Fi** was starved (116 px visible for 786 px of rows; the "Internet from Wi-Fi" card and the Main/Guest switch were fixed above it). Fixed: only the Main/Guest
switch stays pinned (rows start at 90, about 186 px visible); the uplink card is now the first row of the Main list (row kind `("upcard", draw(y) -> tap action)`, 62 px,
`wifi_uplink_card()`), so it scrolls away and the Guest tab no longer shows it. Everything else is fine: share, accent colour, currency, weather fit without scrolling; Sim detail
has 226 px; More, Display etc. start at 56. Fixed single screens (Home, VPN, Monitor, Weather city, QR pages, keyboards, lock) are drawn by hand and were looked at in renders.
Deployed; renders only.

### Package 1.0.3 built and installed (2026-11-27)

`packages/dist/gl-e5800-touch-ui_1.0.3_all.ipk` (built with `./build.sh 1.0.3`, git-ignored; app.py/lib.py inside are identical to `router/`). Dry run, then `opkg install`: exit 0, 1.0.2 -> 1.0.3,
custom screen restored by postinst, `config.json` checksum unchanged, no render errors. The router's opkg version now matches its code. **Not committed, not pushed, and the GitHub release is still v1.0.2**
(its code and docs are older than the router's).

## Not tested on the live router (by design: they disrupt service)

Each of these was built from the stock web UI's exact call and checked with preview renders, but never run
on the router. Ask Holden before testing any of them yourself.

| Feature | Risk |
|---|---|
| A band mask that leaves no usable band (`modem.set_band_config`; the screen refuses it). Masking on with all bands, a partial mask, a mask dropping only the serving band, and network type 4G only and 5G only were tested | Reconnects mobile data; a bad band mask can leave no signal (undo: masking off, Auto) |
| SIM1 / SIM2 / eSIM switching (`switch_sim`, `set_slot_type`) | Drops mobile data for up to a minute; the eSIM switch changes slot 2's mode |
| Turning data on from a SIM card (`ask_data_with`) | Same as above |
| Client blocking (`set_blocked`) | **MacBookPro is Holden's computer.** Blocking it cuts SSH |
| Power & USB writes (`lpm` / `otg set_config`) | Standby, timeouts, USB power direction |
| Ethernet WAN/LAN (`set_eth_mode`) | Drops anything plugged in |
| Guest on/off and rename after the `wifi_rpc` fix | Slow Wi-Fi reload |
| Main Wi-Fi rename / Network mode (`name_row`, `set_wifi_mode`) | Drops devices on that band, including this Mac's SSH, for a minute or more |

Holden **has** used AdGuard (it worked) and the guest rename before the fix (it got 2.4 GHz only).

## Decided against: charge limit (2026-11-25)

Holden asked for "stop charging at 90%". GL has no such setting. The charger (SGM41542S) exposes a writable
`/sys/class/power_supply/charger/constant_charge_voltage` (reads 0) and `input_current_limit`, but the router's
power MCU manages charging and these aren't supported settings. **Holden decided not to do it** ("not native
hardware settings"). Nothing was written. Don't revisit unless he asks.

## Open items and ideas

1. **Measure boot time** after the S13 change. Holden needs to reboot first; then compare the app's start
   time with uptime:
   `ssh root@10.10.1.1 'p=$(pgrep -f "python3 /root/e5ui/app.py"); echo $(( $(awk "{print \$22}" /proc/$p/stat)/100 ))s'`
   It was 66 s at S95.
2. ~~Bring `docs/` up to date~~ (done: docs were updated with every feature on 2026-11-25).
3. **Make the guest SSIDs match** if Holden wants: set 5 GHz to "Guest-A" (More → Network → Name) once the
   new Wi-Fi path is confirmed working.
4. **Keyboard:** if it's still fiddly, add a key preview (the letter pops up above the finger).
5. **eSIM carrier name:** `modem.get_profile_info` returns "Curl request failed", so the eSIM shows a
   generic label.
6. **AdGuard stats:** the stats API needs a web login, so they aren't shown.
7. **Prototype:** it doesn't have the latest changes (lock card, SIM layout, Power & USB, and so on).
   Only update it if Holden asks.

## Working notes

- **Workflow:** edit `router/app.py` → `python3 -m py_compile` → `scp -O` to `/root/e5ui/` →
  `/etc/init.d/e5ui restart`.
- **Checking screens:** use `app.py --preview DIR`, or for one screen, build `App(preview=True)` in a
  `python3 -c` on the router, `r.put()` live data, and `render().save()`. Preview renders show "No signal"
  unless you load the `sim`/`cell` jobs.
- **Checking the live screen:** read back `/dev/fb0` (see DEVELOPER.md, "Capture what's on the physical
  screen").
- **New router features:** find the call in `/www/views/*.js.gz` and send the same payload. Don't invent
  uci writes.
- **Holden's preferences:**
  - Manila time, PHP currency, 12-hour clock, Philippines context.
  - Don't commit or push unless asked; never add a Claude co-author line.
  - Ask before changing live router settings; read-only probing is fine.
- **Temporary files:** `/private/tmp/claude-501/...` (scratchpad) holds extracted web UI JavaScript
  (`tools/*.js`) and render PNGs from the session. It's disposable; everything needed is in this folder.
- **Memory note:** `project_e5800_screen.md` in Claude's memory points here.
