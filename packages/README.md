# Installing as a package (.ipk)

`build.sh` produces `dist/gl-e5800-touch-ui_<version>_all.ipk`, a real opkg package of the touchscreen UI. Nothing is compiled
(all Python and shell), so it builds on a Mac or Linux with only `tar` and `gzip`.

```sh
cd packages && ./build.sh            # default version 1.0.0; the router now has 1.0.2 (./build.sh 1.0.2); or ./build.sh 1.1.0
```

## Install

Either copy it over and install on the router:

```sh
scp -O dist/gl-e5800-touch-ui_1.0.2_all.ipk root@10.10.1.1:/tmp/
ssh root@10.10.1.1 'opkg install /tmp/gl-e5800-touch-ui_1.0.2_all.ipk && opkg install --nodeps python3-pillow'
```

or upload the file in the router's LuCI page (System, Software, Upload Package). The package pulls in `python3`, `libtiff6`,
`qrencode` and the five `zoneinfo-*` packages from GL.iNet's feed. **`python3-pillow` is not a dependency**: it clashes with a file the stock
screen package owns, so it needs `opkg install --nodeps python3-pillow` (the install prints this if Pillow is missing).

Installing does **not** switch the screen over. Turn it on with `/root/e5ui/toggle.sh on` (or hold the power button for a second). Back to the stock screen:
`/root/e5ui/toggle.sh off`. If the custom screen is already showing, installing restarts it so it loads the new code.

Try a package without installing it: `opkg install --noaction /tmp/<file>.ipk` (a dry run).

## What it does

| Script | Does |
|---|---|
| postinst | makes `/root/e5ui/cache`, sets executable bits, checks for Pillow, enables and restarts the power-button watcher (`homebutton`), restarts the screen if it is showing, and restores the custom screen if an upgrade just removed it (within 5 minutes) |
| prerm | if the custom screen is in use or set to start, hands the screen back to the stock UI first (so the display is never left blank), then stops and disables `homebutton` |
| postrm | removes only `__pycache__` and `.backlight_saved`. **Settings (`config.json`) and the data-usage counters (`cache/`) are kept.** Wipe everything with `rm -rf /root/e5ui` |

It conflicts with the older community `gl-e5800-dashboard` package (same `/etc/init.d/homebutton`).

## Format notes (why the build looks the way it does)

- On this router's opkg an `.ipk` is a plain gzip tar containing `debian-binary`, `data.tar.gz`, `control.tar.gz` **in that order**, not an `ar` archive. (From the upstream
  community dashboard's notes; a truncated file is rejected as "Malformed package file", which the dry run confirms.)
- The scripts must not call `opkg` (not even `list-installed`): opkg holds a non-reentrant lock for the whole install, so it would deadlock.
- bsdtar (macOS) and GNU tar take different flags for "root-owned, plain format"; `build.sh` detects which it has. `COPYFILE_DISABLE` stops macOS `._` files.
- The data archive lists files only, so the package does not claim ownership of `/etc` or `/root`.
- `Architecture: all`: tied to the GL-E5800's paths and hardware (framebuffer, touch, backlight, power key), not to a CPU.

## What was tested (2026-11-25)

Built on macOS; inspected (members, order, root ownership, no `._` files, control file); `opkg install --noaction` on the router: exit 0, router unchanged afterwards; a deliberately truncated
copy was rejected with "Malformed package file" (exit 255); `sh -n` on the router passes for postinst, prerm and postrm.

**Real install on the router (same day), over a working manual install:** `opkg install` exit 0; `postinst` ran (no Pillow warning, it was already installed); the package now owns the 8 files, which are byte-identical
to the manual copy; the custom screen stayed the active one with no crash in the log; `homebutton` running and enabled; `config.json` (settings, passcode) and `cache/` untouched; package status `install user installed`.

**Upgrade 1.0.0 -> 1.0.1 (tested on the router, 2026-11-25):** dry run clean, real install exit 0; prerm switched to the stock screen, postinst restored the custom one at once; the 8 files stayed
byte-identical to `router/`, `config.json` and `cache/` untouched, services running and enabled, no errors. A harmless "ubus service delete homebutton (Not found)" line prints during it.

**Upgrade 1.0.1 -> 1.0.2 (tested the same evening):** same procedure, same result (exit 0, custom screen restored, files identical, `config.json` unchanged). The router runs 1.0.2.

**Not tested:** `prerm`/`postrm` as a real remove (`opkg remove`), installing on a router with no previous manual install, and a firmware update wiping the package (it will: reinstall the file).
