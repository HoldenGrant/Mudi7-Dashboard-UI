# E5800 screen: user guide

How to use the touchscreen on the GL.iNet GL-E5800 (router `10.10.1.1`) with the custom UI.

## Getting around

- **Tab bar** (bottom): **Home**, **SIM**, **Wi-Fi**, **VPN**, **More**. An orange dot on More means
  you have unread texts or a newer firmware is available.
- **Back arrow** (top left): on a tab screen it goes to Home; on any other screen it goes back one step.
- **Lists that run off the screen** scroll: drag up or down. A thin bar on the right shows your position.
- **Changes that can cut a connection** (switching SIM, turning something off, blocking a device,
  rebooting) ask you to confirm first.
- **Slow changes** show a spinner. Wi-Fi changes run in the background instead: the switch turns into a
  small spinning circle and a short message pops up when the router has finished.

## Quick panel

Drag down from the very top (the status bar) to pull down the quick panel; the screen dims behind it.

- **Tiles:** *Data* (mobile data on or off), *Wi-Fi* (turns the router's own Wi-Fi on or off: both bands, asks
  first when turning off, and remembers which bands to bring back), *VPN* (the tunnel's switch from the VPN tab; if no location is chosen yet it opens the location list), *Ad block* (start
  or stop AdGuard Home blocking; asks first because DNS restarts), *Airplane*, *Network* (shows the Wi-Fi network
  the router is joined to; opens the Wi-Fi tab) and *Screen off*. A lit tile is on.
- **Reboot** and **Shut down** (red outline): both ask you to confirm first.
- **Brightness**: Low, Medium or High.
- **Close it** by tapping the dimmed area, or by dragging the panel back up. It doesn't open on the lock screen.

## Status bar

The top row of every screen shows:

- **Left**: signal bars, network type (4G, 5G…) and the carrier in use, or "Airplane".
- **Right**: the battery percentage (the number turns yellow while charging) and, to its left, an icon
  for each feature that's on:

| Icon | Means |
|---|---|
| Lock | A screen passcode is set |
| Shield (teal) | VPN connected |
| ⊘ | AdGuard Home is blocking ads and trackers |
| Wi-Fi | Internet is coming from a Wi-Fi network (repeater) |
| ↑↓ arrows | Mobile data is on |
| **R** | Data roaming is on and in use |
| Plane | Airplane mode is on |

## Lock screen

The lock screen appears whenever the screen wakes up.

- **Unlock**: swipe up, or tap "Swipe up to unlock" at the bottom.
- **With a passcode set**: swiping up shows a number pad. After 5 wrong tries it locks for 30 seconds.
- **What it shows**: either a big clock (time, date, your signature) or a status view (data used,
  devices online, speed). Choose under More → Display → *When the screen wakes, show*.
- Small labels at the bottom show unread texts, VPN status and the current weather.

## Home

- **Time and date** for Manila, plus a second city if you've turned on two clocks. Your signature, if
  set, appears under the date.
- **Weather** (top right): tap it for the forecast.
- **SIM card**: the SIM in use, data used this month against your cap, and where internet is coming
  from right now (*Repeater*, *4G*, *5G*…). Shows "data off" when mobile data is off. Tap it to open SIM.
- **Devices**: how many devices are online. Tap for the Clients list.
- **Speed**: live download and upload. Tap for Monitor.
- **VPN** and **Texts**: tap to open them. Texts shows how many are unread.

## SIM (Mobile)

