"""Router helpers extracted from gl-e5800-dashboard (MIT). Generated -- edit app.py, not this."""
import json
import math
import os
import random
import re
import signal
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FB_PATH = "/dev/fb0"


FONT_DIR = "/etc/gl_screen/language/ttf"


STATE_DIR = Path("/root/e5ui/cache")


FX_CACHE = STATE_DIR / "fx_cache.json"


MCC_COUNTRY = {
    "234": "UK", "235": "UK",
    "460": "China", "461": "China",
    "454": "Hong Kong", "466": "Taiwan",
    "206": "Belgium", "208": "France", "204": "Netherlands",
    "262": "Germany", "222": "Italy", "214": "Spain", "268": "Portugal",
    "240": "Sweden", "238": "Denmark", "242": "Norway", "244": "Finland",
    "250": "Russia", "302": "Canada", "310": "USA", "311": "USA",
    "440": "Japan", "441": "Japan", "450": "South Korea", "505": "Australia",
    "228": "Switzerland", "226": "Romania", "231": "Slovakia",
}


_fonts = {}


def font(name, size):
    key = (name, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(f"{FONT_DIR}/{name}.ttf", size)
    return _fonts[key]


def run_checked(cmd, timeout=8):
    """(ok, stdout). ok is False when the command could not run at all
    (binary missing, timeout, ...) or exited non-zero -- which is a
    different thing from a command that ran fine and printed nothing.
    run() collapses both to "" for the many callers that genuinely do not
    care; anything that would otherwise read a failure as a meaningful
    empty value must use this instead."""
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        return out.returncode == 0, out.stdout.strip()
    except Exception:
        return False, ""


def run(cmd, timeout=8):
    return run_checked(cmd, timeout)[1]


def ubus_call(obj, method, params=None):
    args = ["ubus", "call", obj, method]
    if params:
        args.append(json.dumps(params))
    out = run(args)
    try:
        return json.loads(out)
    except Exception:
        return {}


def uci_get(key, default=""):
    """`uci -q get` exits non-zero both for an absent key and for uci
    itself failing, so those two stay indistinguishable here -- callers
    that must tell them apart (get_wifi_radio_state) probe the section as
    well. `default` exists so a caller can at least choose which way an
    unreadable value falls."""
    ok, out = run_checked(["uci", "-q", "get", key])
    return out if ok else default


def uci_set(key, val):
    run(["uci", "set", f"{key}={val}"])
    run(["uci", "commit", key.split(".")[0]])


def get_router_zone():
    """The router's time zone name (system.get_timezone_config, what the stock Display page and clock follow), or None."""
    ok, res = gl_call("system", "get_timezone_config", {}, timeout=15)
    return (res or {}).get("zonename") if ok else None


# The stock screen keeps its settings in uci gl_screen.generic; the keys below mean the same on both screens.
STOCK_SCREEN = "gl_screen.generic."


def stock_get(key):
    return uci_get(STOCK_SCREEN + key, None)


def stock_set(key, val):
    uci_set(STOCK_SCREEN + key, val)


BACKLIGHT_PATH = "/sys/class/backlight/soc:backlight/brightness"


SWITCH_REQUEST_FILE = "/tmp/dashboard_ui_switch_request"


_asleep_cache = {"ts": 0.0, "val": False}


_ASLEEP_TTL = 0.4


def is_screen_asleep():
    """Cached for _ASLEEP_TTL: mode_live polls this every loop iteration
    (~80x/s), and re-opening a sysfs file that often is pure overhead on
    this SoC. 0.4s is far below any human-perceptible wake latency."""
    now = time.time()
    if now - _asleep_cache["ts"] < _ASLEEP_TTL:
        return _asleep_cache["val"]
    try:
        with open(BACKLIGHT_PATH) as f:
            val = f.read().strip() == "0"
    except Exception:
        val = False
    _asleep_cache["ts"] = now
    _asleep_cache["val"] = val
    return val


POWER_SUPPLY_DIR = "/sys/class/power_supply"


_battery_cache = {"ts": -1e9, "val": None}


_BATTERY_TTL = 15.0


def _read_sys(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def get_battery():
    """(percent, plugged_in) or None when there's no battery to report.

    Read from sysfs, not a ubus object -- the GL-E5800 exposes none for
    this: the fuel gauge is a `type=Battery` supply (cw221X-bat, with
    `capacity`) and the charger a separate `type=USB` supply whose
    `online` is 1 while a cable is in. Matched by type rather than by
    those driver names so a board revision with a different gauge chip
    still works. Cached like is_screen_asleep: draw_header runs on every
    frame of every panel, a battery level doesn't move in 15s."""
    now = time.time()
    if now - _battery_cache["ts"] < _BATTERY_TTL:
        return _battery_cache["val"]
    pct, plugged = None, False
    try:
        for name in os.listdir(POWER_SUPPLY_DIR):
            base = os.path.join(POWER_SUPPLY_DIR, name)
            typ = _read_sys(os.path.join(base, "type"))
            if typ == "Battery" and _read_sys(os.path.join(base, "present")) != "0":
                try:
                    pct = max(0, min(100, int(_read_sys(os.path.join(base, "capacity")))))
                except (TypeError, ValueError):
                    pass
            elif typ in ("USB", "Mains") and _read_sys(os.path.join(base, "online")) == "1":
                plugged = True
    except Exception:
        pass
    val = (pct, plugged) if pct is not None else None
    _battery_cache["ts"] = now
    _battery_cache["val"] = val
    return val


class Refresher:
    """Runs the periodic data pulls on one background thread and publishes
    the results, so the render loop only ever reads already-fetched
    values.

    Every one of these jobs used to be called straight from mode_live's
    idle branch. fetch_fx alone blocks for up to curl's --max-time (8s),
    and the weather tick does two of those back to back -- during which
    the loop drew nothing and read no touch events, i.e. the screen was
    genuinely frozen for up to ~16s at a time. The author had already
    diagnosed exactly this class of bug twice (see get_fx_history_cached
    and the repeater-scan thread) and moved those off the UI path; these
    were the ones left behind.

    Jobs are plain callables run in registration order; a job that raises
    keeps its previous value rather than taking the thread down."""

    def __init__(self):
        self.lock = threading.Lock()
        self._values = {}
        self._jobs = []          # [name, fn, interval, next_at]
        self._wake = threading.Event()
        # Bumped whenever any value is published, so the render loop can
        # skip re-reading (and re-deriving from) every value on each ~12ms
        # pass when nothing has changed -- most jobs run every 5-30s.
        self.version = 0

    def add(self, name, fn, interval, initial=None, run_now=True, none_ok=False):
        """none_ok: a result of None is a real answer (e.g. "no VPN connected") and is published, instead of
        being treated like a failed run that keeps the previous value."""
        with self.lock:
            self._values[name] = initial
        self._jobs.append([name, fn, interval, 0.0 if run_now else time.time() + interval, none_ok])

    def get(self, name, default=None):
        with self.lock:
            val = self._values.get(name)
        return default if val is None else val

    def put(self, name, value):
        """Publish a value fetched outside the worker (e.g. the fresh SIM
        state a verified toggle just read), so the render loop's next
        get() can't hand back the older periodic result in its place."""
        with self.lock:
            self._values[name] = value
            self.version += 1

    def request(self, name):
        """Ask for one job to run as soon as the worker next wakes."""
        for job in self._jobs:
            if job[0] == name:
                job[3] = 0.0
        self._wake.set()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not _stop:
            now = time.time()
            sleep_for = 5.0
            for job in self._jobs:
                name, fn, interval, next_at, none_ok = job
                if now >= next_at:
                    ok = True
                    try:
                        value = fn()
                    except Exception:
                        value, ok = None, False
                    job[3] = time.time() + interval
                    if value is not None or (none_ok and ok):
                        with self.lock:
                            self._values[name] = value
                            self.version += 1
                else:
                    sleep_for = min(sleep_for, next_at - now)
            self._wake.wait(max(0.05, sleep_for))
            self._wake.clear()


def fetch_fx(force=False):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cached = None
    if FX_CACHE.exists():
        try:
            cached = json.loads(FX_CACHE.read_text())
        except Exception:
            cached = None
    stale = force or cached is None or "rates" not in cached or (time.time() - cached.get("ts", 0)) > 6 * 3600
    if stale:
        raw = run(["curl", "-s", "--max-time", "6" if force else "8", "https://open.er-api.com/v6/latest/USD"])
        try:
            data = json.loads(raw)
            cached = {"ts": time.time(), "rates": data["rates"]}
            FX_CACHE.write_text(json.dumps(cached))
        except Exception:
            pass
    return cached


def _rate_vs_usd(code, rates):
    """fx["rates"] is base=USD. The API may or may not include "USD": 1.0
    itself in that dict -- treat USD as 1.0 regardless."""
    if code == "USD":
        return 1.0
    return rates.get(code)


def rate_between(from_code, to_code, fx):
    if not fx:
        return None
    if from_code == to_code:
        return 1.0
    rates = fx.get("rates", {})
    rf = _rate_vs_usd(from_code, rates)
    rt = _rate_vs_usd(to_code, rates)
    if rf is None or rt is None:
        return None
    return rt / rf


_WMO_MAP = {
    0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "cloud_sun"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"), 48: ("Fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm", "storm"), 99: ("Thunderstorm", "storm"),
}


def wmo_info(code):
    return _WMO_MAP.get(code, ("Unknown", "cloud"))


def uv_category(uv):
    if uv is None:
        return None
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very High"
    return "Extreme"


def aqi_category(aqi):
    if aqi is None:
        return None
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy (SG)"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


SMS_SPOOL_DIRS = ["/etc/spool/sms/incoming", "/etc/spool/sms/checked"]


def _parse_sms_file(path):
    """smstools3's header is always plain ASCII, but the body's actual byte
    encoding depends on the `Alphabet` header -- confirmed live against a
    real received message: `Alphabet: UCS2` bodies are raw big-endian
    UTF-16 bytes (not UTF-8 text, not hex-encoded), while plain-ASCII
    messages come through as `Alphabet: UTF-8`. Blindly UTF-8-decoding a
    UCS2 body (the original approach) corrupts every non-ASCII message --
    confirmed by a real device test that showed Chinese text as mojibake."""
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    # Accept CRLF as well as LF as the header/body separator -- a spool
    # file written with CRLF contains no "\n\n" at all, so the old check
    # put the whole file in the header and left every body empty.
    sep, sep_len = raw.find(b"\r\n\r\n"), 4
    if sep == -1:
        sep, sep_len = raw.find(b"\n\n"), 2
    header_bytes, body_bytes = (raw, b"") if sep == -1 else (raw[:sep], raw[sep + sep_len:])
    header = header_bytes.decode("ascii", errors="replace")
    fields = {}
    for line in header.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    alphabet = fields.get("alphabet", "").upper()
    if alphabet in ("UCS2", "UCS-2", "UTF-16", "UTF16"):
        body = body_bytes.decode("utf-16-be", errors="replace")
    else:
        body = body_bytes.decode("utf-8", errors="replace")
    sent_raw = fields.get("sent", "")
    try:
        sent = datetime.strptime(sent_raw, "%y-%m-%d %H:%M:%S")
    except Exception:
        sent = None
    return {
        "from": fields.get("from", "Unknown"),
        "sent": sent,
        "sent_raw": sent_raw,
        "body": body.strip(),
    }


def get_sms_messages():
    messages = []
    for d in SMS_SPOOL_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in p.iterdir():
            if not f.is_file():
                continue
            msg = _parse_sms_file(f)
            if msg:
                msg["name"] = f.name                          # stock's id for the message (modem.get_sms_list `name`)
                msg["status"] = 0 if p.name == "incoming" else 1  # stock status: 0 unread, 1 read
                messages.append(msg)
    messages.sort(key=lambda m: m["sent"] or datetime.min, reverse=True)
    return messages


def delete_sms(name=None, scope=10):
    """The stock Texts delete: modem.remove_sms {bus, name, scope}. scope 10 = the one text `name`; 1 = every read text.
    (12 / 13 = all received / all sent in the stock web UI; not used here.)"""
    params = {"bus": "cpu", "scope": scope}
    if name:
        params["name"] = name
    return gl_call("modem", "remove_sms", params, timeout=30)[0]


def get_sent_sms():
    """Texts we sent, newest first, from the stock list (modem.get_sms_list): every message that isn't received (status 0/1), as the stock
    Texts page splits them. status 3/4 = still sending, 5 = failed, anything else (2) = sent. `phone_number` is the recipient.
    A failed read raises, so the screen keeps the list it had."""
    ok, res = gl_call("modem", "get_sms_list", {"bus": "cpu"}, timeout=20)
    if not ok or not isinstance(res, dict):
        raise RuntimeError("get_sms_list failed")
    out = []
    for m in res.get("list") or []:
        if m.get("status") in (0, 1) or not m.get("name"):
            continue
        try:
            when = datetime.strptime(m.get("date") or "", "%y-%m-%d %H:%M:%S")
        except ValueError:
            when = None
        out.append({"name": m["name"], "to": m.get("phone_number") or "", "body": m.get("body") or "", "status": m.get("status"), "sent": when})
    out.sort(key=lambda m: m["sent"] or datetime.min, reverse=True)
    return out


def mark_sms_read(name):
    """What the stock screen does when you open an unread text: modem.set_sms {bus, name, status: 1}."""
    return gl_call("modem", "set_sms", {"bus": "cpu", "name": name, "status": 1}, timeout=30)[0]


def get_firmware_update():
    """The stock firmware check: upgrade.check_firmware_online (what the stock web UI calls when it loads; the router also
    runs it by itself, "Automatic Update Check"). It answers {current_version, current_type, current_compile_time}, plus
    version_new, prompt, release_note when a newer firmware exists. Returns {"current", "new" (None if up to date), "prompt",
    "note"}. A failed check raises, so the screen keeps the last answer."""
    ok, res = gl_call("upgrade", "check_firmware_online", {}, timeout=40)
    if not ok or not isinstance(res, dict) or not (res.get("current_version") or res.get("version_new")):
        raise RuntimeError("check_firmware_online failed")
    try:
        installed = Path("/etc/glversion").read_text().strip()
    except OSError:
        installed = ""
    return {"current": res.get("current_version") or installed,
            "new": res.get("version_new") or None, "prompt": bool(res.get("prompt")),
            "note": res.get("release_note") or ""}


def skip_firmware_update():
    """The stock "Skip This Version" / "Ignore": upgrade.set_config {prompt: false} (stops the prompt, keeps the version known)."""
    return gl_call("upgrade", "set_config", {"prompt": False}, timeout=20)[0]


def _wg_policy_rule_id():
    """The route_policy section that actually carries the VPN connection.
    Matched by section TYPE ("=rule"), not a hardcoded name or the
    `@rule[0]` positional index some earlier exploration used directly --
    both work on this hardware today (there's exactly one), but matching
    by type is what survives the stock app adding a second rule later
    without silently starting to write the wrong one. Route_policy also
    has `=default`/`=rule_process`/`=policy` sections that must NOT match
    here; only a bare "=rule" line does."""
    out = run(["uci", "show", "route_policy"])
    for line in out.splitlines():
        if line.endswith("=rule"):
            return line.split("=", 1)[0][len("route_policy."):]
    return None


WG_CONNECT_TIMEOUT = 30.0

def vpn_log(msg):
    """One line to the router log (`logread | grep e5vpn`), so a VPN problem can be traced afterwards. Carries
    ids and statuses only, never keys."""
    try:
        subprocess.run(["logger", "-t", "e5vpn", msg[:300]], timeout=3)
    except Exception:
        pass


_last_wg_seen = [None]


def gl_call(module, func, params, timeout=60):
    """(ok, result) from one of GL's service modules through `ubus call gl-session call`: the same entry point
    the stock touchscreen and web UI use, run inside GL's own service environment (not a stand-in). The call
    blocks until GL has applied the change. ok is False on a ubus failure or an err_msg reply."""
    try:
        out = subprocess.run(["ubus", "-t", str(timeout), "call", "gl-session", "call",
                              json.dumps({"module": module, "func": func, "params": params})],
                             capture_output=True, text=True, timeout=timeout + 5)
        if out.returncode != 0:
            return False, None
        res = json.loads(out.stdout)
    except Exception:
        return False, None
    body = res.get("result", res) if isinstance(res, dict) else res
    ok = not (isinstance(res, dict) and (res.get("error") or res.get("err_msg")
                                         or (isinstance(body, dict) and body.get("err_msg"))))
    if module == "vpn-client" and func in ("add_tunnel", "set_tunnel", "stop"):
        vpn_log(f"{func} {json.dumps(params, separators=(',', ':'))} -> ok={ok} {json.dumps(body)[:120]}")
    return ok, body


def _gl_wg_args(peer_id):
    """The {group_id, peer_id, type} GL's vpn-client wants, from a "peer_NNNN" uci section id."""
    num = peer_id[len("peer_"):] if peer_id and peer_id.startswith("peer_") else peer_id
    group = uci_get(f"wireguard.{peer_id}.group_id") if peer_id else None
    if not num or not group:
        return None
    return {"group_id": int(group) if str(group).isdigit() else group,
            "peer_id": int(num) if str(num).isdigit() else num, "type": "wireguard"}


def _gl_vpn_tunnels(strict=False):
    ok, res = gl_call("vpn-client", "get_tunnel", {}, timeout=20)
    if strict and not ok:
        raise RuntimeError("get_tunnel failed")
    t = (res or {}).get("tunnels") if ok else None
    if isinstance(t, dict):
        t = list(t.values())
    return [x for x in (t or []) if isinstance(x, dict) and "tunnel_id" in x]


WG_CONNECT_POLL = 1.0


def get_wireguard_peers():
    """One `uci show wireguard` call for the whole list, not one `uci get`
    per peer just to read its name. With a couple of hand-added peers the
    difference is invisible; with a few hundred imported servers, the old
    approach meant a few hundred sequential subprocess spawns just to
    build this list -- a real, felt delay both on the background
    refresher's 120s poll and, worse, on the tap that opens this screen,
    which used to fetch synchronously on the touch-handling thread.
    `uci show` already dumps every key for the whole package in one pass;
    the peers' .name lines are pulled straight out of that same output.
    Each peer is also tagged with a best-guess country (the same
    heuristic OpenClash node names already go through) so the WireGuard
    screen can offer quick country-filter chips without a second pass."""
    out = run(["uci", "show", "wireguard"])
    sections, names = [], {}
    for line in out.splitlines():
        if line.startswith("wireguard.") and line.endswith("=peers"):
            sections.append(line[len("wireguard."):-len("=peers")])
        elif line.startswith("wireguard.") and ".name=" in line:
            key, _, value = line.partition("=")
            if key.endswith(".name"):
                section = key[len("wireguard."):-len(".name")]
                names[section] = value.strip().strip("'\"")
    peers = []
    for section in sections:
        name = names.get(section) or section
        peers.append({"id": section, "name": name, "country": guess_country_from_name(name)})
    return peers


def get_wireguard_active(strict=False):
    """"peer_NNNN" of the WireGuard server that is connected right now (matches get_wireguard_peers()'s ids), or
    None. Read the way the stock UI does: vpn-client's get_status lists each tunnel with its peer_id and a
    numeric status (1 connected, 2 connecting, absent/0 otherwise). Mid-connect counts as not connected yet."""
    ok, res = gl_call("vpn-client", "get_status", {}, timeout=15)
    if strict and not ok:
        raise RuntimeError("get_status failed")
    for e in ((res or {}).get("status_list") or []) if ok else []:
        if e.get("type") != "wireguard" or e.get("peer_id") in (None, ""):
            continue
        st = e.get("status")
        seen = json.dumps(e, sort_keys=True)
        if seen != _last_wg_seen[0]:  # log each change of the status entry, to learn what "connected" looks like
            _last_wg_seen[0] = seen
            vpn_log("status " + seen)
        if st == 1 or (st is None and e.get("enabled")
                       and ubus_call(f"network.interface.{e.get('via') or 'wgclient1'}", "status").get("up")):
            return f"peer_{e['peer_id']}"
    return None


def force_wireguard_off():
    """Backup when `stop` didn't take: ask GL to disable the tunnel, then as a last resort disable the policy rule
    and restart vpn-client (how the older firmware's rule was switched off)."""
    tunnels = _gl_vpn_tunnels()
    if tunnels and gl_call("vpn-client", "set_tunnel", {"enabled": False, "tunnel_id": tunnels[0]["tunnel_id"]})[0]:
        return True
    rule = _wg_policy_rule_id()
    if not rule:
        return False
    uci_set(f"route_policy.{rule}.enabled", "0")
    subprocess.Popen(["/etc/init.d/vpn-client", "restart"])
    return True


def _wg_via(peer_id):
    args = _gl_wg_args(peer_id)
    if not args:
        return None
    return {"type": "wireguard", "configs": [{"group_id": args["group_id"], "id_list": [args["peer_id"]]}]}


def get_vpn_tunnel():
    """The router's VPN tunnel as the stock dashboard shows it (None if none exists yet): its id and name, the
    "Use" switch (`enabled`), the server it points at (`peer`, a "peer_NNNN" id, kept even while switched off) and
    its settings."""
    ts = _gl_vpn_tunnels(strict=True)  # a failed read raises, so the screen keeps what it knew
    if not ts:
        return None
    t = ts[0]
    ids = ((((t.get("via") or {}).get("configs")) or [{}])[0]).get("id_list") or []
    o = t.get("options") or {}
    return {"id": t["tunnel_id"], "name": t.get("name") or "Tunnel", "enabled": bool(t.get("enabled")),
            "peer": f"peer_{ids[0]}" if ids else None, "mtu": o.get("mtu") or 0,
            "opts": {"killswitch": bool(t.get("killswitch")), "local_access": bool(o.get("local_access")),
                     "masq": bool(o.get("masq")), "service_policy": bool(o.get("service_policy"))}}


def set_vpn_enabled(tunnel_id, on):
    """The stock "Use" switch: set_tunnel {tunnel_id, enabled}. Never `stop`, so the tunnel keeps its server."""
    return gl_call("vpn-client", "set_tunnel", {"tunnel_id": tunnel_id, "enabled": bool(on)})[0]


def set_vpn_location(peer_id, tunnel_id=None):
    """The stock "Via" setting: point the tunnel at a server (set_tunnel {tunnel_id, via}); an enabled tunnel
    reconnects to it. With no tunnel yet, create one switched off (add_tunnel, as the stock "+ Add Tunnel")."""
    via = _wg_via(peer_id)
    if not via:
        return False
    if tunnel_id is not None:
        return gl_call("vpn-client", "set_tunnel", {"tunnel_id": tunnel_id, "via": via})[0]
    return gl_call("vpn-client", "add_tunnel", {"from": {"type": "default"}, "to": {"type": "default"}, "via": via,
                                                "name": "Tunnel 1", "enabled": False})[0]


def set_vpn_options(tunnel, **changes):
    """The stock tunnel Settings: set_options {tunnel_id, mtu, killswitch, local_access, masq, service_policy}."""
    o = dict(tunnel["opts"])
    o.update(changes)
    return gl_call("vpn-client", "set_options", {"tunnel_id": tunnel["id"], "mtu": tunnel.get("mtu") or 0, **o})[0]


def wait_for_wireguard_state(want_peer_id, timeout=WG_CONNECT_TIMEOUT, any_peer=False):
    """Blocks -- meant to run on a worker thread, not the render loop -- polling until the connected server matches
    what was just requested (want_peer_id=None waits for the connection to drop), or timeout. The stock UI waits
    about 5 s after a change before re-reading, so the first look is not instant."""
    deadline = time.time() + timeout
    time.sleep(2)
    while time.time() < deadline:
        active = get_wireguard_active()
        if active == want_peer_id or (any_peer and active):
            return active
        time.sleep(WG_CONNECT_POLL)
    return get_wireguard_active()


def get_sim_status(cfg):
    sims = ubus_call("cellular.sim", "info", {"bus": "cpu"}).get("sims", [])
    modem = ubus_call("cellular.modem", "status", {"bus": "cpu"})
    slot = str(modem.get("current_sim_slot", "1"))
    active = next((s for s in sims if str(s.get("slot")) == slot), None)
    traffic_mb = None
    if active:
        net = ubus_call("cellular.network", "status", {"bus": "cpu", "slot": int(slot)})
        for n in net.get("networks", []):
            if str(n.get("slot")) == slot:
                try:
                    traffic_mb = int(n["traffic_total"]) / 1024 / 1024
                except Exception:
                    pass
    country = None
    phone = None
    iccid = None
    roaming = False
    carrier = None
    if active:
        country = MCC_COUNTRY.get(active.get("mcc", ""), f"MCC {active.get('mcc', '?')}")
        phone = active.get("phone_number") or ""
        iccid = active.get("iccid")
        if iccid:
            roaming = get_roaming_config(iccid)
        # The serving network's name, not the SIM's home operator -- a
        # China Unicom SIM roaming in the UK reads "EE" here (confirmed
        # live), which is the one worth showing next to the signal.
        for s in ubus_call("cellular.sim", "status", {"bus": "cpu"}).get("sims", []):
            if str(s.get("slot")) == slot:
                carrier = (s.get("carrier") or s.get("name") or "").strip() or None

    # "sim_choice" reflects the UI's 2-way pick. SIM2 was removed from the
    # picker: it and eSIM both live on slot 2 on this hardware and both just
    # reorder slot priority to prefer slot 2, so there was no way to
    # actually select one over the other -- SIM2 was dead weight in the UI.
    #
    # This MUST be derived from `slot` (current_sim_slot -- what the modem
    # is actually running right now), not from get_slot_priority_config's
    # slot_priority list. Confirmed live on this device: priority is only
    # a *requested* preference and can read [1, 2] while the modem is
    # already sitting on slot 2 (its own backhaul logic reordering things,
    # or a switch still settling) -- the two genuinely diverge, and every
    # OTHER field on this screen (country, phone, iccid) already reads off
    # `slot`. Reading the toggle off priority instead showed "SIM1"
    # selected while the flag, phone number and data cap right next to it
    # were all slot 2's (eSIM) -- a self-contradicting screen.
    sim_choice = "sim1" if slot == "1" else "esim"

    data_iface = ubus_call("network.interface.modem_cpu", "status")
    data_up = bool(data_iface.get("up"))
    # "attached" (network registration -- SMS/calls) is a different thing
    # from "data_up" (a live PDP data session on modem_cpu): the modem can
    # be registered with the network without the data interface being up
    # at all, which is exactly the "receives SMS but not using cellular
    # for data" mode this is meant to represent. No direct ubus getter for
    # registration or airplane mode (cellular.modem only has a setter --
    # cellular_manager keeps the flag internally), so it's inferred from
    # whether cell_info currently reports any serving carrier at all (see
    # _get_active_cell_info).
    attached = is_cell_attached()
    # What the Cellular toggle shows: GL's own airplane-mode flag, the one
    # the stock screen's switch reads -- not inferred from registration
    # (no signal is not the same thing as switched off).
    airplane = get_airplane_mode()

    return {
        "slot": slot, "country": country, "phone": phone, "traffic_mb": traffic_mb,
        "cap_mb": cfg.get("data_cap_mb"), "sim_choice": sim_choice, "data_up": data_up,
        "iccid": iccid, "attached": attached, "roaming": roaming, "carrier": carrier,
        "airplane": airplane,
    }


def get_airplane_mode():
    """GL's airplane-mode flag via its own `system.get_airplane_mode` RPC
    (what the stock screen's Airplane Mode switch uses; backed by
    glconfig.general.airplane_mode). Falls back to reading that uci key."""
    ok, res = gl_lua_rpc(_GL_SYSTEM_RPC, "get_airplane_mode", {}, timeout=15)
    if ok and isinstance(res, dict) and "enable" in res:
        return _as_bool(res["enable"])
    return _as_bool(uci_get("glconfig.general.airplane_mode", "0"))


def is_cell_attached():
    return bool(_get_active_cell_info().get("mode"))


def is_cell_data_up():
    return bool(ubus_call("network.interface.modem_cpu", "status").get("up"))


def _as_bool(v):
    """cellular.sim's config values arrive as JSON booleans on 4.10.0, but
    a string "0" would read as True under plain bool() -- and a roaming
    toggle stuck showing ON is exactly the wrong way to be wrong."""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def get_roaming_config(iccid):
    return _as_bool(ubus_call("cellular.sim", "get_config", {"iccid": iccid}).get("roaming", False))


SIM_PIN_NEEDED, SIM_PUK_NEEDED = 3, 4  # cellular.sim status values the stock page treats as "enter PIN" / "locked, needs PUK"


def get_sim_locks():
    """{slot: {"status", "pin_counter", "iccid", "bus"}} for every SIM, from cellular.sim status (the stock websocket module copies
    `pin_counter` from this same object). status 3 = the SIM wants its PIN (pin_counter = attempts left), 4 = locked out, needs the
    PUK; 2/6/7/8 = ready, 0/5 = no SIM."""
    out = {}
    for s in ubus_call("cellular.sim", "status", {"bus": "cpu"}).get("sims", []):
        try:
            slot = int(s.get("slot"))
        except (TypeError, ValueError):
            continue
        out[slot] = {"status": s.get("status"), "pin_counter": s.get("pin_counter"), "iccid": s.get("iccid"), "bus": s.get("bus") or "cpu"}
    return out


def unlock_sim_pin(bus, iccid, pin):
    """The stock unlock: modem.set_sim_pin_code {bus, iccid, pin_code} (PIN 4-8 digits). A wrong PIN costs one of the SIM's 3 attempts,
    so callers must check get_sim_locks() first and never call this twice in a row. Returns (ok, reply). The PIN is not logged."""
    return gl_call("modem", "set_sim_pin_code", {"bus": bus, "iccid": iccid, "pin_code": pin}, timeout=45)


def get_sim_details():
    """Read-only details for the SIM in use, the fields of the stock "SIM n Details & Configs" page (labels from the stock screen):
    SIM (phone number, ICCID, operator, type), network (configured type, radio, roaming, APN, IP, gateway, DNS), cellular (band, cell id, TAC,
    PCI, ARFCN, RSRP/RSRQ/RSSI/SINR of the primary carrier) and modem (model, firmware, IMEI). Missing values are "". The stock max bit rate
    (AMBR) is left out: its unit isn't known. Raises if the router won't answer, so the screen keeps the last answer."""
    modem = ubus_call("cellular.modem", "status", {"bus": "cpu"})
    if not modem:
        raise RuntimeError("cellular.modem status failed")
    try:
        slot = int(modem.get("current_sim_slot", 1))
    except (TypeError, ValueError):
        slot = 1

    def mine(items):
        return next((x for x in items if str(x.get("slot")) == str(slot)), {})
    info = mine(ubus_call("cellular.sim", "info", {"bus": "cpu"}).get("sims", []))
    st = mine(ubus_call("cellular.sim", "status", {"bus": "cpu"}).get("sims", []))
    net = mine(ubus_call("cellular.network", "info", {"bus": "cpu", "slot": slot}).get("networks", []))
    raw = ubus_call("cellular.network", "cell_info", {"bus": "cpu", "slot": slot})
    cell = _parse_cell_signal(raw) if "signal" in raw else {}
    prim = next((s for s in sorted(raw.get("signal") or [], key=lambda s: _cell_int(s.get("ca")) or 0) if _cell_int(s.get("band"))), {})
    mi = ubus_call("cellular.modem", "info", {"bus": "cpu"})
    ipv4 = net.get("ipv4") or {}
    dns = [d for d in (ipv4.get("dns") or []) if d]

    def num(v, unit):  # the modem reports -32768 for "no value"
        n = _cell_int(v)
        return f"{n} {unit}" if n is not None and n > -30000 else ""
    label = cell_network_label(cell)
    bands = " + ".join(f"{c['band']}" + (f" ({c['mhz']:g} MHz)" if c.get("mhz") else "") for c in cell.get("carriers") or [])
    roaming = ""
    if info.get("iccid") or st.get("iccid"):
        roaming = "On" if get_roaming_config(info.get("iccid") or st.get("iccid")) else "Off"
    return {
        "slot": slot, "phone": info.get("phone_number") or net.get("phone_number") or "", "iccid": info.get("iccid") or st.get("iccid") or "",
        "operator": st.get("carrier") or net.get("carrier") or "", "type": "eSIM" if st.get("type") == 1 else "SIM",
        "net_type": str(net.get("network_mode") or "").title(), "radio": " ".join(label) if label else "", "roaming": roaming, "apn": net.get("apn") or st.get("apn") or "",
        "ip": ipv4.get("ip") or "", "gateway": ipv4.get("gateway") or "", "dns1": dns[0] if dns else "", "dns2": dns[1] if len(dns) > 1 else "",
        "band": bands, "cell_id": str(raw.get("cell_id") or ""), "tac": str(raw.get("tac") or ""), "pci": str(_cell_int(prim.get("pci")) if _cell_int(prim.get("pci")) is not None else ""),
        "arfcn": str(_cell_int(prim.get("earfcn")) if _cell_int(prim.get("earfcn")) is not None else ""),
        "rsrp": num(prim.get("rsrp"), "dBm"), "rsrq": num(prim.get("rsrq"), "dB"), "rssi": num(prim.get("rssi"), "dBm"), "sinr": num(prim.get("sinr"), "dB"),
        "model": f"{mi.get('vendor') or ''} {mi.get('name') or ''}".strip(), "firmware": mi.get("version") or "",
        "imei": next((x.get("imei") for x in mi.get("imei") or [] if str(x.get("slot")) == str(slot)), "") or "",
    }


BAND_GROUPS = ("NR-SA", "NR-NSA", "LTE")  # the stock web UI's three groups, in its order
NETWORK_MODES = (("Auto", "AUTO"), ("5G", "NR5G"), ("4G", "LTE"))


def get_band_state():
    """The stock web UI's "Network Type" + "Band Masking" for the SIM in use: modem.get_band_config {bus, slot} for the saved choice and
    cellular.modem info for the bands the modem supports. Returns {"slot", "supported": {group: [bands]}, "supports": bool, "enable": bool,
    "mode": "AUTO"|"NR5G"|"LTE", "list": {group: [bands]}}. With band masking off the router sends no list: it is empty here.
    Raises if the router won't answer, so the screen keeps the last answer."""
    modem = ubus_call("cellular.modem", "status", {"bus": "cpu"})
    try:
        slot = int(modem.get("current_sim_slot", 1))
    except (TypeError, ValueError):
        slot = 1
    mi = ubus_call("cellular.modem", "info", {"bus": "cpu"})
    ok, res = gl_call("modem", "get_band_config", {"bus": "cpu", "slot": slot}, timeout=30)
    if not mi or not ok or not isinstance(res, dict):
        raise RuntimeError("get_band_config failed")
    sup = mi.get("band") or {}
    have = res.get("band_list") or {}

    def ints(v):
        return sorted(int(x) for x in v or [] if str(x).lstrip("-").isdigit())
    return {"slot": slot, "supported": {g: ints(sup.get(g)) for g in BAND_GROUPS},
            "supports": bool(res.get("supports_band", any(sup.get(g) for g in BAND_GROUPS))),
            "enable": bool(res.get("band_enable")), "mode": res.get("network_mode") or "AUTO",
            "list": {g: ints(have.get(g)) for g in BAND_GROUPS}}


def set_band_config(slot, enable, mode, lists):
    """What the stock "Apply" sends: modem.set_band_config {bus, slot, band_enable, network_mode} plus, only when masking is on,
    band_list {LTE, NR-NSA, NR-SA} (the 5G lists are empty in 4G mode). The call blocks until the modem has applied it."""
    params = {"bus": "cpu", "slot": int(slot), "band_enable": bool(enable), "network_mode": mode}
    if enable:
        nr = mode != "LTE"
        params["band_list"] = {"LTE": list(lists.get("LTE", [])), "NR-NSA": list(lists.get("NR-NSA", [])) if nr else [],
                               "NR-SA": list(lists.get("NR-SA", [])) if nr else []}
    ok, _ = gl_call("modem", "set_band_config", params, timeout=90)
    return ok


def band_warnings(enable, mode, lists, supported):
    """The stock UI's red "Please select at least one of the allowed bands." flags (its `bandsWarning`), per group: {"LTE", "NR-NSA", "NR-SA"}.
    Apply stays off while any is set."""
    w = {"LTE": False, "NR-NSA": False, "NR-SA": False}
    if not enable:
        return w
    lte, nsa, sa = lists.get("LTE", []), lists.get("NR-NSA", []), lists.get("NR-SA", [])
    if mode == "LTE":
        nsa, sa = [], []
    for g in BAND_GROUPS:
        w[g] = bool(supported.get(g))
    if lte or (sa and not nsa):
        w = {g: False for g in BAND_GROUPS}
    elif nsa:
        w["NR-NSA"] = w["NR-SA"] = False
    if mode == "NR5G":
        w["NR-NSA"] = w["NR-SA"] = not (nsa or sa)
    return w


class EsimUnavailable(Exception):
    """The eSIM couldn't be read right now; the message is shown on screen as is."""


ESIM_TOTAL_KB = 360  # the stock page shows free / 360 KB


def esim_free_kb():
    """Free eSIM storage in KB, the way the stock page gets it: POST {method: info2, env: 1} to the local eSIM helper (what the web UI's /sdk/v1 proxies to),
    whose `extCardResource` (JSON text) holds `non_volatile_mem` in bytes. None if the helper doesn't answer."""
    try:
        out = subprocess.run(["curl", "-s", "-m", "30", "-X", "POST", "-H", "Content-Type: application/json", "-d",
                              json.dumps({"txId": "1", "method": "info2", "env": 1}), "http://127.0.0.1:3456/sdk/v1"],
                             capture_output=True, text=True, timeout=40).stdout
        ext = json.loads((json.loads(out).get("data") or {}).get("extCardResource") or "{}")
        return math.ceil(float(ext["non_volatile_mem"]) / 1024)
    except Exception:
        return None


def get_esim_info():
    """Read-only eSIM information, the fields of the stock eSIM page: modem.get_profile_info -> eid, iccid, imsi, profile_list (iccid, sp_name = supplier,
    nk_name = nickname, state 1 = enabled) and seed_profile_list; modem.get_cos_version {eid} -> cos (card OS); storage via esim_free_kb(). The eSIM helper can take
    a minute to answer and refuses while the card isn't ready, so this is only called when the screen is opened. Raises EsimUnavailable with a readable reason."""
    ok, res = gl_call("modem", "get_profile_info", {"bus": "cpu"}, timeout=45)
    res = res if isinstance(res, dict) else {}
    if not ok:
        code = res.get("err_code") or (res.get("error") or {}).get("code")
        if code == 20002057:  # "Curl request failed": the eSIM helper didn't answer in time
            raise EsimUnavailable("The eSIM isn't responding. It may still be starting. Try again in a minute.")
        raise EsimUnavailable("The router couldn't read the eSIM" + (f" (code {code})." if code else "."))
    eid = res.get("eid") or ""
    cos = ""
    if eid:
        ok2, r2 = gl_call("modem", "get_cos_version", {"eid": eid}, timeout=30)
        cos = ((r2 or {}).get("cos") or "") if ok2 else ""
    profiles = [{"iccid": p.get("iccid") or "", "supplier": p.get("sp_name") or "", "name": p.get("nk_name") or "", "enabled": p.get("state") == 1}
                for p in res.get("profile_list") or []]
    return {"eid": eid, "iccid": res.get("iccid") or "", "imsi": res.get("imsi") or "", "cos": cos, "free_kb": esim_free_kb() if eid else None,
            "profiles": profiles, "count": len(profiles) + len(res.get("seed_profile_list") or [])}


def get_failover():
    """The stock SIM failover settings: modem.get_slot_failover_config {bus} -> enable_switch, slot_priority [slot, ...],
    enable_timing + hour/min (scheduled switch to the preferred SIM), failover_interval (seconds), current_sim. A failed
    read raises, so the screen keeps what it knew."""
    ok, res = gl_call("modem", "get_slot_failover_config", {"bus": "cpu"}, timeout=20)
    if not ok or not isinstance(res, dict):
        raise RuntimeError("get_slot_failover_config failed")
    return res


def set_failover(cfg, **changes):
    """Save SIM failover the way the stock web dialog does: modem.set_slot_failover_config {bus, enable_switch} and, only when
    switched on, also slot_priority, enable_timing, hour, min. (Switching the SIM by hand is a different call, {current_sim}.)"""
    c = dict(cfg)
    c.update(changes)
    p = {"bus": "cpu", "enable_switch": bool(c.get("enable_switch"))}
    if p["enable_switch"]:
        p.update(slot_priority=list(c.get("slot_priority") or [1, 2]), enable_timing=bool(c.get("enable_timing")),
                 hour=str(c.get("hour") or "00").zfill(2), min=str(c.get("min") or "00").zfill(2))
    return gl_call("modem", "set_slot_failover_config", p, timeout=60)[0]


def set_sim_choice(choice):
    """choice: 'sim1' | 'esim'. eSIM lives on slot 2 on this hardware --
    same slot the removed 'sim2' option used to target."""
    target_slot = 1 if choice == "sim1" else 2
    other = 2 if target_slot == 1 else 1
    run(["ubus", "call", "cellular.modem", "set_slot_priority_config",
         json.dumps({"bus": "cpu", "slot_priority": [target_slot, other]})])


def _current_slot():
    try:
        return int(ubus_call("cellular.modem", "status", {"bus": "cpu"}).get("current_sim_slot", 1))
    except (TypeError, ValueError):
        return 1


def set_cellular_data_enabled(enabled):
    """The web UI's own cellular "dial" switch (handleDialEnableChange in
    gl-sdk4-ui-internet): modem.set_connect / modem.disconnect {bus, slot}
    through GL's RPC, so cellular_manager knows it was switched off on
    purpose. A bare `ifdown modem_cpu` (the old approach) only told netifd,
    behind the back of the daemon that owns dialing. Falls back to
    ifup/ifdown if the RPC can't be run."""
    ok, _ = gl_c_rpc("modem", "set_connect" if enabled else "disconnect",
                     {"bus": "cpu", "slot": _current_slot()})
    if not ok:
        subprocess.Popen(["ifup" if enabled else "ifdown", "modem_cpu"])


def set_network_attach_enabled(enabled):
    """The Cellular toggle -- airplane mode, inverted: enabled=False puts
    the modem in airplane mode (no signal, SMS, calls or data at all).
    Goes through GL's own `system.set_airplane_mode` RPC, the call behind
    the stock screen's Airplane Mode switch: besides the
    `cellular.modem set_airplane_mode` ubus call (all the old code did),
    it records the state in glconfig.general.airplane_mode, which is what
    the stock screen and web UI read -- without that they kept showing
    cellular as on. Falls back to the bare ubus call."""
    ok, _ = gl_lua_rpc(_GL_SYSTEM_RPC, "set_airplane_mode", {"enable": not enabled}, timeout=30)
    if not ok:
        run(["ubus", "call", "cellular.modem", "set_airplane_mode",
             json.dumps({"enable": not enabled})])


def set_roaming_enabled(iccid, enabled):
    """Data roaming for the active SIM the way the web UI's cellular
    settings apply it (gl-sdk4-ui-internet handleApply): read the SIM's
    whole config with modem.get_sim_config, change only `roaming`, write
    it back with modem.set_sim_config, then modem.set_connect so the
    session picks it up -- but only if data is currently on, since
    set_connect would otherwise switch data on as a side effect. Falls
    back to cellular.sim get_config/set_config over ubus."""
    if not iccid:
        return
    slot = _current_slot()
    ok, cur = gl_c_rpc("modem", "get_sim_config", {"bus": "cpu", "slot": slot, "iccid": iccid})
    if ok and isinstance(cur, dict) and cur:
        cur = dict(cur, roaming=bool(enabled))
        ok, _ = gl_c_rpc("modem", "set_sim_config", dict(cur, bus="cpu", slot=slot, iccid=iccid))
        if ok:
            if is_cell_data_up():
                gl_c_rpc("modem", "set_connect", {"bus": "cpu", "slot": slot})
            return
    cur = ubus_call("cellular.sim", "get_config", {"iccid": iccid})
    if not cur:
        return
    cur["roaming"] = enabled
    run(["ubus", "call", "cellular.sim", "set_config",
         json.dumps({"iccid": iccid, "data": cur})])


SIM_VERIFY_POLL = 1.0


SIM_ATTACH_TIMEOUT = 40.0


SIM_DETACH_TIMEOUT = 15.0


SIM_DATA_TIMEOUT = 30.0


SIM_ROAM_TIMEOUT = 8.0


def _wait_until(check, timeout, poll=SIM_VERIFY_POLL):
    deadline = time.time() + timeout
    while time.time() < deadline and not _stop:
        if check():
            return True
        time.sleep(poll)
    return check()


def apply_roaming(iccid, want):
    set_roaming_enabled(iccid, want)
    return _wait_until(lambda: get_roaming_config(iccid) == want, SIM_ROAM_TIMEOUT, poll=0.5)


def get_repeater_status():
    st = ubus_call("repeater", "status")
    if not st or not st.get("running"):
        return {"connected": False, "ssid": None, "signal": None, "ip": None}
    connected = st.get("state_s") == "connected"
    ip = (st.get("ipv4") or {}).get("ip", "").split("/")[0] or None
    return {
        "connected": connected,
        "ssid": st.get("ssid"),
        "signal": st.get("signal"),
        "ip": ip,
        "band": st.get("band") if connected else None,
    }


def repeater_scan():
    result = ubus_call("repeater", "scan", {"cached": True})
    survey = result.get("survey", []) if result else []
    best = {}
    for ap in survey:
        ssid = ap.get("ssid")
        if not ssid:
            continue
        sig = ap.get("signal", -999)
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {
                "ssid": ssid,
                "signal": sig,
                "bssid": ap.get("bssid"),
                "band": ap.get("band"),
                "open": not ap.get("caps", {}).get("PRIVACY", True),
            }
    return sorted(best.values(), key=lambda a: -a["signal"])


def repeater_connect(ssid, bssid, key):
    params = {"ssid": ssid, "bssid": bssid, "remember": True}
    if key:
        params["key"] = key
    subprocess.Popen(["ubus", "call", "repeater", "connect", json.dumps(params)])


def get_remembered_repeater_keys():
    """SSID -> key for every network repeater_connect's remember=True has
    ever saved, straight from /etc/config/repeater's anonymous @network[]
    sections (this is where the ubus 'repeater' service itself persists
    them -- not a separate store of our own). Used so re-selecting a
    previously-connected network can reconnect immediately instead of
    demanding the password again."""
    out = run(["uci", "show", "repeater"])
    ssid_by_idx, key_by_idx = {}, {}
    for line in out.splitlines():
        if ".ssid=" not in line and ".key=" not in line:
            continue
        try:
            idx = line.split("[", 1)[1].split("]", 1)[0]
            value = line.split("=", 1)[1].strip().strip("'")
        except IndexError:
            continue
        if ".ssid=" in line:
            ssid_by_idx[idx] = value
        else:
            key_by_idx[idx] = value
    return {ssid_by_idx[i]: key_by_idx[i] for i in ssid_by_idx if i in key_by_idx}


def get_saved_aps():
    """SSIDs the router remembers for Wi-Fi internet (the stock "Known Networks"): repeater.get_saved_ap_list. Passwords are
    never read here. A failed call raises, so the screen keeps the list it had."""
    ok, res = gl_call("repeater", "get_saved_ap_list", {}, timeout=15)
    if not ok:
        raise RuntimeError("get_saved_ap_list failed")
    seen = []
    for a in (res or {}).get("res") or []:
        if a.get("ssid") and a["ssid"] not in seen:
            seen.append(a["ssid"])
    return seen


def get_saved_ap(ssid):
    """The full saved record (ssid, bssid, key, macaddr, ...) for one known network, or None. Holds a password: use it
    only for the action in hand, never keep it in a job."""
    ok, res = gl_call("repeater", "get_saved_ap_list", {}, timeout=15)
    return next((a for a in ((res or {}).get("res") or []) if a.get("ssid") == ssid), None) if ok else None


def repeater_set_key(rec, key):
    """Change the password of a known network the way the stock page does: repeater.connect with the saved record's fields,
    remember: true and the new key (a re-join). Falls back to the direct ubus call the Join screen uses if GL refuses.
    Only issues the request; the caller waits for the connection."""
    params = {k: v for k, v in rec.items() if k != "key"}
    params.update(ssid=rec["ssid"], remember=True)
    if key:
        params["key"] = key
    if not gl_call("repeater", "connect", params, timeout=40)[0]:
        repeater_connect(rec["ssid"], rec.get("bssid"), key)


def forget_saved_ap(ssid):
    """The stock "Delete" on a known network: repeater.remove_saved_ap {ssid}."""
    return gl_call("repeater", "remove_saved_ap", {"ssid": ssid})[0]


def repeater_disconnect():
    subprocess.Popen(["ubus", "call", "repeater", "disconnect"])


def get_wifi_radio_state(iface):
    """iface: the AP-mode wifi-iface section name ('wifi2g'/'wifi5g' on
    this device -- the actual "GL-E5800" SSID), NOT the underlying radio
    device name ('wifi0'/'wifi1'). The radio device's own 'disabled' flag
    only gates whether the physical radio hardware is powered on at all
    (needed regardless, e.g. for this router's repeater-client uplink) --
    completely separate from whether the AP interface actually broadcasts
    its SSID. Confirmed live: wifi0/wifi1 (radio) read disabled=0 while
    wifi2g/wifi5g (the real AP) read disabled=1 -- toggling the
    radio-level flag never touched the setting that actually determines
    whether the WiFi network is visible, which is why the toggle could
    show "on" while the network was genuinely off the whole time."""
    ok, out = run_checked(["uci", "-q", "get", f"wireless.{iface}.disabled"])
    if ok:
        return out != "1"
    # Non-zero also means "key absent", which on OpenWrt is the normal way
    # of saying enabled -- so only call it unknown if the section itself
    # cannot be read either. Returning None rather than True keeps a broken
    # uci from being displayed as a confident "WiFi is on".
    if run_checked(["uci", "-q", "show", f"wireless.{iface}"])[0]:
        return True
    return None


_wifi_reload_state = {"running": False, "pending": False}


_wifi_reload_lock = threading.Lock()


def _wifi_reload_worker():
    """The try/finally matters: without it, any exception out of
    subprocess.run kills this thread while `running` stays True, and
    request_wifi_reload then refuses to ever start another worker -- every
    later WiFi toggle would write UCI and silently never reload, which is
    the exact desync this coalescing was added to prevent."""
    try:
        while True:
            with _wifi_reload_lock:
                _wifi_reload_state["pending"] = False
            try:
                subprocess.run(["/sbin/wifi", "reload"], timeout=60)
            except Exception:
                pass
            with _wifi_reload_lock:
                if not _wifi_reload_state["pending"]:
                    return
    finally:
        with _wifi_reload_lock:
            _wifi_reload_state["running"] = False


def request_wifi_reload():
    """`/sbin/wifi reload` serializes on its own file lock and takes ~8-10s
    per call -- firing one per toggle tap (the old behavior) let calls pile
    up faster than they drained, and a backlog of them was found stuck
    mid-queue after a round of testing, leaving the AP UCI state and the
    actual broadcasting hostapd state out of sync. This coalesces any
    reloads requested while one is already in flight into a single trailing
    reload instead of stacking a new subprocess per request."""
    with _wifi_reload_lock:
        if _wifi_reload_state["running"]:
            _wifi_reload_state["pending"] = True
            return
        _wifi_reload_state["running"] = True
    threading.Thread(target=_wifi_reload_worker, daemon=True).start()


_GL_WIFI_RPC = "/usr/lib/oui-httpd/rpc/wifi"


_GL_WIFI_LUA = r'''
local cjson = require "cjson"
local ubus = require "ubus"
local noop = function() end
ngx = setmetatable({
    log = noop, ERR = 1, WARN = 2, NOTICE = 3, INFO = 4, DEBUG = 5,
    timer = { at = function(_, fn, ...) fn(false, ...) return true end },
    sleep = function(s) os.execute("sleep " .. tonumber(s)) end,
    pipe = { spawn = function(cmd)
        if type(cmd) == "table" then
            local q = {}
            for _, a in ipairs(cmd) do q[#q + 1] = "'" .. tostring(a):gsub("'", "'\\''") .. "'" end
            cmd = table.concat(q, " ")
        end
        local h = io.popen(cmd .. " 2>&1")
        local out = h:read("*a") or ""
        h:close()
        local done = false
        local proc = {
            set_timeouts = noop, shutdown = noop,
            wait = function() return true, "exit", 0 end,
            stdout_read_all = function() if done then return "" end done = true return out end,
            stdout_read_line = function() return nil, "closed" end,
            stderr_read_all = function() return "" end,
            write = function() return 0 end,
            kill = function() return true end,
            pid = function() return 0 end,
        }
        return setmetatable(proc, { __index = function() return noop end })
    end },
}, { __index = function() return noop end })
package.loaded["oui.ubus"] = {
    call = function(object, method, params)
        local conn = ubus.connect()
        local res, err = conn:call(object, method, params or {})
        conn:close()
        return res, err
    end,
    send = function(...) local conn = ubus.connect() conn:send(...) conn:close() end,
    objects = function() local conn = ubus.connect() local o = conn:objects() conn:close() return o end,
}
local m = dofile(arg[1])
local ok, res = pcall(m[arg[2]], cjson.decode(arg[3]))
if not ok then io.stderr:write(tostring(res) .. "\n") os.exit(1) end
io.write("\n", cjson.encode(res or {}), "\n")
'''


def gl_lua_rpc(module_path, method, params, timeout=90):
    """(ok, result) from one of GL's service modules, given its file path (/usr/lib/oui-httpd/rpc/<name>).
    Goes through the stock entry point (gl_call, `ubus call gl-session call`), the way the stock screen and web UI
    run these modules. Only Wi-Fi still uses the stand-in (gl_lua_shim_rpc), see gl_wifi_call."""
    return gl_call(os.path.basename(module_path), method, params, timeout)


def gl_lua_shim_rpc(module_path, method, params, timeout=90):
    """(ok, result) from one of GL's Lua RPC modules (the web UI's own
    backend: /usr/lib/oui-httpd/rpc/<name>), run outside nginx with the
    stubs in _GL_WIFI_LUA. ok is False if it couldn't run (module missing
    on another firmware, Lua error) or returned an err_msg."""
    if not os.path.exists(module_path):
        return False, None
    try:
        out = subprocess.run(["lua", "-", module_path, method, json.dumps(params)],
                             input=_GL_WIFI_LUA, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return False, None
    if out.returncode != 0:
        return False, None
    try:
        res = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        res = {}
    if isinstance(res, dict) and res.get("err_msg"):
        return False, res
    return True, res


def gl_wifi_call(method, params, timeout=90):
    return gl_lua_shim_rpc(_GL_WIFI_RPC, method, params, timeout)


_GL_SYSTEM_RPC = "/usr/lib/oui-httpd/rpc/system"


_GLC = "/www/cgi-bin/glc"


def gl_c_rpc(obj, method, args, timeout=60):
    """(ok, result) from one of GL's C RPC modules (rpc/<obj>.so, e.g.
    modem) -- run the way nginx runs them: POST {object, method, args} to
    the /www/cgi-bin/glc CGI. Invoked directly as a CGI process here, so
    no web login is involved. glc needs REQUEST_URI=/rpc (it segfaults
    without it) and answers "Content-type: ...\\n\\n<code> <json>", code 0
    meaning success."""
    if not (os.path.exists(_GLC) and os.path.exists(f"/usr/lib/oui-httpd/rpc/{obj}.so")):
        return False, None
    body = json.dumps({"object": obj, "method": method, "args": args})
    env = dict(os.environ, REQUEST_METHOD="POST", REQUEST_URI="/rpc",
               CONTENT_TYPE="application/json", CONTENT_LENGTH=str(len(body.encode())))
    try:
        out = subprocess.run([_GLC], input=body, env=env, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return False, None
    payload = out.stdout.split("\n\n", 1)[-1].strip()
    code, _, rest = payload.partition(" ")
    if code != "0":
        return False, rest or None
    try:
        return True, json.loads(rest) if rest.strip() else {}
    except Exception:
        return True, {}


def set_wifi_iface_enabled(iface, enabled):
    """Turn one AP network (wifi2g / wifi5g / wifi6g) on or off the way
    the web UI does. Writing `wireless.<iface>.disabled` + `wifi reload`
    ourselves (the old approach) did change the radio, but it's not the
    path GL's own UI and web page are built around -- after using it, the
    stock screen and web page were reported still showing that Wi-Fi as
    on. Going through GL's RPC makes a dashboard toggle indistinguishable
    from one made in the web UI. Falls back to the raw uci path only if
    the RPC can't be run."""
    ok, _ = gl_wifi_call("set_config", {"init": True, "iface_name": iface, "enabled": bool(enabled)})
    if ok:
        return True
    uci_set(f"wireless.{iface}.disabled", "0" if enabled else "1")
    request_wifi_reload()
    return False


def set_wifi_radio_state(iface, enabled):
    set_wifi_iface_enabled(iface, enabled)


def wait_for_wifi_reload(timeout=15.0, poll=0.2):
    """Blocks until request_wifi_reload's coalesced background worker has
    actually finished (or timeout) -- not a check that the radio is
    genuinely broadcasting the new state (no such signal was verified for
    this hardware), but a real improvement over the previous behaviour:
    the 2.4GHz/5G/6G toggles used to flip their displayed state the
    instant the tap landed, while `/sbin/wifi reload` was still running
    for ~8-10s in the background -- so the UI could show "off" for
    several seconds while the radio was, in fact, still broadcasting."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _wifi_reload_lock:
            running = _wifi_reload_state["running"] or _wifi_reload_state["pending"]
        if not running:
            return True
        time.sleep(poll)
    return False


_lan_ip_cache = {"ts": 0.0, "val": None}


def get_system_info():
    """Reads /proc/uptime directly instead of spawning `cat`, and caches
    the LAN IP for a minute: mode_live calls this every 2s purely for the
    uptime line, and two process spawns every 2s is real load on this
    SoC for a number that changes once a minute."""
    uptime_min = 0
    try:
        with open("/proc/uptime") as f:
            uptime_min = int(float(f.read().split()[0]) / 60)
    except Exception:
        pass
    now = time.time()
    if _lan_ip_cache["val"] is None or now - _lan_ip_cache["ts"] > 60:
        _lan_ip_cache["val"] = uci_get("network.lan.ipaddr") or "192.168.8.1"
        _lan_ip_cache["ts"] = now
    return {"uptime_min": uptime_min, "lan_ip": _lan_ip_cache["val"]}


def _power_via_gl(func):
    """system.reboot / system.poweroff through GL's own `system` module (what the stock screen's reboot and power-off
    tasks call; the stock web UI sends {delay: 1} for reboot), instead of running /sbin/<func> ourselves. If GL refuses,
    or the router is still up 30 s later, fall back to the plain command so the button always does something. Runs on a
    thread: the call can block while GL winds the router down."""
    def run():
        ok, _ = gl_call("system", func, {"delay": 1}, timeout=20)
        if ok:
            time.sleep(30)  # still here: GL accepted but did nothing
        subprocess.Popen(["/sbin/" + func])
    threading.Thread(target=run, daemon=True).start()


def reboot_router():
    _power_via_gl("reboot")


def shutdown_router():
    _power_via_gl("poweroff")


def switch_to_stock_ui():
    # Non-blocking AND detached: toggle.sh off stops citydash (this very
    # process), so it has to outlive us. Popen alone leaves it in our
    # process group, so procd's stop can take it down partway through --
    # after gl_screen has been stopped but before it is started again,
    # which leaves the physical screen dark with neither UI running.
    # start_new_session puts it in its own session so that can't happen.
    try:
        subprocess.Popen(["/root/e5ui/toggle.sh", "off"], start_new_session=True)
    except TypeError:      # very old Python without start_new_session
        subprocess.Popen(["setsid", "/root/e5ui/toggle.sh", "off"])


def get_wan_iface():
    """Pick the interface holding the lowest-metric default route. This
    device dual-WANs (repeater WiFi uplink, usually wlan4, vs. the cellular
    modem rmnet_data0 as failover) so the active WAN interface isn't fixed --
    br-lan is just the local LAN bridge and stays near-zero unless another
    device is actively using this router's own AP, which made the old
    hardcoded br-lan reading look permanently decorative.

    Cached for 2s: mode_live's idle branch reaches this through
    get_wan_conn_type on every ~12ms loop pass (911 reads of
    /proc/net/route in a 25s profile), for a value that changes on a WAN
    failover, not per frame."""
    now = time.time()
    if now - _wan_iface_cache["ts"] < _WAN_IFACE_TTL:
        return _wan_iface_cache["val"]
    best_iface, best_metric = None, None
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                parts = line.split()
                if len(parts) < 7 or parts[1] != "00000000":
                    continue
                metric = int(parts[6])
                if best_metric is None or metric < best_metric:
                    best_iface, best_metric = parts[0], metric
    except Exception:
        pass
    _wan_iface_cache["ts"] = now
    _wan_iface_cache["val"] = best_iface
    return best_iface


_wan_iface_cache = {"ts": -1e9, "val": None}


_WAN_IFACE_TTL = 2.0


_CELL_NR_TYPES = {5, 51}


_CELL_LTE_TYPES = {4, 41}


_CELL_INVALID = -32768


def _cell_int(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return None if v == _CELL_INVALID else v


def _parse_cell_signal(raw):
    """Normalises firmware 4.10's `cellular.network cell_info` reply --
    a `signal` list with one entry per aggregated carrier, `ca` 0 being
    the primary -- into the dict shape the rest of this file reads:
    `mode` (non-empty only while registered), primary `rsrp`/`strength`,
    and `carriers` for the band/CA display."""
    carriers = []
    for s in sorted(raw.get("signal") or [], key=lambda s: _cell_int(s.get("ca")) or 0):
        band = _cell_int(s.get("band"))
        ntype = _cell_int(s.get("network_type"))
        # In airplane mode (or with no service) cell_info isn't empty: it
        # keeps one placeholder entry with band 0, network_type 0 and
        # rsrp -32768 -- confirmed live. Counting that as a carrier ("B0")
        # made the modem look registered, kept the header's signal bars
        # up and made airplane mode look like it never took.
        if not band or not ntype:
            continue
        nr = ntype in _CELL_NR_TYPES
        try:
            mhz = float(s.get("bandwidth"))
        except (TypeError, ValueError):
            mhz = None
        carriers.append({
            "band": f"n{band}" if nr else f"B{band}",
            "nr": nr,
            "lte": ntype in _CELL_LTE_TYPES,
            "mhz": mhz if mhz and mhz > 0 else None,
            "rsrp": _cell_int(s.get("rsrp")),
            "strength": _cell_int(s.get("strength")),
        })
    if not carriers:
        return {}
    n_nr = sum(1 for c in carriers if c["nr"])
    n_lte = sum(1 for c in carriers if c["lte"])
    if n_nr and n_lte:
        mode = "NR5G-NSA"
    elif n_nr:
        mode = "NR5G-SA"
    elif n_lte:
        mode = "LTE"
    else:
        mode = {1: "GSM", 2: "WCDMA", 3: "WCDMA"}.get(_cell_int(raw.get("network_type")), "Cellular")
    primary = carriers[0]
    return {"mode": mode, "rsrp": primary["rsrp"], "strength": primary["strength"],
            "carriers": carriers}


def _get_active_cell_info():
    """cell_info dict (mode/rsrp/strength/carriers) for the currently-active
    SIM slot, or {} when not registered. Shared by get_wan_conn_type/
    get_cell_signal/get_sim_status so they don't each make their own
    redundant ubus round trip.

    Firmware 4.10.0 moved this out of `cellular.network info` (whose
    networks[] no longer carry a cell_info at all -- confirmed live) into
    its own `cellular.network cell_info` method. Reading only the old
    location left `mode` permanently empty on 4.10: no header signal bars,
    a WAN label stuck at "Cellular", and the Net toggle always drawn off.
    The old location is still tried as a fallback for 4.8.x."""
    modem = ubus_call("cellular.modem", "status", {"bus": "cpu"})
    try:
        slot = int(modem.get("current_sim_slot", 1))
    except (TypeError, ValueError):
        slot = 1
    raw = ubus_call("cellular.network", "cell_info", {"bus": "cpu", "slot": slot})
    if "signal" in raw:
        return _parse_cell_signal(raw)
    net = ubus_call("cellular.network", "info", {"bus": "cpu", "slot": slot})
    for n in net.get("networks", []):
        cell = n.get("cell_info") or {}
        if cell.get("mode"):
            return cell
    return {}


def cell_network_label(cell):
    """(headline, detail) for the SIM page's network-type readout, e.g.
    ("5G", "NSA"), ("4G+", "LTE-A"), ("4G", "LTE") -- the same 4G / 4G+ /
    5G vocabulary a phone status bar uses. None when not registered."""
    mode = (cell or {}).get("mode", "")
    if not mode:
        return None
    mode_u = mode.upper()
    carriers = cell.get("carriers") or []
    if "NR" in mode_u:
        return "5G", "SA" if "SA" in mode_u and "NSA" not in mode_u else "NSA"
    if "LTE" in mode_u:
        if sum(1 for c in carriers if c.get("lte")) > 1:
            return "4G+", "LTE-A"
        return "4G", "LTE"
    if "WCDMA" in mode_u or "UMTS" in mode_u:
        return "3G", "WCDMA"
    if "GSM" in mode_u:
        return "2G", "GSM"
    return "4G", mode


def get_wan_conn_type(cell_info=None):
    """Short label for the header's connection-status indicator: Repeater
    (WiFi client uplink), Ethernet, or 4G/5G (cellular, radio access tech
    read from cellular.network's cell_info.mode, e.g. "LTE FDD" -> 4G,
    anything with "NR" -> 5G). Does a couple of ubus calls, so -- same
    lesson as the fx-history and repeater-scan fixes -- this is refreshed
    periodically in mode_live's idle loop, never called from inside a
    panel's own render function."""
    iface = get_wan_iface()
    if not iface:
        return None
    if iface.startswith("wlan"):
        return "Repeater"
    if iface.startswith("eth"):
        return "Ethernet"
    if "rmnet" in iface or "modem" in iface:
        label = cell_network_label(cell_info if cell_info is not None else _get_active_cell_info())
        return label[0] if label else "Cellular"
    return None


def get_cell_signal(cell_info=None):
    """(bars 0-4, "4G"/"4G+"/"5G") for the active SIM's current cellular
    signal -- the modem's own level where it reports one, else derived
    from RSRP (dBm); None if not registered/no signal at all --
    matches ordinary phone status-bar behavior of hiding the cellular
    indicator entirely when there's nothing to show. Independent of
    whether cellular is actually the active WAN (get_wan_conn_type) --
    this reflects the modem's own registration/signal, the same way a
    phone shows signal bars regardless of whether you're on WiFi."""
    cell = cell_info if cell_info is not None else _get_active_cell_info()
    label = cell_network_label(cell)
    if not label:
        return None
    rat = label[0]
    # The modem's own 0-4 level (4.10's cell_info) is what the stock UI
    # draws, so prefer it over re-deriving bars from RSRP here.
    strength = cell.get("strength")
    if isinstance(strength, int) and 0 <= strength <= 4:
        return strength, rat
    try:
        rsrp = int(cell.get("rsrp"))
    except (TypeError, ValueError):
        return None
    if rsrp >= -80:
        bars = 4
    elif rsrp >= -95:
        bars = 3
    elif rsrp >= -105:
        bars = 2
    elif rsrp >= -115:
        bars = 1
    else:
        bars = 0
    return bars, rat


def sample_bandwidth(prev):
    """prev: (iface, ts, rx_bytes, tx_bytes) or None. Returns (new_sample, down_mbps, up_mbps).
    Rates are None until there's a previous sample on the *same* interface to
    diff against -- if the active WAN interface changed (failover) between
    calls, this resets rather than diffing two different interfaces' counters."""
    iface = get_wan_iface()
    if iface is None:
        return prev, None, None
    try:
        with open(f"/sys/class/net/{iface}/statistics/rx_bytes") as f:
            rx = int(f.read().strip())
        with open(f"/sys/class/net/{iface}/statistics/tx_bytes") as f:
            tx = int(f.read().strip())
    except Exception:
        return prev, None, None
    now = time.time()
    if prev is None or prev[0] != iface:
        return (iface, now, rx, tx), None, None
    _, pts, prx, ptx = prev
    dt = now - pts
    if dt <= 0:
        return (iface, now, rx, tx), None, None
    down_mbps = max(0.0, (rx - prx) * 8 / dt / 1_000_000)
    up_mbps = max(0.0, (tx - ptx) * 8 / dt / 1_000_000)
    return (iface, now, rx, tx), down_mbps, up_mbps


def sample_cpu(prev):
    """prev: (idle, total) or None, from /proc/stat's aggregate 'cpu' line.
    Returns (new_sample, cpu_pct). cpu_pct is None until there's a previous
    sample (needs a delta, not just a point-in-time read)."""
    try:
        with open("/proc/stat") as f:
            fields = [int(x) for x in f.readline().split()[1:]]
        idle = fields[3] + fields[4]
        total = sum(fields)
    except Exception:
        return prev, None
    if prev is None:
        return (idle, total), None
    pidle, ptotal = prev
    dtotal = total - ptotal
    if dtotal <= 0:
        return (idle, total), None
    pct = max(0.0, min(100.0, 100 * (1 - (idle - pidle) / dtotal)))
    return (idle, total), pct


def get_ram_stats():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total_kb = info.get("MemTotal", 0)
        avail_kb = info.get("MemAvailable", 0)
        if not total_kb:
            return None, None, None
        used_kb = total_kb - avail_kb
        return 100 * used_kb / total_kb, used_kb / 1024 / 1024, total_kb / 1024 / 1024
    except Exception:
        return None, None, None


_TEMP_ZONE_PATH = None


_TEMP_ZONE_PREFERRED = ["cpuss-0", "aoss-0", "sys-therm-1"]


def get_temp_c():
    """thermal_zone0 on this hardware ('sdr0') is an unpowered sensor that
    always reports the sentinel -273000 (absolute zero); pick a real sensor
    by name instead of assuming zone index 0, and cache the path found."""
    global _TEMP_ZONE_PATH
    if _TEMP_ZONE_PATH is None:
        base = "/sys/class/thermal"
        candidates = {}
        try:
            for name in os.listdir(base):
                if not name.startswith("thermal_zone"):
                    continue
                try:
                    with open(f"{base}/{name}/type") as f:
                        ztype = f.read().strip()
                    with open(f"{base}/{name}/temp") as f:
                        raw = int(f.read().strip())
                except Exception:
                    continue
                if -50000 < raw < 150000:
                    candidates[ztype] = f"{base}/{name}/temp"
        except Exception:
            pass
        for name in _TEMP_ZONE_PREFERRED:
            if name in candidates:
                _TEMP_ZONE_PATH = candidates[name]
                break
        else:
            _TEMP_ZONE_PATH = next(iter(candidates.values()), False)
    if not _TEMP_ZONE_PATH:
        return None
    try:
        with open(_TEMP_ZONE_PATH) as f:
            return int(f.read().strip()) / 1000
    except Exception:
        return None


SPEEDTEST_DOWN_URL = "https://speed.cloudflare.com/__down?bytes={}"


SPEEDTEST_UP_URL = "https://speed.cloudflare.com/__up"


SPEEDTEST_STREAMS = 4           # parallel connections per direction


SPEEDTEST_PHASE_S = 6.0         # length of each of download / upload


SPEEDTEST_RAMP_S = 1.0          # excluded from the result: TCP slow start


SPEEDTEST_DOWN_CAP = 250 * 10**6   # hard stop, bytes -- this is mobile data


SPEEDTEST_UP_CAP = 80 * 10**6


SPEEDTEST_CHUNK = 256 * 1024


class SpeedTest:
    """Download then upload over SPEEDTEST_STREAMS parallel curl processes,
    run on its own thread so the screen keeps animating.

    Throughput is counted from the bytes these streams themselves move
    (piped through this process), NOT from the WAN interface's counters:
    those include every LAN client's traffic too -- measured live, a 5 MB
    test download moved the rmnet_data0 counter by 6.5 MB. curl does the
    TLS; Python only counts and discards, so it's never the bottleneck.

    The result is the average over the phase minus its first
    SPEEDTEST_RAMP_S. For upload the count is of bytes handed to curl, so
    pipe/socket buffering makes it run ahead at the start -- the same
    ramp cut is what keeps that out of the number."""

    def __init__(self):
        self.lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._reset()

    def _reset(self):
        self.phase = "idle"         # idle | download | upload | done | error | cancelled
        self.live_mbps = 0.0
        self.progress = 0.0         # 0..1 through the current phase
        self.down_mbps = None
        self.up_mbps = None
        self.bytes_used = 0
        self.error = None
        self.via = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        with self.lock:
            self._reset()
            self.phase = "download"
            self.via = get_wan_conn_type() or get_wan_iface()
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        if self.running:
            self._cancel.set()

    def snapshot(self):
        with self.lock:
            return {"phase": self.phase, "live": self.live_mbps, "progress": self.progress,
                    "down": self.down_mbps, "up": self.up_mbps, "bytes": self.bytes_used,
                    "error": self.error, "via": self.via}

    def _run(self):
        try:
            down = self._phase("download")
            with self.lock:
                self.down_mbps = down
            if self._cancel.is_set() or _stop:
                raise _SpeedTestCancelled()
            with self.lock:
                self.phase, self.live_mbps, self.progress = "upload", 0.0, 0.0
            up = self._phase("upload")
            with self.lock:
                self.up_mbps = up
                self.phase, self.live_mbps = "done", 0.0
        except _SpeedTestCancelled:
            with self.lock:
                self.phase, self.live_mbps = "cancelled", 0.0
        except Exception as e:
            with self.lock:
                self.phase, self.live_mbps, self.error = "error", 0.0, str(e) or "Test failed"

    def _phase(self, kind):
        download = kind == "download"
        cap = SPEEDTEST_DOWN_CAP if download else SPEEDTEST_UP_CAP
        count = [0]
        count_lock = threading.Lock()
        stop = threading.Event()
        procs = []

        def add(n):
            with count_lock:
                count[0] += n

        def reader(p):
            try:
                while not stop.is_set():
                    chunk = p.stdout.read(SPEEDTEST_CHUNK)
                    if not chunk:
                        break
                    add(len(chunk))
            except Exception:
                pass

        payload = os.urandom(SPEEDTEST_CHUNK)   # incompressible

        def writer(p):
            try:
                while not stop.is_set():
                    add(p.stdin.write(payload) or 0)   # raw pipe: may be partial
            except Exception:
                pass                             # curl killed / pipe closed

        max_time = str(int(SPEEDTEST_PHASE_S + 6))
        per_stream = cap // SPEEDTEST_STREAMS + 1
        for _ in range(SPEEDTEST_STREAMS):
            if download:
                cmd = ["curl", "-s", "--max-time", max_time, "-o", "-",
                       SPEEDTEST_DOWN_URL.format(per_stream)]
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                target = reader
            else:
                cmd = ["curl", "-s", "--max-time", max_time, "-o", "/dev/null", "-X", "POST",
                       "-T", "-", "-H", "Content-Type: application/octet-stream", SPEEDTEST_UP_URL]
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, bufsize=0)
                target = writer
            procs.append(p)
            threading.Thread(target=target, args=(p,), daemon=True).start()

        t0 = time.time()
        samples = [(t0, 0)]
        ramp = None
        try:
            while True:
                time.sleep(0.2)
                now = time.time()
                with count_lock:
                    total = count[0]
                samples.append((now, total))
                elapsed = now - t0
                if ramp is None and elapsed >= SPEEDTEST_RAMP_S:
                    ramp = (now, total)
                # live figure: rate over roughly the last second
                past = next((s for s in samples if s[0] >= now - 1.0), samples[0])
                live = (total - past[1]) * 8 / max(0.05, now - past[0]) / 1e6
                with self.lock:
                    self.live_mbps = live
                    self.progress = min(1.0, elapsed / SPEEDTEST_PHASE_S)
                if (elapsed >= SPEEDTEST_PHASE_S or total >= cap or self._cancel.is_set() or _stop
                        or all(p.poll() is not None for p in procs)):
                    break
        finally:
            stop.set()
            for p in procs:
                try:
                    p.kill()
                except Exception:
                    pass
            for p in procs:
                try:
                    p.wait(timeout=2)
                except Exception:
                    pass
            with count_lock:
                total = count[0]
            with self.lock:
                self.bytes_used += total

        if self._cancel.is_set() or _stop:
            raise _SpeedTestCancelled()
        end_t, end_b = samples[-1]
        if end_b == 0:
            raise RuntimeError("No connection to the test server")
        start_t, start_b = ramp if ramp and end_t - ramp[0] >= 0.5 else samples[0]
        return (end_b - start_b) * 8 / max(0.05, end_t - start_t) / 1e6


class _SpeedTestCancelled(Exception):
    pass


_COUNTRY_NAME_HINTS = [
    ("HONGKONG", "Hong Kong"), ("HONG KONG", "Hong Kong"), ("HK", "Hong Kong"),
    ("香港", "Hong Kong"),
    ("TAIWAN", "Taiwan"), ("TW", "Taiwan"), ("台湾", "Taiwan"),
    ("SINGAPORE", "Singapore"), ("SG", "Singapore"), ("新加坡", "Singapore"), ("狮城", "Singapore"),
    ("KOREA", "South Korea"), ("KR", "South Korea"), ("韩国", "South Korea"), ("韓國", "South Korea"),
    ("JAPAN", "Japan"), ("TOKYO", "Japan"), ("JP", "Japan"), ("日本", "Japan"),
    ("BRITAIN", "UK"), ("LONDON", "UK"), ("UK", "UK"), ("GBR", "UK"), ("英国", "UK"), ("英國", "UK"),
    ("GERMANY", "Germany"), ("DE", "Germany"), ("德国", "Germany"), ("德國", "Germany"),
    ("FRANCE", "France"), ("FR", "France"), ("法国", "France"), ("法國", "France"),
    ("CHINA", "China"), ("CN", "China"), ("中国", "China"), ("中國", "China"), ("大陆", "China"), ("大陸", "China"),
    ("CANADA", "Canada"), ("CA", "Canada"), ("加拿大", "Canada"),
    ("AUSTRALIA", "Australia"), ("AU", "Australia"), ("澳洲", "Australia"), ("澳大利亚", "Australia"),
    ("AMERICA", "USA"), ("UNITED STATES", "USA"), ("US", "USA"), ("USA", "USA"), ("美国", "USA"), ("美國", "USA"),
    # Added for the WireGuard quick-filter chips -- a "hundreds of
    # imported servers" list is exactly the case where these show up
    # constantly and were previously unrecognized.
    ("RUSSIA", "Russia"), ("RU", "Russia"), ("俄罗斯", "Russia"), ("俄羅斯", "Russia"),
    ("NETHERLANDS", "Netherlands"), ("NL", "Netherlands"), ("荷兰", "Netherlands"), ("荷蘭", "Netherlands"),
    ("INDIA", "India"), ("印度", "India"),
    # "IN" deliberately excluded as a bare hint: unlike most other 2-letter
    # codes here, "in" is a common standalone English word/prefix
    # ("in-house", "check-in", "opt-in", ...) and matched exactly that
    # kind of unrelated peer name in testing. The narrower
    # _ISO2_HOSTNAME_PREFIX check below (a bare code directly followed by
    # a digit, e.g. "in174.expressvpn.com") still catches India-coded
    # hostnames without that false-positive risk.
    ("BRAZIL", "Brazil"), ("BR", "Brazil"), ("巴西", "Brazil"),
    ("TURKEY", "Turkey"), ("TR", "Turkey"), ("土耳其", "Turkey"),
    ("ARGENTINA", "Argentina"), ("AR", "Argentina"), ("阿根廷", "Argentina"),
]


_COUNTRY_HINT_PATTERNS = [
    (re.compile(r"(?<![A-Za-z])" + re.escape(key) + r"(?![A-Za-z])"), country)
    for key, country in _COUNTRY_NAME_HINTS
]


_ISO2_HOSTNAME_PREFIX = {
    "US": "USA", "GB": "UK", "UK": "UK", "DE": "Germany", "FR": "France",
    "HK": "Hong Kong", "TW": "Taiwan", "SG": "Singapore", "KR": "South Korea",
    "JP": "Japan", "CN": "China", "CA": "Canada", "AU": "Australia",
    "RU": "Russia", "NL": "Netherlands", "IN": "India", "BR": "Brazil",
    "TR": "Turkey", "AR": "Argentina",
    "IE": "Ireland", "AM": "Armenia", "ES": "Spain", "IT": "Italy",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "CH": "Switzerland", "AT": "Austria", "BE": "Belgium",
    "PT": "Portugal", "GR": "Greece", "CZ": "Czechia", "RO": "Romania",
    "HU": "Hungary", "UA": "Ukraine", "MX": "Mexico", "CL": "Chile",
    "CO": "Colombia", "ZA": "South Africa", "EG": "Egypt", "IL": "Israel",
    "AE": "UAE", "SA": "Saudi Arabia", "TH": "Thailand", "VN": "Vietnam",
    "MY": "Malaysia", "ID": "Indonesia", "PH": "Philippines",
    "NZ": "New Zealand", "IS": "Iceland", "LU": "Luxembourg",
    "MD": "Moldova", "RS": "Serbia", "BG": "Bulgaria", "HR": "Croatia",
    "SK": "Slovakia", "SI": "Slovenia", "EE": "Estonia", "LV": "Latvia",
    "LT": "Lithuania",
}


_ISO2_PREFIX_RE = re.compile(r"^([A-Za-z]{2})\d")


def guess_country_from_name(name):
    if not name:
        return None
    upper = name.upper()
    for pattern, country in _COUNTRY_HINT_PATTERNS:
        if pattern.search(upper):
            return country
    # Checked after the hint list, not instead of it: an explicit hint
    # spans more of the name and so is less likely to be a coincidence,
    # so it wins first when both would apply.
    m = _ISO2_PREFIX_RE.match(name)
    if m:
        return _ISO2_HOSTNAME_PREFIX.get(m.group(1).upper())
    return None


_truncate_cache = {}


_TRUNCATE_CACHE_MAX = 512


def truncate_to_width(d, text, f, max_w):
    """Longest prefix of `text` that fits in max_w with an ellipsis.

    Binary search over the prefix length, cached per (text, font, width).
    It used to drop one character at a time and re-measure the whole
    string on each step -- quadratic in the text, and the Home tile passes
    it the latest SMS body, which can be hundreds of CJK characters.
    Profiled live: 124ms per call, 34% of a core with the dashboard just
    sitting on Home (it redraws every second), which is what made swiping
    feel sluggish. Measuring with the font directly (what textbbox does at
    the origin) keeps `d` out of the cache key."""
    key = (text, f, max_w)
    hit = _truncate_cache.get(key)
    if hit is not None:
        return hit
    width = lambda s: f.getbbox(s)[2]
    if width(text) <= max_w:
        out = text
    else:
        lo, hi = 1, len(text) - 1            # lo always fits (or is the floor)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if width(text[:mid] + "…") <= max_w:
                lo = mid
            else:
                hi = mid - 1
        out = text[:lo] + "…"
    if len(_truncate_cache) >= _TRUNCATE_CACHE_MAX:
        _truncate_cache.clear()
    _truncate_cache[key] = out
    return out


def wrap_text_to_lines(d, text, f, max_w):
    """Character-by-character wrap so it works for CJK, which has no
    spaces between words -- but when the line being broken does contain a
    space, the break moves back to it, so English text wraps between
    words instead of mid-word ("rou / ter")."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for ch in paragraph:
            candidate = line + ch
            if line and d.textbbox((0, 0), candidate, font=f)[2] > max_w:
                cut = line.rfind(" ")
                if ch != " " and cut > 0:
                    lines.append(line[:cut])
                    line = line[cut + 1:] + ch
                else:
                    lines.append(line.rstrip())
                    line = "" if ch == " " else ch
            else:
                line = candidate
        lines.append(line)
    return lines


_fb = None


def _fb_handle():
    """Keep /dev/fb0 open for the process lifetime instead of reopening it
    per frame. During a drag this runs ~80x/s; open+close per frame is
    pure syscall overhead in the one path where smoothness matters most.
    Falls back to per-frame opens if the handle ever goes bad."""
    global _fb
    if _fb is None:
        _fb = open(FB_PATH, "r+b", buffering=0)
    return _fb


_stop = False


def _on_term(signum, frame):
    global _stop
    _stop = True


TOUCH_DEV = "/dev/input/event0"


_EVENT_FMT = "qqHHi"


_EVENT_SIZE = struct.calcsize(_EVENT_FMT)


EV_ABS = 3


ABS_MT_SLOT = 47


ABS_MT_POSITION_X = 53


ABS_MT_POSITION_Y = 54


ABS_MT_TRACKING_ID = 57


TAP_JITTER_PX = 10


_VEL_SMOOTHING = 0.6


class TouchState:
    """Shared between the reader thread and the render loop."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.dx = 0
        self.dy = 0
        self.down_x = 0
        self.down_y = 0
        self.have_pos = False   # a position event has arrived for THIS touch
        self.vx = 0.0           # smoothed horizontal velocity, px/s
        self.release_pending = False
        self.release_dx = 0
        self.release_dy = 0
        self.release_vx = 0.0
        self.error = None       # set if the input device can't be read


touch_state = TouchState()


def _touch_reader():
    import os as _os
    start_x = start_y = None
    last_x = None
    last_t = 0.0
    down = False
    slot = 0
    try:
        f = open(TOUCH_DEV, "rb")
    except Exception as e:
        # Losing the touch device leaves a dashboard that still redraws
        # happily but ignores every tap. That used to be a single line on
        # stderr nobody reads; surface it on the screen instead so the
        # device doesn't just look wedged.
        with touch_state.lock:
            touch_state.error = "touch input unavailable"
        print(f"touch reader could not open {TOUCH_DEV}: {e}", file=sys.stderr)
        return
    try:
        with f:
            fd = f.fileno()
            _os.set_blocking(fd, False)
            while not _stop:
                try:
                    data = f.read(_EVENT_SIZE)
                except (BlockingIOError, TypeError):
                    data = None
                if not data or len(data) < _EVENT_SIZE:
                    time.sleep(0.008)
                    continue
                _, _, typ, code, val = struct.unpack(_EVENT_FMT, data)
                if typ != EV_ABS:
                    continue
                # Multitouch protocol B interleaves slots. Without tracking
                # ABS_MT_SLOT, a second finger's coordinates were folded
                # into the same gesture, which on a screen this small made
                # an accidental two-finger touch jump panels.
                if code == ABS_MT_SLOT:
                    slot = val
                    continue
                if slot != 0:
                    continue
                if code == ABS_MT_TRACKING_ID:
                    if val == -1 and down:
                        with touch_state.lock:
                            touch_state.active = False
                            touch_state.release_pending = True
                            touch_state.release_dx = touch_state.dx
                            touch_state.release_dy = touch_state.dy
                            touch_state.release_vx = touch_state.vx
                        down = False
                        start_x = start_y = last_x = None
                    else:
                        down = True
                        start_x = start_y = last_x = None
                        with touch_state.lock:
                            touch_state.active = True
                            touch_state.dx = 0
                            touch_state.dy = 0
                            touch_state.vx = 0.0
                            # down_x/down_y still hold the PREVIOUS touch's
                            # coordinates until the first position event of
                            # this one lands; have_pos marks them stale so a
                            # release in that window can't be hit-tested
                            # against where the last tap happened to be.
                            touch_state.have_pos = False
                elif code == ABS_MT_POSITION_X and down:
                    now_t = time.time()
                    if start_x is None:
                        start_x = val
                        with touch_state.lock:
                            touch_state.down_x = val
                            touch_state.have_pos = True
                    elif last_x is not None and now_t > last_t:
                        inst = (val - last_x) / (now_t - last_t)
                        with touch_state.lock:
                            touch_state.vx = (_VEL_SMOOTHING * touch_state.vx
                                              + (1 - _VEL_SMOOTHING) * inst)
                    last_x, last_t = val, now_t
                    with touch_state.lock:
                        touch_state.dx = val - start_x
                elif code == ABS_MT_POSITION_Y and down:
                    if start_y is None:
                        start_y = val
                        with touch_state.lock:
                            touch_state.down_y = val
                    with touch_state.lock:
                        touch_state.dy = val - start_y
    except Exception as e:
        with touch_state.lock:
            touch_state.error = "touch input stopped"
        print(f"touch reader stopped: {e}", file=sys.stderr)


