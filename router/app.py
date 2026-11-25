#!/usr/bin/env python3
"""GL-E5800 touchscreen UI: tab bar (Home / SIM / Wi-Fi / VPN / More), lock screen,
settings. Router data and actions come from lib.py (extracted from gl-e5800-dashboard).
Run: app.py            -> live on /dev/fb0
     app.py --preview D -> render every screen to PNGs in D (screen untouched)"""
import colorsys, json, math, os, re, signal, subprocess, sys, threading, time, urllib.parse
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, ImageChops, ImageDraw

import lib

_orig_rr = ImageDraw.ImageDraw.rounded_rectangle


def _safe_rr(self, xy, radius=0, fill=None, outline=None, width=1, **kw):
    """Pillow 9.5 raises on rounded boxes smaller than 2*radius; draw those square."""
    try:
        return _orig_rr(self, xy, radius, fill, outline, width, **kw)
    except ValueError:
        return self.rectangle(xy, fill=fill, outline=outline, width=width)


ImageDraw.ImageDraw.rounded_rectangle = _safe_rr

W, H = 240, 320
HERE = Path(__file__).resolve().parent
CFG_FILE = HERE / "config.json"
CACHE = HERE / "cache"
TOGGLE = str(HERE / "toggle.sh")
SLEEP = str(HERE / "screen_sleep.sh")
BL_SAVED = HERE / ".backlight_saved"
STOCK_WALL = "/etc/gl_screen/image/wallpaper.png"
CUSTOM_WALLS = [HERE / n for n in ("wallpaper.jpg", "wallpaper.jpeg", "wallpaper.png")]

BG = (14, 17, 22); SURF = (23, 28, 36); EDGE = (35, 42, 53); DIV = (30, 36, 46)
FG = (232, 234, 237); DIM = (154, 164, 176); TEAL = (79, 209, 181); TEAL2 = (47, 168, 143)
TEALBG = (20, 35, 31); CHIPBG = (31, 59, 54); CHIPFG = (127, 227, 204)
WARNBG = (61, 46, 18); WARNFG = (245, 194, 107); WARN = (245, 165, 36)
RED = (255, 154, 154); REDLINE = (122, 52, 52); GRAYBG = (35, 42, 53); GRAYFG = (184, 193, 204)
TABBG = (18, 22, 28); TABDIM = (139, 149, 161); KEY = (38, 45, 56); TGOFF = (42, 49, 60); KNOB = (174, 183, 194)
SUN = (245, 194, 107); CLOUD = (201, 209, 218); RAIN = (108, 168, 235)
ON_ACCENT = (4, 20, 15)  # text on a filled accent button: dark on light accents, white on dark ones
ACCENTS = [("Teal", (79, 209, 181)), ("Blue", (96, 165, 250)), ("Purple", (167, 139, 250)), ("Pink", (244, 114, 182)), ("Lime", (163, 230, 53))]


def accent_fix(rgb):
    """Keep a chosen color readable on the dark screen: dark colors are lightened (brightness at least 60%)."""
    h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in rgb])
    return tuple(round(x * 255) for x in colorsys.hsv_to_rgb(h, s, max(v, 0.6)))


def apply_accent(rgb):
    """Recolor the whole UI: the accent constants are module globals read at draw time, so reassigning them is enough."""
    global TEAL, TEAL2, TEALBG, CHIPBG, CHIPFG, ON_ACCENT
    def mix(a, b, t):
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    base = accent_fix(rgb)
    if base == ACCENTS[0][1]:  # the original teal keeps its hand-picked shades
        TEAL, TEAL2, TEALBG, CHIPBG, CHIPFG = base, (47, 168, 143), (20, 35, 31), (31, 59, 54), (127, 227, 204)
    else:
        TEAL, TEAL2 = base, tuple(round(x * 0.8) for x in base)
        TEALBG, CHIPBG, CHIPFG = mix(BG, base, 0.08), mix(BG, base, 0.2), mix(base, (255, 255, 255), 0.3)
    lum = (0.2126 * TEAL2[0] + 0.7152 * TEAL2[1] + 0.0722 * TEAL2[2]) / 255
    ON_ACCENT = (4, 20, 15) if lum > 0.38 else (255, 255, 255)


def accent_current(cfg):
    if cfg.get("accent") == "custom" and cfg.get("accent_custom"):
        return tuple(cfg["accent_custom"])
    return dict(ACCENTS).get(cfg.get("accent"), ACCENTS[0][1])

_FN = {"m": "default_medium", "s": "default_semibold", "b": "default_bold", "mono": "default_mono_medium"}


FONT_BUMP = 3  # body text is drawn this many px larger; big display numbers (>16px) are left alone


def F(size, w="m"):
    return lib.font(_FN[w], size + FONT_BUMP if size <= 16 else size)


TAP = 10
TOP = 8  # gap between the status bar and each screen's content
TABS = ["home", "sim", "wifi", "vpn", "more"]
PLMN = {"51501": "Globe", "51502": "Globe", "51503": "Smart", "51505": "Sun", "51566": "DITO"}
CAP_OPTS = [None, 5, 10, 20, 25, 50, 100]
FX_NAMES = {"PHP": "Philippine Peso", "USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound", "JPY": "Japanese Yen", "CNY": "Chinese Yuan",
            "SGD": "Singapore Dollar", "AUD": "Australian Dollar", "CAD": "Canadian Dollar", "NZD": "New Zealand Dollar", "HKD": "Hong Kong Dollar",
            "KRW": "South Korean Won", "TWD": "New Taiwan Dollar", "THB": "Thai Baht", "MYR": "Malaysian Ringgit", "IDR": "Indonesian Rupiah",
            "VND": "Vietnamese Dong", "INR": "Indian Rupee", "AED": "UAE Dirham", "SAR": "Saudi Riyal", "CHF": "Swiss Franc", "SEK": "Swedish Krona",
            "NOK": "Norwegian Krone", "DKK": "Danish Krone", "MXN": "Mexican Peso", "BRL": "Brazilian Real", "ZAR": "South African Rand",
            "TRY": "Turkish Lira", "PLN": "Polish Zloty", "ILS": "Israeli Shekel", "QAR": "Qatari Riyal", "KWD": "Kuwaiti Dinar"}

CLOCKS = [("Tokyo", "Asia/Tokyo"), ("Singapore", "Asia/Singapore"), ("Hong Kong", "Asia/Hong_Kong"),
          ("Sydney", "Australia/Sydney"), ("Dubai", "Asia/Dubai"), ("London", "Europe/London"),
          ("Paris", "Europe/Paris"), ("New York", "America/New_York"), ("Los Angeles", "America/Los_Angeles"),
          ("Toronto", "America/Toronto")]
VPN_CC = {"ph": "Philippines", "uk": "United Kingdom", "gb": "United Kingdom", "us": "United States", "sg": "Singapore",
          "de": "Germany", "jp": "Japan", "hk": "Hong Kong", "au": "Australia", "ca": "Canada", "fr": "France",
          "nl": "Netherlands", "kr": "South Korea", "tw": "Taiwan", "th": "Thailand", "my": "Malaysia", "id": "Indonesia",
          "vn": "Vietnam", "in": "India", "ae": "UAE", "es": "Spain", "it": "Italy", "ch": "Switzerland", "se": "Sweden"}
VPN_CITY = {"mnl": "Manila", "gla": "Glasgow", "lon": "London", "edi": "Edinburgh", "man": "Manchester", "sea": "Seattle",
            "bdn": "Bend", "sfo": "San Francisco", "sjc": "San Jose", "lax": "Los Angeles", "slc": "Salt Lake City",
            "las": "Las Vegas", "phx": "Phoenix", "den": "Denver", "oma": "Omaha", "kan": "Kansas City", "chi": "Chicago",
            "ltm": "Latham", "dtw": "Detroit", "dal": "Dallas", "buf": "Buffalo", "hou": "Houston", "bna": "Nashville",
            "bos": "Boston", "ash": "Ashburn", "nyc": "New York", "atl": "Atlanta", "clt": "Charlotte", "mia": "Miami",
            "sng": "Singapore", "ber": "Berlin", "fra": "Frankfurt", "tok": "Tokyo", "hkg": "Hong Kong", "syd": "Sydney"}

DEFAULTS = {
    "tz": "Asia/Manila",
    "city": {"name": "Manila", "country": "Philippines", "lat": 14.5995, "lon": 120.9842},
    "recent": [{"name": "Manila", "country": "Philippines", "lat": 14.5995, "lon": 120.9842},
               {"name": "Cebu City", "country": "Philippines", "lat": 10.3157, "lon": 123.8854},
               {"name": "Tokyo", "country": "Japan", "lat": 35.6762, "lon": 139.6503}],
    "two_clocks": False, "clock2": ["Tokyo", "Asia/Tokyo"], "h24": False, "sig": "", "wake": "Clock",
    "pin": "", "pass_on": False, "auto_lock": 60, "always_on": False,
    "caps": {"sim1": 20, "sim2": 25, "esim": 5}, "fx": "USD", "home_fx": "PHP", "accent": "Teal", "accent_custom": None, "bright": "Medium", "vpn_peer": None, "sms_read": [],
    "wallpaper": "Earth", "wall_on": "Lock screen", "data_last": None,
}


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        cfg.update(json.loads(CFG_FILE.read_text()))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    tmp = CFG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CFG_FILE)


# ---------------- data ----------------

def carrier_name(s):
    raw = (s.get("carrier") or s.get("name") or "").strip()
    digits = raw.replace(" ", "")
    if digits.isdigit():
        return PLMN.get(digits, raw)
    return raw.title() if raw.upper() in ("SMART", "GLOBE", "SUN") else (raw or "Unknown")


USAGE_FILE = CACHE / "usage.json"


class Usage:
    """Data used per SIM (by ICCID) this calendar month, kept in cache/usage.json so it survives reboots.

    The modem's traffic_total is cumulative (it never resets monthly) and reads 0 for a while after boot.
    So only the increase between readings is added. A 0 reading is ignored, and a smaller non-zero reading
    is treated as a counter reset. Saved every 10 MB or 10 minutes, and on exit."""
    def __init__(self):
        self.lock = threading.Lock()
        try:
            self.d = json.loads(USAGE_FILE.read_text())
        except Exception:
            self.d = {}
        self.saved_at, self.dirty_bytes = time.time(), 0

    def update(self, key, counter):
        month = time.strftime("%Y-%m")
        with self.lock:
            e = self.d.get(key)
            if counter <= 0:
                return e["used"] if e and e["month"] == month else 0
            if e is None:  # first time we see this SIM: count what the modem has as this month's so far
                e = self.d[key] = {"month": month, "used": counter, "last": counter}
                self.dirty_bytes += 1 << 30
            else:
                delta = counter - e["last"] if counter >= e["last"] else counter
                if e["month"] != month:
                    e["month"], e["used"] = month, 0
                    self.dirty_bytes += 1 << 30
                e["used"] += delta
                e["last"] = counter
                self.dirty_bytes += delta
            if self.dirty_bytes >= 10e6 or time.time() - self.saved_at > 600:
                self.save_locked()
            return e["used"]

    def save_locked(self):
        if not self.dirty_bytes:
            return
        try:
            CACHE.mkdir(exist_ok=True)
            tmp = USAGE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d))
            os.replace(tmp, USAGE_FILE)
            self.saved_at, self.dirty_bytes = time.time(), 0
        except Exception:
            pass

    def save(self):
        with self.lock:
            self.save_locked()


USAGE = Usage()


def get_sims():
    st = lib.ubus_call("cellular.sim", "status", {"bus": "cpu"}).get("sims", [])
    # no bus filter: with {"bus": "cpu"} the router only returns the SIM in use, not both
    net = [n for n in lib.ubus_call("cellular.network", "status").get("networks", []) if n.get("bus", "cpu") == "cpu"]
    ok, fo = lib.gl_c_rpc("modem", "get_slot_failover_config", {"bus": "cpu"}, timeout=20)
    fo = fo if ok and isinstance(fo, dict) else {}
    types = {str(x.get("slot")): int(x.get("type", 0)) for x in fo.get("slot_type", [])}
    cur = str(lib.ubus_call("cellular.modem", "status", {"bus": "cpu"}).get("current_sim_slot", fo.get("current_sim", 1)))
    traffic = {}
    for n in net:
        try:
            counter = int(n.get("traffic_total") or 0)
        except (TypeError, ValueError):
            continue
        traffic[str(n.get("slot"))] = USAGE.update(n.get("iccid") or f"slot{n.get('slot')}", counter)
    phones = {str(x.get("slot")): x.get("phone_number") or ""
              for x in lib.ubus_call("cellular.sim", "info", {"bus": "cpu"}).get("sims", [])}
    return {"cur": cur, "slot2_type": types.get("2", 0), "dial": get_dial(cur), "phones": phones,
            "names": {str(s.get("slot")): carrier_name(s) for s in st}, "traffic": traffic,
            "locks": {str(s.get("slot")): {"status": s.get("status"), "pin_counter": s.get("pin_counter")} for s in st}}


def get_dial(slot=None):
    """The saved "mobile data on" setting, worked out the way the stock web UI does
    (/usr/share/gl-ngx/websocket/cellular.lua): a SIM's `dial_status` 0 in cellular.network status means
    dialing is enabled. Unlike the data link being up, it holds through reboots, no signal and
    reconnects. Uses the SIM in use when given, otherwise any SIM like the stock UI. None if unreported."""
    nets = [n for n in lib.ubus_call("cellular.network", "status").get("networks", [])
            if n.get("bus", "cpu") == "cpu" and "dial_status" in n]
    if slot is None:
        slot = lib._current_slot()
    mine = [n for n in nets if str(n.get("slot")) == str(slot)]
    if mine:
        return int(mine[0]["dial_status"] or 0) == 0
    return any(int(n["dial_status"] or 0) == 0 for n in nets) if nets else None


def set_data(want):
    """modem.set_connect / disconnect (the stock switch), then wait for the saved setting to match."""
    lib.set_cellular_data_enabled(want)
    if get_dial() is None:  # no setting to read: fall back to the live link
        ok = lib._wait_until(lambda: lib.is_cell_data_up() == want, lib.SIM_DATA_TIMEOUT)
    else:
        ok = lib._wait_until(lambda: get_dial() == want, 30, poll=2)
    if not ok:
        raise RuntimeError("mobile data didn't turn " + ("on" if want else "off"))


def fmt_phone(n):
    """+639171234567 / 639171234567 -> 0917 123 4567 (Philippine mobile); anything else as given."""
    d = re.sub(r"\D", "", n or "")
    if d.startswith("63") and len(d) == 12:
        d = "0" + d[2:]
    if d.startswith("09") and len(d) == 11:
        return f"{d[:4]} {d[4:7]} {d[7:]}"
    return (n or "").strip()


def switch_sim(target):
    slot = 1 if target == "sim1" else 2
    if slot == 2:
        want = 1 if target == "esim" else 0
        if get_sims()["slot2_type"] != want:
            ok, _ = lib.gl_c_rpc("modem", "set_slot_type", {"bus": "cpu", "slot": 2, "type": want}, timeout=60)
            if not ok:
                raise RuntimeError("modem refused slot 2 change")
            time.sleep(3)
    ok, _ = lib.gl_c_rpc("modem", "set_slot_failover_config", {"bus": "cpu", "current_sim": slot}, timeout=60)
    if not ok:
        raise RuntimeError("modem refused the switch")
    if not lib._wait_until(lambda: str(lib.ubus_call("cellular.modem", "status", {"bus": "cpu"})
                                       .get("current_sim_slot")) == str(slot), 60, poll=2):
        raise RuntimeError("SIM didn't switch")


AGH_RPC = "/usr/lib/oui-httpd/rpc/adguardhome"


def get_agh():
    ok, r = lib.gl_lua_rpc(AGH_RPC, "get_config", {}, timeout=20)
    return {"enabled": bool(r.get("enabled")), "dns": bool(r.get("dns_enabled"))} if ok and isinstance(r, dict) else None


def set_agh(enabled, dns):
    """Same call the stock AdGuard page makes: adguardhome.set_config {enabled, dns_enabled}."""
    lib.gl_lua_rpc(AGH_RPC, "set_config", {"enabled": enabled, "dns_enabled": dns and enabled}, timeout=60)
    applied = lambda a: bool(a) and a["enabled"] == enabled and (not enabled or a["dns"] == dns)
    if not lib._wait_until(lambda: applied(get_agh()), 30, poll=2):
        raise RuntimeError("AdGuard didn't change")


RPC_DIR = "/usr/lib/oui-httpd/rpc/"
IDLE_OPTS = [(0, "Never"), (600, "10 min"), (900, "15 min"), (1800, "30 min"), (2700, "45 min"), (3600, "1 h"), (7200, "2 h")]
OFF_OPTS = [(0, "Never")] + [(h * 3600, f"{h} h") for h in range(1, 13)]
USB_MODES = [("askme", "Ask me"), ("device", "Tethering"), ("host", "Host")]
PWR_ROLES = [("Sink", "Input"), ("Source", "Output")]


def gl_get(mod, method="get_config", args=None):
    ok, r = lib.gl_lua_rpc(RPC_DIR + mod, method, args or {}, timeout=20)
    return r if ok and isinstance(r, (dict, list)) else None


def gl_set(mod, cfg):
    """Send the whole form back, like the stock web page does (lpm / otg set_config)."""
    ok, r = lib.gl_lua_rpc(RPC_DIR + mod, "set_config", cfg, timeout=60)
    if not ok:
        raise RuntimeError((r or {}).get("err_msg") or "router refused the change")


def is_blocked(acl, mac):
    mac = (mac or "").upper()
    if (acl or {}).get("mode") == "white":
        return mac not in [m.upper() for m in acl.get("white_mac", [])]
    return mac in [m.upper() for m in (acl or {}).get("black_mac", [])]


def set_blocked(mac, block):
    """black_white_list.set_single_mac, exactly like the stock Clients page's block switch."""
    acl = gl_get("black_white_list") or {"mode": "black"}
    mode = acl.get("mode", "black")
    operate = ("add" if block else "del") if mode == "black" else ("del" if block else "add")
    ok, r = lib.gl_lua_rpc(RPC_DIR + "black_white_list", "set_single_mac", {"mode": mode, "operate": operate, "mac": mac}, timeout=30)
    if not ok:
        raise RuntimeError((r or {}).get("err_msg") or "router refused the change")
    lib._wait_until(lambda: is_blocked(gl_get("black_white_list"), mac) == block, 15, poll=1)


def wifi_procs():
    """[(pid, ppid, args, age_s)] for running `/sbin/wifi` reloads."""
    out = []
    try:
        now = float(Path("/proc/uptime").read_text().split()[0])
        hz = os.sysconf("SC_CLK_TCK")
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                args = [x.decode(errors="replace") for x in args if x]
                if "/sbin/wifi" not in args[:2]:
                    continue
                st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                out.append((int(pid), int(st[1]), args[args.index("/sbin/wifi") + 1:], now - int(st[19]) / hz))
            except (OSError, IndexError, ValueError):
                continue
    except Exception:
        pass
    return out


def wifi_stuck(args):
    """GL firmware bug: `/sbin/wifi multi_up wifiN` with no wlanX after it never ends. qcacld32.sh's
    multi_radio_wifi_updown only advances its outer loop inside the per-interface loop, so with no interface
    name it spins forever. GL's set_config calls it that way for a network that has no `ifname` yet (guest)."""
    return bool(args) and args[0] in ("multi_up", "multi_down") and not any(a.startswith("wlan") for a in args[1:])


def wifi_reloading(max_age=300):
    """True while a recent, healthy `/sbin/wifi` reload is running. Stuck ones (wifi_stuck) and ones older than
    max_age are ignored, so a hung process can't block later changes."""
    return any(age < max_age and not wifi_stuck(args) for _, _, args, age in wifi_procs())


def end_tree(pid):
    """End a process we started and everything under it (used only on our own stuck set_config)."""
    kids = {}
    for p, pp, _, _ in wifi_procs():
        kids.setdefault(pp, []).append(p)
    for p in [pid] + kids.get(pid, []):
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass


def unstick_hostapd_cli(min_age=20):
    """End `hostapd_cli -i status` (empty interface name, see fix_ifnames) started by a /sbin/wifi reload: it never
    returns. The script then reads an empty DFS state and carries on, which is what it does for a missing iface."""
    reloads = {q for q, _, _, _ in wifi_procs()}
    try:
        now = float(Path("/proc/uptime").read_text().split()[0])
        hz = os.sysconf("SC_CLK_TCK")
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                args = [x.decode(errors="replace") for x in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if x]
                if not args or not args[0].endswith("hostapd_cli") or args[1:] != ["-i", "status"]:
                    continue
                st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                if int(st[1]) in reloads and now - int(st[19]) / hz > min_age:
                    os.kill(int(pid), signal.SIGTERM)
            except (OSError, IndexError, ValueError):
                continue
    except Exception:
        pass


class WifiStuck(RuntimeError):
    pass