- **Mobile data** (top): turns mobile internet on or off. Texts and calls keep working when it's off.
- **SIM cards**: **SIM1** (physical), **SIM2** (physical) and **eSIM**. SIM2 and the eSIM share slot 2,
  so only one of them can be on at a time; the other shows "Slot 2 busy".
  Each SIM that's in its slot shows its phone number (as the network reports it) and the data used.
  - With data **on**, the SIM in use is highlighted with "In use ›". Tap it for **Details & info** (read-only: phone number, ICCID, operator, network type and radio, roaming, APN,
    IP address, gateway, DNS, the cell's band, ID, TAC, PCI, ARFCN and signal levels, and the modem's model, firmware and IMEI) and to set its **monthly data cap**
    (No cap, 5–100 GB). The cap is only for the usage bar; it never cuts data off.
  - **Network & bands** (same page, under Details & info): the stock admin panel's **Network type** (Auto, 5G or 4G) and **Band masking** for the SIM in use.
    Switch Band masking on and tick the bands the modem may use, in groups (5G NR SA, 5G NR NSA, 4G LTE; **All** / **None** per group). A yellow
    "pick one" flag means that group would leave no usable network; **Apply** stays off until it's fixed. Nothing changes until you tap Apply and confirm; mobile
    data reconnects and devices may lose internet while it does (a band change was seamless in testing; switching network type took about 25 seconds). To undo: switch Band masking off (and set Auto) and apply. If you end up with no signal, the
    stock admin panel (SIM details, Settings) shows the same switch. Lock operator and Lock tower are only in the admin panel.
  - Tap another SIM to switch to it. Mobile internet pauses for up to a minute while the modem
    reconnects.
  - With data **off**, no SIM is selected. Tap a SIM to turn data on with that SIM.
- **Data roaming** (bottom): asks before turning on, because roaming can be expensive.
- **Locked SIM**: a SIM that asks for its PIN shows **Locked ›** on its card (and "locked" on Home). Tap it to see how many attempts are left and
  enter the PIN (shown as dots). **Be careful: 3 wrong PINs lock the SIM**, and then it needs its PUK code, which you enter on a phone; the screen
  warns before the last attempt and only ever sends one PIN per tap. A SIM that isn't asking for a PIN can't be sent one.
- **eSIM information** (below SIM failover; scroll): read-only details of the eSIM card, like the stock screen: EID, ICCID, IMSI, card OS version, free storage, and the installed profiles with their
  names and whether each is enabled. It reads the card only when you open it and can take up to a minute; if the eSIM isn't ready you see why and can try again. Slot 2 must be set to the eSIM. Managing profiles
  (enable, rename, delete) is done in the admin panel.
- **SIM failover** (below Data roaming; scroll): lets the router switch SIMs by itself if the current one stops working, like the
  stock screen. **Enable**, then the **priority** order (**Swap priority** flips it; Priority 1 is the preferred SIM) and an optional
  **Scheduled switch**: at the **Execution time** each day the router goes back to Priority 1. Changes save straight away.

## Wi-Fi

- **Internet from Wi-Fi**: the network the router is using for internet (repeater mode).
  - **Change** / **Join** lists nearby networks with their signal strength and a band tag after the
    name: **2.4 GHz**, **5 GHz**, or **2.4/5 GHz** when the network is on both. Open and saved networks join
    straight away; others ask for the password on the on-screen keyboard (at least 8 characters).
  - **Scan again** searches for networks again. **Disconnect** stops using Wi-Fi for internet.
- **Main / Guest** switch (under the internet card): shows the router's own Wi-Fi or the guest Wi-Fi. A tab
  says "· off" when both of its bands are off.
- **2.4 GHz** and **5 GHz** (Main): each band has its own section:
  - **Network** turns the band on or off.
  - **Password** changes that band's password (8 to 63 characters; the keyboard opens with the current one). It asks first on
    the main Wi-Fi, because devices disconnect and have to join again with the new password. An open network shows "None (open)".
  - **Name** renames just that band. It asks first, because devices on it disconnect and have to join the
    new name. The password doesn't change.
  - **Hide network name** stops the name showing in Wi-Fi lists; devices that saved it can still join. It asks first on the main Wi-Fi,
    because devices disconnect while it restarts.
  - **Network mode** picks the Wi-Fi standards the band allows (for example *b/g/n/ax/be* or *ax/be*).
    Newer-only modes can stop older devices connecting. The band restarts, and guest Wi-Fi on the same
    band drops too.
- **Channel** (per band, shared by main and guest): **Auto** or a specific channel. The list only has channels that fit the band's
  bandwidth, and channels marked **DFS** need a radar check each time Wi-Fi starts, so the band is unavailable for a while (it asks first).
  While the router uses Wi-Fi for internet, that band's channel is **locked** (the network it joined decides it), as on the stock screen.
- **TX power** (per band, shared by main and guest): **Max**, **High**, **Medium** or **Low**. Lower power shortens the range; devices far from the router may lose
  signal. Changing it restarts the band, so it asks first.
- **Guest** tab: a separate network for visitors, with the same 2.4 GHz and 5 GHz sections: **Network**, **Name**
  and **Network mode** rows. Guests get internet but can't see your devices. Network mode is one setting per
  band, shared with the main Wi-Fi: changing it on either changes both. Renaming a guest band doesn't ask
  first.
- **With the router joined to a Wi-Fi network for internet, only two of your own networks can run** (for example
  main 2.4 GHz plus guest 5 GHz). A third is refused. This is a limit in the router's Wi-Fi driver, and it doesn't apply when the router
  gets its internet from mobile data or a cable: then all four can run. Turning on a third one asks which
  of the two to turn off, then swaps them. The switches show what is actually running.
- **Some combinations don't run together.** For example, guest 5 GHz was refused while the router was joined
  to a 5 GHz network with three other networks on. If the router refuses, the screen says so: turn another
  network off and try again. **Share guest Wi-Fi** (QR code) appears when a guest band is on.
- **5 / 6 GHz band** (Main tab, if your router has a 6 GHz band): the router's 5 GHz and 6 GHz Wi-Fi share one radio, so you pick **5 GHz**, **6 GHz** or **Auto**. Auto prefers 5 GHz and follows
  the band of a Wi-Fi network the router repeats. Only the bands that can work are offered: 6 GHz is not available when the router's usage environment is Outdoor (set in the admin panel), and while the
  router uses a Wi-Fi network on one band, the other fixed band is hidden. The band restarts when you change it, so it asks first.