def wifi_rpc(params, done, timeout=300):
    """Run wifi.set_config detached and wait (never kill a healthy one) until the reload has finished and
    `done()` reports the new state. GL's backend reloads the radio synchronously, which can outlast any sane
    timeout; killing it midway left half-finished `wifi multi_up` processes and unsaved settings.
    If it starts a reload that hits the firmware loop bug (wifi_stuck), end our own process tree and raise
    WifiStuck so the caller can use the full Wi-Fi start instead."""
    lib._wait_until(lambda: (unstick_hostapd_cli(), not wifi_reloading())[1], 120, poll=2)
    p = subprocess.Popen(["lua", "-", RPC_DIR + "wifi", "set_config", json.dumps(params)], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    p.stdin.write(lib._GL_WIFI_LUA)
    p.stdin.close()
    stuck = []

    def check():
        unstick_hostapd_cli()
        mine = [(q, args) for q, pp, args, _ in wifi_procs() if pp == p.pid]
        if any(wifi_stuck(args) for _, args in mine):
            stuck.append(True)
            return True
        return p.poll() is not None and not wifi_reloading() and done()
    ok = lib._wait_until(check, timeout, poll=2)
    if stuck:
        end_tree(p.pid)
        raise WifiStuck("router Wi-Fi reload got stuck")
    if not ok and not done():
        raise RuntimeError("the router hasn't applied the change yet")


def iface_named(iface):
    return bool(lib.uci_get(f"wireless.{iface}.ifname", ""))


# Fixed names for guest networks: free on this E5800 (wlan0 main 2.4, wlan1 main 5, wlan2 6 GHz, wlan4 repeater sta).
GUEST_IFNAME = {"guest2g": "wlan3", "guest5g": "wlan5"}


def name_iface(iface):
    """Give a guest network a fixed, unused uci `ifname` so GL's per-band reload is called as
    `multi_up wifiN wlanX` (no firmware loop) and boot's assign_vif_ifname keeps it ("manual-used")
    instead of auto-picking one that clashes."""
    want = GUEST_IFNAME.get(iface)
    if not want:
        raise RuntimeError("this network can't be started from here on this firmware")
    if lib.uci_get(f"wireless.{iface}.ifname", "") == want:
        return
    out = subprocess.run(["uci", "show", "wireless"], capture_output=True, text=True, timeout=10).stdout
    for line in out.splitlines():
        if line.endswith(f".ifname='{want}'") and not line.startswith(f"wireless.{iface}."):
            raise RuntimeError(f"{want} is already in use")
    if want in os.listdir("/sys/class/net"):
        raise RuntimeError(f"{want} is already in use")
    subprocess.run(["uci", "set", f"wireless.{iface}.ifname={want}"], timeout=10, check=True)
    subprocess.run(["uci", "commit", "wireless"], timeout=10, check=True)


def fix_ifnames():
    """GL's repeater code moves `wlan4` from the sta to guest5g in uci (seen 03:19). With the sta enabled but
    nameless, starting any 5 GHz AP runs `hostapd_cli -i $pri_ifname status` with an empty name, i.e.
    `hostapd_cli -i status`, which retries forever (qcacld32.sh hostapd_setup_vif). Put the names back."""
    changed = False
    if not lib.uci_get("wireless.sta.ifname", ""):
        if lib.uci_get("wireless.guest5g.ifname", "") == "wlan4":
            subprocess.run(["uci", "set", f"wireless.guest5g.ifname={GUEST_IFNAME['guest5g']}"], timeout=10)
        subprocess.run(["uci", "set", "wireless.sta.ifname=wlan4"], timeout=10)
        changed = True
    if changed:
        subprocess.run(["uci", "commit", "wireless"], timeout=10)


def set_wifi_enabled(iface, enabled):
    """Per-band wifi.set_config. A network with no uci `ifname` hits the firmware loop bug (wifi_stuck), so it is
    refused up front. Don't fall back to a full `/sbin/wifi up`: its assign_vif_ifname gave guest2g `wlan1`,
    which is already the main 5 GHz interface (2026-11-25), and left guest APs running while uci said off."""
    fix_ifnames()
    if enabled and (iface in GUEST_IFNAME or not iface_named(iface)):
        name_iface(iface)  # always: GL rewrites guest5g.ifname to wlan4 (the repeater sta) after a repeater connect
    wifi_rpc({"init": True, "iface_name": iface, "enabled": bool(enabled)},
             lambda: (lib.uci_get(f"wireless.{iface}.disabled", "0") != "1") == bool(enabled))
    if enabled and not broadcasting(lib.uci_get(f"wireless.{iface}.ifname", "")):
        # e.g. guest 5 GHz while the repeater uses 5 GHz: the driver refuses it
        # (policy_mgr_allow_concurrency: disallow connection) although uci says on.
        # Nothing is running, so just save it as off again (no reload needed) instead of leaving it saved as on.
        subprocess.run(["uci", "set", f"wireless.{iface}.disabled=1"], timeout=10)
        subprocess.run(["uci", "commit", "wireless"], timeout=10)
        raise RuntimeError("the router's Wi-Fi driver refused this combination. Turn another network off and try again")


def net_on(iface):
    """Saved on AND actually broadcasting (the driver can refuse a band while uci still says on)."""
    return lib.uci_get(f"wireless.{iface}.disabled", "1") != "1" and broadcasting(lib.uci_get(f"wireless.{iface}.ifname", ""))


guest_on = net_on

NET_NAMES = {"wifi2g": "Main 2.4 GHz", "wifi5g": "Main 5 GHz", "guest2g": "Guest 2.4 GHz", "guest5g": "Guest 5 GHz"}
OWN_NETS_WHILE_JOINED = 2  # sta + 2 own networks run; the driver refuses a 4th interface (seen 2026-11-25)


def joined_to_wifi():
    return broadcasting(lib.uci_get("wireless.sta.ifname", "wlan4"))


def running_nets():
    return [k for k in NET_NAMES if net_on(k)]


def broadcasting(ifname):
    if not ifname:
        return False
    try:
        out = subprocess.run(["iw", "dev", ifname, "info"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False
    return any(line.strip().startswith("ssid ") for line in out.splitlines())


def rename_wifi(ifaces, ssid):
    """wifi.set_config per network with only the name changed (the stock Wi-Fi page sends the whole form)."""
    fix_ifnames()
    cfg = gl_get("wifi") or {}
    by_name = {i.get("name"): i for radio in cfg.get("res", []) for i in radio.get("ifaces", [])}
    for name in ifaces:
        cur = by_name.get(name)
        if not cur:
            continue
        if cur.get("ssid") == ssid:
            continue
        form = {k: cur.get(k) for k in ("encryption", "key", "hidden", "random_bssid", "bssid") if k in cur}
        wifi_rpc(dict(form, iface_name=name, ssid=ssid), lambda n=name: lib.uci_get(f"wireless.{n}.ssid", "") == ssid)


def wifi_security():
    """{iface: {"enc": encryption, "key": password}} for every Wi-Fi network, from the stock wifi.get_config. Raises if the read
    fails, so the screen keeps what it knew."""
    cfg = gl_get("wifi")
    if cfg is None:
        raise RuntimeError("wifi get_config failed")
    return {i["name"]: {"enc": i.get("encryption"), "key": i.get("key"), "hidden": bool(i.get("hidden"))}
            for radio in cfg.get("res", []) for i in radio.get("ifaces", []) if i.get("name")}


def set_wifi_key(ifaces, key):
    """wifi.set_config per network with only the password changed (like rename_wifi: the stock Wi-Fi page sends the whole form).
    Open networks (encryption none) have no password and are skipped, as on the stock page."""
    fix_ifnames()
    cfg = gl_get("wifi") or {}
    by_name = {i.get("name"): i for radio in cfg.get("res", []) for i in radio.get("ifaces", [])}
    for name in ifaces:
        cur = by_name.get(name)
        if not cur or (cur.get("encryption") or "none") == "none" or cur.get("key") == key:
            continue
        form = {k: cur.get(k) for k in ("encryption", "key", "hidden", "random_bssid", "bssid") if k in cur}
        form["key"] = key
        ssid = lib.uci_get(f"wireless.{name}.ssid", "") or cur.get("ssid")
        wifi_rpc(dict(form, iface_name=name, ssid=ssid), lambda n=name: lib.uci_get(f"wireless.{n}.key", "") == key)


def radio_main_iface(radio):
    return next((i for i in radio.get("ifaces", []) if not i.get("guest") and not i.get("iot")), None)


def mode_label(m):
    """11b/g/n/ax/be -> b/g/n/ax/be (what the stock page lists, without the 11 prefix)."""
    return str(m or "")[2:] if str(m or "").startswith("11") else str(m or "")


def set_wifi_mode(device, hwmode):
    set_wifi_radio(device, hwmode=hwmode)


def set_wifi_radio(device, hwmode=None, channel=None, txpower=None, usemode=None):
    """wifi.set_config for one radio with a new Network mode, channel and/or TX power (Max/High/Medium/Low), built the way the stock
    Modify Wi-Fi drawer builds it. channel 0 = Auto. Anything not given keeps its current setting (auto stays auto)."""
    fix_ifnames()
    cfg = gl_get("wifi") or {}
    radio = next((r for r in cfg.get("res", []) if r.get("device") == device), None)
    cur = radio and radio_main_iface(radio)
    hwmode = hwmode or (radio or {}).get("hwmode")
    if not cur or hwmode not in radio.get("hwmodes", []):
        raise RuntimeError("unknown Wi-Fi mode")
    htmodes = radio.get("htmodes", {})
    widths = [str(10 * 2 ** k) for k in range(1, int(math.log2(int(htmodes.get(hwmode, 20)) / 10)) + 1)]
    allowed = widths + (["auto"] if htmodes.get("auto") else [])
    htmode = str(radio.get("htmode")) if str(radio.get("htmode")) in allowed else widths[-1]  # stock: keep if valid, else widest
    form = {k: cur.get(k) for k in ("init", "encryption", "key", "hidden", "random_bssid") if k in cur}
    saved = lib.uci_get(f"wireless.{device}.channel", "auto")  # the saved setting: get_config reports the live channel (36) even on auto
    keep = int(saved) if saved.isdigit() else 0
    form.update(iface_name=cur["name"], ssid=lib.uci_get(f"wireless.{cur['name']}.ssid", ""), device=device,
                txpower=txpower or radio.get("txpower"), hwmode=hwmode, htmode=htmode, channel=keep if channel is None else channel)
    if "chan_6g_only_psc" in radio:
        form["chan_6g_only_psc"] = radio["chan_6g_only_psc"]
    bm = cfg.get("bandmode") or {}
    if str(radio.get("band", "")).lower() in str(bm.get("band_mutex", "")).lower().split("+"):
        form["usemode"] = usemode or bm.get("usemode")  # the 5/6 GHz choice: 5g, 6g or auto (stock sends it with the radio form)

    def done():
        r = next((r for r in (gl_get("wifi") or {}).get("res", []) if r.get("device") == device), {})
        if r.get("hwmode") != hwmode or (txpower and r.get("txpower") != txpower):
            return False
        if usemode and lib.uci_get("wireless.autoparam.usemode", "") != usemode:
            return False
        return channel is None or lib.uci_get(f"wireless.{device}.channel", "auto") == ("auto" if channel == 0 else str(channel))
    wifi_rpc(form, done)


# 5 GHz channels in the order the stock page groups them, and how many bandwidth-sized blocks each width has
CHANNELS_5G = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165]
BLOCKS_5G = {40: 12, 80: 6, 160: 2}


def wifi_radios():
    """Per radio: band, modes, bandwidth, channel (0 = auto, from uci because get_config shows the live channel), the channels the
    router offers, whether DFS is allowed, and whether the repeater is using it (the stock page locks the channel then).
    Raises if the read fails, so the screen keeps what it knew."""
    cfg = gl_get("wifi")
    if cfg is None:
        raise RuntimeError("wifi get_config failed")
    ok, rep = lib.gl_call("repeater", "get_status", {}, timeout=15)
    using = (rep or {}).get("device") if ok and (rep or {}).get("state") not in (None, 0) else None
    out = {}
    for r in cfg.get("res", []):
        dev = r.get("device")
        ch = lib.uci_get(f"wireless.{dev}.channel", "auto")
        out[dev] = {"band": r.get("band"), "hwmode": r.get("hwmode"), "hwmodes": r.get("hwmodes"), "htmode": str(r.get("htmode") or ""),
                    "txpower": r.get("txpower"),
                    "channels": [{"channel": c.get("channel"), "dfs": bool(c.get("dfs"))} for c in r.get("channels") or []],
                    "channel": int(ch) if ch.isdigit() else 0, "dfs_support": bool(cfg.get("dfs_support")), "repeater": dev == using}
    return out


BAND_LABELS = {"5g": "5 GHz", "6g": "6 GHz", "auto": "Auto"}


def wifi_bandmode():
    """The shared 5 / 6 GHz radio setting (stock `bandmode`): which bands exclude each other, the choice (`usemode`: 5g / 6g / auto), the band in use,
    which band radios the router offers right now, the indoor/outdoor setting and the band the repeater uses. {} on a router without a shared band.
    Raises if the read fails, so the screen keeps what it knew."""
    cfg = gl_get("wifi")
    if cfg is None:
        raise RuntimeError("wifi get_config failed")
    bm = cfg.get("bandmode") or {}
    mutex = [b for b in str(bm.get("band_mutex", "")).lower().split("+") if b]
    if len(mutex) < 2:
        return {}
    ok, env = lib.gl_call("wifi", "get_environment_config", {}, timeout=15)
    ok2, rep = lib.gl_call("repeater", "get_status", {}, timeout=15)
    rep_band = str((rep or {}).get("band") or "").lower() if ok2 and (rep or {}).get("state") not in (None, 0) else ""
    return {"mutex": mutex, "usemode": str(bm.get("usemode") or "").lower(), "useband": str(bm.get("useband") or "").lower(),
            "present": {str(r.get("band", "")).lower(): r.get("device") for r in cfg.get("res", [])},
            "env": (env or {}).get("use_environment") if ok else None, "repeater_band": rep_band}


def band_options(bm):
    """[(value, label)] for the 5 / 6 GHz choice with the stock page's rules: a band is offered only if its radio is in the config, not 6 GHz in
    outdoor mode (use_environment 0; stock: 6 GHz is unavailable there), and, while the repeater uses one of these bands, no other fixed band.
    Auto is always offered (5 GHz preferred; it follows the repeater)."""
    opts = []
    for b in bm.get("mutex") or []:
        if b not in (bm.get("present") or {}):
            continue
        if bm.get("repeater_band") in bm["mutex"] and b != bm["repeater_band"]:
            continue
        if bm.get("env") == 0 and b == "6g":
            continue
        opts.append((b, BAND_LABELS.get(b, b)))
    return opts + [("auto", BAND_LABELS["auto"])] if opts else []


def channel_options(radio):
    """[(value, label)] the way the stock page lists channels: Auto, then the channels that fit the current bandwidth (5 GHz is
    grouped into bandwidth-sized blocks and only whole blocks the router offers are kept), DFS ones only if DFS is allowed."""
    chans = radio.get("channels") or []
    by = {c["channel"]: c for c in chans}
    if str(radio.get("band", "")).lower() == "5g":
        width = int(radio["htmode"]) if str(radio.get("htmode", "")).isdigit() else 20
        o = width // 20
        if o > 1 and width in BLOCKS_5G:
            marked = [c if c in by else None for c in CHANNELS_5G[:BLOCKS_5G[width] * o]]
            keep = []
            for k in range(len(marked) // o):
                grp = marked[k * o:(k + 1) * o]
                if None not in grp:
                    keep += grp
            chans = [by[c] for c in keep]
        chans = [c for c in chans if radio.get("dfs_support") or not c["dfs"]]
    return [(0, "Auto")] + [(c["channel"], f"{c['channel']} · DFS" if c["dfs"] else str(c["channel"])) for c in chans]


def set_wifi_hidden(ifaces, hidden):
    """wifi.set_config per network with only the SSID visibility changed (stock: "SSID Visibility" Shown / Hidden)."""
    fix_ifnames()
    cfg = gl_get("wifi") or {}
    by_name = {i.get("name"): i for radio in cfg.get("res", []) for i in radio.get("ifaces", [])}
    for name in ifaces:
        cur = by_name.get(name)
        if not cur or bool(cur.get("hidden")) == bool(hidden):
            continue
        form = {k: cur.get(k) for k in ("encryption", "key", "hidden", "random_bssid", "bssid") if k in cur}
        form["hidden"] = bool(hidden)
        ssid = lib.uci_get(f"wireless.{name}.ssid", "") or cur.get("ssid")

        def done(n=name):
            now = next((bool(i.get("hidden")) for rd in (gl_get("wifi") or {}).get("res", []) for i in rd.get("ifaces", []) if i.get("name") == n), None)
            return now == bool(hidden)
        wifi_rpc(dict(form, iface_name=name, ssid=ssid), done)


def set_eth_mode(mode):
    """cable.set_port_config, built the way the stock Ethernet Port page builds it."""
    port = next((p for p in (gl_get("cable", "get_ports_config") or {}).get("ports", []) if p.get("support_wan") == "1"), None)
    if not port:
        raise RuntimeError("no switchable Ethernet port")
    cfg = {"name": port["name"], "mode": mode}
    if mode == "wan":
        mac = port.get("macaddr") or {}
        cfg["macaddr"] = {"mode": mac.get("mode", "default"), "macaddr": mac.get("macaddr") or mac.get("defmacaddr")}
    else:
        cfg["vlan_mode"] = lib.uci_get(f"eth_ports_config_map.{port['name']}.vlan_mode", "access") or "access"
        cfg["pvid"] = lib.uci_get(f"eth_ports_config_map.{port['name']}.pvid", "1") or "1"
    ok, r = lib.gl_lua_rpc(RPC_DIR + "cable", "set_port_config", cfg, timeout=90)
    if not ok:
        raise RuntimeError((r or {}).get("err_msg") or "router refused the change")


def opt_label(opts, v):
    return next((l for val, l in opts if str(val) == str(v)), str(v))


def get_clients():
    out = []
    for mac, c in (lib.ubus_call("gl-clients", "list").get("clients") or {}).items():
        try:
            total = int(c.get("total_rx") or 0) + int(c.get("total_tx") or 0)
        except (TypeError, ValueError):
            total = 0
        out.append({"mac": mac, "name": c.get("alias") or c.get("name") or mac, "online": bool(c.get("online")),
                    "iface": c.get("iface") or "", "ip": c.get("ip") or "", "bytes": total,
                    "rx": c.get("rx") or 0, "tx": c.get("tx") or 0})
    out.sort(key=lambda c: (not c["online"], c["name"].lower()))
    return out


def curl_json(url, t=8):
    try:
        return json.loads(lib.run(["curl", "-s", "--max-time", str(t), url], timeout=t + 2))
    except Exception:
        return None


def _cache(name):
    CACHE.mkdir(exist_ok=True)
    return CACHE / name


def fetch_wx(c):
    f = _cache(f"wx_{c['lat']:.2f}_{c['lon']:.2f}.json")
    try:
        old = json.loads(f.read_text())
        if time.time() - old["ts"] < 1800:
            return old
    except Exception:
        old = None
    d = curl_json("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current=temperature_2m,"
                  "apparent_temperature,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                  "precipitation_probability_max,uv_index_max&timezone=auto&forecast_days=3" % (c["lat"], c["lon"]))
    try:
        dl = d["daily"]
        out = {"ts": time.time(), "now": d["current"]["temperature_2m"], "feels": d["current"]["apparent_temperature"],
               "code": d["current"]["weather_code"],
               "days": [{"date": dl["time"][i], "code": dl["weather_code"][i], "hi": dl["temperature_2m_max"][i],
                         "lo": dl["temperature_2m_min"][i], "rain": dl["precipitation_probability_max"][i],
                         "uv": dl["uv_index_max"][i]} for i in range(len(dl["time"]))]}
        f.write_text(json.dumps(out))
        return out
    except Exception:
        return old


def fetch_aq(c):
    d = curl_json("https://air-quality-api.open-meteo.com/v1/air-quality?latitude=%s&longitude=%s&current=us_aqi"
                  % (c["lat"], c["lon"]))
    try:
        return {"aqi": d["current"]["us_aqi"]}
    except Exception:
        return None


def geo_search(q):
    d = curl_json("https://photon.komoot.io/api/?limit=6&lang=en&osm_tag=place:city&osm_tag=place:town&q="
                  + urllib.parse.quote(q), 6) or {}
    out = []
    for f in d.get("features", []):
        p, (lon, lat) = f.get("properties", {}), f.get("geometry", {}).get("coordinates", (None, None))
        if p.get("name") and lat is not None:
            out.append({"name": p["name"], "country": p.get("country", ""), "region": p.get("state") or "",
                        "lat": lat, "lon": lon})
    if out:
        return out
    d = curl_json("https://geocoding-api.open-meteo.com/v1/search?count=6&language=en&format=json&name="
                  + urllib.parse.quote(q), 6) or {}
    return [{"name": r.get("name", ""), "country": r.get("country") or r.get("admin1") or "",
             "region": r.get("admin1") or "", "lat": r["latitude"], "lon": r["longitude"]}
            for r in d.get("results", []) if "latitude" in r]


BAND_GHZ = {"2g": "2.4", "5g": "5", "6g": "6"}


def scan_nets():
    """lib.repeater_scan plus `bands`: every band the network name was seen on (it keeps only the strongest AP)."""
    nets = lib.repeater_scan()
    seen = {}
    for ap in lib.ubus_call("repeater", "scan", {"cached": True}).get("survey", []):
        if ap.get("ssid") and ap.get("band"):
            seen.setdefault(ap["ssid"], set()).add(ap["band"])
    for n in nets:
        bands = sorted(seen.get(n["ssid"], {n.get("band")} - {None}), key=lambda b: list(BAND_GHZ).index(b) if b in BAND_GHZ else 9)
        n["bands"] = "/".join(BAND_GHZ.get(b, b) for b in bands) + " GHz" if bands else ""
    return nets


def vpn_switch_to(tunnel, want):
    """The stock "Use" switch for the tunnel, then wait for the router to really connect or drop."""
    lib.vpn_log(f"switch tunnel={tunnel['id']} peer={tunnel['peer']} want={want}")
    if not lib.set_vpn_enabled(tunnel["id"], want):
        raise RuntimeError("The router refused the VPN " + ("connect" if want else "stop"))
    if want:
        got = lib.wait_for_wireguard_state(tunnel["peer"], any_peer=True)
        if not got:
            raise RuntimeError("VPN didn't connect")
        if tunnel["peer"] and got != tunnel["peer"]:
            raise RuntimeError("Joined a different server")
    elif lib.wait_for_wireguard_state(None, timeout=10) is not None:
        lib.force_wireguard_off()  # GL's switch didn't take
        if lib.wait_for_wireguard_state(None, timeout=15) is not None:
            raise RuntimeError("VPN didn't turn off")


_wrap_cache = {}


def wrap(d, text, f, w):
    """lib.wrap_text_to_lines measures every character; cached because rows() calls it on every frame."""
    key = (text, f, w)
    if key not in _wrap_cache:
        if len(_wrap_cache) > 400:
            _wrap_cache.clear()
        _wrap_cache[key] = lib.wrap_text_to_lines(d, text, f, w)
    return _wrap_cache[key]


def vpn_label(name):
    m = re.match(r"([a-z]{2})-([a-z]{3})", name or "")
    if not m:
        return name
    return f"{VPN_CC.get(m.group(1), m.group(1).upper())} · {VPN_CITY.get(m.group(2), m.group(2).upper())}"


def zone(name):
    """tzinfo for a zone name, or None. The router's Python only has region zones (Asia/Manila) and top-level
    GMT±N, so Etc/GMT-8 is tried as GMT-8, then as a fixed offset (Etc/GMT-8 is UTC+8: the sign is inverted)."""
    name = name or ""
    for n in (name, name[4:] if name.startswith("Etc/") else ""):
        if n:
            try:
                return ZoneInfo(n)
            except Exception:
                pass
    m = re.match(r"Etc/GMT([+-])(\d+)$", name)
    if m:
        return timezone(timedelta(hours=-int(m.group(2)) if m.group(1) == "+" else int(m.group(2))))
    return None


def tz_label(z):
    m = re.match(r"Etc/GMT([+-])(\d+)$", z or "")
    if m:  # POSIX Etc zones are sign-inverted: Etc/GMT-8 is UTC+8
        return f"UTC{'+' if m.group(1) == '-' else '-'}{m.group(2)}"
    return (z or "").split("/")[-1].replace("_", " ")


def fmt_bytes(n):
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e3:.0f} KB"


def wifi_info(iface):
    return lib.uci_get(f"wireless.{iface}.ssid", ""), lib.uci_get(f"wireless.{iface}.key", "")


_qr_cache = {}


def qr_matrix(text):
    """Rows of booleans (dark module) from the `qrencode` CLI (opkg install qrencode), or None."""
    if text not in _qr_cache:
        try:
            out = subprocess.run(["qrencode", "-t", "ASCII", "-m", "0", "-o", "-", text],
                                 capture_output=True, text=True, timeout=5).stdout
            rows = [[line[i] == "#" for i in range(0, len(line), 2)] for line in out.splitlines() if line.strip()]
            n = max(len(r) for r in rows)
            _qr_cache[text] = [r + [False] * (n - len(r)) for r in rows]
        except Exception:
            return None
    return _qr_cache[text]


def wifi_qr_text(ssid, key, enc):
    esc = lambda v: re.sub(r'([\\;,:"])', r"\\\1", v)
    if not key or enc in ("none", "owe"):
        return f"WIFI:T:nopass;S:{esc(ssid)};;"
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(key)};;"


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def set_brightness(level):
    mx = int(read("/sys/class/backlight/soc:backlight/max_brightness", "120") or 120)
    val = {"Low": int(mx * 0.25), "Medium": int(mx * 0.6), "High": mx}[level]
    try:
        Path(lib.BACKLIGHT_PATH).write_text(str(val))
        BL_SAVED.write_text(str(val))
    except Exception:
        pass


_wall_cache = {}


def wallpaper(choice, dim):
    """240x320 RGB wallpaper (cover-cropped, darkened by `dim`), or None for Plain/missing."""
    if choice == "Earth":
        path = STOCK_WALL
    elif choice == "Your own":
        path = next((str(p) for p in CUSTOM_WALLS if p.exists()), None)
    else:
        return None
    if not path or not os.path.exists(path):
        return None
    key = (path, os.path.getmtime(path), dim)
    if key not in _wall_cache:
        try:
            im = Image.open(path).convert("RGB")
            scale = max(W / im.width, H / im.height)
            im = im.resize((max(W, round(im.width * scale)), max(H, round(im.height * scale))), Image.LANCZOS)
            left, top = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((left, top, left + W, top + H))
            if len(_wall_cache) >= 2:  # lock and home use different dims; keep both so unlocking doesn't re-resize
                _wall_cache.clear()
            _wall_cache[key] = Image.blend(im, Image.new("RGB", (W, H), (0, 0, 0)), dim)
        except Exception:
            return None
    return _wall_cache[key]


def to565(img):
    r, g, b = img.split()
    hi = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    lo = ImageChops.add(g.point(lambda v: (v & 0x1C) << 3), b.point(lambda v: v >> 3))
    return Image.merge("LA", (lo, hi)).tobytes()


def write_frame(img):
    data = to565(img)
    try:
        fb = lib._fb_handle()
        fb.seek(0)
        fb.write(data)
    except Exception:
        lib._fb = None
        with open(lib.FB_PATH, "r+b") as fb:
            fb.write(data)


# ---------------- app ----------------

class App:
    def __init__(self, preview=False):
        self.cfg = load_cfg()
        apply_accent(accent_current(self.cfg))
        self.sync_from_stock()
        self.preview = preview
        self.view, self.stack = "home", []
        self.hits, self.scroll, self.scroll_area, self.drag_dy = [], {}, None, 0
        self.sheet = self.busy = self.kb = None
        self.toast, self.toast_t = "", 0
        self.locked, self.lock_stage, self.ubuf, self.uerr, self.tries, self.lock_until = False, "face", "", "", 0, 0
        self.pinbuf = ""
        self.q, self.geo, self.geo_q, self.geo_busy, self.q_t = "", [], "", False, 0
        self.scan, self.scanning = [], False
        self.speed = lib.SpeedTest()
        self.mon = {"net": None, "down": 0.0, "up": 0.0, "cpu": None, "cpu_pct": 0.0, "t": 0}
        self.sel = {}
        self.panel_open, self.panel_drag = False, None  # swipe-down quick panel (open flag / live drag extent in px)
        self.pending, self.wifi_lock = {}, threading.Lock()  # Wi-Fi changes running in the background
        self.dirty, self.last_touch = True, time.time()
        try:  # first ~2.5 minutes after a router boot (not after a plain UI restart)
            up = float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            up = 1e9
        self.boot_until = time.time() + max(0, 180 - up)
        r = self.r = lib.Refresher()
        r.add("sim", lambda: lib.get_sim_status({}), 30)
        r.add("sims", get_sims, 30)
        r.add("cell", lib._get_active_cell_info, 10)
        r.add("rep", lib.get_repeater_status, 20)
        r.add("sms", lib.get_sms_messages, 20)
        r.add("wgp", lib.get_wireguard_peers, 300)
        r.add("tzr", lib.get_router_zone, 300)
        r.add("savedap", lib.get_saved_aps, 120)
        r.add("failover", lib.get_failover, 60)
        r.add("smssent", lib.get_sent_sms, 30)
        r.add("siminfo", lib.get_sim_details, 60)
        r.add("bands", lib.get_band_state, 120)
        r.add("fw", lib.get_firmware_update, 21600)  # the router itself checks too; the stock web UI asks on every page load
        r.add("wga", lambda: lib.get_wireguard_active(strict=True), 20, none_ok=True)  # None = no VPN connected
        r.add("vpnt", lib.get_vpn_tunnel, 20, none_ok=True)  # None = no tunnel yet
        r.add("wx", lambda: fetch_wx(self.cfg["city"]), 1800)
        r.add("aq", lambda: fetch_aq(self.cfg["city"]), 1800)
        r.add("fx", lib.fetch_fx, 3600)
        r.add("clients", get_clients, 20)
        r.add("agh", get_agh, 60)
        r.add("lpm", lambda: gl_get("lpm"), 120)
        r.add("otg", lambda: gl_get("otg"), 120)
        r.add("usbp", lambda: gl_get("system", "get_usb_info"), 3600)
        r.add("wifi", lambda: {"2g": net_on("wifi2g"), "5g": net_on("wifi5g"),
                               "g2": net_on("guest2g"), "g5": net_on("guest5g")}, 60)
        r.add("radios", wifi_radios, 120)
        r.add("wband", wifi_bandmode, 120)
        r.add("ports", lambda: gl_get("cable", "get_ports_config"), 120)
        r.add("wsec", wifi_security, 120)
        r.add("acl", lambda: gl_get("black_white_list"), 60)

    # ---- helpers ----
    def g(self, k, default=None):
        return self.r.get(k, default)

    def save(self):
        save_cfg(self.cfg)

    def go(self, v):
        self.stack.append(self.view)
        self.view = v
        self.scroll[v] = 0
        self.dirty = True

    def back(self):
        if self.view == "monitor" and self.speed.running:
            self.speed.cancel()
        self.view = self.stack.pop() if self.stack else "home"
        self.dirty = True

    def tab(self, v):
        self.stack, self.view = [], v
        self.scroll[v] = 0
        self.dirty = True

    def say(self, msg):
        self.toast, self.toast_t = msg, time.time()
        self.dirty = True

    def work(self, label, fn, refresh=(), done=None):
        def run():
            try:
                fn()
                if done:
                    done()
            except Exception as e:
                self.say(f"Failed: {e}"[:40])
            finally:
                for k in refresh:
                    self.r.request(k)
                self.busy = None
                self.dirty = True
        self.busy = (label, time.time())
        threading.Thread(target=run, daemon=True).start()

    def confirm(self, title, body, yes, fn, danger=False):
        self.sheet = {"title": title, "body": body, "yes": yes, "fn": fn, "danger": danger}
        self.dirty = True

    def is_unread(self, m):
        """Unread on the router (stock status 0) and not opened on this screen either."""
        return m.get("status", 0) == 0 and self.sms_id(m) not in set(self.cfg["sms_read"])

    def unread(self):
        return [m for m in self.g("sms", []) if self.is_unread(m)]

    def fw_prompt(self):
        """A newer firmware exists and the router is still prompting for it (stock: version_new and prompt)."""
        f = self.g("fw")
        return bool(f and f.get("new") and f.get("prompt"))

    @staticmethod
    def sms_id(m):
        return f"{m.get('from')}|{m.get('sent_raw')}"

    def sync_from_stock(self):
        """Take the settings both screens share from the stock screen's own config (uci gl_screen.generic), so whichever
        screen you used last decides. Auto lock only for the timed choices: the stock value for "Never" is unconfirmed."""
        on, secs = lib.stock_get("ALWAYS_ON"), lib.stock_get("AUTO_LOCK_TIME")
        if on in ("0", "1"):
            self.cfg["always_on"] = on == "1"
        if secs in ("30", "60", "300"):
            self.cfg["auto_lock"] = int(secs)

    def home_zone(self):
        """The main clock's zone: the router's own (it follows the router's auto time zone, like the stock screen), else
        the one saved here."""
        return zone(self.g("tzr")) or ZoneInfo(self.cfg["tz"])

    def tfmt(self, tz, show_ap=True):
        dt = datetime.now(tz if isinstance(tz, tzinfo) else ZoneInfo(tz))
        if self.cfg["h24"]:
            return dt.strftime("%H:%M"), ""
        return f"{dt.hour % 12 or 12}:{dt.minute:02d}", dt.strftime("%p") if show_ap else ""

    def data_on(self):
        """Mobile data switched on (the saved setting), not whether the link happens to be up right now."""
        sim = self.g("sim", {})
        if sim.get("airplane"):
            return False
        dial = self.g("sims", {}).get("dial")
        last = self.cfg.get("data_last")
        if time.time() < self.boot_until and last is not None and dial is not True:
            # Just after a reboot the modem reports "off" (or nothing) for about a minute before it
            # redials. Show the last known setting until it catches up.
            return last
        if dial is None:
            return bool(sim.get("data_up")) if last is None else last
        return dial

    def remember_data(self):
        """Keep the last real setting in config.json so the switch is right straight after a reboot."""
        dial = self.g("sims", {}).get("dial")
        if dial is not None and time.time() >= self.boot_until and dial != self.cfg.get("data_last"):
            self.cfg["data_last"] = dial
            self.save()

    def active_sim(self):
        s = self.g("sims", {"cur": "1", "slot2_type": 0, "names": {}, "traffic": {}})
        key = "sim1" if s["cur"] == "1" else ("esim" if s["slot2_type"] == 1 else "sim2")
        name = s["names"].get(s["cur"], "SIM")
        used = s["traffic"].get(s["cur"], 0) / 1e9
        cap = self.cfg["caps"].get(key)
        locked = (s.get("locks", {}).get(s["cur"]) or {}).get("status") in (lib.SIM_PIN_NEEDED, lib.SIM_PUK_NEEDED)
        return {"key": key, "name": name, "slot": {"sim1": "SIM1", "sim2": "SIM2", "esim": "eSIM"}[key], "locked": locked,
                "used": used, "cap": cap, "pct": min(1.0, used / cap) if cap else 0.0}

    # ---- drawing primitives ----
    def btn(self, box, fn):
        self.hits.append((box, fn))

    _text_cache = {}

    def t(self, xy, s, f, fill=FG, anchor="la"):
        """Draw text. Most of a frame's text is identical to the previous frame's, and rasterizing it was ~75% of
        render time, so the glyph mask is cached per (text, font, anchor) and pasted (RGB surfaces only)."""
        s = str(s)
        img = getattr(self.d, "_image", None)
        if img is None or img.mode != "RGB" or not s:
            self.d.text(xy, s, font=f, fill=fill, anchor=anchor)
            return
        key = (s, f, anchor)
        hit = App._text_cache.get(key)
        if hit is None:
            x0, y0, x1, y1 = f.getbbox(s, anchor=anchor)
            w, h = max(1, x1 - x0 + 2), max(1, y1 - y0 + 2)
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).text((-x0 + 1, -y0 + 1), s, font=f, fill=255, anchor=anchor)
            if len(App._text_cache) > 3000:
                App._text_cache.clear()
            hit = App._text_cache[key] = (mask, x0 - 1, y0 - 1)
        mask, ox, oy = hit
        px, py = int(round(xy[0])) + ox, int(round(xy[1])) + oy
        img.paste(fill, (px, py, px + mask.width, py + mask.height), mask)

    def fit(self, s, f, w):
        return lib.truncate_to_width(self.d, str(s), f, w)

    def card(self, box, fill=SURF, edge=EDGE, r=10):
        self.d.rounded_rectangle(box, radius=r, fill=fill, outline=edge, width=1)

    def bar(self, x0, y0, x1, pct, h=5):
        self.d.rounded_rectangle((x0, y0, x1, y0 + h), radius=h // 2, fill=KEY)
        if pct > 0:
            self.d.rounded_rectangle((x0, y0, x0 + max(h, int((x1 - x0) * min(1, pct))), y0 + h), radius=h // 2, fill=TEAL)

    def chip(self, xr, y, s, kind="teal", anchor_right=True):
        bg, fg = {"teal": (CHIPBG, CHIPFG), "warn": (WARNBG, WARNFG), "gray": (GRAYBG, GRAYFG)}[kind]
        f = F(9, "b")
        w = int(self.d.textlength(s, font=f)) + 10
        x0 = xr - w if anchor_right else xr
        self.d.rounded_rectangle((x0, y, x0 + w, y + 15), radius=7, fill=bg)
        self.t((x0 + w / 2, y + 8), s, f, fg, "mm")
        return w

    def toggle(self, xr, cy, on):
        x0 = xr - 34
        self.d.rounded_rectangle((x0, cy - 10, xr, cy + 10), radius=10, fill=TEAL2 if on else TGOFF)
        kx = x0 + 17 if on else x0 + 3
        self.d.ellipse((kx, cy - 7, kx + 14, cy + 7), fill=(255, 255, 255) if on else KNOB)

    def chevron(self, x, cy, color=FG, left=True, s=5):
        if left:
            self.d.line([(x + s, cy - s * 1.4), (x, cy), (x + s, cy + s * 1.4)], fill=color, width=2, joint="curve")
        else:
            self.d.line([(x - s * 1.4, cy + s * 0.7), (x, cy - s * 0.7), (x + s * 1.4, cy + s * 0.7)],
                        fill=color, width=2, joint="curve")

    def spinner(self, cx, cy, r=13):
        ph = (time.time() * 300) % 360
        self.d.arc((cx - r, cy - r, cx + r, cy + r), 0, 360, fill=TGOFF, width=3)
        self.d.arc((cx - r, cy - r, cx + r, cy + r), ph, ph + 100, fill=TEAL, width=3)

    def bars(self, x, yb, n):
        for i in range(4):
            h = 3 + i * 2
            self.d.rounded_rectangle((x + i * 3, yb - h, x + i * 3 + 2, yb), radius=1, fill=CLOUD if i < n else (58, 66, 78))

    def battery(self, xr, cy):
        b = lib.get_battery()
        if not b:
            return xr
        pct, chg = b
        x0 = xr - 25
        self.d.rounded_rectangle((x0, cy - 6, x0 + 22, cy + 5), radius=3, outline=CLOUD, width=1)
        self.d.rectangle((x0 + 22, cy - 2, x0 + 24, cy + 1), fill=CLOUD)
        self.t((x0 + 11, cy), str(pct), F(8, "b"), WARNFG if chg else FG, "mm")
        return x0

    def wx_icon(self, cx, cy, code, s=1.0):
        kind = lib.wmo_info(code)[1] if code is not None else "cloud"
        d = self.d
        if kind in ("sun", "cloud_sun"):
            ox = -5 * s if kind == "cloud_sun" else 0
            r = 6 * s if kind == "cloud_sun" else 8 * s
            d.ellipse((cx + ox - r, cy - 4 * s - r, cx + ox + r, cy - 4 * s + r), outline=SUN, width=2)
            if kind == "sun":
                return
        cy2 = cy + 2 * s
        d.ellipse((cx - 11 * s, cy2 - 5 * s, cx - 1 * s, cy2 + 5 * s), fill=BG, outline=CLOUD, width=2)
        d.ellipse((cx - 5 * s, cy2 - 10 * s, cx + 7 * s, cy2 + 3 * s), fill=BG, outline=CLOUD, width=2)
        d.ellipse((cx + 1 * s, cy2 - 5 * s, cx + 11 * s, cy2 + 5 * s), fill=BG, outline=CLOUD, width=2)
        d.rectangle((cx - 6 * s, cy2 - 1 * s, cx + 6 * s, cy2 + 4 * s), fill=BG)
        d.line([(cx - 6 * s, cy2 + 5 * s), (cx + 6 * s, cy2 + 5 * s)], fill=CLOUD, width=2)
        if kind == "rain":
            for i in (-5, 0, 5):
                d.line([(cx + i * s, cy2 + 8 * s), (cx + (i - 2) * s, cy2 + 13 * s)], fill=RAIN, width=2)
        elif kind == "storm":
            d.line([(cx + 1 * s, cy2 + 7 * s), (cx - 2 * s, cy2 + 11 * s), (cx + 2 * s, cy2 + 11 * s),
                    (cx - 1 * s, cy2 + 15 * s)], fill=SUN, width=2)
        elif kind == "snow":
            for i in (-5, 0, 5):
                d.ellipse((cx + i * s - 1.5, cy2 + 9 * s, cx + i * s + 1.5, cy2 + 12 * s), fill=CLOUD)

    # ---- chrome ----
    def status_icons(self, xr, cy):
        """Small icons right-to-left, left of the battery, for each feature that is on. Returns the new left edge."""
        d, sim, rep = self.d, self.g("sim", {}), self.g("rep", {})
        on = []
        if self.cfg["pass_on"] and self.cfg["pin"]:
            on.append("lock")
        if self.g("wga"):
            on.append("vpn")
        agh = self.g("agh") or {}
        if agh.get("enabled") and agh.get("dns"):
            on.append("adblock")
        if rep.get("connected"):
            on.append("wifi")
        if sim.get("airplane"):
            on.append("plane")
        else:
            if sim.get("data_up"):
                on.append("data")
            if sim.get("roaming") and sim.get("data_up"):
                on.append("roam")
        for k in on:
            x = xr - 11
            c = TEAL if k == "vpn" else CLOUD
            if k == "lock":
                d.rounded_rectangle((x + 1, cy - 1, x + 9, cy + 5), radius=1, fill=c)
                d.arc((x + 2, cy - 7, x + 8, cy + 1), 180, 360, fill=c, width=2)
            elif k == "vpn":
                d.polygon([(x + 5, cy - 6), (x + 10, cy - 4), (x + 9, cy + 2), (x + 5, cy + 6), (x + 1, cy + 2), (x, cy - 4)], fill=c)
            elif k == "wifi":
                for r in (6, 3):
                    d.arc((x + 5 - r, cy + 4 - r, x + 5 + r, cy + 4 + r), 225, 315, fill=c, width=2)
                d.ellipse((x + 4, cy + 3, x + 6, cy + 5), fill=c)
            elif k == "data":
                d.line([(x + 3, cy + 5), (x + 3, cy - 5)], fill=c, width=2)
                d.polygon([(x, cy - 2), (x + 3, cy - 6), (x + 6, cy - 2)], fill=c)
                d.line([(x + 8, cy - 5), (x + 8, cy + 5)], fill=c, width=2)
                d.polygon([(x + 5, cy + 2), (x + 8, cy + 6), (x + 11, cy + 2)], fill=c)
            elif k == "adblock":
                d.ellipse((x, cy - 5, x + 10, cy + 5), outline=c, width=2)
                d.line([(x + 2, cy + 3), (x + 8, cy - 3)], fill=c, width=2)
            elif k == "roam":
                d.rounded_rectangle((x, cy - 6, x + 10, cy + 6), radius=2, outline=c, width=1)
                self.t((x + 5, cy), "R", lib.font(_FN["b"], 9), c, "mm")
            elif k == "plane":
                d.line([(x + 5, cy - 6), (x + 5, cy + 6)], fill=c, width=2)
                d.polygon([(x, cy + 1), (x + 5, cy - 2), (x + 10, cy + 1)], fill=c)
                d.line([(x + 3, cy + 6), (x + 7, cy + 6)], fill=c, width=2)
            xr -= 14
        return xr

    def status_bar(self):
        sim = self.g("sim", {})
        cell = self.g("cell", {})
        n, tech = lib.get_cell_signal(cell) if cell else (0, "")
        if sim.get("airplane"):
            n, tech = 0, "Airplane"
        xr = self.status_icons(self.battery(W - 8, 11) - 4, 11)
        self.bars(10, 15, n or 0)
        x = 26
        f = F(10, "s")
        tech = tech or "No signal"
        self.t((x, 11), tech, f, CLOUD, "lm")
        x += self.d.textlength(tech, font=f) + 5
        if not sim.get("airplane") and xr - x > 20:
            self.t((x, 11), self.fit(self.active_sim()["name"], f, xr - x - 4), f, DIM, "lm")

    def header(self, title, back=None):
        self.btn((0, 22, 44, 56), back or self.back)
        self.chevron(17, 39)
        self.t((44, 39), title, F(14, "b"), FG, "lm")

    def tabbar(self):
        y0 = 276
        self.d.rectangle((0, y0, W, H), fill=TABBG)
        self.d.line([(0, y0), (W, y0)], fill=(34, 40, 51))
        cur = self.view if self.view in TABS else ("vpn" if self.view in ("vpn_loc", "vpn_opts") else
                                                   "wifi" if self.view in ("join", "share", "saved", "saved_net") else
                                                   "sim" if self.view in ("sim_detail", "sim_info", "failover", "sim_unlock", "esim", "bands") else "more")
        labels = {"home": "Home", "sim": "SIM", "wifi": "Wi-Fi", "vpn": "VPN", "more": "More"}
        for i, k in enumerate(TABS):
            x0 = i * 48
            col = TEAL if k == cur else TABDIM
            cx, cy = x0 + 24, y0 + 16
            d = self.d
            if k == "home":
                d.line([(cx - 7, cy), (cx, cy - 6), (cx + 7, cy)], fill=col, width=2)
                d.rectangle((cx - 5, cy - 1, cx + 5, cy + 7), outline=col, width=2)
            elif k == "sim":
                d.polygon([(cx - 5, cy - 8), (cx + 2, cy - 8), (cx + 6, cy - 4), (cx + 6, cy + 8), (cx - 5, cy + 8)], outline=col, width=2)
                d.rectangle((cx - 2, cy - 1, cx + 3, cy + 4), outline=col, width=1)
            elif k == "wifi":
                for r in (9, 6, 3):
                    d.arc((cx - r, cy + 4 - r, cx + r, cy + 4 + r), 225, 315, fill=col, width=2)
                d.ellipse((cx - 1.5, cy + 3, cx + 1.5, cy + 6), fill=col)
            elif k == "vpn":
                d.polygon([(cx, cy - 8), (cx + 7, cy - 5), (cx + 6, cy + 3), (cx, cy + 8), (cx - 6, cy + 3), (cx - 7, cy - 5)], outline=col, width=2)
            else:
                for dx, dy in ((-7, -7), (1, -7), (-7, 1), (1, 1)):
                    d.rounded_rectangle((cx + dx, cy + dy, cx + dx + 6, cy + dy + 6), radius=1, outline=col, width=2)
                if self.unread() or self.fw_prompt():
                    d.ellipse((cx + 6, cy - 11, cx + 11, cy - 6), fill=WARN)
            self.t((cx, y0 + 34), labels[k], F(9, "s"), col, "mm")
            self.btn((x0, y0, x0 + 48, H), lambda k=k: self.tab(k))

    # ---- row list engine ----
    def row_h(self, r):
        k = r[0]
        if k == "note":
            return 8 + 12 * len(wrap(self.d, r[1], F(9), W - 24))
        if k == "para":
            return 8 + 16 * len(wrap(self.d, r[1], F(12), W - 24))
        if k == "bands":  # a title line, then the band chips four to a row
            return 28 + 28 * -(-len(r[2]) // 4) + 4
        return {"head": 22, "seg": 54, "btn": 46, "btn3": 46, "tiles": 48, "msg": 40, "gap": r[1] if len(r) > 1 else 8}.get(k, 36)

    def draw_row(self, d, y, r, hits):
        k, X0, X1 = r[0], 10, W - 10
        if k == "head":
            self.t((X0 + 2, y + 14), r[1].upper(), F(9, "s"), DIM, "lm")
        elif k in ("link", "toggle", "value"):
            label, span = r[1], X1 - X0 - 4
            if k == "link":
                val = self.fit(r[2] or "", F(10), 110)
                vw = d.textlength(val, font=F(10)) + (14 if val else 4)
                tag = r[4] if len(r) > 4 else ""  # small gray chip after the label (Wi-Fi band on Join)
                tw = d.textlength(tag, font=F(9, "b")) + 16 if tag else 0
                lbl = self.fit(label, F(12), span - vw - 16 - tw)
                self.t((X0 + 2, y + 18), lbl, F(12), FG, "lm")
                if tag:
                    self.chip(X0 + 8 + d.textlength(lbl, font=F(12)), y + 10, tag, "gray", anchor_right=False)
                self.t((X1 - 2, y + 18), "›", F(12), DIM, "rm")
                self.t((X1 - 14, y + 18), val, F(10), DIM, "rm")
                hits.append(((0, y, W, y + 36), r[3]))
            elif k == "toggle":
                self.t((X0 + 2, y + 18), self.fit(label, F(12), span - 46), F(12), FG, "lm")
                if len(r) > 4 and r[4]:  # change still applying: spinner instead of the switch
                    self.spinner(X1 - 19, y + 18, 9)
                else:
                    self.toggle(X1 - 2, y + 18, r[2])
                hits.append(((0, y, W, y + 36), r[3]))
            else:
                avail = max(140, span - d.textlength(label, font=F(12)) - 10)
                vf = next((f for f in (F(11, "b"), F(10, "b")) if d.textlength(r[2], font=f) <= avail), F(9, "b"))  # long identifiers (ICCID) step down to fit in full
                val = self.fit(r[2], vf, avail)
                vw = d.textlength(val, font=vf)
                self.t((X0 + 2, y + 18), self.fit(label, F(12), span - vw - 12), F(12), FG, "lm")
                self.t((X1 - 2, y + 18), val, vf, FG, "rm")
            d.line([(X0, y + 35), (X1, y + 35)], fill=DIV)
        elif k == "swatch":  # a color dot, its name and a check on the one in use
            _, label, rgb, on, fn = r
            d.ellipse((X0 + 4, y + 8, X0 + 24, y + 28), fill=rgb or SURF, outline=EDGE if rgb else (74, 83, 97), width=1)
            self.t((X0 + 34, y + 18), label, F(12), FG, "lm")
            if on:
                self.t((X1 - 2, y + 18), "✓", F(12, "b"), TEAL, "rm")
            else:
                self.t((X1 - 2, y + 18), "›", F(12), DIM, "rm")
            d.line([(X0, y + 35), (X1, y + 35)], fill=DIV)
            hits.append(((0, y, W, y + 36), fn))
        elif k == "bands":
            _, label, sup, picked, prefix, flip, flip_all, warn = r
            self.t((X0 + 2, y + 14), label, F(11, "b"), FG, "lm")
            if warn:
                self.chip(X0 + 8 + d.textlength(label, font=F(11, "b")), y + 6, "pick one", "warn", anchor_right=False)
            all_on = bool(sup) and len(picked) == len(sup)
            self.t((X1 - 2, y + 14), "None" if all_on else "All", F(10, "b"), TEAL, "rm")
            hits.append(((X1 - 50, y, X1, y + 26), flip_all))
            cw = (X1 - X0 - 12) / 4
            for i, b in enumerate(sup):
                bx, by = X0 + (i % 4) * (cw + 4), y + 28 + (i // 4) * 28
                on = b in picked
                d.rounded_rectangle((bx, by, bx + cw, by + 24), radius=7, fill=CHIPBG if on else SURF, outline=TEAL2 if on else EDGE)
                self.t((bx + cw / 2, by + 12), f"{prefix}{b}", F(10, "b"), CHIPFG if on else DIM, "mm")
                hits.append(((bx, by, bx + cw, by + 24), lambda b=b: flip(b)))
        elif k == "seg":
            _, label, opts, sel, fn = r
            self.t((X0 + 2, y + 11), label, F(11), FG, "lm")
            self.card((X0, y + 22, X1, y + 48), r=8)
            w = (X1 - X0 - 4) / len(opts)
            for i, o in enumerate(opts):
                bx = X0 + 2 + i * w
                if o == sel:
                    d.rounded_rectangle((bx, y + 24, bx + w, y + 46), radius=6, fill=TGOFF)
                self.t((bx + w / 2, y + 35), o, F(10, "s"), FG if o == sel else DIM, "mm")
                hits.append(((bx, y + 22, bx + w, y + 48), lambda o=o: fn(o)))
            d.line([(X0, y + 53), (X1, y + 53)], fill=DIV)
        elif k in ("note", "para"):
            f, lh, col = (F(9), 12, DIM) if k == "note" else (F(12), 16, FG)
            for i, line in enumerate(wrap(d, r[1], f, W - 24)):
                self.t((X0 + 2, y + 4 + i * lh), line, f, col)
        elif k == "btn":
            _, label, fn, style = r
            edge, fill, col = {"pri": (TEAL2, TEAL2, ON_ACCENT), "danger": (REDLINE, None, RED)}.get(style, ((57, 66, 79), None, FG))
            d.rounded_rectangle((X0, y + 6, X1, y + 40), radius=10, outline=edge, fill=fill, width=1)
            self.t((W / 2, y + 23), label, F(12, "b"), col, "mm")
            hits.append(((X0, y + 6, X1, y + 40), fn))
        elif k == "btn3":
            items = r[1]
            w = (X1 - X0 - 12) / 3
            for i, (label, fn, style) in enumerate(items):
                bx = X0 + i * (w + 6)
                edge, col = (REDLINE, RED) if style == "danger" else ((57, 66, 79), FG)
                d.rounded_rectangle((bx, y + 6, bx + w, y + 40), radius=10, outline=edge, width=1)
                self.t((bx + w / 2, y + 23), label, F(10, "b"), col, "mm")
                hits.append(((bx, y + 6, bx + w, y + 40), fn))
        elif k == "tiles":
            w = (X1 - X0 - 6) / 2
            for i, (title, sub, fn) in enumerate(r[1]):
                bx = X0 + i * (w + 6)
                self.card((bx, y + 3, bx + w, y + 45))
                self.t((bx + 10, y + 17), title, F(11, "s"), FG, "lm")
                self.t((bx + 10, y + 32), self.fit(sub, F(9), w - 16), F(9), DIM, "lm")
                hits.append(((bx, y + 3, bx + w, y + 45), fn))
        elif k == "msg":
            _, frm, preview, tag, unread, fn = r
            self.t((X0 + 2, y + 12), self.fit(frm, F(11, "b"), 140), F(11, "b"), FG, "lm")
            xr = X1 - 2
            xr -= self.chip(xr, y + 4, tag, "gray") + 4
            if unread:
                d.ellipse((xr - 6, y + 9, xr, y + 15), fill=WARN)
            self.t((X0 + 2, y + 28), self.fit(preview, F(10), W - 24), F(10), DIM, "lm")
            d.line([(X0, y + 39), (X1, y + 39)], fill=DIV)
            hits.append(((0, y, W, y + 40), fn))

    def rows(self, y0, y1, rows, key=None):
        key = key or self.view
        y1 = min(y1, getattr(self, "content_bottom", H))
        hs = [self.row_h(r) for r in rows]
        total = sum(hs)
        span = y1 - y0
        maxoff = max(0, total - span)
        off = self.scroll.get(key, 0)
        if self.drag_key == key:
            off -= self.drag_dy
        off = int(max(0, min(maxoff, off)))
        layer = Image.new("RGB", (W, max(span, total)), BG)
        saved = self.d
        self.d = ImageDraw.Draw(layer)
        hits, y = [], 0
        for r, h in zip(rows, hs):
            if y + h >= off and y <= off + span:
                self.draw_row(self.d, y, r, hits)
            y += h
        self.d = saved
        self.img.paste(layer.crop((0, off, W, off + span)), (0, y0))
        for (x0, ya, x1, yb), fn in hits:
            ya, yb = ya - off + y0, yb - off + y0
            if yb > y0 and ya < y1:
                self.btn((x0, max(ya, y0), x1, min(yb, y1)), fn)
        if maxoff:
            th = max(20, span * span / total)
            ty = y0 + (span - th) * off / maxoff
            self.d.rounded_rectangle((W - 4, ty, W - 2, ty + th), radius=1, fill=(60, 68, 80))
        sh = getattr(self, "yshift", 0)
        self.scroll_area = (key, y0 + sh, y1 + sh, maxoff)
        self.scroll[key] = self.scroll.get(key, 0)

    # ---- screens ----
    def v_home(self):
        tm, ap = self.tfmt(self.home_zone())
        f = F(38, "b")
        self.t((10, 54), tm, f, FG, "ls")
        if ap:
            self.t((14 + self.d.textlength(tm, font=f), 54), ap, F(12, "b"), DIM, "ls")
        y = 60
        self.t((10, y), datetime.now(self.home_zone()).strftime("%A, %b %-d"), F(11), DIM)
        y += 15
        if self.cfg["two_clocks"]:
            n, tz = self.cfg["clock2"]
            t2, a2 = self.tfmt(tz)
            self.t((10, y), f"{n} ", F(10), DIM)
            self.t((10 + self.d.textlength(n + " ", font=F(10)), y), f"{t2} {a2}".strip(), F(10, "b"), FG)
            y += 13
        if self.cfg["sig"]:
            self.t((10, y), self.fit(self.cfg["sig"], F(10, "s"), 150), F(10, "s"), TEAL)
        wx = self.g("wx")
        self.wx_icon(W - 26, 42, wx["code"] if wx else None)
        self.t((W - 10, 74), f"{round(wx['now'])}°" if wx else "--°", F(15, "b"), FG, "rs")
        self.t((W - 10, 86), self.fit(self.cfg["city"]["name"], F(9), 80), F(9), DIM, "rm")
        self.btn((150, 22, W, 94), lambda: self.go("weather"))
        a = self.active_sim()
        self.card((10, 100, W - 10, 154))
        self.t((20, 114), a["name"], F(13, "b"), FG, "lm")
        self.t((24 + self.d.textlength(a["name"], font=F(13, "b")), 115),
               a["slot"] + (" · locked" if a["locked"] else "" if self.data_on() else " · data off"), F(10), DIM, "lm")
        self.chip(W - 20, 107, lib.get_wan_conn_type(self.g("cell", {})) or "Offline")
        self.t((20, 132), f"{a['used']:.1f} GB used", F(10), FG, "lm")
        self.t((W - 20, 132), f"of {a['cap']} GB" if a["cap"] else "no cap set", F(10), DIM, "rm")
        self.bar(20, 141, W - 20, a["pct"])
        self.btn((10, 100, W - 10, 154), lambda: self.tab("sim"))
        cl = self.g("clients", [])
        self.card((10, 160, 117, 206))
        self.t((19, 171), "DEVICES", F(9, "s"), DIM, "lm")
        self.t((19, 192), str(sum(1 for c in cl if c["online"])), F(16, "b"), FG, "lm")
        self.t((19 + self.d.textlength(str(sum(1 for c in cl if c["online"])), font=F(16, "b")) + 4, 194), "online", F(10), DIM, "lm")
        self.btn((10, 160, 117, 206), lambda: self.open_set("clients"))
        self.card((123, 160, W - 10, 206))
        self.t((132, 171), "SPEED", F(9, "s"), DIM, "lm")
        self.t((132, 188), f"↓ {self.mon['down']:.1f}", F(11, "b"), FG, "lm")
        self.t((185, 188), f"↑ {self.mon['up']:.1f}", F(11), DIM, "lm")
        self.t((132, 200), "Mbps", F(8), DIM, "lm")
        self.btn((123, 160, W - 10, 206), lambda: self.go("monitor"))
        wga = self.g("wga")
        self.card((10, 212, 117, 244))
        self.t((20, 228), self.fit("VPN · " + vpn_label(self.peer_name(wga)).split(" · ")[0] if wga else "VPN off", F(11, "s"), 90), F(11, "s"), FG, "lm")
        self.btn((10, 212, 117, 244), lambda: self.tab("vpn"))
        self.card((123, 212, W - 10, 244))
        self.t((141, 228), "Texts", F(11, "s"), FG, "lm")
        u = len(self.unread())
        if u:
            self.chip(W - 18, 221, f"{u} new", "warn")
        self.btn((123, 212, W - 10, 244), lambda: self.go("texts"))

    def peer_name(self, pid):
        for p in self.g("wgp", []):
            if p["id"] == pid:
                return p["name"]
        return pid or ""

    def v_sim(self):
        self.header("Mobile", lambda: self.tab("home"))
        s = self.g("sims", {"cur": "1", "slot2_type": 0, "names": {}, "traffic": {}})
        cur = "sim1" if s["cur"] == "1" else ("esim" if s["slot2_type"] == 1 else "sim2")
        names = s["names"]
        sim = self.g("sim", {})
        data_on = self.data_on()
        self.rows(56, 92, [("toggle", "Mobile data", data_on, self.toggle_data)], "sim_data")
        rows = [("sim1", names.get("1", "SIM1"), "SIM1", "1"),
                ("sim2", names.get("2", "SIM2") if s["slot2_type"] == 0 else "SIM2", "SIM2", "2"),
                ("esim", names.get("2", "eSIM") if s["slot2_type"] == 1 else "eSIM", "eSIM · slot 2", "2")]
        y = 94
        for key, name, kind, slot in rows:
            on = key == cur and data_on  # with mobile data off, no carrier is in use
            active_type = (key == "sim1") or (key == "sim2" and s["slot2_type"] == 0) or (key == "esim" and s["slot2_type"] == 1)
            self.card((10, y, W - 10, y + 38), fill=TEALBG if on else SURF, edge=TEAL2 if on else EDGE)
            self.d.ellipse((20, y + 12, 34, y + 26), outline=TEAL if on else (74, 83, 97), width=2)
            if on:
                self.d.ellipse((24, y + 16, 30, y + 22), fill=TEAL)
            busy = not on and not active_type
            lk = (s.get("locks") or {}).get(slot) or {}
            locked = active_type and lk.get("status") in (lib.SIM_PIN_NEEDED, lib.SIM_PUK_NEEDED)
            cw = self.chip(W - 18, y + 5, "Locked ›" if locked else "In use ›" if on else ("Slot 2 busy" if busy else "Ready"),
                           "warn" if locked else "teal" if on else "gray")
            nm = self.fit(name, F(12, "b"), 80)
            self.t((42, y + 13), nm, F(12, "b"), FG, "lm")
            if kind != name:  # "SIM2 SIM2" when the SIM has no carrier name
                self.t((46 + self.d.textlength(nm, font=F(12, "b")), y + 14),
                       self.fit(kind, F(9), W - 18 - cw - 52 - self.d.textlength(nm, font=F(12, "b"))), F(9), DIM, "lm")
            cap = self.cfg["caps"].get(key)
            used = s["traffic"].get(slot, 0) / 1e9 if active_type else 0
            phone = fmt_phone(s.get("phones", {}).get(slot)) if active_type else ""
            usage = (f"{used:.1f} / {cap} GB" if cap else f"{used:.1f} GB used") if phone else \
                (f"{used:.1f} of {cap} GB this month" if cap else f"{used:.1f} GB this month")
            line = (f"{phone} · {usage}" if phone else usage) if active_type else \
                "Turns SIM2 off when used" if key == "esim" else "Turns eSIM off when used" if key == "sim2" else ""
            self.t((42, y + 28), self.fit(line, F(9), W - 60), F(9), DIM, "lm")
            if locked:
                fn = lambda sl=int(slot), k=key: self.open_unlock(sl, k)
            elif on:
                fn = lambda: self.go("sim_detail")
            elif not data_on:
                fn = lambda k=key, n=name: self.ask_data_with(k, n, k == cur)
            else:
                fn = lambda k=key, n=name: self.ask_switch(k, n)
            self.btn((10, y, W - 10, y + 38), fn)
            y += 41
        note = "Mobile data is off. Tap a SIM to use it." if not data_on else "SIM2 and eSIM share slot 2: one at a time."
        self.t((12, y + 2), self.fit(note, F(9), W - 24), F(9), DIM)
        fo = self.g("failover")
        self.rows(y + 15, 276, [("toggle", "Data roaming", sim.get("roaming", False), self.toggle_roam),
                                ("link", "SIM failover", ("On" if fo.get("enable_switch") else "Off") if fo else "", lambda: self.go("failover")),
                                ("link", "eSIM information", "", self.open_esim)],
                  "sim_rows")

    SIM_LABELS = {"sim1": "SIM1", "sim2": "SIM2", "esim": "eSIM"}

    def open_unlock(self, slot, key):
        self.sel["unlock_slot"], self.sel["unlock_name"] = slot, self.SIM_LABELS.get(key, f"SIM{slot}")
        self.go("sim_unlock")

    @staticmethod
    def pin_tips(count):
        """What the stock Unlock dialog says about attempts left (unknown = the generic warning)."""
        if isinstance(count, int) and count > 1:
            return f"{count} attempts remaining."
        if count == 1:
            return "Last attempt before the SIM locks and needs its PUK code from a phone."
        return "A SIM locks after 3 wrong PINs."

    def v_sim_unlock(self):
        """Stock "SIM n Unlock": enter the SIM's PIN. Safety first: a wrong PIN can lock the SIM, so it only ever sends one PIN per tap, only
        while the SIM is really asking for it, always with the attempts left in view."""
        slot, name = self.sel.get("unlock_slot", 1), self.sel.get("unlock_name", "SIM")
        self.header(f"{name} unlock")
        lk = (self.g("sims", {}).get("locks") or {}).get(str(slot)) or {}
        st, count = lk.get("status"), lk.get("pin_counter")
        if st == lib.SIM_PUK_NEEDED:
            self.rows(56, H, [("note", f"{name} is locked because a wrong PIN was entered too many times. Unlock it with its PUK code on a phone.")])
            return
        if st != lib.SIM_PIN_NEEDED:
            self.rows(56, H, [("note", f"{name} isn't asking for a PIN.")])
            return

        def got_pin(pin):
            if not (pin.isdigit() and 4 <= len(pin) <= 8):
                self.say("A PIN is 4 to 8 digits")
                return
            last = count == 1
            body = self.pin_tips(count) + (" A wrong PIN locks the SIM until you enter its PUK code on a phone." if last else " A wrong PIN uses one attempt.")
            self.confirm(f"Unlock {name}?", body, "Try PIN",
                         lambda: self.work("Unlocking SIM", lambda: self.run_unlock(slot, name, pin), ("sims", "sim", "cell"), self.sims_refresh), True)

        def enter():
            self.open_kb("pin", f"{name} PIN", "", 8, got_pin, min_len=4)
            self.kb["digits"] = True
        self.rows(56, H, [("note", f"{name} is locked. Enter its PIN to use it. {self.pin_tips(count)}"),
                          ("btn", "Enter PIN", enter, "pri")])

    def sims_refresh(self):
        self.r.put("sims", get_sims())

    def run_unlock(self, slot, name, pin):
        """Send the PIN once. Re-reads the SIM's state first (must still be asking for a PIN) and afterwards (attempts left)."""
        before = lib.get_sim_locks().get(slot) or {}
        if before.get("status") != lib.SIM_PIN_NEEDED or not before.get("iccid"):
            raise RuntimeError("SIM isn't asking for a PIN")
        ok, body = lib.unlock_sim_pin(before.get("bus") or "cpu", before["iccid"], pin)
        if ok:
            gone = lib._wait_until(lambda: (lib.get_sim_locks().get(slot) or {}).get("status") not in (lib.SIM_PIN_NEEDED, lib.SIM_PUK_NEEDED), 30, poll=2)
            self.say(f"{name} unlocked" if gone else "PIN sent. Waiting for the SIM")
            return
        after = lib.get_sim_locks().get(slot) or {}
        err = body if isinstance(body, dict) else {}
        code = err.get("err_code") or err.get("code") or (err.get("error") or {}).get("code")
        n0, n1 = before.get("pin_counter"), after.get("pin_counter")
        wrong = code == 20002022 or (isinstance(n0, int) and isinstance(n1, int) and n1 < n0)
        if after.get("status") == lib.SIM_PUK_NEEDED:
            self.say("Wrong PIN. The SIM is now locked.")
        elif wrong:
            self.say(f"Wrong PIN. {n1} left." if isinstance(n1, int) else "Wrong PIN. Try again.")
        else:
            self.say("Couldn't unlock. Try again later.")

    def open_esim(self):
        self.go("esim")
        self.load_esim()

    def load_esim(self):
        """Read the eSIM in the background (the helper can take a minute, or refuse while the card isn't ready). Only when asked: never polled."""
        st = self.sel["esim"] = {"state": "loading"}

        def run():
            try:
                st.update(state="ok", info=lib.get_esim_info())
            except lib.EsimUnavailable as e:
                st.update(state="error", msg=str(e))
            except Exception:
                st.update(state="error", msg="The router couldn't read the eSIM.")
            self.dirty = True
        threading.Thread(target=run, daemon=True).start()
        self.dirty = True

    def v_esim(self):
        """Read-only eSIM information, the stock "eSIM Information" fields: EID, ICCID, IMSI, card OS version, free storage, profile count and list."""
        self.header("eSIM information")
        st = self.sel.get("esim") or {"state": "loading"}
        if (self.g("sims", {}).get("slot2_type")) != 1:
            self.rows(56, H, [("note", "Slot 2 is set to a physical SIM. Switch it to the eSIM (SIM tab) to see eSIM information.")])
            return
        if st["state"] == "loading":
            self.spinner(W // 2, 120, 14)
            self.t((W / 2, 156), "Reading the eSIM…", F(12, "b"), FG, "mm")
            self.t((W / 2, 174), "This can take up to a minute.", F(10), DIM, "mm")
            return
        if st["state"] == "error":
            self.rows(56, H, [("note", st.get("msg") or "The router couldn't read the eSIM."), ("btn", "Try again", self.load_esim, "pri")])
            return
        i = st["info"]
        rows = [("head", "Current eSIM"), ("note", "EID " + (i["eid"] or "—")), ("value", "ICCID", i["iccid"] or "—"), ("value", "IMSI", i["imsi"] or "—"),
                ("value", "OS version", i["cos"] or "—"),
                ("value", "Free storage", f"{i['free_kb']} KB / {lib.ESIM_TOTAL_KB} KB" if i.get("free_kb") is not None else "—"),
                ("value", "Profiles", str(i["count"])), ("head", "Profiles")]
        for p in i["profiles"]:
            rows.append(("value", p["name"] or p["supplier"] or "Profile", "Enabled" if p["enabled"] else "Off"))
            rows.append(("note", f"{p['supplier'] or 'Unknown supplier'} · {p['iccid']}"))
        if not i["profiles"]:
            rows.append(("note", "No profiles are installed."))
        rows += [("btn", "Refresh", self.load_esim, ""), ("note", "Read-only. Enabling, renaming and deleting profiles is done in the admin panel.")]
        self.rows(56, H, rows)

    def v_sim_info(self):
        """Read-only SIM details for the SIM in use: the stock "SIM n Details & Configs" fields, grouped like the stock page."""
        a = self.active_sim()
        self.header(f"{a['slot']} details")
        d = self.g("siminfo")
        if not d:
            self.rows(56, H, [("note", "Reading SIM details…")])
            return

        def val(label, key, fmt=None):
            v = (fmt(d.get(key)) if fmt and d.get(key) else d.get(key)) or ""
            if len(v) > 26 and key not in ("iccid", "imei"):  # long text (modem firmware) wraps on its own lines instead of being clipped
                return ("note", f"{label}: {v}")
            return ("value", label, v or "—")
        rows = [("head", "SIM"), val("Phone number", "phone", fmt_phone), val("ICCID", "iccid"), val("Network operator", "operator"), val("SIM type", "type"),
                ("head", "Network"), val("Network type", "net_type"), val("Radio", "radio"), val("Data roaming", "roaming"), val("APN", "apn"),
                val("IP address", "ip"), val("Gateway", "gateway"), val("Primary DNS", "dns1"), val("Secondary DNS", "dns2"),
                ("head", "Cellular"), val("Band", "band"), val("Cell ID", "cell_id"), val("TAC", "tac"), val("PCI", "pci"), val("ARFCN", "arfcn"),
                val("RSRP", "rsrp"), val("RSRQ", "rsrq"), val("RSSI", "rssi"), val("SINR", "sinr"),
                ("head", "Modem"), val("Model", "model"), val("Firmware", "firmware"), val("IMEI", "imei"),
                ("note", "Read-only. Network type, APN and the cellular band settings are changed in the admin panel.")]
        self.rows(56, H, rows)

    def open_bands(self):
        """Stock web UI (SIM details > Settings): Network Type and Band Masking for the SIM in use. The page edits a copy; nothing is sent until Apply."""
        self.sel.pop("bands", None)
        self.r.request("bands")
        self.go("bands")

    def v_bands(self):
        self.header("Network & bands")
        st = self.g("bands")
        if not st:
            self.rows(56, H, [("note", "Reading the modem…")])
            return
        if not st["supports"]:
            self.rows(56, H, [("note", "This SIM's modem doesn't support network type or band settings.")])
            return
        if self.sel.get("bands") is None or self.sel["bands"]["slot"] != st["slot"]:
            self.sel["bands"] = {"slot": st["slot"], "enable": st["enable"], "mode": st["mode"], "list": {g: list(v) for g, v in st["list"].items()}}
        b = self.sel["bands"]
        sup = st["supported"]
        warn = lib.band_warnings(b["enable"], b["mode"], b["list"], sup)
        mode_name = {v: n for n, v in lib.NETWORK_MODES}
        names = [n for n, _ in lib.NETWORK_MODES]

        def set_mode(name):
            b["mode"] = dict(lib.NETWORK_MODES)[name]
            self.dirty = True

        def set_enable():
            b["enable"] = not b["enable"]
            if b["enable"] and not any(b["list"].values()):  # stock: switching it on starts with every band ticked
                b["list"] = {g: list(sup[g]) for g in lib.BAND_GROUPS}
            self.dirty = True

        def flip(group, band):
            cur = b["list"][group]
            b["list"][group] = [x for x in cur if x != band] if band in cur else sorted(cur + [band])
            self.dirty = True

        def flip_all(group):
            b["list"][group] = [] if sup[group] and len(b["list"][group]) == len(sup[group]) else list(sup[group])
            self.dirty = True
        rows = [("seg", "Network type", names, mode_name.get(b["mode"], "Auto"), set_mode),
                ("note", "Select 5G for faster speed (requires 5G signal) or 4G for stability."),
                ("toggle", "Band masking", b["enable"], set_enable)]
        if b["enable"]:
            for g, label, prefix in (("NR-SA", "5G NR SA", "n"), ("NR-NSA", "5G NR NSA", "n"), ("LTE", "4G LTE", "B")):
                if sup[g] and not (g != "LTE" and b["mode"] == "LTE"):
                    rows.append(("bands", label, sup[g], b["list"][g], prefix, lambda x, g=g: flip(g, x), lambda g=g: flip_all(g), warn[g]))
            rows.append(("note", "Only the ticked bands are used. Tick at least one allowed band." if any(warn.values()) else
                         "Only the ticked bands are used. To undo, switch Band masking off and apply."))
        same = (b["enable"], b["mode"]) == (st["enable"], st["mode"]) and (not b["enable"] or b["list"] == st["list"])
        can = not any(warn.values()) and not same

        def apply():
            slot, enable, mode, lists = b["slot"], b["enable"], b["mode"], {g: list(v) for g, v in b["list"].items()}

            def run():
                if not lib.set_band_config(slot, enable, mode, lists):
                    raise RuntimeError("The router refused that")
            self.confirm("Apply these network settings?", "Mobile data reconnects for a moment, and devices may lose internet while it does.", "Apply",
                         lambda: self.work("Applying", run, ("bands", "siminfo", "cell", "sim"), lambda: self.sel.pop("bands", None)))
        rows.append(("btn", "Apply", apply if can else (lambda: self.say("Nothing to apply" if same else "Fix the red flags first")), "pri" if can else ""))
        self.rows(56, H, rows)

    def v_failover(self):
        """The stock "SIM Failover" page: switch SIMs automatically, in priority order, with an optional daily switch back to
        the preferred SIM."""
        self.header("SIM failover")
        f, s = self.g("failover"), self.g("sims", {"slot2_type": 0})
        if not f:
            self.rows(56, H, [("note", "Reading SIM failover…")])
            return

        def name(slot):
            return "SIM1" if slot == 1 else ("eSIM" if s.get("slot2_type") == 1 else "SIM2")

        def apply(**changes):
            def run():
                if not lib.set_failover(f, **changes):
                    raise RuntimeError("The router refused that")
            self.work("Saving SIM failover", run, ("failover", "sims", "sim", "cell"),
                      lambda: self.r.put("failover", lib.get_failover()))
        on, timing = bool(f.get("enable_switch")), bool(f.get("enable_timing"))
        order = list(f.get("slot_priority") or [1, 2])
        hhmm = f"{str(f.get('hour') or '00').zfill(2)}:{str(f.get('min') or '00').zfill(2)}"
        mins = max(1, int(f.get("failover_interval") or 300) // 60)
        rows = [("toggle", "Enable", on, lambda: apply(enable_switch=not on)),
                ("note", f"Lets the router switch SIMs by itself if the current one stops working. It checks about every {mins} min.")]
        if on:
            rows += [("head", "Priority"),
                     ("value", "Priority 1", name(order[0])),
                     ("value", "Priority 2", name(order[1]) if len(order) > 1 else "—"),
                     ("btn", "Swap priority", lambda: apply(slot_priority=order[::-1]), "")]
            rows += [("toggle", "Scheduled switch", timing, lambda: apply(enable_timing=not timing))]
            if timing:
                times = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
                if hhmm not in times:
                    times.insert(0, hhmm)
                rows += [("link", "Execution time", hhmm, lambda: self.open_pick(
                    "Execution time", [(t, t) for t in times], hhmm, lambda v: apply(hour=v[:2], min=v[3:])))]
            rows += [("note", "Priority 1 is the preferred SIM. Scheduled switch: the router goes back to it at the chosen time each day.")]
        self.rows(56, H, rows)

    def ask_data_with(self, key, name, same):
        label = {"sim1": "SIM1", "sim2": "SIM2", "esim": "eSIM"}[key]

        def do():
            if not same:
                switch_sim(key)
            set_data(True)
            self.cfg["data_last"] = True
            self.save()
        body = "Turns mobile data on." + ("" if same else " The modem switches SIMs first, which can take up to a minute.")
        self.confirm(f"Use {name} ({label}) for data?", body, "Turn on",
                     lambda: self.work(f"Turning on data with {name}", do, ("sims", "sim", "cell")))

    def ask_switch(self, key, name):
        label = {"sim1": "SIM1", "sim2": "SIM2", "esim": "eSIM"}[key]
        body = ("Your eSIM uses slot 2, so SIM2 turns off. " if key == "esim" else
                "SIM2 uses slot 2, so the eSIM turns off. " if key == "sim2" else "") + \
            "Mobile internet pauses while the modem reconnects (up to a minute)."
        self.confirm(f"Switch to {name} ({label})?", body, "Switch",
                     lambda: self.work(f"Switching to {name}", lambda: switch_sim(key), ("sims", "sim", "cell")))

    def toggle_data(self):
        want = not self.data_on()
        def do():
            set_data(want)
            self.cfg["data_last"] = want
            self.save()
        if want:
            self.work("Turning mobile data on", do, ("sims", "sim", "cell"))
        else:
            self.confirm("Turn mobile data off?", "Texts and calls still work. Devices only get internet from Wi-Fi or Ethernet.",
                         "Turn off", lambda: self.work("Turning mobile data off", do, ("sims", "sim", "cell")), True)

    def toggle_roam(self):
        sim = self.g("sim", {})
        want = not sim.get("roaming", False)
        go = lambda: self.work("Updating roaming", lambda: lib.apply_roaming(sim.get("iccid"), want), ("sim",))
        if want:
            self.confirm("Turn data roaming on?", "Roaming abroad can be expensive, depending on your plan.", "Turn on", go)
        else:
            go()

    def v_sim_detail(self):
        a = self.active_sim()
        self.header(f"{a['name']}  {a['slot']}")
        self.t((12, 66), f"{a['used']:.1f} GB used", F(11, "b"), FG, "lm")
        self.t((W - 12, 66), f"of {a['cap']} GB" if a["cap"] else "no cap set", F(10), DIM, "rm")
        self.bar(12, 76, W - 12, a["pct"])

        def setcap(c):
            self.cfg["caps"][a["key"]] = c
            self.save()
            self.dirty = True
        self.rows(86, H, [("link", "Details & info", "", lambda: (self.r.request("siminfo"), self.go("sim_info"))),
                          ("link", "Network & bands", "", self.open_bands), ("head", "Monthly data cap")] +
                  [("link", f"{c} GB" if c else "No cap", "✓" if self.cfg["caps"].get(a["key"]) == c else "", lambda c=c: setcap(c))
                   for c in CAP_OPTS] + [("note", "Usage is counted from the 1st of each month and kept through reboots. The cap is only shown here; it doesn't cut data off.")])

    def v_wifi(self):
        self.header("Wi-Fi", lambda: self.tab("home"))
        rep = self.g("rep", {})
        self.card((10, 58, W - 10, 108))
        self.t((20, 69), "INTERNET FROM WI-FI", F(9, "s"), DIM, "lm")
        if rep.get("connected"):
            self.t((20, 86), self.fit(rep.get("ssid"), F(13, "b"), 140), F(13, "b"), FG, "lm")
            sig = rep.get("signal") or -100
            self.t((20, 100), "Connected · " + ("strong" if sig > -60 else "fair" if sig > -72 else "weak") + " signal", F(9), DIM, "lm")
        else:
            self.t((20, 88), "Not connected", F(13, "b"), FG, "lm")
        self.d.rounded_rectangle((W - 74, 74, W - 20, 100), radius=8, outline=(57, 66, 79))
        self.t((W - 47, 87), "Change" if rep.get("connected") else "Join", F(10, "s"), FG, "mm")
        self.btn((W - 80, 66, W - 10, 108), self.open_join)
        cl = self.g("clients", [])
        wf = self.g("wifi", {})
        tab = self.sel.get("wifi_tab", "Main")

        def pick_tab(o):
            if o != tab:
                self.sel["wifi_tab"] = o
                self.scroll.pop("wifi_rows", None)
                self.dirty = True
        X0, X1 = 10, W - 10
        self.card((X0, 114, X1, 140), r=8)
        sw = (X1 - X0 - 4) / 2
        for i, o in enumerate(("Main", "Guest")):
            bx = X0 + 2 + i * sw
            if o == tab:
                self.d.rounded_rectangle((bx, 116, bx + sw, 138), radius=6, fill=TGOFF)
            on = wf.get("2g") or wf.get("5g") if o == "Main" else wf.get("g2") or wf.get("g5")
            self.t((bx + sw / 2, 127), o + ("" if on else " · off"), F(10, "s"), FG if o == tab else DIM, "mm")
            self.btn((bx, 112, bx + sw, 142), lambda o=o: pick_tab(o))

        def band(iface, label, guest):
            on = self.wifi_state(iface, "", not guest)[0]
            flip = self.toggle_guest if guest else self.toggle_band
            return [("head", label),
                    ("toggle", "Network", on, lambda: flip(iface, label, self.wifi_state(iface, "", not guest)[0]), iface in self.pending),
                    self.name_row(iface, label, guest),
                    self.pass_row(iface, label, guest),
                    self.hidden_row(iface, label, guest),
                    self.mode_row(iface, label),
                    self.channel_row(iface, label),
                    self.txpower_row(iface, label)]
        if tab == "Main":
            rows = band("wifi2g", "2.4 GHz", False) + band("wifi5g", "5 GHz", False) + [
                ("head", ""),
                ("link", "Share Wi-Fi", "QR code", lambda: (self.sel.__setitem__("share_set", "main"), self.go("share"))),
                *self.band_rows(),
                ("link", "Saved networks", str(len(self.g("savedap", []))), lambda: self.go("saved")),
                ("link", "Devices connected", str(sum(1 for c in cl if c["online"])), lambda: self.open_set("clients"))]
        else:
            rows = band("guest2g", "2.4 GHz", True) + band("guest5g", "5 GHz", True)
            if wf.get("g2") or wf.get("g5"):
                rows += [("head", ""), ("link", "Share guest Wi-Fi", "QR code", lambda: (self.sel.__setitem__("share_set", "guest"), self.go("share")))]
            rows.append(("note", "Guests get internet but can't see your devices or each other. Network mode, channel and TX power are shared with the main Wi-Fi on the same band."))
        self.rows(144, 276, rows, "wifi_rows")

    WIFI_KEYS = {"wifi2g": "2g", "wifi5g": "5g", "guest2g": "g2", "guest5g": "g5"}

    def wifi_state(self, iface, label, default):
        """(on, label) for a Wi-Fi toggle, showing the target state while a change is still applying."""
        if iface in self.pending:
            return self.pending[iface], label
        return self.g("wifi", {}).get(self.WIFI_KEYS[iface], default), label

    def bg_wifi(self, iface, label, want):
        """The router's Wi-Fi reload can take a while; apply it in the background instead of blocking the screen."""
        self.pending[iface] = want
        self.dirty = True

        def run():
            with self.wifi_lock:  # one reload at a time
                try:
                    set_wifi_enabled(iface, want)
                    w = dict(self.g("wifi", {}))
                    w[self.WIFI_KEYS[iface]] = want
                    self.r.put("wifi", w)
                    self.say(f"{label} is {'on' if want else 'off'}")
                except Exception as e:
                    if want and "refused" in str(e):
                        self.confirm(f"Couldn't turn on {label}", "The router's Wi-Fi driver refused this combination of networks. Turn another network off and try again.", "OK", lambda: None)
                    else:
                        self.say(f"Couldn't change {label}")
                finally:
                    self.pending.pop(iface, None)
                    self.r.request("wifi")
                    self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def rename_net(self, ifaces, what, key, name):
        """Rename both bands of a network in the background (one Wi-Fi reload at a time)."""
        name = name.strip()
        if not name:
            return
        self.pending[key] = True
        self.dirty = True

        def run():
            with self.wifi_lock:
                try:
                    rename_wifi(ifaces, name)
                    self.say(f"{what} renamed")
                except Exception:
                    self.say(f"Couldn't rename {what}")
                finally:
                    self.pending.pop(key, None)
                    self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    BAND_RADIO = {"wifi2g": "wifi0", "wifi5g": "wifi1", "guest2g": "wifi0", "guest5g": "wifi1"}

    def ssid(self, iface):
        return lib.uci_get(f"wireless.{iface}.ssid", "")

    def name_row(self, iface, label, guest):
        """'Name' link for one band; renames only that band."""
        key = "name:" + iface
        what = ("Guest " if guest else "") + label + " Wi-Fi"

        def done(name):
            name = name.strip()
            if not name or name == self.ssid(iface):
                return
            act = lambda: self.rename_net([iface], what, key, name)
            if guest:
                act()
            else:
                self.confirm(f"Rename {label} to \"{self.fit(name, F(10), 130)}\"?",
                             f"Devices on {label} disconnect and have to join the new name. The password stays the same.",
                             "Rename", act, True)
        return ("link", "Name", "Renaming…" if self.pending.get(key) else (self.ssid(iface) or "—"),
                lambda: None if self.pending.get(key) else self.open_kb("ssid", f"{what} name", self.ssid(iface), 32, done, min_len=1))

    def change_key(self, ifaces, what, key, pw):
        """Change the password of one network in the background (one Wi-Fi reload at a time)."""
        self.pending[key] = True
        self.dirty = True

        def run():
            with self.wifi_lock:
                try:
                    set_wifi_key(ifaces, pw)
                    self.say(f"{what} password changed")
                except Exception:
                    self.say("Couldn't change the password")
                finally:
                    self.pending.pop(key, None)
                    self.r.request("wsec")
                    self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def pass_row(self, iface, label, guest):
        """'Password' link for one band, with the stock page's rules: only on a secured network, 8 to 63 characters."""
        key = "pass:" + iface
        what = ("Guest " if guest else "") + label + " Wi-Fi"
        sec = self.g("wsec", {}).get(iface)
        if sec and (sec.get("enc") or "none") == "none":
            return ("value", "Password", "None (open)")

        def done(pw):
            if not pw or not sec or pw == sec.get("key"):
                return
            act = lambda: self.change_key([iface], what, key, pw)
            if guest:
                act()
            else:
                self.confirm(f"Change the {label} password?", f"Devices on {label} disconnect and have to join again with the new password.",
                             "Change", act, True)
        return ("link", "Password", "Changing…" if self.pending.get(key) else ("••••••••" if sec else "—"),
                lambda: None if self.pending.get(key) or not sec else self.open_kb("wifi", f"{what} password", sec.get("key") or "", 63, done, min_len=8))

    def hidden_row(self, iface, label, guest):
        """Stock "SSID Visibility" as a switch: hide the network name so it doesn't show in Wi-Fi lists."""
        key = "hide:" + iface
        what = ("Guest " if guest else "") + label + " Wi-Fi"
        sec = self.g("wsec", {}).get(iface)
        hidden = bool(sec and sec.get("hidden"))
        want = self.pending.get(key, hidden)

        def apply():
            self.pending[key] = not hidden
            self.dirty = True

            def run():
                with self.wifi_lock:
                    try:
                        set_wifi_hidden([iface], not hidden)
                        self.say(f"{what} name is {'hidden' if not hidden else 'shown'}")
                    except Exception:
                        self.say("Couldn't change the visibility")
                    finally:
                        self.pending.pop(key, None)
                        self.r.request("wsec")
                        self.dirty = True
            threading.Thread(target=run, daemon=True).start()

        def tap():
            if key in self.pending or not sec:
                return
            if guest or hidden:
                apply()
            else:
                self.confirm(f"Hide the {label} name?", f"The name stops showing in Wi-Fi lists; devices that saved it can still join. Devices on {label} disconnect while it restarts.",
                             "Hide", apply, True)
        return ("toggle", "Hide network name", want, tap, key in self.pending)

    def channel_row(self, iface, label):
        """Stock "Channel" for the radio behind a band (main and guest share it): Auto or a channel that fits the bandwidth.
        Locked while the router uses Wi-Fi for internet on that radio, like the stock page."""
        dev = self.BAND_RADIO[iface]
        radio = self.g("radios", {}).get(dev) or {}
        key = "chan:" + dev
        cur = radio.get("channel", 0)
        shown = "Auto" if not cur else str(cur)
        if radio.get("repeater"):
            return ("value", "Channel", f"{shown} · locked")
        opts = channel_options(radio) if radio else []

        def pick(v):
            chan = {c["channel"]: c for c in radio.get("channels") or []}
            dfs_new = bool(chan.get(v, {}).get("dfs")) and not bool(chan.get(cur, {}).get("dfs"))
            wide = radio.get("htmode") == "160"

            def run():
                self.pending[key] = v
                self.dirty = True
                with self.wifi_lock:
                    try:
                        set_wifi_radio(dev, channel=v)
                        rs = dict(self.g("radios", {}))
                        rs[dev] = dict(rs.get(dev) or {}, channel=v)
                        self.r.put("radios", rs)
                        self.say(f"{label} channel is {'Auto' if not v else v}")
                    except Exception:
                        self.say(f"Couldn't change {label} channel")
                    finally:
                        self.pending.pop(key, None)
                        self.r.request("radios")
                        self.dirty = True
            body = f"Main and guest {label} share this setting. Both restart, so their devices drop for a minute."
            if str(radio.get("band", "")).lower() == "5g" and radio.get("dfs_support") and (dfs_new or wide):
                body += " A DFS channel needs a radar check each time Wi-Fi starts, so 5 GHz is unavailable for a while."
            self.confirm(f"Set {label} to channel {'Auto' if not v else v}?", body, "Change",
                         lambda: threading.Thread(target=run, daemon=True).start(), True)
        return ("link", "Channel", "Changing…" if self.pending.get(key) else shown,
                lambda: None if self.pending.get(key) or not opts else self.open_pick(f"{label} channel", opts, cur, pick))

    TXPOWERS = ("Max", "High", "Medium", "Low")

    def txpower_row(self, iface, label):
        """Stock "TX Power" for the radio behind a band (main and guest share it): Max, High, Medium or Low."""
        dev = self.BAND_RADIO[iface]
        radio = self.g("radios", {}).get(dev) or {}
        key = "txp:" + dev
        cur = radio.get("txpower")

        def pick(v):
            def run():
                self.pending[key] = v
                self.dirty = True
                with self.wifi_lock:
                    try:
                        set_wifi_radio(dev, txpower=v)
                        rs = dict(self.g("radios", {}))
                        rs[dev] = dict(rs.get(dev) or {}, txpower=v)
                        self.r.put("radios", rs)
                        self.say(f"{label} power is {v}")
                    except Exception:
                        self.say(f"Couldn't change {label} power")
                    finally:
                        self.pending.pop(key, None)
                        self.r.request("radios")
                        self.dirty = True
            body = f"Main and guest {label} share this setting. Both restart, so their devices drop for a minute."
            if v in ("Medium", "Low"):
                body += " Devices far from the router may lose signal."
            self.confirm(f"Set {label} power to {v}?", body, "Change", lambda: threading.Thread(target=run, daemon=True).start(), True)
        opts = [(v, v) for v in self.TXPOWERS]
        return ("link", "TX power", "Changing…" if self.pending.get(key) else (cur or "—"),
                lambda: None if self.pending.get(key) or not radio else self.open_pick(f"{label} TX power", opts, cur, pick))

    def band_rows(self):
        """Stock "Wi-Fi band" for the shared 5 / 6 GHz radio: 5 GHz, 6 GHz or Auto (5 GHz preferred; if the router repeats a Wi-Fi network, the band
        follows it). [] on a router without a shared band, or with nothing to choose."""
        bm = self.g("wband") or {}
        opts = band_options(bm) if bm.get("mutex") else []
        if len(opts) < 2:
            return []
        key = "band:mode"
        cur = bm.get("usemode") or ""
        shown = ("Auto · " + BAND_LABELS.get(bm.get("useband"), "")) if cur == "auto" else BAND_LABELS.get(cur, cur or "—")

        def pick(v):
            dev = (bm.get("present") or {}).get(bm.get("useband") if v == "auto" else v)
            if not dev:
                self.say("That band isn't available")
                return

            def run():
                self.pending[key] = v
                self.dirty = True
                with self.wifi_lock:
                    try:
                        set_wifi_radio(dev, usemode=v)
                        self.say(f"Wi-Fi band is {BAND_LABELS.get(v, v)}")
                    except Exception:
                        self.say("Couldn't change the Wi-Fi band")
                    finally:
                        self.pending.pop(key, None)
                        self.r.request("wband")
                        self.r.request("radios")
                        self.dirty = True
            fixed = BAND_LABELS.get(v, v)
            body = ("5 GHz is preferred. If the router joins a Wi-Fi network on another band, the band follows it." if v == "auto" else
                    f"Wi-Fi is set to {fixed} only. Joining a network on another band switches it back to Auto.") + \
                " The band restarts, so its devices drop for a minute."
            self.confirm(f"Set the Wi-Fi band to {fixed}?", body, "Change", lambda: threading.Thread(target=run, daemon=True).start(), True)
        rows = [("link", "5 / 6 GHz band", "Changing…" if self.pending.get(key) else shown,
                 lambda: None if self.pending.get(key) else self.open_pick("Wi-Fi band", opts, cur, pick))]
        if "6g" in bm.get("mutex", []) and bm.get("env") == 0:
            rows.append(("note", "6 GHz is off because the usage environment is Outdoor (the stock setting). Change it in the admin panel."))
        return rows

    def mode_row(self, iface, label):
        """'Network mode' link for the radio behind a main band (guest shares the same radio)."""
        dev = self.BAND_RADIO[iface]
        radio = self.g("radios", {}).get(dev) or {}
        key = "mode:" + dev
        cur = radio.get("hwmode")

        def pick(v):
            def run():
                self.pending[key] = v
                self.dirty = True
                with self.wifi_lock:
                    try:
                        set_wifi_mode(dev, v)
                        rs = dict(self.g("radios", {}))
                        rs[dev] = dict(rs.get(dev) or {}, hwmode=v)
                        self.r.put("radios", rs)
                        self.say(f"{label} mode is {mode_label(v)}")
                    except Exception:
                        self.say(f"Couldn't change {label} mode")
                    finally:
                        self.pending.pop(key, None)
                        self.r.request("radios")
                        self.dirty = True
            self.confirm(f"Set {label} to {mode_label(v)}?",
                         f"Main and guest {label} share this setting. Both restart, so their devices drop for a minute. Older devices may not connect to a newer-only mode.",
                         "Change", lambda: threading.Thread(target=run, daemon=True).start(), True)
        opts = [(m, mode_label(m)) for m in radio.get("hwmodes") or []]
        return ("link", "Network mode", "Changing…" if self.pending.get(key) else (mode_label(cur) or "—"),
                lambda: None if self.pending.get(key) or not opts else self.open_pick(f"{label} network mode", opts, cur, pick))

    def bg_swap(self, off, on):
        """Turn one network off, then another on, in the background (two Wi-Fi reloads)."""
        self.pending[off], self.pending[on] = False, True
        self.dirty = True

        def run():
            with self.wifi_lock:
                try:
                    set_wifi_enabled(off, False)
                    w = dict(self.g("wifi", {}))
                    w[self.WIFI_KEYS[off]] = False
                    self.r.put("wifi", w)
                    set_wifi_enabled(on, True)
                    w[self.WIFI_KEYS[on]] = True
                    self.r.put("wifi", w)
                    self.say(f"{NET_NAMES[on]} is on")
                except Exception as e:
                    self.confirm(f"Couldn't turn on {NET_NAMES[on]}", "The router's Wi-Fi driver refused it. Turn another network off and try again." if "refused" in str(e) else "The router didn't apply the change.", "OK", lambda: None)
                finally:
                    self.pending.pop(off, None)
                    self.pending.pop(on, None)
                    self.r.request("wifi")
                    self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def room_for(self, iface, go):
        """While the router is joined to a Wi-Fi network, only 2 of its own networks fit (the driver refuses a
        4th interface). Offer to swap one out instead of failing after a 35 s reload."""
        busy = [k for k in NET_NAMES if k in self.pending]
        if busy:
            return
        running = [k for k in running_nets() if k != iface]
        if len(running) < OWN_NETS_WHILE_JOINED or not joined_to_wifi():
            go()
            return
        self.open_pick("Make room: turn off", [(k, NET_NAMES[k]) for k in running], None,
                       lambda off: self.bg_swap(off, iface))

    def toggle_guest(self, iface, label, cur):
        if iface in self.pending:
            return
        act = lambda: self.bg_wifi(iface, f"Guest {label}", not cur)
        if not cur:
            return self.room_for(iface, act)
        if cur:
            self.confirm(f"Turn guest {label} Wi-Fi off?", "Guests on this band disconnect.", "Turn off", act, True)
        else:
            act()

    def toggle_band(self, iface, label, cur):
        if iface in self.pending:
            return
        act = lambda: self.bg_wifi(iface, f"{label} Wi-Fi", not cur)
        if not cur:
            return self.room_for(iface, act)
        if cur:
            self.confirm(f"Turn {label} Wi-Fi off?", "Devices on this band disconnect. If you're managing the router over it, you'll lose access.", "Turn off", act, True)
        else:
            act()

    def open_join(self):
        self.go("join")
        self.scanning, self.scan = True, []

        def run():
            try:
                self.scan = scan_nets()
            finally:
                self.scanning = False
                self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def v_join(self):
        self.header("Join a network")
        rep = self.g("rep", {})
        saved = self.sel.get("saved_keys")
        if saved is None:
            saved = self.sel["saved_keys"] = lib.get_remembered_repeater_keys()
        rows = []
        if self.scanning:
            rows.append(("note", "Scanning for networks…"))
        for ap in self.scan:
            cur = rep.get("connected") and ap["ssid"] == rep.get("ssid")
            sig = ap.get("signal") or -100
            q = "strong" if sig > -60 else "fair" if sig > -72 else "weak"
            val = "Connected" if cur else ("Saved · " if ap["ssid"] in saved else "Open · " if ap["open"] else "") + q
            rows.append(("link", ap["ssid"], val, (lambda: None) if cur else (lambda ap=ap: self.pick_net(ap, saved)), ap.get("bands")))
        if not self.scanning and not self.scan:
            rows.append(("note", "No networks found."))
        rows.append(("btn", "Scan again", self.rescan, ""))
        if rep.get("connected"):
            rows.append(("btn", "Disconnect from " + rep.get("ssid", ""), lambda: self.confirm(
                "Disconnect Wi-Fi internet?", "The router falls back to mobile data or Ethernet.", "Disconnect",
                lambda: self.work("Disconnecting", lib.repeater_disconnect, ("rep",)), True), "danger"))
        self.rows(56, H, rows)

    def rescan(self):
        self.stack.pop() if self.stack else None
        self.view = "wifi"
        self.open_join()

    def pick_net(self, ap, saved):
        if ap["open"] or ap["ssid"] in saved:
            self.join(ap, saved.get(ap["ssid"]))
        else:
            self.open_kb("wifi", f"Password for {ap['ssid']}", "", 63, lambda pw: self.join(ap, pw), min_len=8)

    def join(self, ap, key):
        def do():
            lib.repeater_connect(ap["ssid"], ap.get("bssid"), key)
            ok = lib._wait_until(lambda: (lambda r: r.get("connected") and r.get("ssid") == ap["ssid"])(lib.get_repeater_status()), 40, poll=2)
            if not ok:
                self.say("Couldn't join " + ap["ssid"])
        self.work(f"Joining {ap['ssid']}", do, ("rep", "cell"), done=lambda: self.tab("wifi"))

    def v_share(self):
        self.header("Share guest Wi-Fi" if self.sel.get("share_set") == "guest" else "Share Wi-Fi")
        guest = self.sel.get("share_set") == "guest"
        choices = (("guest5g", "5 GHz"), ("guest2g", "2.4 GHz")) if guest else (("wifi5g", "5 GHz"), ("wifi2g", "2.4 GHz"))
        bands = [(i, l) for i, l in choices if wifi_info(i)[0] and (not guest or lib.uci_get(f"wireless.{i}.disabled", "1") != "1")]
        if not bands:
            self.t((W / 2, 140), "No Wi-Fi network found.", F(11), DIM, "mm")
            return
        iface = self.sel.get("share_band")
        if iface not in [b[0] for b in bands]:
            iface = bands[0][0]
        ssid, key = wifi_info(iface)
        m = qr_matrix(wifi_qr_text(ssid, key, lib.uci_get(f"wireless.{iface}.encryption", "psk2")))
        box = 140
        x0, y0 = (W - box) // 2, 58
        self.d.rounded_rectangle((x0, y0, x0 + box, y0 + box), radius=8, fill=(255, 255, 255))
        if m:
            n = len(m)
            sc = max(1, (box - 16) // n)
            ox, oy = x0 + (box - sc * n) // 2, y0 + (box - sc * n) // 2
            for r, row in enumerate(m):
                for c, dark in enumerate(row):
                    if dark:
                        self.d.rectangle((ox + c * sc, oy + r * sc, ox + c * sc + sc - 1, oy + r * sc + sc - 1), fill=(0, 0, 0))
        else:
            self.t((W / 2, y0 + box / 2), "QR unavailable", F(10), (90, 96, 106), "mm")
        self.t((W / 2, y0 + box + 12), "Scan with a phone camera to join", F(9), DIM, "mm")
        self.t((W / 2, y0 + box + 28), self.fit(ssid, F(12, "b"), 220), F(12, "b"), FG, "mm")
        self.t((W / 2, y0 + box + 44), self.fit(f"Password: {key}" if key else "Open network, no password", F(10), 220), F(10), DIM, "mm")
        if len(bands) > 1:
            def pick(label):
                self.sel["share_band"] = next(i for i, l in bands if l == label)
                self.dirty = True
            self.rows(250, H, [("seg", "", [l for _, l in bands], dict(bands)[iface], pick)], "share_seg")

    def vpn_switch(self):
        """The stock "Use" switch (VPN page and quick-panel tile): turn the tunnel on or off, keeping its server."""
        t, on = self.g("vpnt"), bool(self.g("wga"))
        lib.vpn_log(f"tap: switch connected={on} tunnel={t and t['id']} enabled={t and t['enabled']} peer={t and t['peer']}")
        if not t or not t["peer"]:
            self.close_panel()
            self.go("vpn_loc")  # no tunnel or no server yet: choose one, then use the switch
            self.say("Choose a VPN location first")
            return
        want = not (on or t["enabled"])
        self.work("Connecting VPN" if want else "Turning VPN off", lambda: vpn_switch_to(t, want), ("wga", "vpnt"), self.vpn_refresh)

    def vpn_refresh(self):
        """Publish the VPN state right after a change (runs on the worker thread), so the screen never acts on the
        state from before it."""
        try:
            self.r.put("wga", lib.get_wireguard_active(strict=True))
            self.r.put("vpnt", lib.get_vpn_tunnel())
        except Exception:
            pass  # the periodic refresh will catch up

    def v_saved(self):
        """The stock "Known Networks": Wi-Fi networks the router remembers for internet. Tap one for its details."""
        self.header("Saved networks")
        saved, rep = self.g("savedap", []), self.g("rep", {})
        cur = rep.get("ssid") if rep.get("connected") else None

        def open_net(ssid):
            self.sel["saved_ssid"] = ssid
            self.go("saved_net")
        rows = [("link", ssid, "In use" if ssid == cur else "", lambda s=ssid: open_net(s)) for ssid in saved]
        if not rows:
            rows = [("note", "No saved networks. Networks you join from the Wi-Fi tab are remembered here.")]
        self.rows(56, H, rows)

    def v_saved_net(self):
        """One known network: its password (only for the network in use, like the stock repeater page) and Forget."""
        ssid = self.sel.get("saved_ssid") or ""
        self.header(self.fit(ssid, F(14, "b"), 170))
        rep = self.g("rep", {})
        inuse = bool(rep.get("connected")) and rep.get("ssid") == ssid
        keys = lib.get_remembered_repeater_keys()

        def forget():
            def run():
                if not lib.forget_saved_ap(ssid):
                    raise RuntimeError("The router refused that")
            body = ("You're using it for internet now, so internet from Wi-Fi stops. " if inuse else "") + "You'll need its password to join it again."
            self.confirm(f"Forget {ssid[:20]}?", body, "Forget", lambda: (self.back(), self.work(
                "Forgetting network", run, ("savedap", "rep"), lambda: self.r.put("savedap", lib.get_saved_aps()))), True)

        def change(new):
            if not new or new == keys.get(ssid):
                return
            self.confirm(f"Change the password for {ssid[:16]}?",
                         "The router reconnects with the new password. Internet from Wi-Fi pauses for a moment. If it can't join, it goes back to the old one.",
                         "Change", lambda: self.change_repeater_key(ssid, new), True)
        rows = [("value", "Status", "In use" if inuse else "Saved")]
        if ssid in keys and inuse:
            rows.append(("link", "Password", "••••••••", lambda: self.open_kb("wifi", f"{ssid[:22]} password", keys[ssid], 63, change, min_len=8)))
        elif ssid in keys:
            rows.append(("note", "To change this network's password, connect to it first."))
        else:
            rows.append(("value", "Password", "None (open)"))
        rows.append(("btn", "Forget this network", forget, "danger"))
        self.rows(56, H, rows)

    def change_repeater_key(self, ssid, new):
        """Re-join the network in use with a new password (stock: repeater.connect with the new key). If it doesn't connect,
        go back to the old password so a typo can't leave the router without its Wi-Fi internet."""
        def joined():
            r = lib.get_repeater_status()
            return bool(r.get("connected")) and r.get("ssid") == ssid

        def run():
            rec = lib.get_saved_ap(ssid)
            if not rec:
                raise RuntimeError("Network not found")
            old = rec.get("key")
            lib.repeater_set_key(rec, new)
            if lib._wait_until(joined, 45, poll=2):
                self.say("Password changed")
                return
            lib.repeater_set_key(rec, old)
            back = lib._wait_until(joined, 45, poll=2)
            self.say("Wrong password. Old one restored." if back else "Wrong password. Couldn't rejoin.")
        self.work("Changing password", run, ("rep", "cell", "savedap"))

    def v_vpn(self):
        self.header("VPN", lambda: self.tab("home"))
        wga, t = self.g("wga"), self.g("vpnt")
        peers = self.g("wgp", [])
        on = bool(wga)
        cx, cy = W // 2, 96
        self.d.ellipse((cx - 40, cy - 40, cx + 40, cy + 40), fill=TEALBG if on else SURF, outline=TEAL if on else (57, 66, 79), width=3)
        col = TEAL if on else DIM
        self.d.arc((cx - 12, cy - 16, cx + 12, cy + 8), 300, 240, fill=col, width=3)
        self.d.line([(cx, cy - 20), (cx, cy - 5)], fill=col, width=3)
        self.t((cx, cy + 24), "On" if on else "Off", F(11, "b"), col, "mm")
        self.btn((cx - 44, cy - 44, cx + 44, cy + 44), self.vpn_switch)
        loc = t["peer"] if t and t["peer"] else None
        cap = f"All devices go through {vpn_label(self.peer_name(wga))}." if on else \
            ("Switch on to connect. Devices use your normal connection until then." if loc else
             "Choose a location to set up the VPN tunnel." if peers else "No WireGuard servers set up on this router.")
        for i, line in enumerate(wrap(self.d, cap, F(11), W - 40)[:2]):
            self.t((W / 2, 152 + i * 14), line, F(11), DIM, "mm")
        self.card((10, 184, W - 10, 218))
        self.t((20, 201), "Location", F(12), FG, "lm")
        self.t((W - 30, 201), self.fit(vpn_label(self.peer_name(loc)) if loc else "Choose", F(11, "b"), 130), F(11, "b"), FG, "rm")
        self.t((W - 20, 201), "›", F(12), DIM, "rm")
        self.btn((10, 184, W - 10, 218), lambda: self.go("vpn_loc"))
        if t:
            self.card((10, 224, W - 10, 258))
            self.t((20, 241), "Settings", F(12), FG, "lm")
            self.t((W - 20, 241), "›", F(12), DIM, "rm")
            self.btn((10, 224, W - 10, 258), lambda: self.go("vpn_opts"))

    def v_vpn_loc(self):
        self.header("VPN location")
        t, on = self.g("vpnt"), bool(self.g("wga"))
        cur = t["peer"] if t else None

        def pick(p):
            self.back()
            if p["id"] == cur:
                return

            def run():
                lib.vpn_log(f"location {p['id']} tunnel={t and t['id']} connected={on}")
                if not lib.set_vpn_location(p["id"], t["id"] if t else None):
                    raise RuntimeError("The router refused that location")
                if on and lib.wait_for_wireguard_state(p["id"]) != p["id"]:  # connected: it reconnects to the new one
                    raise RuntimeError("Didn't switch server")
            self.work("Setting VPN location", run, ("wga", "vpnt"), self.vpn_refresh)
        peers = sorted(self.g("wgp", []), key=lambda p: vpn_label(p["name"]))
        self.rows(56, H, [("link", vpn_label(p["name"]), "✓" if p["id"] == cur else "", lambda p=p: pick(p)) for p in peers]
                  or [("note", "No WireGuard servers are set up. Add them in the router's admin panel.")])

    def v_vpn_opts(self):
        self.header("VPN settings")
        t = self.g("vpnt")
        if not t:
            self.rows(56, H, [("note", "Reading the VPN tunnel…")])
            return

        def apply(key):
            if not lib.set_vpn_options(t, **{key: not t["opts"][key]}):
                raise RuntimeError("The router refused that setting")

        def flip(key):
            self.work("Applying", lambda: apply(key), ("vpnt", "wga"), self.vpn_refresh)
        o = t["opts"]
        self.rows(56, H, [
            ("toggle", "Kill switch", o["killswitch"], lambda: flip("killswitch")),
            ("note", "Blocks internet for devices if the VPN drops, instead of leaking your real connection."),
            ("toggle", "Remote access to LAN", o["local_access"], lambda: flip("local_access")),
            ("toggle", "IP masquerading", o["masq"], lambda: flip("masq")),
            ("toggle", "Services use VPN", o["service_policy"], lambda: flip("service_policy")),
            ("note", "Changing these restarts the VPN for a few seconds. MTU and which devices use the tunnel are set in the admin panel."),
        ])

    def v_more(self):
        self.header("More", lambda: self.tab("home"))
        sim, wx, cl = self.g("sim", {}), self.g("wx"), self.g("clients", [])
        u = len(self.unread())
        rows = [("toggle", "Airplane mode", sim.get("airplane", False), self.toggle_air),
                ("tiles", [("Texts", f"{u} unread" if u else "All read", lambda: self.go("texts")),
                           ("Weather", f"{self.cfg['city']['name']} · {round(wx['now'])}°" if wx else self.cfg["city"]["name"], lambda: self.go("weather"))]),
                ("tiles", [("Monitor", "Speed test inside", lambda: self.go("monitor")),
                           ("Currency", f"{self.cfg['fx']} → {self.cfg['home_fx']}", lambda: self.go("fx"))]),
                ("head", "Router settings")]
        for label, val, key in (("Clients", f"{sum(1 for c in cl if c['online'])} online", "clients"), ("Internet", lib.get_wan_conn_type(self.g("cell", {})) or "", "internet"),
                                ("Network", "Ethernet, IP", "network"), ("Display", self.cfg["bright"], "display"),
                                ("Security", "Passcode on" if self.cfg["pass_on"] else "No passcode", "security"),
                                ("Power & USB", (lambda b: f"{b[0]}%" if b else "")(lib.get_battery()), "power"),
                                ("AdGuard Home", (lambda a: "Blocking" if a.get("enabled") and a.get("dns") else "On" if a.get("enabled") else "Off")(self.g("agh") or {}), "agh"), ("GL.iNet Account", "", "account")):
            rows.append(("link", label, val, lambda k=key: self.open_set(k)))
        fw = self.g("fw")
        fw_val = "" if not fw else (f"{fw['new']} available" if fw.get("new") else "Up to date")
        rows += [("link", "Dashboard", "Clocks, stock screen", lambda: self.go("dash")),
                 ("link", "Firmware", fw_val, lambda: self.go("firmware")),
                 ("link", "About device", "GL-E5800", lambda: self.open_set("about")),
                 ("btn3", [("Screen off", self.screen_off, ""),
                           ("Reboot", lambda: self.confirm("Reboot the router?", "Wi-Fi and internet drop for about a minute.", "Reboot",
                                                           lambda: self.power("Restarting", lib.reboot_router), True), "danger"),
                           ("Shut down", lambda: self.confirm("Shut down the router?", "Everything goes offline until you press the power button.",
                                                              "Shut down", lambda: self.power("Shutting down", lib.shutdown_router), True), "danger")])]
        self.rows(56, 276, rows)

    @staticmethod
    def fw_note(note, limit=520):
        """The release note (markdown) as a few plain lines for the small screen: no headings, no markup."""
        lines = []
        for ln in (note or "").replace("\r", "").split("\n"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            ln = re.sub(r"[*_`>]+", "", ln).strip()
            lines.append(("• " + ln[1:].strip()) if ln.startswith("-") else ln)
        text = " ".join(lines)
        return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"

    def v_firmware(self):
        """Firmware update notice, from the stock check (upgrade.check_firmware_online). Installing is left to the stock screen
        or the admin panel."""
        self.header("Firmware")
        f = self.g("fw")
        if not f:
            self.rows(56, H, [("note", "Checking for updates…"),
                              ("btn", "Check again", lambda: self.r.request("fw"), "")])
            return

        def check():
            def run():
                self.r.put("fw", lib.get_firmware_update())
            self.work("Checking for updates", run, ("fw",))

        def skip():
            def run():
                if not lib.skip_firmware_update():
                    raise RuntimeError("The router refused that")
            self.work("Skipping this version", run, ("fw",), lambda: self.r.put("fw", lib.get_firmware_update()))
        ip = lib.get_system_info().get("lan_ip", "") or "10.10.1.1"
        rows = [("value", "Installed", f["current"] or "—")]
        if f.get("new"):
            rows += [("value", "Available", f["new"]),
                     ("note", self.fw_note(f.get("note")) or "No release notes were provided."),
                     ("note", f"To install it, use the admin panel at {ip} or switch to the stock screen (More, Dashboard). It downloads, installs and restarts the router.")]
            if f.get("prompt"):
                rows.append(("btn", "Skip this version", skip, ""))
        else:
            rows += [("note", "Firmware is up to date. The router also checks by itself.")]
        rows.append(("btn", "Check again", check, ""))
        self.rows(56, H, rows)

    def power(self, label, fn):
        self.busy = (label, time.time())
        fn()

    def screen_off(self):
        self.locked, self.lock_stage = True, "face"
        subprocess.Popen([SLEEP, "off"])

    def toggle_air(self):
        on = self.g("sim", {}).get("airplane", False)
        do = lambda: lib.set_network_attach_enabled(on)
        if on:
            self.work("Turning airplane mode off", do, ("sim", "cell"))
        else:
            self.confirm("Turn airplane mode on?", "Mobile data, texts and calls stop. Wi-Fi keeps working.", "Turn on",
                         lambda: self.work("Turning airplane mode on", do, ("sim", "cell")), True)

    def sms_refresh(self):
        self.r.put("sms", lib.get_sms_messages())

    def v_texts(self):
        self.header("Texts")
        msgs = self.g("sms", [])

        def open_(m):
            self.sel["sms"] = m
            if self.is_unread(m):
                self.cfg["sms_read"] = (self.cfg["sms_read"] + [self.sms_id(m)])[-300:]
                self.save()
                if m.get("name"):  # tell the router too, like the stock screen, so the stock screen shows it read
                    threading.Thread(target=lambda: (lib.mark_sms_read(m["name"]), self.sms_refresh()), daemon=True).start()
            self.go("text")

        def delete_read():
            def run():
                if not lib.delete_sms(scope=1):
                    raise RuntimeError("The router refused that")
            self.confirm("Delete read texts?", "Texts you've opened are removed from the router. Unread ones stay.", "Delete",
                         lambda: self.work("Deleting texts", run, ("sms",), self.sms_refresh), True)
        sent = self.g("smssent", [])
        rows = [("link", "Sent texts", str(len(sent)) if sent else "", lambda: self.go("sent"))] + [
                ("msg", m.get("from") or "?", m.get("body", "").replace("\n", " "),
                 (m["sent"].strftime("%d %b") if m.get("sent") else ""), self.is_unread(m),
                 lambda m=m: open_(m)) for m in msgs]
        if any(m.get("status", 0) == 1 or self.sms_id(m) in set(self.cfg["sms_read"]) for m in msgs):
            rows.append(("btn", "Delete read texts", delete_read, "danger"))
        self.rows(56, H, rows or [("note", "No texts yet.")])

    SENT_STATE = {3: "Sending…", 4: "Sending…", 5: "Failed"}

    def v_sent(self):
        """Texts we sent (the stock "Sent" list): who to, a start of the message, when, and an orange dot on ones that failed."""
        self.header("Sent texts")
        sent = self.g("smssent", [])

        def open_(m):
            self.sel["sent_msg"] = m
            self.go("sent_text")
        rows = [("msg", "To " + (m["to"] or "?"), (self.SENT_STATE.get(m["status"], "") + (": " if m["status"] in self.SENT_STATE else "") + m["body"].replace("\n", " ")),
                 (m["sent"].strftime("%d %b") if m.get("sent") else ""), m["status"] == 5, lambda m=m: open_(m)) for m in sent]
        self.rows(56, H, rows or [("note", "No sent texts yet.")])

    def v_sent_text(self):
        m = self.sel.get("sent_msg") or {}
        self.header(self.fit("To " + (m.get("to") or ""), F(14, "b"), 170))
        state = self.SENT_STATE.get(m.get("status"), "Sent")
        when = (m["sent"].strftime("%a %d %b %Y, ") + self.tfmt_dt(m["sent"]) + " · ") if m.get("sent") else ""

        def delete_one():
            def run():
                if not lib.delete_sms(m["name"]):
                    raise RuntimeError("The router refused that")
            self.confirm("Delete this text?", "It's removed from the router, so the stock screen won't show it either.", "Delete",
                         lambda: (self.back(), self.work("Deleting text", run, ("smssent",), lambda: self.r.put("smssent", lib.get_sent_sms()))), True)
        rows = [("note", when + state), ("para", m.get("body", ""))]
        if m.get("name"):
            rows.append(("btn", "Delete this text", delete_one, "danger"))
        self.rows(56, H, rows)

    def v_text(self):
        m = self.sel.get("sms") or {}
        self.header(self.fit(m.get("from", ""), F(14, "b"), 170))
        when = m["sent"].strftime("%a %d %b %Y, ") + self.tfmt_dt(m["sent"]) if m.get("sent") else m.get("sent_raw", "")

        def delete_one():
            def run():
                if not lib.delete_sms(m["name"]):
                    raise RuntimeError("The router refused that")
            self.confirm("Delete this text?", "It's removed from the router, so the stock screen won't show it either.", "Delete",
                         lambda: (self.back(), self.work("Deleting text", run, ("sms",), self.sms_refresh)), True)
        rows = [("note", when), ("para", m.get("body", ""))]
        if m.get("name"):
            rows.append(("btn", "Delete this text", delete_one, "danger"))
        self.rows(56, H, rows)

    def tfmt_dt(self, dt):
        return dt.strftime("%H:%M") if self.cfg["h24"] else f"{dt.hour % 12 or 12}:{dt.minute:02d} {dt.strftime('%p')}"

    def v_weather(self):
        c = self.cfg["city"]
        self.btn((0, 22, 44, 56), self.back)
        self.chevron(17, 39)
        self.t((44, 39), self.fit(c["name"], F(14, "b"), 100), F(14, "b"), FG, "lm")
        self.d.rounded_rectangle((W - 92, 26, W - 10, 52), radius=8, outline=(57, 66, 79))
        self.t((W - 51, 39), "Change city", F(10, "s"), FG, "mm")
        self.btn((W - 96, 22, W, 56), self.open_city)
        wx, aq = self.g("wx"), self.g("aq")
        if not wx:
            self.t((W / 2, 120), "Loading weather…", F(11), DIM, "mm")
            return
        w3 = (W - 20 - 12) / 3
        for i, dday in enumerate(wx["days"][:3]):
            x0 = 10 + i * (w3 + 6)
            self.card((x0, 60, x0 + w3, 128))
            name = "Today" if i == 0 else datetime.strptime(dday["date"], "%Y-%m-%d").strftime("%a")
            self.t((x0 + w3 / 2, 70), name.upper(), F(9, "s"), DIM, "mm")
            self.wx_icon(x0 + w3 / 2, 88, dday["code"], 0.8)
            self.t((x0 + w3 / 2, 108), f"{round(dday['hi'])}°", F(13, "b"), FG, "mm")
            self.t((x0 + w3 / 2, 121), f"{round(dday['lo'])}° · {dday['rain'] or 0}%", F(9), DIM, "mm")
        uv = wx["days"][0].get("uv")
        rows = [("value", "Now", f"{round(wx['now'])}° · {lib.wmo_info(wx['code'])[0]}"),
                ("value", "Feels like", f"{round(wx['feels'])}°"),
                ("value", "UV index", f"{round(uv)} · {lib.uv_category(uv)}" if uv is not None else "No data"),
                ("value", "Air quality", f"{aq['aqi']} · {lib.aqi_category(aq['aqi'])}" if aq and aq.get("aqi") is not None else "No data")]
        self.rows(134, H, rows)

    def open_city(self):
        self.q, self.geo, self.geo_q = "", [], ""
        self.go("city")

    def v_city(self):
        self.header("Weather city")
        self.card((8, 58, W - 8, 84), r=8)
        self.d.ellipse((16, 65, 25, 74), outline=DIM, width=2)
        self.d.line([(24, 73), (28, 77)], fill=DIM, width=2)
        self.t((34, 71), self.q or "Type a city name", F(12, "s"), FG if self.q else DIM, "lm")
        if self.q:
            x = 34 + self.d.textlength(self.q, font=F(12, "s")) + 1
            self.d.line([(x, 64), (x, 78)], fill=TEAL, width=1)
        if self.q:
            items = self.geo[:3]
            label = "Searching…" if self.geo_busy else ("Results" if items else ("No city found" if self.geo_q == self.q.strip() else ""))
        else:
            items, label = self.cfg["recent"][:3], "Recent"
        self.t((10, 92), label.upper(), F(9, "s"), DIM, "lm")
        for i, c in enumerate(items):
            y = 98 + i * 24
            self.t((10, y + 12), self.fit(c["name"], F(11, "s"), 110), F(11, "s"), FG, "lm")
            self.t((14 + self.d.textlength(self.fit(c["name"], F(11, "s"), 110), font=F(11, "s")), y + 12),
                   self.fit(", ".join(x for x in (c.get("region") if c.get("region") != c["name"] else "", c.get("country")) if x), F(9), 100), F(9), DIM, "lm")
            if c["name"] == self.cfg["city"]["name"] and abs(c["lat"] - self.cfg["city"]["lat"]) < 0.05:
                self.t((W - 12, y + 12), "✓", F(11, "b"), TEAL, "rm")
            self.d.line([(10, y + 23), (W - 10, y + 23)], fill=DIV)
            self.btn((0, y, W, y + 24), lambda c=c: self.pick_city(c))
        self.keyboard(172, lambda ch: self.city_type(self.q + ch), lambda: self.city_type(self.q[:-1]), letters_only=True, kh=30)

    def city_type(self, q):
        self.q = q[:24]
        self.q_t = time.time()
        self.dirty = True

    def pick_city(self, c):
        c = {k: c[k] for k in ("name", "country", "lat", "lon")} | ({"region": c["region"]} if c.get("region") else {})
        self.cfg["city"] = c
        same = lambda r: r["name"] == c["name"] and abs(r["lat"] - c["lat"]) < 0.05  # San Jose CA vs San Jose CR
        self.cfg["recent"] = ([c] + [r for r in self.cfg["recent"] if not same(r)])[:3]
        self.save()
        self.r.put("wx", None)
        self.r.put("aq", None)
        self.r.request("wx")
        self.r.request("aq")
        self.back()

    def v_monitor(self):
        self.header("Monitor")
        m = self.mon
        w2 = (W - 26) / 2
        for i, (lbl, v) in enumerate((("DOWNLOAD", m["down"]), ("UPLOAD", m["up"]))):
            x0 = 10 + i * (w2 + 6)
            self.card((x0, 58, x0 + w2, 100))
            self.t((x0 + 9, 69), lbl, F(9, "s"), DIM, "lm")
            self.t((x0 + 9, 88), f"{v:.1f}", F(15, "b"), FG, "lm")
            self.t((x0 + 13 + self.d.textlength(f"{v:.1f}", font=F(15, "b")), 90), "Mbps", F(9), DIM, "lm")
        ram = lib.get_ram_stats()
        self.t((10, 112), "CPU", F(10), FG, "lm")
        self.t((W - 10, 112), f"{m['cpu_pct']:.0f}%", F(10), DIM, "rm")
        self.bar(10, 120, W - 10, m["cpu_pct"] / 100)
        self.t((10, 138), "Memory", F(10), FG, "lm")
        if ram:
            self.t((W - 10, 138), f"{ram[1]:.1f} of {ram[2]:.1f} GB", F(10), DIM, "rm")
            self.bar(10, 146, W - 10, ram[0] / 100)
        t = lib.get_temp_c()
        self.t((10, 166), f"{t:.0f}°C" if t else "", F(10), FG, "lm")
        up = lib.get_system_info().get("uptime_min", 0)
        self.t((W - 10, 166), f"Up {up // 60} h {up % 60} m", F(10), DIM, "rm")
        sp = self.speed.snapshot()
        y = 182
        if sp["phase"] in ("download", "upload"):
            self.card((10, y, W - 10, y + 54))
            self.t((20, y + 12), sp["phase"].upper(), F(9, "s"), DIM, "lm")
            self.t((20, y + 30), f"{sp['live']:.1f}", F(18, "b"), FG, "lm")
            self.t((24 + self.d.textlength(f"{sp['live']:.1f}", font=F(18, "b")), y + 32), "Mbps", F(9), DIM, "lm")
            prog = (sp["progress"] / 2) + (0.5 if sp["phase"] == "upload" else 0)
            self.bar(20, y + 44, W - 90, prog)
            self.d.rounded_rectangle((W - 80, y + 14, W - 18, y + 42), radius=8, outline=(57, 66, 79))
            self.t((W - 49, y + 28), "Cancel", F(10, "b"), FG, "mm")
            self.btn((W - 84, y, W - 10, y + 54), self.speed.cancel)
        elif sp["phase"] == "done":
            self.card((10, y, W - 10, y + 54))
            self.t((20, y + 18), f"↓ {sp['down'] or 0:.1f}  ↑ {sp['up'] or 0:.1f} Mbps", F(12, "b"), FG, "lm")
            self.t((20, y + 36), f"{fmt_bytes(sp['bytes'])} used · via {sp.get('via') or '?'}", F(9), DIM, "lm")
            self.d.rounded_rectangle((W - 74, y + 14, W - 18, y + 42), radius=8, outline=(57, 66, 79))
            self.t((W - 46, y + 28), "Again", F(10, "b"), FG, "mm")
            self.btn((W - 80, y, W - 10, y + 54), self.speed.start)
        else:
            if sp["phase"] == "error":
                self.t((W / 2, y - 4), self.fit(f"Test failed: {sp.get('error')}", F(9), 220), F(9), RED, "mm")
            self.d.rounded_rectangle((10, y + 4, W - 10, y + 40), radius=10, outline=(57, 66, 79))
            self.t((W / 2, y + 22), "Run speed test", F(12, "b"), FG, "mm")
            self.btn((10, y + 4, W - 10, y + 40), self.speed.start)
            self.t((W / 2, y + 50), "Uses up to ~330 MB of mobile data", F(8), DIM, "mm")

    def v_fx(self):
        self.header("Currency")
        home = self.cfg["home_fx"]
        code = self.cfg["fx"] if self.cfg["fx"] != home else ("PHP" if home != "PHP" else "USD")
        fx = self.g("fx")
        rate = None
        try:
            rate = lib.rate_between(code, home, fx) if fx else None
        except Exception:
            pass
        per = next((p for p in (1, 100, 1000, 10000) if rate and rate * p >= 1), 1)  # small rates (yen, won) are shown per 100 / 1,000
        self.card((10, 60, W - 10, 132))
        self.t((20, 74), self.fit(f"{per:,} {FX_NAMES.get(code, code)}", F(11), W - 50), F(11), DIM, "lm")
        txt = f"{rate * per:,.2f}" if rate else "--"
        big = F(26, "b") if self.d.textlength(txt, font=F(26, "b")) < 150 else F(20, "b")  # big amounts (rupiah, dong) step down to fit
        self.t((20, 103), txt, big, FG, "lm")
        self.t((26 + self.d.textlength(txt, font=big), 106), home, F(13, "b"), DIM, "lm")
        if rate:
            back = 1 / rate
            self.t((20, 122), f"1 {home} = {back:,.6f} {code}" if back < 0.01 else f"1 {home} = {back:,.4f} {code}" if back < 100 else f"1 {home} = {back:,.2f} {code}", F(9), DIM, "lm")

        self.rows(138, H, [("link", "Compare with", code, lambda: self.go("fx_cmp")),
                           ("link", "My currency", home, lambda: self.go("fx_home"))], "fx_rows")

    def fx_list(self, title, current, skip, pick):
        """A list of currencies to choose from: every one we have a name for that the rate list also has (all of them while rates aren't loaded yet)."""
        self.header(title)
        have = (self.g("fx") or {}).get("rates") or {}
        self.rows(56, H, [("link", f"{c} · {n}", "✓" if c == current else "", lambda c=c: pick(c))
                          for c, n in FX_NAMES.items() if c != skip and (not have or c in have or c == "USD")])

    def v_fx_home(self):
        """The main (home) currency the Currency page converts into. Everything is converted through USD, so any code the rate list has works."""
        def pick(c):
            self.cfg["home_fx"] = c
            if self.cfg["fx"] == c:  # it can't compare with itself
                self.cfg["fx"] = "PHP" if c != "PHP" else "USD"
            self.save()
            self.back()
        self.fx_list("My currency", self.cfg["home_fx"], None, pick)

    def v_fx_cmp(self):
        """The currency to compare with the main one."""
        def pick(c):
            self.cfg["fx"] = c
            self.save()
            self.back()
        self.fx_list("Compare with", self.cfg["fx"], self.cfg["home_fx"], pick)

    def set_accent(self, name, rgb=None):
        self.cfg["accent"] = name
        if rgb is not None:
            self.cfg["accent_custom"] = list(rgb)
        self.save()
        apply_accent(accent_current(self.cfg))
        self.dirty = True

    def v_accent(self):
        """Accent color: five ready-made colors and one of your own (More > Display). Everything teal on the screen follows it."""
        self.header("Accent color")
        cur, mine = self.cfg["accent"], self.cfg.get("accent_custom")
        rows = [("swatch", n, rgb, cur == n, lambda n=n: self.set_accent(n)) for n, rgb in ACCENTS]
        rows.append(("swatch", "Your color" + (f"  #{''.join(f'{x:02X}' for x in mine)}" if mine else ""), tuple(mine) if mine else None, cur == "custom",
                     self.open_accent_custom))
        rows.append(("note", "Very dark colors are lightened so they stay readable on the dark screen."))
        self.rows(56, H, rows)

    def open_accent_custom(self):
        mine = self.cfg.get("accent_custom") or list(accent_current(self.cfg))
        h, s_, _ = colorsys.rgb_to_hsv(*[x / 255 for x in mine])
        self.sel["acc"] = {"h": min(h, 0.96), "s": max(0.3, s_)}
        self.go("accent_custom")

    HUES, SHADES = 24, 8

    def v_accent_custom(self):
        """Pick your own accent: tap a hue, then how strong it is (or type a hex code). Nothing changes until "Use this color"."""
        self.header("Your color")
        a = self.sel.setdefault("acc", {"h": 0.5, "s": 1.0})
        rgb = accent_fix(tuple(round(x * 255) for x in colorsys.hsv_to_rgb(a["h"], a["s"], 1.0)))
        d = self.d
        self.card((10, 56, W - 10, 92))
        d.ellipse((20, 62, 44, 86), fill=rgb)
        self.t((54, 74), "#" + "".join(f"{x:02X}" for x in rgb), F(13, "b"), FG, "lm")
        d.rounded_rectangle((W - 92, 64, W - 20, 84), radius=10, fill=tuple(round(x * 0.8) for x in rgb))
        lum = (0.2126 * rgb[0] * 0.8 + 0.7152 * rgb[1] * 0.8 + 0.0722 * rgb[2] * 0.8) / 255
        self.t((W - 56, 74), "Button", F(10, "b"), (4, 20, 15) if lum > 0.38 else (255, 255, 255), "mm")
        X0, X1 = 10, W - 10
        self.t((X0 + 2, 104), "Color", F(10), DIM, "lm")
        sw = (X1 - X0) / self.HUES
        for i in range(self.HUES):
            x = X0 + i * sw
            d.rectangle((x, 112, x + sw + 0.5, 138), fill=tuple(round(c * 255) for c in colorsys.hsv_to_rgb(i / (self.HUES - 1) * 0.96, 1, 1)))
            self.btn((x, 108, x + sw, 142), lambda i=i: (a.__setitem__("h", i / (self.HUES - 1) * 0.96), setattr(self, "dirty", True)))
        hi = min(self.HUES - 1, max(0, round(a["h"] / 0.96 * (self.HUES - 1))))
        d.rounded_rectangle((X0 + hi * sw - 1, 109, X0 + hi * sw + sw + 1, 141), radius=3, outline=(255, 255, 255), width=2)
        self.t((X0 + 2, 154), "Strength", F(10), DIM, "lm")
        sw2 = (X1 - X0) / self.SHADES
        for j in range(self.SHADES):
            ss = 0.3 + 0.7 * j / (self.SHADES - 1)
            x = X0 + j * sw2
            d.rectangle((x, 162, x + sw2 + 0.5, 188), fill=accent_fix(tuple(round(c * 255) for c in colorsys.hsv_to_rgb(a["h"], ss, 1.0))))
            self.btn((x, 158, x + sw2, 192), lambda ss=ss: (a.__setitem__("s", ss), setattr(self, "dirty", True)))
        sj = min(self.SHADES - 1, max(0, round((a["s"] - 0.3) / 0.7 * (self.SHADES - 1))))
        d.rounded_rectangle((X0 + sj * sw2 - 1, 159, X0 + sj * sw2 + sw2 + 1, 191), radius=3, outline=(255, 255, 255), width=2)

        def typed(txt):
            v = tuple(int(txt[i:i + 2], 16) for i in (0, 2, 4))
            self.set_accent("custom", accent_fix(v))
            self.back()  # on to the accent list: the keyboard has already stepped back to this page

        def use():
            self.set_accent("custom", rgb)
            self.back()
        self.rows(194, H, [("link", "Type a hex code", "", lambda: self.open_kb("hex", "Color code", "".join(f"{x:02X}" for x in rgb), 6, typed, min_len=6)),
                           ("btn", "Use this color", use, "pri")])

    def v_dash(self):
        self.header("Dashboard")

        def setc(k, v):
            self.cfg[k] = v
            self.save()
            self.dirty = True
        self.rows(56, H, [("seg", "Clocks on home", ["One", "Two"], "Two" if self.cfg["two_clocks"] else "One", lambda o: setc("two_clocks", o == "Two")),
                          ("link", "Second clock", self.cfg["clock2"][0], lambda: self.go("clock_pick")),
                          ("toggle", "24-hour time", self.cfg["h24"], lambda: setc("h24", not self.cfg["h24"])),
                          ("link", "Switch to stock screen", "", lambda: self.confirm(
                              "Switch to the stock screen?", "Hold the power button for 1 second to come back.", "Switch",
                              lambda: subprocess.Popen([TOGGLE, "off"], start_new_session=True))),
                          ("note", "Brightness, passcode and wake screen are under More › Display and Security.")])

    def v_clock_pick(self):
        self.header("Second clock")

        def pick(n, tz):
            self.cfg["clock2"], self.cfg["two_clocks"] = [n, tz], True
            self.save()
            self.back()
        rows = []
        for n, tz in CLOCKS:
            tm, ap = self.tfmt(tz)
            rows.append(("link", n, ("✓ " if self.cfg["clock2"][0] == n else "") + f"{tm} {ap}".strip(), lambda n=n, tz=tz: pick(n, tz)))
        self.rows(56, H, rows)

    # ---- settings sections ----
    def open_set(self, key):
        self.sel["set"] = key
        self.go("set")

    def set_rows(self, key):
        c = self.cfg

        def setc(k, v):
            c[k] = v
            self.save()
            self.dirty = True
            if k == "always_on":
                lib.stock_set("ALWAYS_ON", "1" if v else "0")
            elif k == "auto_lock" and v:  # None = Never: not written to stock yet (encoding unconfirmed)
                lib.stock_set("AUTO_LOCK_TIME", str(v))
        if key == "clients":
            cl = self.g("clients", [])

            def open_(x):
                self.sel["client"] = x
                self.go("client")
            acl = self.g("acl")
            nb = sum(1 for x in cl if is_blocked(acl, x["mac"]))
            return "Clients", [("head", f"{sum(1 for x in cl if x['online'])} online · {len(cl)} known" + (f" · {nb} blocked" if nb else ""))] + \
                [("link", x["name"], "Blocked" if is_blocked(acl, x["mac"]) else fmt_bytes(x["bytes"]) if x["online"] else "Offline",
                  lambda x=x: open_(x)) for x in cl]
        if key == "internet":
            sim, rep = self.g("sim", {}), self.g("rep", {})
            now = lib.get_wan_conn_type(self.g("cell", {})) or "None"
            return "Internet", [("value", "Using now", now),
                                ("value", "Mobile (" + self.active_sim()["name"] + ")", "Airplane" if sim.get("airplane") else "Data on" if self.data_on() else "Data off"),
                                ("value", "Wi-Fi (" + (rep.get("ssid") or "none") + ")", "Connected" if rep.get("connected") else "Off"),
                                ("value", "Ethernet", "Up" if lib.ubus_call("network.interface.wan", "status").get("up") else "No cable"),
                                ("note", "The router uses Wi-Fi or Ethernet first and falls back to mobile data. Change the order in the admin panel.")]
        if key == "network":
            ip = lib.get_system_info().get("lan_ip", "")
            port = next((p for p in (self.g("ports") or {}).get("ports", []) if p.get("support_wan") == "1"), None)
            rows = []
            if port:
                cur = port.get("mode", "lan")

                def eth(label):
                    m = "wan" if label.startswith("WAN") else "lan"
                    if m == cur:
                        return
                    body = ("The port takes internet from a cable (modem or wall socket). " if m == "wan" else
                            "The port gives a wired device internet from this router. ") + \
                        "Anything plugged in disconnects briefly."
                    self.confirm(f"Use the Ethernet port as {m.upper()}?", body, "Switch", lambda: self.work("Switching Ethernet port", lambda: set_eth_mode(m), ("ports",)))
                rows += [("head", "Ethernet port"),
                         ("seg", "Use the port for", ["WAN · internet in", "LAN · devices"], "WAN · internet in" if cur == "wan" else "LAN · devices", eth),
                         ("value", "Cable", "Connected" if lib.ubus_call("network.interface.wan", "status").get("up") else "Not connected")]
            rows += [("head", "Router"), ("value", "Router IP address", ip),
                     ("note", f"IP address, DHCP and VLAN settings are in the admin panel at {ip}.")]
            return "Network", rows
        if key == "display":
            def bright(o):
                setc("bright", o)
                set_brightness(o)
            return "Display", [("seg", "Brightness", ["Low", "Medium", "High"], c["bright"], bright),
                               ("link", "Accent color", "Custom" if c["accent"] == "custom" else c["accent"], lambda: self.go("accent")),
                               ("toggle", "24-hour time", c["h24"], lambda: setc("h24", not c["h24"])),
                               ("value", "Time zone", tz_label(lib.uci_get("system.@system[0].zonename", "") or c["tz"])),
                               ("seg", "When the screen wakes, show", ["Clock", "Status"], c["wake"], lambda o: setc("wake", o)),
                               ("link", "Personal signature", c["sig"] or "None", lambda: self.open_kb(
                                   "sig", "Personal signature", c["sig"], 24, lambda s: setc("sig", s.strip()))),
                               ("note", "Your signature shows on the home and lock screens."),
                               ("seg", "Wallpaper", ["Earth", "Plain", "Your own"], c["wallpaper"], lambda o: setc("wallpaper", o)),
                               ("seg", "Show wallpaper on", ["Lock screen", "Lock + Home"], c["wall_on"], lambda o: setc("wall_on", o)),
                               ("note", "Your own: copy a photo to /root/e5ui/wallpaper.jpg (or .png). It's cropped to fit the screen."
                                if not any(p.exists() for p in CUSTOM_WALLS) or c["wallpaper"] != "Your own"
                                else "Using your photo from /root/e5ui.")]
        if key == "security":
            def passcode():
                if c["pass_on"]:
                    setc("pass_on", False)
                elif c["pin"]:
                    setc("pass_on", True)
                else:
                    self.pinbuf = ""
                    self.go("pin")
            al = {30: "30 s", 60: "1 min", 300: "5 min", None: "Never"}
            return "Security", [("toggle", "Screen passcode", c["pass_on"], passcode),
                                ("link", "Change passcode", "Set" if c["pin"] else "Not set", lambda: (setattr(self, "pinbuf", ""), self.go("pin"))),
                                ("seg", "Auto lock after", list(al.values()), al.get(c["auto_lock"], "1 min"),
                                 lambda o: setc("auto_lock", {v: k for k, v in al.items()}[o])),
                                ("toggle", "Screen always on", c["always_on"], lambda: setc("always_on", not c["always_on"])),
                                ("note", "Auto lock turns the screen off; with a passcode on, it asks for it when you wake the screen."),
                                ("btn", "Lock screen now", self.lock_now, "pri")]
        if key == "power":
            b, lp, og = lib.get_battery(), self.g("lpm"), self.g("otg")
            if not lp or not og:
                return "Power & USB", [("note", "Reading power settings…")]
            keys_l = ("wifi_sleep_time", "phy_sleep_time", "auto_shutdown_time", "power_plugin_turnon", "system_sleep_enable")
            keys_o = ("protocol", "data_role", "pwr_role", "pwr_role_c2", "threshold")

            def setp(field, val, label):
                cfg = {k: lp.get(k) for k in keys_l} | {field: val}
                self.work(label, lambda: gl_set("lpm", cfg), ("lpm",))

            def setu(field, val, label):
                cfg = {k: og.get(k) for k in keys_o if og.get(k) is not None} | {field: val}
                self.work(label, lambda: gl_set("otg", cfg), ("otg",))

            def picker(title, opts, cur, fn):
                return ("link", title, opt_label(opts, cur), lambda: self.open_pick(title, opts, cur, fn))
            protos = [(x["value"], x["label"]) for x in (self.g("usbp") or [])] or [("usb2.0", "USB 2.0"), ("usb3.1", "USB 3.1")]

            def proto(label):
                v = next(val for val, l in protos if l == label)
                if v == og.get("protocol"):
                    return
                body = ("USB 3 can interfere with 2.4 GHz Wi-Fi. " if v.startswith("usb3") else "") + \
                    "Connected USB devices disconnect briefly."
                self.confirm(f"Switch USB to {label}?", body, "Switch", lambda: setu("protocol", v, "Switching USB protocol"))
            return "Power & USB", [
                ("head", "Power"),
                ("toggle", "Power on with charger", bool(lp.get("power_plugin_turnon")),
                 lambda: setp("power_plugin_turnon", 0 if lp.get("power_plugin_turnon") else 1, "Saving")),
                ("toggle", "Auto standby when idle", bool(lp.get("system_sleep_enable")),
                 lambda: setp("system_sleep_enable", 0 if lp.get("system_sleep_enable") else 1, "Saving")),
                ("note", "Standby kicks in when networks are idle, no USB is plugged in and the repeater isn't in use."),
                picker("Wi-Fi idle timeout", IDLE_OPTS, lp.get("wifi_sleep_time"), lambda v: setp("wifi_sleep_time", v, "Saving")),
                picker("Ethernet idle timeout", IDLE_OPTS, lp.get("phy_sleep_time"), lambda v: setp("phy_sleep_time", v, "Saving")),
                picker("Auto power off", OFF_OPTS, lp.get("auto_shutdown_time"), lambda v: setp("auto_shutdown_time", v, "Saving")),
                ("head", "USB"),
                ("seg", "USB mode", [l for _, l in USB_MODES], opt_label(USB_MODES, og.get("data_role")),
                 lambda l: setu("data_role", next(v for v, x in USB_MODES if x == l), "Saving USB mode")),
                ("seg", "USB protocol", [l for _, l in protos], opt_label(protos, og.get("protocol")), proto),
                ("seg", "Data port power", [l for _, l in PWR_ROLES], opt_label(PWR_ROLES, og.get("pwr_role")),
                 lambda l: setu("pwr_role", next(v for v, x in PWR_ROLES if x == l), "Saving")),
                ("seg", "Power port power", [l for _, l in PWR_ROLES], opt_label(PWR_ROLES, og.get("pwr_role_c2")),
                 lambda l: setu("pwr_role_c2", next(v for v, x in PWR_ROLES if x == l), "Saving")),
                picker("Stop USB power below", [(str(v), f"{v}%") for v in range(0, 55, 5)], str(og.get("threshold", "0")),
                       lambda v: setu("threshold", v, "Saving")),
                ("note", "Output powers or charges a device from the router's battery. USB power output stops below this battery level."),
                ("head", "Battery"),
                ("value", "Battery", f"{b[0]}%" if b else "—"), ("value", "Charging", "Yes" if b and b[1] else "No")]
        if key == "agh":
            agh = self.g("agh")
            if not agh:
                return "AdGuard Home", [("note", "Reading AdGuard Home settings…")]
            en, dns = agh["enabled"], agh["dns"]

            def change(new_en, new_dns, label):
                body = "DNS restarts, so devices may lose internet for a few seconds."
                self.confirm(label + "?", body, "OK", lambda: self.work(label, lambda: set_agh(new_en, new_dns), ("agh",)), danger=not (new_en and new_dns))
            rows = [("toggle", "AdGuard Home", en, lambda: change(not en, dns if not en else False,
                                                                 "Turn AdGuard Home " + ("off" if en else "on")))]
            if en:
                rows.append(("toggle", "Block ads & trackers", dns, lambda: change(True, not dns,
                                                                                    ("Stop" if dns else "Start") + " blocking ads & trackers")))
            rows += [("value", "Status", "Blocking" if en and dns else "On, not blocking" if en else "Off"),
                     ("note", "Blocking makes AdGuard Home the DNS for every device on this router, so ads and trackers are "
                              "filtered out. Stats and filter lists are in the admin panel.")]
            return "AdGuard Home", rows
        if key == "account":
            return "GL.iNet Account", [("value", "Remote management", "On" if lib.uci_get("gl-cloud.@cloud[0].enable", "0") == "1" else "Off"),
                                       ("note", "Link the router in the GL.iNet app to manage it remotely.")]
        if key == "about":
            modem = lib.ubus_call("cellular.modem", "info", {"bus": "cpu"})
            t = lib.get_temp_c()
            up = lib.get_system_info().get("uptime_min", 0)
            return "About device", [("value", "Model", read("/tmp/sysinfo/model", "GL-E5800").split(",")[0]),
                                    ("value", "Firmware", read("/etc/glversion")), ("value", "Modem", f"{modem.get('vendor', '')} {modem.get('name', '')}".strip()),
                                    ("value", "CPU temperature", f"{t:.0f}°C" if t else "—"), ("value", "Uptime", f"{up // 60} h {up % 60} m"),
                                    ("value", "Admin panel", lib.get_system_info().get("lan_ip", ""))]
        return key, []

    def open_pick(self, title, opts, cur, fn):
        self.sel["pick"] = (title, opts, cur, fn)
        self.go("pick")

    def v_pick(self):
        title, opts, cur, fn = self.sel["pick"]
        self.header(title)

        def choose(v):
            self.back()
            if str(v) != str(cur):
                fn(v)
        self.rows(56, H, [("link", l, "✓" if str(v) == str(cur) else "", lambda v=v: choose(v)) for v, l in opts])

    def v_set(self):
        title, rows = self.set_rows(self.sel.get("set", "about"))
        self.header(title)
        self.rows(56, H, rows, "set_" + self.sel.get("set", ""))

    def v_client(self):
        x = self.sel.get("client") or {}
        x = next((c for c in self.g("clients", []) if c["mac"] == x.get("mac")), x)  # live values
        name = x.get("name", "")
        blocked = is_blocked(self.g("acl"), x.get("mac"))
        self.header(self.fit(name, F(14, "b"), 170))
        if blocked:
            act = lambda: self.work(f"Unblocking {name}", lambda: set_blocked(x["mac"], False), ("acl", "clients"))
        else:
            act = lambda: self.confirm(f"Block {name}?", "It's cut off from the main and guest Wi-Fi until you unblock it here or in the admin panel.",
                                       "Block", lambda: self.work(f"Blocking {name}", lambda: set_blocked(x["mac"], True), ("acl", "clients")), True)
        self.rows(56, H, [("value", "Status", "Blocked" if blocked else "Online" if x.get("online") else "Offline"),
                          ("value", "Connection", f"Wi-Fi {x.get('iface')}" if x.get("iface") else "Ethernet"),
                          ("value", "IP address", x.get("ip") or "—"), ("value", "Data used", fmt_bytes(x.get("bytes"))),
                          ("value", "Speed now", f"↓ {int(x.get('rx') or 0) * 8 / 1e6:.1f}  ↑ {int(x.get('tx') or 0) * 8 / 1e6:.1f} Mbps"),
                          ("btn", "Unblock this device" if blocked else "Block this device", act, "pri" if blocked else "danger")])

    def lock_now(self):
        self.locked, self.lock_stage = True, "face"
        self.dirty = True

    # ---- keypad / keyboard ----
    def keypad(self, y0, on_key, left="", dots=0, msg="", msg_col=DIM):
        cx = W / 2
        for i in range(4):
            x = cx - 30 + i * 20
            self.d.ellipse((x - 6, y0 - 6, x + 6, y0 + 6), outline=TEAL, width=2, fill=TEAL if i < dots else None)
        self.t((cx, y0 + 18), msg, F(9), msg_col, "mm")
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", left, "0", "⌫"]
        kw, kh, gap = 68, 44, 6
        for i, k in enumerate(keys):
            r, col = divmod(i, 3)
            x0, y = 12 + col * (kw + gap), y0 + 28 + r * (kh + gap)
            if not k:
                continue
            self.d.rounded_rectangle((x0, y, x0 + kw, y + kh), radius=8, fill=KEY)
            lbl = "Del" if k == "⌫" else k
            self.t((x0 + kw / 2, y + kh / 2), lbl, F(12 if len(lbl) > 1 else 20, "s"), FG, "mm")
            self.btn((x0 - 2, y - 2, x0 + kw + 2, y + kh + 2), lambda k=k: on_key(k))

    def keyboard(self, y0, on_char, on_del, letters_only=False, shift=False, digits=False, on_shift=None, on_mode=None,
                 on_space=None, kh=34):
        rows = ["1234567890", "-/:;()$&@#", ".,?!_+=*%"] if digits else ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
        for ri, row in enumerate(rows):
            n = len(row)
            kw = 21
            x = (W - (n * kw + (n - 1) * 2)) / 2
            y = y0 + ri * (kh + 3)
            for ch in row:
                c = ch.upper() if shift and not digits else ch
                self.d.rounded_rectangle((x, y, x + kw, y + kh), radius=5, fill=KEY)
                self.t((x + kw / 2, y + kh / 2), c, F(13, "s"), FG, "mm")
                self.btn((x - 1, y - 1.5, x + kw + 1, y + kh + 1.5), lambda c=c: on_char(c))
                x += kw + 2
        y = y0 + 3 * (kh + 3)
        items = []
        if not letters_only:
            items += [("aA", 32, on_shift, shift), ("abc" if digits else "123", 36, on_mode, False)]
        items += [("space", 0, on_space or (lambda: on_char(" ")), False), ("Del", 44, on_del, False)]
        fixed = sum(w for _, w, _, _ in items) + 2 * (len(items) - 1)
        flex = W - 16 - fixed
        x = 8
        for label, w, fn, on in items:
            w = w or flex
            self.d.rounded_rectangle((x, y, x + w, y + kh), radius=5, fill=TEAL2 if on else KEY)
            self.t((x + w / 2, y + kh / 2), label, F(10, "s"), FG, "mm")
            self.btn((x - 1, y - 1.5, x + w + 1, y + kh + 1.5), fn)
            x += w + 2
        return y + kh

    def open_kb(self, target, title, text, maxlen, on_done, min_len=0):
        self.kb = {"target": target, "title": title, "text": text, "max": maxlen, "done": on_done, "min": min_len, "shift": False, "digits": False}
        self.go("kb")

    def v_kb(self):
        kb = self.kb
        self.header(self.fit(kb["title"], F(12, "b"), 180))
        self.card((8, 58, W - 8, 86), r=8)
        shown = "•" * len(kb["text"]) if kb["target"] == "pin" else kb["text"]  # a SIM PIN is never shown on screen
        self.t((16, 72), self.fit(shown, F(13, "s"), W - 40) if shown else "", F(13, "s"), FG, "lm")
        x = 16 + self.d.textlength(self.fit(shown, F(13, "s"), W - 40), font=F(13, "s")) + 1
        self.d.line([(x, 65), (x, 80)], fill=TEAL)
        hint = f"{len(kb['text'])} / {kb['max']} characters" if kb["target"] in ("sig", "ssid") else \
            (f"{len(kb['text'])} digits (4 to 8)" if kb["target"] == "pin" else
             (f"{len(kb['text'])} / 6 digits (0-9, A-F), like 4FD1B5" if kb["target"] == "hex" else
              f"At least {kb['min']} characters" if len(kb["text"]) < kb["min"] else ""))
        self.t((12, 94), hint, F(8), DIM, "lm")

        def add(ch):
            if kb["target"] == "pin" and not ch.isdigit():
                return  # PINs are digits only
            if kb["target"] == "hex":
                ch = ch.upper()
                if ch not in "0123456789ABCDEF":
                    return  # a color code is 6 hex digits
            kb["text"] = (kb["text"] + ch)[:kb["max"]]
            self.dirty = True

        def flip(k):
            kb[k] = not kb[k]
            self.dirty = True
        end = self.keyboard(104, add, lambda: (kb.__setitem__("text", kb["text"][:-1]), setattr(self, "dirty", True)),
                            shift=kb["shift"], digits=kb["digits"], on_shift=lambda: flip("shift"), on_mode=lambda: flip("digits"))
        ok = len(kb["text"]) >= kb["min"]
        self.d.rounded_rectangle((8, end + 6, W - 8, end + 38), radius=10, fill=TEAL2 if ok else TGOFF)
        self.t((W / 2, end + 22), "Save" if kb["target"] in ("sig", "ssid") else "Unlock" if kb["target"] == "pin" else "Use color" if kb["target"] == "hex" else "Connect", F(12, "b"), ON_ACCENT if ok else DIM, "mm")

        def done():
            if ok:
                text = kb["text"]
                self.back()
                kb["done"](text)
        self.btn((8, end + 6, W - 8, end + 38), done)

    def v_pin(self):
        self.header("New passcode")

        def key(k):
            if k == "⌫":
                self.pinbuf = self.pinbuf[:-1]
            else:
                self.pinbuf += k
                if len(self.pinbuf) == 4:
                    self.cfg["pin"], self.cfg["pass_on"] = self.pinbuf, True
                    self.save()
                    self.say("Passcode set")
                    self.back()
            self.dirty = True
        self.keypad(78, key, "", len(self.pinbuf), "Choose 4 digits")

    # ---- lock screen ----
    def unlock_start(self):
        if self.cfg["pass_on"] and self.cfg["pin"]:
            self.lock_stage, self.ubuf, self.uerr = "pad", "", ""
        else:
            self.locked = False
            self.tab("home")
        self.dirty = True

    def unlock_key(self, k):
        if k == "Back":
            self.lock_stage, self.ubuf = "face", ""
        elif self.lock_until > time.time():
            return
        elif k == "⌫":
            self.ubuf = self.ubuf[:-1]
        else:
            self.ubuf += k
            if len(self.ubuf) == 4:
                if self.ubuf == self.cfg["pin"]:
                    self.locked, self.tries, self.uerr = False, 0, ""
                    self.tab("home")
                else:
                    self.tries += 1
                    if self.tries >= 5:
                        self.lock_until, self.tries, self.uerr = time.time() + 30, 0, ""
                    else:
                        self.uerr = f"Wrong passcode · {5 - self.tries} tries left"
                self.ubuf = ""
        self.dirty = True

    def lock_info(self, y0):
        """See-through card listing what's in use: internet source, mobile carrier, VPN, AdGuard."""
        sim, rep, cell = self.g("sim", {}), self.g("rep", {}), self.g("cell", {})
        conn = lib.get_wan_conn_type(cell) if cell else None
        tech = (lib.get_cell_signal(cell) if cell else (0, ""))[1]
        if conn == "Repeater":
            internet = "Wi-Fi · " + (rep.get("ssid") or "")
        elif conn == "Ethernet":
            internet = "Ethernet"
        elif conn:
            internet = "Mobile · " + conn
        else:
            internet = "Offline"
        name = self.active_sim()["name"]
        mobile = "Airplane mode" if sim.get("airplane") else f"{name} · {tech or 'on'}" if self.data_on() else f"{name} · data off"
        wga = self.g("wga")
        agh = self.g("agh") or {}
        rows = [("Internet", internet), ("Mobile", mobile), ("VPN", vpn_label(self.peer_name(wga)) if wga else "Off"),
                ("AdGuard", "Blocking ads" if agh.get("enabled") and agh.get("dns") else "On, not blocking" if agh.get("enabled") else "Off")]
        box = (12, y0, W - 12, y0 + 10 + 20 * len(rows))
        region = self.img.crop(box)
        self.img.paste(Image.blend(region, Image.new("RGB", region.size, (8, 10, 14)), 0.6), box[:2])
        self.d = ImageDraw.Draw(self.img)
        self.d.rounded_rectangle(box, radius=10, outline=(52, 60, 72), width=1)
        for i, (k, v) in enumerate(rows):
            y = y0 + 15 + i * 20
            self.t((22, y), k, F(10), DIM, "lm")
            on = v not in ("Off", "Offline") and "data off" not in v
            self.t((W - 22, y), self.fit(v, F(10, "s"), 135), F(10, "s"), FG if on else DIM, "rm")

    def v_lock(self):
        wall = wallpaper(self.cfg["wallpaper"], 0.35)
        if wall:
            self.img.paste(wall)
        else:
            self.d.rectangle((0, 0, W, H), fill=(11, 14, 19))
        self.status_bar()
        if self.lock_stage == "pad":
            self.t((W / 2, 40), "Enter passcode", F(13, "b"), FG, "mm")
            left = self.lock_until - time.time()
            msg, col = (f"Too many tries · wait {int(left) + 1} s", RED) if left > 0 else (self.uerr, RED)
            self.keypad(66, self.unlock_key, "Back", len(self.ubuf), msg, col)
            return
        tm, ap = self.tfmt(self.home_zone())
        today = datetime.now(self.home_zone()).strftime("%A, %b %-d")
        if self.cfg["wake"] == "Status":
            self.t((12, 52), tm, F(28, "b"), FG, "ls")
            self.t((16 + self.d.textlength(tm, font=F(28, "b")), 52), ap, F(11, "b"), DIM, "ls")
            self.t((W - 12, 36), today, F(10), DIM, "rm")
            if self.cfg["sig"]:
                self.t((W - 12, 49), self.fit(self.cfg["sig"], F(10, "s"), 110), F(10, "s"), TEAL, "rm")
            a = self.active_sim()
            self.card((12, 62, W - 12, 100))
            self.t((22, 75), f"{a['name']} · {a['used']:.1f} GB used", F(10, "b"), FG, "lm")
            self.t((W - 22, 75), f"of {a['cap']} GB" if a["cap"] else "", F(10), DIM, "rm")
            self.bar(22, 86, W - 22, a["pct"])
            cl = self.g("clients", [])
            self.card((12, 106, 116, 148))
            self.t((21, 117), "DEVICES", F(9, "s"), DIM, "lm")
            self.t((21, 135), str(sum(1 for c in cl if c["online"])), F(15, "b"), FG, "lm")
            self.card((124, 106, W - 12, 148))
            self.t((133, 117), "SPEED", F(9, "s"), DIM, "lm")
            self.t((133, 136), f"↓ {self.mon['down']:.1f}  ↑ {self.mon['up']:.1f}", F(10, "b"), FG, "lm")
            self.lock_info(156)
        else:
            f = F(54, "b")
            wt = self.d.textlength(tm, font=f) + (self.d.textlength(ap, font=F(13, "b")) + 4 if ap else 0)
            x = (W - wt) / 2
            self.t((x, 98), tm, f, FG, "ls")
            if ap:
                self.t((x + self.d.textlength(tm, font=f) + 4, 98), ap, F(13, "b"), DIM, "ls")
            self.t((W / 2, 112), today, F(12), DIM, "mm")
            if self.cfg["sig"]:
                self.t((W / 2, 132), self.fit(self.cfg["sig"], F(11, "s"), 200), F(11, "s"), TEAL, "mm")
            self.lock_info(148)
        chips = []
        u = len(self.unread())
        if u:
            chips.append((f"{u} new texts", "warn"))
        wx = self.g("wx")
        if wx:
            chips.append((f"{round(wx['now'])}° {self.cfg['city']['name']}", "gray"))
        f9 = F(9, "b")
        widths = [self.d.textlength(s, font=f9) + 10 for s, _ in chips]
        x = (W - (sum(widths) + 6 * (len(chips) - 1))) / 2
        for (s, k), w in zip(chips, widths):
            self.chip(x, 248, s, k, anchor_right=False)
            x += w + 6
        self.chevron(W / 2, 278, DIM, left=False)
        self.t((W / 2, 296), "Swipe up to enter passcode" if self.cfg["pass_on"] and self.cfg["pin"] else "Swipe up to unlock", F(10, "s"), DIM, "mm")
        self.btn((0, 268, W, H), self.unlock_start)

    # ---- overlays ----
    def v_sheet(self):
        s = self.sheet
        self.img.paste(Image.blend(self.img, Image.new("RGB", (W, H), (5, 7, 10)), 0.72))
        self.d = ImageDraw.Draw(self.img)
        lines = wrap(self.d, s["body"], F(10), W - 28)
        tl = wrap(self.d, s["title"], F(13, "b"), W - 28)
        h = 14 + 18 * len(tl) + 14 * len(lines) + 58
        y0 = H - h
        self.d.rounded_rectangle((0, y0, W, H + 14), radius=14, fill=(26, 32, 41))
        y = y0 + 14
        for line in tl:
            self.t((12, y), line, F(13, "b"), FG)
            y += 18
        for line in lines:
            self.t((12, y), line, F(10), DIM)
            y += 14
        y += 6
        bw = (W - 32) / 2
        self.hits = [((0, 0, W, y0), lambda: None)]
        for i, (label, fn, style) in enumerate((("Cancel", None, ""), (s["yes"], s["fn"], "danger" if s["danger"] else "pri"))):
            x0 = 12 + i * (bw + 8)
            edge, fill, col = {"pri": (TEAL2, TEAL2, ON_ACCENT), "danger": (REDLINE, None, RED)}.get(style, ((57, 66, 79), None, FG))
            self.d.rounded_rectangle((x0, y, x0 + bw, y + 38), radius=10, outline=edge, fill=fill)
            self.t((x0 + bw / 2, y + 19), label, F(12, "b"), col, "mm")

            def act(fn=fn):
                self.sheet = None
                self.dirty = True
                if fn:
                    fn()
            self.btn((x0, y, x0 + bw, y + 38), act)

    def v_busy(self):
        label, _ = self.busy
        self.img.paste(Image.blend(self.img, Image.new("RGB", (W, H), BG), 0.94))
        self.d = ImageDraw.Draw(self.img)
        self.spinner(W / 2, 130, 14)
        for i, line in enumerate(wrap(self.d, label, F(13, "b"), W - 40)[:2]):
            self.t((W / 2, 166 + i * 18), line, F(13, "b"), FG, "mm")
        self.hits = []

    # ---- swipe-down quick panel ----
    PANEL_H = 242

    def close_panel(self):
        self.panel_open, self.panel_drag = False, None
        self.dirty = True

    def panel_vpn_toggle(self):
        """Quick-panel VPN tile: the same "Use" switch as the VPN page."""
        self.vpn_switch()

    def panel_wifi_toggle(self):
        """Quick on/off for the router's own Wi-Fi (both main bands). Remembers which bands were on."""
        w = self.g("wifi", {})
        bands = [(k, lab) for k, key, lab in (("wifi2g", "2g", "2.4 GHz"), ("wifi5g", "5g", "5 GHz")) if w.get(key)]
        if any(k in self.pending for k in ("wifi2g", "wifi5g")):
            return
        if bands:
            def off():
                self.cfg["wifi_last"] = [k for k, _ in bands]
                self.save()
                for k, lab in bands:
                    self.bg_wifi(k, f"{lab} Wi-Fi", False)
            self.confirm("Turn Wi-Fi off?", "Every device on your Wi-Fi disconnects. If you're managing the router over Wi-Fi, you'll lose access.",
                         "Turn off", off, True)
        else:
            names = {"wifi2g": "2.4 GHz", "wifi5g": "5 GHz"}
            for k in self.cfg.get("wifi_last") or ["wifi2g", "wifi5g"]:
                if k in names:
                    self.bg_wifi(k, f"{names[k]} Wi-Fi", True)

    def draw_panel(self, extent):
        """Slide-down quick settings: tiles for the things people reach for most, plus brightness."""
        PH = self.PANEL_H
        sim, rep = self.g("sim", {}), self.g("rep", {})
        air = sim.get("airplane", False)
        saved_d, saved_hits = self.d, self.hits
        panel = Image.new("RGB", (W, PH), BG)
        self.d, self.hits = ImageDraw.Draw(panel), []
        d = self.d
        d.line([(0, PH - 1), (W, PH - 1)], fill=EDGE)
        d.rounded_rectangle((W / 2 - 18, PH - 9, W / 2 + 18, PH - 6), radius=2, fill=KEY)
        tm, ap = self.tfmt(self.home_zone())
        self.t((12, 14), f"{tm} {ap}".strip() + "  ·  " + datetime.now(self.home_zone()).strftime("%a, %b %-d"), F(10, "s"), DIM, "lm")
        reboot = lambda: self.confirm("Reboot the router?", "Wi-Fi and internet drop for about a minute.", "Reboot",
                                      lambda: self.power("Restarting", lib.reboot_router), True)
        shutdown = lambda: self.confirm("Shut down the router?", "Everything goes offline until you press the power button.",
                                        "Shut down", lambda: self.power("Shutting down", lib.shutdown_router), True)
        agh = self.g("agh") or {}
        blocking = bool(agh.get("enabled") and agh.get("dns"))

        def agh_toggle():
            if not agh:
                self.say("AdGuard Home is still loading")
                return
            new_dns = not blocking
            label = ("Stop" if blocking else "Start") + " blocking ads & trackers"
            self.confirm(label + "?", "DNS restarts, so devices may lose internet for a few seconds.", "OK",
                         lambda: self.work(label, lambda: set_agh(True, new_dns), ("agh",)), danger=blocking)
        wf = self.g("wifi", {})
        wifi_on = bool(wf.get("2g") or wf.get("5g"))
        wifi_busy = any(k in self.pending for k in ("wifi2g", "wifi5g"))
        tiles = [
            ("Data", self.data_on(), "On" if self.data_on() else "Off", self.toggle_data, False),
            ("Wi-Fi", wifi_on, "Working…" if wifi_busy else "On" if wifi_on else "Off", self.panel_wifi_toggle, False),
            ("VPN", bool(self.g("wga")), "On" if self.g("wga") else "Off", self.panel_vpn_toggle, False),
            ("Ad block", blocking, "Blocking" if blocking else "Off" if agh else "Loading", agh_toggle, False),
            ("Airplane", air, "On" if air else "Off", self.toggle_air, False),
            ("Network", bool(rep.get("connected")), self.fit(rep.get("ssid") or "Not joined", F(8), 58), lambda: self.tab("wifi"), False),
            ("Screen off", False, "Sleep", self.screen_off, False),
            ("Reboot", False, "", reboot, True),
            ("Shut down", False, "", shutdown, True),
        ]
        tw, th, gap = 70, 46, 6
        for i, (label, on, sub, fn, danger) in enumerate(tiles):
            r, c = divmod(i, 3)
            x0, y0 = 12 + c * (tw + gap), 28 + r * (th + gap)
            self.card((x0, y0, x0 + tw, y0 + th), fill=TEALBG if on else SURF, edge=REDLINE if danger else TEAL2 if on else EDGE, r=10)
            if sub:
                self.t((x0 + tw / 2, y0 + 17), self.fit(label, F(10, "b"), tw - 8), F(10, "b"), TEAL if on else FG, "mm")
                self.t((x0 + tw / 2, y0 + 33), sub, F(8), DIM, "mm")
            else:
                self.t((x0 + tw / 2, y0 + th / 2), self.fit(label, F(8, "b"), tw - 6), F(8, "b"), RED if danger else FG, "mm")
            self.btn((x0, y0, x0 + tw, y0 + th), lambda fn=fn: (self.close_panel(), fn()))
        cur = self.cfg["bright"]
        by = 28 + 3 * (th + gap) + 2
        self.t((14, by + 8), "BRIGHTNESS", F(8, "s"), DIM, "lm")
        self.card((12, by + 18, W - 12, by + 46), r=8)
        bw = (W - 24 - 4) / 3
        for i, o in enumerate(("Low", "Medium", "High")):
            bx = 14 + i * bw
            if o == cur:
                d.rounded_rectangle((bx, by + 20, bx + bw, by + 44), radius=6, fill=TGOFF)
            self.t((bx + bw / 2, by + 32), o, F(10, "s"), FG if o == cur else DIM, "mm")
            self.btn((bx, by + 18, bx + bw, by + 46), lambda o=o: (self.cfg.__setitem__("bright", o), self.save(), set_brightness(o)))
        local_hits = self.hits
        self.d, self.hits = saved_d, saved_hits
        shade = max(0.0, min(1.0, extent / PH))
        self.img.paste(Image.blend(self.img, Image.new("RGB", (W, H), (5, 7, 10)), 0.6 * shade))
        y = int(extent - PH)
        self.img.paste(panel, (0, y))
        self.d = ImageDraw.Draw(self.img)
        self.hits = [((0, 0, W, H), self.close_panel)] + [((x0, y0 + y, x1, y1 + y), fn) for (x0, y0, x1, y1), fn in local_hits]

    # ---- frame ----
    def render(self):
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)
        self.hits, self.scroll_area = [], None
        if self.locked:
            self.v_lock()
        else:
            if self.view == "home" and self.cfg["wall_on"] == "Lock + Home":
                wall = wallpaper(self.cfg["wallpaper"], 0.55)
                if wall:
                    self.img.paste(wall)
            shift = TOP if self.view != "home" else 0  # Home already lays out its own gap
            self.yshift = shift
            self.content_bottom = (276 if self.view in TABS else H) - shift
            getattr(self, "v_" + self.view, self.v_home)()
            if shift:
                body = self.img.crop((0, 22, W, H - shift))
                self.img = Image.new("RGB", (W, H), BG)
                self.img.paste(body, (0, 22 + shift))
                self.d = ImageDraw.Draw(self.img)
                self.hits = [((x0, y0 + shift, x1, y1 + shift), fn) for (x0, y0, x1, y1), fn in self.hits]
            self.status_bar()
            if self.view in TABS:
                self.tabbar()
            if self.toast and time.time() - self.toast_t < 3:
                w = self.d.textlength(self.toast, font=F(10, "s")) + 20
                self.d.rounded_rectangle(((W - w) / 2, 248, (W + w) / 2, 270), radius=11, fill=(46, 54, 66))
                self.t((W / 2, 259), self.toast, F(10, "s"), FG, "mm")
        if self.locked:
            self.panel_open, self.panel_drag = False, None
        elif self.panel_drag is not None or self.panel_open:
            self.draw_panel(self.PANEL_H if self.panel_drag is None else self.panel_drag)
        if self.sheet:
            self.v_sheet()
        if self.busy:
            self.v_busy()
        if not self.preview:
            write_frame(self.img)
        return self.img

    # ---- input / loop ----
    drag_key = None

    def tap(self, x, y):
        for (x0, y0, x1, y1), fn in reversed(self.hits):
            if x0 <= x <= x1 and y0 <= y <= y1:
                try:
                    fn()
                except Exception as e:
                    self.say(f"Error: {e}"[:40])
                self.dirty = True
                return

    def handle_touch(self, now):
        ts = lib.touch_state
        with ts.lock:
            active, rel, dy, have = ts.active, ts.release_pending, ts.dy, ts.have_pos
            x, y, rdx, rdy = ts.down_x, ts.down_y, ts.release_dx, ts.release_dy
            ts.release_pending = False
        if active:
            self.last_touch = now
            blocked = self.busy or self.sheet or self.locked
            if not blocked and not self.panel_open and y < 28 and dy > 6:  # pull down from the status bar
                self.panel_drag = min(self.PANEL_H, max(0, dy))
                self.dirty = True
            elif not blocked and self.panel_open and dy < -6:  # push the open panel back up
                self.panel_drag = max(0, self.PANEL_H + dy)
                self.dirty = True
            if self.panel_drag is not None:
                pass
            elif self.scroll_area and abs(dy) > 8 and not self.busy and not self.sheet and not self.locked:
                key, y0, y1, maxoff = self.scroll_area
                if maxoff and y0 <= y <= y1:
                    self.drag_key, self.drag_dy = key, dy
                    self.dirty = True
        if rel:
            self.last_touch = now
            if self.busy:
                pass
            elif self.panel_drag is not None:
                self.panel_open = self.panel_drag > self.PANEL_H * 0.4
                self.panel_drag = None
            elif self.drag_key:
                self.scroll[self.drag_key] = max(0, self.scroll.get(self.drag_key, 0) - rdy)
                if self.scroll_area:
                    self.scroll[self.drag_key] = min(self.scroll_area[3], self.scroll[self.drag_key])
            elif self.locked and self.lock_stage == "face" and rdy < -30:
                self.unlock_start()
            elif have and abs(rdx) <= TAP and abs(rdy) <= TAP:
                self.tap(x, y)
            self.drag_key, self.drag_dy = None, 0
            self.dirty = True

    def tick(self, now):
        if os.path.exists(lib.SWITCH_REQUEST_FILE):  # power button held: confirm before leaving
            try:
                os.remove(lib.SWITCH_REQUEST_FILE)
            except OSError:
                pass
            # shown over the lock screen if locked; unlocking here would skip the passcode
            self.confirm("Switch to the stock screen?", "Hold the power button for 1 second to come back.", "Switch",
                         lambda: subprocess.Popen([TOGGLE, "off"], start_new_session=True))
        if now - self.mon["t"] >= 2:
            self.mon["net"], down, up = lib.sample_bandwidth(self.mon["net"])
            self.mon["cpu"], cpu = lib.sample_cpu(self.mon["cpu"])
            self.mon["down"], self.mon["up"], self.mon["cpu_pct"] = down or 0.0, up or 0.0, cpu or 0.0
            self.mon["t"] = now
        if self.view == "city" and self.q.strip() and self.q.strip() != self.geo_q and now - self.q_t > 0.7 and not self.geo_busy:
            q = self.q.strip()
            self.geo_busy = True

            def run():
                try:
                    res = geo_search(q)
                    if q == self.q.strip():
                        self.geo = res
                    self.geo_q = q
                finally:
                    self.geo_busy = False
                    self.dirty = True
            threading.Thread(target=run, daemon=True).start()
        self.remember_data()
        al = self.cfg["auto_lock"]
        if al and not self.cfg["always_on"] and not self.busy and not self.speed.running and now - self.last_touch > al:
            self.last_touch = now
            self.screen_off()

    def warm_up(self, seconds=120, every=5):
        """We start early in boot, before modem/Wi-Fi/network are ready. For the first couple of minutes,
        re-run any job that hasn't produced data yet instead of waiting out its normal interval."""
        end = time.time() + seconds
        while time.time() < end and not lib._stop:
            time.sleep(every)
            for name, *_ in self.r._jobs:
                if self.r.get(name) is None or (name in ("sims", "sim") and time.time() < self.boot_until):
                    self.r.request(name)  # sims/sim: pick up the modem redialing as soon as it happens

    def run(self):
        signal.signal(signal.SIGTERM, lib._on_term)
        signal.signal(signal.SIGINT, lib._on_term)
        threading.Thread(target=lib._touch_reader, daemon=True).start()
        self.r.start()
        threading.Thread(target=self.warm_up, daemon=True).start()
        set_brightness(self.cfg["bright"]) if not BL_SAVED.exists() else None
        last_draw, last_ver, asleep = 0.0, -1, False
        while not lib._stop:
            now = time.time()
            if lib.is_screen_asleep():
                if not asleep:
                    asleep = True
                with lib.touch_state.lock:
                    lib.touch_state.release_pending = False
                self.remember_data()  # tick() doesn't run while asleep
                time.sleep(0.1)
                continue
            if asleep:
                asleep, self.locked, self.lock_stage = False, True, "face"
                self.last_touch, self.dirty = now, True
            self.handle_touch(now)
            self.tick(now)
            anim = self.busy or self.pending or self.speed.running or self.scanning or self.drag_key or self.geo_busy or self.lock_until > now or self.panel_drag is not None or (self.view == "esim" and (self.sel.get("esim") or {}).get("state") == "loading")
            due = self.dirty or self.r.version != last_ver or now - last_draw >= 1.0 or (anim and now - last_draw >= 1 / 15)
            if due:
                last_ver, self.dirty = self.r.version, False
                try:
                    self.render()
                except Exception as e:
                    print("render error:", repr(e), file=sys.stderr)
                    self.view, self.stack, self.sheet = "home", [], None
                last_draw = now
            time.sleep(0.015)
        USAGE.save()
        sys.exit(0)


def preview(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = App(preview=True)
    for name, fn in app.r._jobs and [(j[0], j[1]) for j in app.r._jobs]:
        try:
            app.r.put(name, fn())
        except Exception as e:
            print("job", name, e)
    app.r.put("sms", app.g("sms", []))
    app.mon["net"], _, _ = lib.sample_bandwidth(None)
    time.sleep(1)
    app.tick(time.time())
    shots = []

    def shot(name, view=None, **kw):
        if view:
            app.view = view
        for k, v in kw.items():
            setattr(app, k, v)
        shots.append((name, app.render().copy()))
    shot("home", "home")
    shot("sim", "sim")
    shot("sim_detail", "sim_detail")
    real_sims = app.g("sims") or {}
    app.r.put("sims", dict(real_sims, locks={"1": {"status": 3, "pin_counter": 2}, "2": {"status": 6, "pin_counter": None}}))  # example: preview only
    shot("sim_locked", "sim")
    app.sel["unlock_slot"], app.sel["unlock_name"] = 1, "SIM1"
    shot("sim_unlock", "sim_unlock")
    app.kb = {"target": "pin", "title": "SIM1 PIN", "text": "12", "max": 8, "done": None, "min": 4, "shift": False, "digits": True}
    shot("pin_kb", "kb")
    app.r.put("sims", dict(real_sims, locks={"1": {"status": 4, "pin_counter": 0}}))
    shot("sim_puk", "sim_unlock")
    app.r.put("sims", real_sims)
    app.r.put("siminfo", {"slot": 1, "phone": "+639170001111", "iccid": "89630000000000000000", "operator": "Example", "type": "SIM", "net_type": "Auto",  # invented values
                          "radio": "4G LTE", "roaming": "Off", "apn": "internet", "ip": "10.20.30.40", "gateway": "10.20.30.1", "dns1": "8.8.8.8", "dns2": "1.1.1.1",
                          "band": "B1 (20 MHz)", "cell_id": "1234567", "tac": "AB12", "pci": "95", "arfcn": "150", "rsrp": "-107 dBm", "rsrq": "-13 dB",
                          "rssi": "-73 dBm", "sinr": "14 dB", "model": "Example Modem X1", "firmware": "X1.2.3-example-build-20260101-long-example-v", "imei": "350000000000000"})
    shot("sim_info", "sim_info")
    app.scroll["sim_info"] = 900
    shot("sim_info_2", "sim_info")
    app.scroll["sim_info"] = 0
    shot("sim_detail_link", "sim_detail")
    shot("accent", "accent")
    app.set_accent("custom", (255, 140, 66))  # example custom color, preview only
    shot("accent_custom_set", "accent")
    app.open_accent_custom()
    shot("accent_custom", "accent_custom")
    app.cfg["accent"] = "Blue"
    apply_accent(accent_current(app.cfg))
    shot("home_blue", "home")
    shot("sim_blue", "sim")
    app.cfg["accent"] = "Pink"
    apply_accent(accent_current(app.cfg))
    shot("home_pink", "home")
    shot("bands_pink", "bands")
    app.cfg["accent"], app.cfg["accent_custom"] = "Teal", None
    apply_accent(accent_current(app.cfg))
    app.sel.pop("bands", None)
    shot("bands_off", "bands")
    st = app.g("bands")
    if st:
        app.sel["bands"] = {"slot": st["slot"], "enable": True, "mode": "AUTO", "list": {"NR-SA": [78, 77], "NR-NSA": [78, 77, 41], "LTE": [1, 3, 8, 41]}}  # example choice, preview only
        shot("bands_on", "bands")
        app.scroll["bands"] = 400
        shot("bands_on_2", "bands")
        app.scroll["bands"] = 0
        app.sel["bands"] = {"slot": st["slot"], "enable": True, "mode": "NR5G", "list": {"NR-SA": [], "NR-NSA": [], "LTE": []}}
        shot("bands_warn", "bands")
        app.sel.pop("bands", None)
    real_slot2 = (app.g("sims") or {}).get("slot2_type")
    app.r.put("sims", dict(app.g("sims") or {}, slot2_type=1))
    app.sel["esim"] = {"state": "loading"}
    shot("esim_loading", "esim")
    app.sel["esim"] = {"state": "error", "msg": "The eSIM isn't responding. It may still be starting. Try again in a minute."}
    shot("esim_error", "esim")
    app.sel["esim"] = {"state": "ok", "info": {"eid": "89049032000000000000000000000000", "iccid": "8963000000000000001", "imsi": "515000000000001", "cos": "COS 3.1.2-example",  # invented values
                                              "free_kb": 214, "count": 3, "profiles": [
                                                  {"iccid": "8963000000000000001", "supplier": "Example Telco", "name": "Travel plan", "enabled": True},
                                                  {"iccid": "8963000000000000002", "supplier": "Other Telco", "name": "", "enabled": False}]}}
    shot("esim_info", "esim")
    app.scroll["esim"] = 300
    shot("esim_info_2", "esim")
    app.scroll["esim"] = 0
    app.r.put("sims", dict(app.g("sims") or {}, slot2_type=real_slot2 if real_slot2 is not None else 0))
    shot("failover", "failover")
    app.r.put("failover", dict(app.g("failover") or {}, enable_switch=True, enable_timing=True, slot_priority=[2, 1], hour="06", min="30"))
    shot("failover_on", "failover")  # example values: only the preview, nothing is sent to the router
    shot("firmware", "firmware")
    shot("more_fw", "more")
    app.r.put("fw", {"current": "4.10.4", "new": "4.10.5", "prompt": True,  # example update: only the preview
                     "note": "# V4.10.5\r\n\r\n## Overview\r\n\r\n**Please upgrade.**\r\n\r\n* **Security**: Fixed an example issue.\r\n* **Wi-Fi**: Example improvement."})
    shot("firmware_new", "firmware")
    shot("wifi", "wifi")
    app.scan = scan_nets()
    app.scroll["wifi_rows"] = 160
    real_wband = app.g("wband")
    app.scroll["wifi_rows"] = 520
    shot("wifi_band_live", "wifi")
    app.r.put("wband", {"mutex": ["5g", "6g"], "usemode": "auto", "useband": "5g", "present": {"2g": "wifi0", "5g": "wifi1", "6g": "wifi2"}, "env": 1, "repeater_band": ""})  # example
    shot("wifi_band_example", "wifi")
    app.sel["pick"] = ("Wi-Fi band", band_options((app.g("wband") or {})), "auto", lambda v: None)
    shot("pick_band", "pick")
    app.r.put("wband", real_wband if real_wband is not None else {})
    app.scroll["wifi_rows"] = 160
    shot("wifi_mid", "wifi")
    app.scroll["wifi_rows"] = 440
    shot("wifi_5g", "wifi")
    app.scroll["wifi_rows"] = 0
    radio5 = (app.g("radios") or {}).get("wifi1") or {}
    app.sel["pick"] = ("5 GHz TX power", [(v, v) for v in App.TXPOWERS], radio5.get("txpower"), lambda v: None)
    shot("pick_txpower", "pick")
    app.sel["pick"] = ("5 GHz channel", channel_options(dict(radio5, repeater=False)), 0, lambda v: None)
    shot("pick_channel", "pick")
    shot("join", "join")
    shot("saved", "saved")
    app.sel["saved_ssid"] = (app.g("rep") or {}).get("ssid") or "Space Rice"
    shot("saved_net", "saved_net")
    shot("vpn", "vpn")
    shot("vpn_loc", "vpn_loc")
    shot("vpn_opts", "vpn_opts")
    shot("more", "more")
    app.scroll["more"] = 400
    shot("more_bottom", "more")
    shot("texts", "texts")
    from datetime import datetime as _dt
    example_sent = [  # example data: preview only
        {"name": "s2", "to": "09179998888", "body": "Running late, start without me.", "status": 4, "sent": _dt(2026, 11, 25, 10, 30)},
        {"name": "s1", "to": "+639171234567", "body": "On my way, see you in 10 minutes.", "status": 2, "sent": _dt(2026, 11, 25, 9, 0)},
        {"name": "s3", "to": "+639175550000", "body": "Did you get my message about tomorrow?", "status": 5, "sent": _dt(2026, 11, 24, 18, 15)}]
    real_sent = app.g("smssent")
    app.r.put("smssent", example_sent)
    shot("texts_sent_link", "texts")
    shot("sent_list", "sent")
    app.sel["sent_msg"] = example_sent[2]
    shot("sent_failed", "sent_text")
    app.r.put("smssent", real_sent if real_sent is not None else [])
    shot("weather", "weather")
    app.q = "par"
    app.geo, app.geo_q = geo_search("par"), "par"
    shot("city", "city")
    shot("monitor", "monitor")
    shot("fx", "fx")
    shot("fx_home", "fx_home")
    shot("fx_cmp", "fx_cmp")
    app.cfg["home_fx"], app.cfg["fx"] = "JPY", "PHP"  # example choice, preview only
    shot("fx_jpy", "fx")
    app.cfg["home_fx"], app.cfg["fx"] = "IDR", "USD"
    shot("fx_idr", "fx")
    app.cfg["home_fx"], app.cfg["fx"] = "PHP", "USD"
    shot("dash", "dash")
    shot("clock_pick", "clock_pick")
    app.sel["share_set"] = "main"
    shot("share", "share")
    msgs = app.g("sms", [])
    if msgs:
        app.sel["sms"] = msgs[0]
        shot("text", "text")
    for k in ("clients", "internet", "network", "display", "security", "power", "agh", "account", "about"):
        app.sel["set"] = k
        shot("set_" + k, "set")
    cl = app.g("clients", [])
    if cl:
        app.sel["client"] = cl[0]
        shot("client", "client")
    app.sel["pick"] = ("Wi-Fi idle timeout", IDLE_OPTS, 0, lambda v: None)
    shot("pick", "pick")
    app.pinbuf = "12"
    shot("pin", "pin")
    app.kb = {"target": "sig", "title": "Personal signature", "text": "Holden", "max": 24, "done": None, "min": 0, "shift": True, "digits": False}
    shot("kb", "kb")
    app.cfg["sig"] = "Holden"
    shot("lock_clock", locked=True)
    app.cfg["wall_on"] = "Lock + Home"
    app.locked = False
    shot("home_wall", "home")
    app.cfg["wall_on"] = "Lock screen"
    app.cfg["wake"] = "Status"
    shot("lock_status", locked=True)
    app.lock_stage, app.uerr = "pad", "Wrong passcode · 3 tries left"
    shot("lock_pad", locked=True)
    app.locked, app.lock_stage = False, "face"
    app.confirm("Switch to DITO (SIM2)?", "Mobile internet pauses while the modem reconnects (up to a minute).", "Switch", None)
    shot("sheet", "sim")
    app.sheet, app.busy = None, ("Switching to DITO", time.time())
    shot("busy", "sim")
    cols = 6
    rows_n = (len(shots) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 250 + 10, rows_n * 330 + 10), (40, 40, 40))
    for i, (n, im) in enumerate(shots):
        im.save(os.path.join(outdir, n + ".png"))
        sheet.paste(im, (10 + (i % cols) * 250, 10 + (i // cols) * 330))
    sheet.save(os.path.join(outdir, "contact.png"))
    print("wrote", len(shots), "screens")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        preview(sys.argv[sys.argv.index("--preview") + 1])
    else:
        App().run()