- **Saved networks** (Main tab): the Wi-Fi networks the router remembers for internet, like the stock "Known Networks". The one in use is marked.
  Tap a network for its details: **Password** (only for the network you're using now: it re-joins with the new password, and if it can't join it goes back
  to the old one) and **Forget this network** (it asks first; you'll need the password to join it again).
- **Share Wi-Fi**: shows a QR code that phones can scan to join, plus the network name and password.
  Switch between 5 GHz and 2.4 GHz at the bottom.
- **Devices connected**: opens the Clients list.

### Keyboard

- **aA**: capital letters on or off. **123** / **abc**: switch between letters and numbers/symbols.
- **space** and **Del** (delete). **Connect** or **Save** stays dim until the text is long enough.

## VPN

Works like the VPN Dashboard in the stock screen and admin panel: one tunnel with a switch, a server and settings.

- **Big round button** (the tunnel's "Use" switch): connects or disconnects. It keeps the chosen server when you
  switch off. When it's on, all devices go through the VPN. The quick-panel VPN tile is the same switch.
- **Location** (the tunnel's "Via"): pick a WireGuard server (for example "United States · Seattle"). If the VPN is
  on, it reconnects to the new server. With no tunnel yet, choosing a location creates one, switched off; then use
  the switch.
- **Settings**: **Kill switch** (blocks internet for devices if the VPN drops), **Remote access to LAN**,
  **IP masquerading** and **Services use VPN** (GL.iNet's own services). Changing one restarts the VPN for a few
  seconds. The MTU and which devices use the tunnel are set in the admin panel.
- Servers are the WireGuard configs saved on the router. Add new ones in the admin panel.
- If the router refuses a change, or connects to a different server than the one chosen, the screen says so.

## More

At the top: **Airplane mode** (stops mobile data, texts and calls; Wi-Fi keeps working).

### Tools

- **Texts**: the texts you received, newest first, with an orange dot on unread ones. Open one to read it (the router marks it
  read, so the stock screen agrees). **Delete this text** at the bottom of a text, or **Delete read texts** at the bottom of the
  list; both ask first and remove the text from the router itself. **Sent texts** lists what was sent earlier (read or delete only).
  **Sending texts was removed from this screen on 2026-11-25** because it wasn't working: use the stock screen or the admin panel to send.
- **Weather**: today and the next two days, plus current temperature, feels-like, UV index and air
  quality. **Change city** opens a search: type part of any city in the world and pick it from the
  results. Your last three cities are listed for quick switching.
- **Monitor**: live speed, CPU, memory, temperature and uptime. **Run speed test** measures download and
  upload. It uses up to about 330 MB, which counts against your mobile data if the router is on mobile
  data. Leaving the screen stops the test.
- **Currency**: converts one currency into your main currency (the Philippine peso until you change it). **Compare with** and **My currency** each open the
  same list of about 30 currencies; pick one and the page and the More tile follow. The main currency is left out of the Compare list so it never
  compares with itself, and changing the main currency to the one you were comparing swaps the comparison to PHP (or USD). Small rates (yen, won) are shown per 100 or 1,000. Rates come from open.er-api.com and refresh every few hours.

### Router settings

- **Clients**: every known device, online first, with its data used. Tap one for its details and
  **Block this device** / **Unblock this device**. A blocked device can't use the main or guest Wi-Fi.
  Careful: blocking the computer you're using cuts its connection.
- **Internet**: which connection is in use and the state of mobile, Wi-Fi and Ethernet.
- **Network**:
  - **Ethernet port**: *WAN · internet in* takes internet from a cable (modem or wall socket);
    *LAN · devices* gives a wired device internet from the router.
- **Display**: brightness, **Accent color** (see below), 24-hour time, time zone (the router's own, shown here; the clocks follow it), what the lock screen shows, your **personal
  signature** (up to 24 characters), **Wallpaper** (Earth, Plain or Your own) and where it shows
  (Lock screen, or Lock + Home).
- **Security**: screen passcode (4 digits, kept on this screen only; the stock screen has its own), auto lock after
  30 s / 1 min / 5 min / Never, screen always on, and **Lock screen now**. Screen always on and the timed auto-lock
  choices are shared with the stock screen. Auto lock turns the screen off when you haven't touched it for that long.
- **Power & USB**: power on with charger, auto standby, Wi-Fi and Ethernet idle timeouts, auto power off,
  USB mode (Ask me / Tethering / Host), USB protocol (2.0 / 3.1), power direction for each USB port
  (Input or Output), the battery level below which USB power output stops, and battery status.
- **AdGuard Home**: turn it on or off, and **Block ads & trackers**. Changing either restarts DNS, so
  devices may lose internet for a few seconds.
- **GL.iNet Account**: whether remote management is on.
- **Dashboard**: one or two clocks on Home, the second clock's city, 24-hour time, and **Switch to stock
  screen**.
- **Firmware**: the installed version and whether a newer one is available (the router's own update check, like the stock
  screen). With an update, you see the version and a short release note, and **Skip this version** stops the prompt. An orange dot on
  More means the router is prompting for an update. **Check again** asks the router now. To install, use the admin panel or the stock
  screen: this screen doesn't install firmware.
- **About device**: model, firmware, modem, CPU temperature, uptime and the admin panel address.

At the bottom: **Screen off**, **Reboot** and **Shut down**.

## Your own wallpaper

Copy a photo to the router, then choose More → Display → Wallpaper → **Your own**. It's cropped to fill
the screen and darkened a little so text stays readable.

```sh
scp -O photo.jpg root@10.10.1.1:/root/e5ui/wallpaper.jpg
```

## Power button

- **Quick tap**: screen off or on.
- **Hold about 1 second**: switch between this UI and the stock GL.iNet screen. From this UI it asks you
  to confirm on screen first.

## Going back to the stock screen

Any of these works, and you can switch back the same way:

- More → Dashboard → **Switch to stock screen**.
- Hold the power button for about a second.
- From a computer: `ssh root@10.10.1.1 /root/e5ui/toggle.sh off` (and `on` to come back).

If the custom UI ever crashes three times in a row, the router switches to the stock screen by itself.

## Accent color

More → Display → **Accent color** changes the color used for the tab highlight, switches, buttons, progress bars, chips and the check marks. Pick one of five ready-made
colors (Teal is the original, then Blue, Purple, Pink, Lime) or **Your color**: tap a hue, tap how strong it should be, or choose **Type a hex code** (six digits,
0-9 and A-F, for example 4FD1B5), then **Use this color**. Very dark colors are lightened so they stay readable on the dark screen, and the text on filled buttons
switches between dark and white to stay readable. It applies at once and is remembered. Warning orange and the red for delete / danger don't change.
