"""Pipeline monitor: checks the real data in Supabase every minute, keeps check state in SQLite, sends ntfy alerts when
a check changes state, and serves a status page with controls (run now, test notification, mute, pause).

    python3 services/monitor/monitor.py              # loop + status page on http://127.0.0.1:8100
    python3 services/monitor/monitor.py --once       # one run, print every result, exit 1 if any check fails
    python3 services/monitor/monitor.py --port 8101 --interval 120

Settings come from the environment or the repository's .env file (see .env.example): SUPABASE_URL and
SUPABASE_SECRET_KEY (read-only use here), MONITOR_DEVICES (default node1), NTFY_TOPIC (no topic = alerts are only
printed), NTFY_SERVER (default https://ntfy.sh), NTFY_TOKEN (optional), MONITOR_HTTP (optional URLs to check,
"name=url,name=url"). State lives in data/monitor.sqlite (gitignored). Standard library only.
"""
import argparse
import hmac
import html
import http.client
import http.server
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import checks
from checks import FAIL, OK, OFF, PLAUSIBLE, PROBES, UNKNOWN, WARN, Snapshot
from store import CONFIRM_RUNS, Store

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "jobs"))
from fetch_weather import load_env   # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "monitor.sqlite"
ROW_LIMIT = 1000                      # Supabase's default max rows per answer; 30 min of one node is ~30
TOPIC_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")   # ASCII: ids end up in notification titles (HTTP headers)
NET_ERRORS = (OSError, http.client.HTTPException, ValueError)   # URLError/HTTPError are OSErrors


def config(env=os.environ):
    """Settings from the environment. Raises KeyError for a missing Supabase setting, ValueError for a bad value."""
    topic = env.get("NTFY_TOPIC", "").strip()
    if topic and not TOPIC_RE.fullmatch(topic):
        raise ValueError("NTFY_TOPIC may only contain letters, digits, - and _ (at most 64)")
    for name in ("SUPABASE_URL", "NTFY_SERVER"):
        if name in env and not env[name].startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with https:// (or http://)")
    devices = [d.strip() for d in env.get("MONITOR_DEVICES", "node1").split(",") if d.strip()]
    if not all(DEVICE_RE.fullmatch(d) for d in devices):
        raise ValueError("MONITOR_DEVICES: ids may only contain letters, digits, - and _ (at most 32 each)")
    targets = {}
    for item in filter(None, (s.strip() for s in env.get("MONITOR_HTTP", "").split(","))):
        name, sep, url = item.partition("=")
        if not sep or not re.fullmatch(r"[a-z0-9_-]+", name) or not url.startswith(("http://", "https://")):
            raise ValueError(f"MONITOR_HTTP entry {item!r}: expected name=http(s)://...")
        targets[name] = url
    return {
        "supabase_url": env["SUPABASE_URL"].rstrip("/"),
        "supabase_key": env["SUPABASE_SECRET_KEY"],
        "devices": devices,
        "ntfy_server": env.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        "ntfy_topic": topic,
        "ntfy_token": env.get("NTFY_TOKEN", "").strip(),
        "http": targets,
    }


def rest_get(cfg, table, params):
    """GET rows from Supabase's REST API (PostgREST) as a list of dicts."""
    key = cfg["supabase_key"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):   # legacy service_role JWT
        headers["Authorization"] = f"Bearer {key}"
    url = f"{cfg['supabase_url']}/rest/v1/{table}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as resp:
        return json.load(resp)


def describe(e):
    """Short error text for the status page, logs and alerts. Headers (the key) are never included, and anything that
    looks like a URL or path is cut out: urllib puts the whole URL, with the ntfy topic, into some error messages."""
    if isinstance(e, urllib.error.HTTPError):
        text = f"HTTP {e.code} {e.reason}"
    elif isinstance(e, urllib.error.URLError):
        text = f"cannot connect ({e.reason})"
    else:
        text = f"{type(e).__name__}: {e}"
    return re.sub(r"\S*/\S*", "<url>", text)


def ts(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def gather(cfg, now, get=rest_get):
    """Fetch what the checks need: about 4 + 2 per node small queries per run (more while a probe is missing)."""
    snap = Snapshot(devices=cfg["devices"])
    try:
        for d in cfg["devices"]:
            # Newest row by measured_at (indexed); its received_at says when the node last got through
            newest = get(cfg, "indoor_readings", {"select": "received_at", "device_id": f"eq.{d}",
                                                  "order": "measured_at.desc", "limit": 1})
            snap.last_received[d] = ts(newest[0]["received_at"]) if newest else None
        since = f"gte.{(now - checks.WINDOW).isoformat()}"
        rows = []
        for d in cfg["devices"]:
            # Per node and newest first: if a flood of rows hits the row cap, the oldest ones are cut, not the newest
            newest_first = get(cfg, "indoor_readings", {
                "select": ",".join(["device_id", "measured_at", "received_at", *PLAUSIBLE]), "device_id": f"eq.{d}",
                "measured_at": since, "order": "measured_at.desc", "limit": ROW_LIMIT})
            rows += reversed(newest_first)
        for r in rows:
            r["measured_at"], r["received_at"] = ts(r["measured_at"]), ts(r["received_at"])
        snap.rows = rows
        others = get(cfg, "indoor_readings", {"select": "device_id", "device_id": f"not.in.({','.join(cfg['devices'])})",
                                              "measured_at": since, "order": "measured_at.desc", "limit": ROW_LIMIT})
        snap.other_devices = {str(r["device_id"]) for r in others}
        for d in cfg["devices"]:
            for col in PROBES:
                seen = [r["measured_at"] for r in rows if r["device_id"] == d and r.get(col) is not None]
                if not seen:   # not in the window: look further back (lost recently, or never fitted?)
                    found = get(cfg, "indoor_readings", {
                        "select": "measured_at", "device_id": f"eq.{d}", col: "not.is.null",
                        "measured_at": f"gte.{(now - checks.PROBE_LOOKBACK).isoformat()}",
                        "order": "measured_at.desc", "limit": 1})
                    seen = [ts(found[0]["measured_at"])] if found else []
                snap.probe_seen[(d, col)] = seen[-1] if seen else None
        this_hour = now.replace(minute=0, second=0, microsecond=0)
        hours = get(cfg, "weather_hourly", {"select": "observed_at", "source": "eq.open-meteo",
                                            "observed_at": f"gte.{(this_hour - checks.WEATHER_GAP_WINDOW).isoformat()}",
                                            "order": "observed_at", "limit": 1000})
        snap.weather_hours = {ts(h["observed_at"]) for h in hours}
        last = get(cfg, "weather_hourly", {"select": "fetched_at", "order": "fetched_at.desc", "limit": 1})
        snap.weather_fetched_at = ts(last[0]["fetched_at"]) if last else None
    except (*NET_ERRORS, KeyError, TypeError) as e:   # also unexpected JSON shapes
        snap.error = describe(e)
    return snap


def http_probe(url, timeout=5):
    """(status code, None) or (None, error text). Redirects are followed; 4xx/5xx come back as codes."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except NET_ERRORS as e:
        return None, describe(e)


def ntfy_send(cfg, title, message, priority, tags):
    """POST one notification (https://docs.ntfy.sh/publish/). Title and tags are ASCII; the body may be UTF-8."""
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if cfg["ntfy_token"]:
        headers["Authorization"] = f"Bearer {cfg['ntfy_token']}"
    req = urllib.request.Request(f"{cfg['ntfy_server']}/{cfg['ntfy_topic']}", data=message.encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def alert_text(t):
    """(title, priority, tags) for a transition row."""
    new, was = t["new_status"], t["was"]
    if new == FAIL:
        return f"FAIL {t['check_id']}", "high", "rotating_light"
    if new == WARN:
        return f"WARN {t['check_id']}", "default", "warning"
    return f"OK {t['check_id']} (was {was})", "low", "white_check_mark"


def deliver(cfg, store, now, send=ntfy_send, log=print):
    """Send queued alerts in order; stop at the first failure and retry on the next run (an alert ntfy rejects for good,
    HTTP 4xx, is marked failed instead of blocking the rest). Alerts of checks muted now, and all alerts while paused,
    are marked instead of sent; store.update() already marks those raised during a mute or pause."""
    if not cfg["ntfy_topic"]:
        return
    paused, muted = store.paused_until(now), store.mutes(now)
    for t in store.unsent(now):
        if paused or t["check_id"] in muted:
            store.mark_sent(t["id"], now, "paused" if paused else "muted")
            continue
        title, priority, tags = alert_text(t)
        try:
            send(cfg, title, t["message"], priority, tags)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code not in (408, 429):   # rejected for good: retrying cannot help
                log(f"ntfy: rejected {t['check_id']} alert ({describe(e)}), skipped")
                store.mark_sent(t["id"], now, "failed")
                continue
            log(f"ntfy: not delivered ({describe(e)}), retrying next run")
            return
        except NET_ERRORS as e:
            log(f"ntfy: not delivered ({describe(e)}), retrying next run")
            return
        store.mark_sent(t["id"], now)


def run_once(cfg, store, now=None, get=rest_get, probe_url=http_probe, send=ntfy_send, log=print):
    now = now or datetime.now(timezone.utc)
    snap = gather(cfg, now, get)
    snap.http = {name: probe_url(url) for name, url in cfg["http"].items()}
    results = checks.evaluate(snap, now)
    for t in store.update(results, now):
        log(f"{now:%Y-%m-%d %H:%M:%S} {t['check_id']}: {t['old_status']} -> {t['new_status']} ({t['message']})"
            + (" [alert]" if t["alert"] else ""))
    deliver(cfg, store, now, send, log)
    store.set_meta("last_run", now.isoformat())
    return results


# --- Status page and controls -------------------------------------------------------------------------------------
# Listens on 127.0.0.1 only. Buttons are POST forms carrying a random token that only this page knows: any website
# open in the same browser can send a POST to localhost (cross-site request forgery), but it cannot read the page to
# learn the token. The Host header must be 127.0.0.1 or localhost, so a domain re-pointed at 127.0.0.1 (DNS
# rebinding) cannot read the page or the token either.

ORDER = {FAIL: 0, WARN: 1, UNKNOWN: 2, OK: 3, OFF: 4}
MUTE_HOURS = (1, 24)
FLASH = {   # the page shows these fixed texts after a button; nothing from the request is echoed
    "ran": "Checks ran just now.",
    "run-queued": "Run requested; it is taking a while, results appear on the next refresh.",
    "test-sent": "Test notification sent: it should be on your phone now.",
    "test-failed": "Test notification failed (see the monitor's terminal for the error).",
    "test-off": "NTFY_TOPIC is not set: alerts are only printed in the terminal.",
    "muted": "Check muted: it is still tracked and shown, but its alerts are not sent.",
    "unmuted": "Check unmuted.",
    "paused": "All alerts paused: changes are still recorded, nothing is sent.",
    "resumed": "Alerts resumed.",
}
HOW_IT_WORKS = """
<p>Every <b>{interval} s</b> the monitor asks Supabase (read only) for the newest row of each node, its rows of the
last {window}, which other device ids sent rows, when each probe last reported, and the weather hours. It also opens the URLs in MONITOR_HTTP. Pure rules
(<code>checks.py</code>) turn that into one status per check:</p>
<ul><li><span class="s ok">ok</span> fine; <span class="s off">off</span> sensor never fitted (no alert);
<span class="s warn">warn</span> needs a look; <span class="s fail">fail</span> broken;
<span class="s unknown">unknown</span> nothing to judge (Supabase not answering, or the node is silent, so its sensor
checks are not blamed too).</li>
<li><b>Debounce:</b> a new status only counts after {confirm} runs in a row agree, so one odd sample does not alert.
While it waits the row shows e.g. "(fail? 1/{confirm})".</li>
<li><b>Alerts</b> go to ntfy only when the severity changes (ok/off &rarr; warn &rarr; fail and back). Going to or from
unknown never alerts by itself. Undelivered alerts are retried every run for 24 h.</li>
<li><b>Mute</b> silences one check's alerts for a while; <b>pause</b> silences all. Changes are still recorded below
(alert column: muted / paused) and are not sent afterwards.</li>
<li>State lives in <code>{db}</code>, so a restart does not alert again. This page and the monitor only run while this
Mac is awake: nothing watches the watcher yet (an outside ping to /healthz would).</li></ul>
"""


def local(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%d %b %H:%M:%S") if iso else ""


class Controls:
    """What the page's buttons act on, shared between the page threads and the monitor loop."""

    def __init__(self, cfg, interval, db_path, send=ntfy_send, run_wait=20):
        self.cfg, self.interval, self.db_path, self.send, self.run_wait = cfg, interval, db_path, send, run_wait
        self.token = secrets.token_urlsafe(24)   # new on every start; old tabs need a reload
        self.run_now = threading.Event()         # set by the page, cleared by the loop when it starts a run
        self.run_done = threading.Event()        # set by the loop after each run


def status_data(store, interval, now):
    last_run = store.get_meta("last_run")
    stale = last_run is None or (now - datetime.fromisoformat(last_run)).total_seconds() > 3 * interval
    return {
        "last_run": last_run,
        "monitor_ok": not stale,
        "paused_until": store.paused_until(now),
        "mutes": store.mutes(now),
        "checks": [dict(r) for r in sorted(store.checks(), key=lambda r: (ORDER[r["status"]], r["check_id"]))],
        "transitions": [dict(r) for r in store.transitions(30)],
    }


def render(data, controls, flash=None):
    """Status page HTML. Every value from the database is escaped: device ids come from rows anyone holding the
    publishable key can insert."""
    e = html.escape
    cfg = controls.cfg

    def button(action, label, **fields):
        hidden = "".join(f"<input type='hidden' name='{k}' value='{e(str(v))}'>" for k, v in fields.items())
        return (f"<form method='post' action='/action'><input type='hidden' name='token' value='{controls.token}'>"
                f"<input type='hidden' name='action' value='{action}'>{hidden}<button>{label}</button></form>")

    rows = []
    for c in data["checks"]:
        cid = c["check_id"]
        pending = (f" <span class='meta'>({e(c['pending'])}? {c['pending_runs']}/{CONFIRM_RUNS})</span>"
                   if c["pending"] else "")
        explained = checks.explain(cid)
        details = (f"<details><summary>{e(cid)}</summary><p><b>Watches:</b> {e(explained[0])}</p>"
                   f"<p><b>Rule:</b> {e(explained[1])}</p><p><b>If it fails:</b> {e(explained[2])}</p></details>"
                   if explained else e(cid))
        until = data["mutes"].get(cid)
        mute = (f"<span class='meta'>muted until {e(local(until))}</span>{button('unmute', 'Unmute', check=cid)}"
                if until else "".join(button("mute", f"Mute {h} h", check=cid, hours=h) for h in MUTE_HOURS))
        rows.append(f"<tr><td class='s {e(c['status'])}'>{e(c['status'])}</td><td>{details}</td>"
                    f"<td>{e(c['message'])}{pending}</td><td class='when'>{e(local(c['since']))}</td>"
                    f"<td class='ctl'>{mute}</td></tr>")
    history = [f"<tr><td class='when'>{e(local(t['at']))}</td><td>{e(t['check_id'])}</td>"
               f"<td><span class='s {e(t['old_status'])}'>{e(t['old_status'])}</span> &rarr; "
               f"<span class='s {e(t['new_status'])}'>{e(t['new_status'])}</span></td><td>{e(t['message'])}</td>"
               f"<td class='meta'>{e(t['delivery'] or ('queued' if t['alert'] else ''))}</td></tr>"
               for t in data["transitions"]]

    state = "running" if data["monitor_ok"] else "<span class='fail'>not running (no recent run)</span>"
    if not cfg["ntfy_topic"]:
        alerts = "alerts off (NTFY_TOPIC not set, printed only)"
    elif data["paused_until"]:
        alerts = f"<span class='warn'>alerts paused until {e(local(data['paused_until']))}</span>"
    else:
        alerts = f"alerts on via {e(cfg['ntfy_server'])}"
    pause = (button("resume", "Resume alerts") if data["paused_until"]
             else "".join(button("pause", f"Pause alerts {h} h", hours=h) for h in MUTE_HOURS))
    settings = [("Devices", ", ".join(cfg["devices"])), ("Run every", f"{controls.interval} s"),
                ("Supabase", cfg["supabase_url"]), ("ntfy server", cfg["ntfy_server"] if cfg["ntfy_topic"] else "off"),
                ("HTTP targets", ", ".join(f"{k} = {v}" for k, v in cfg["http"].items()) or "none (MONITOR_HTTP)"),
                ("State file", str(controls.db_path))]
    settings_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in settings)
    flash_html = f"<p class='flash'>{e(FLASH[flash])}</p>" if flash in FLASH else ""
    how = HOW_IT_WORKS.format(interval=controls.interval, confirm=CONFIRM_RUNS, db=e(str(controls.db_path)),
                              window=checks.fmt_age(checks.WINDOW))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30; url=/"><title>Pipeline Monitor</title><style>{PAGE_CSS}</style></head>
<body><h1>mould-detect monitor</h1>
<p class="meta">Monitor {state}; last run {e(local(data['last_run'])) or 'never'}; {alerts}.
Refreshes every 30 s; times are local. Click a check name for what it watches and what to do.</p>
<div class="bar">{button('run', 'Run checks now')}{button('test', 'Send test notification')}{pause}</div>
{flash_html}
<div class="table-wrap"><table><tr><th>Status</th><th>Check</th><th>Detail</th><th>Since</th><th>Alerts</th></tr>
{''.join(rows) or '<tr><td colspan=5>No runs yet</td></tr>'}</table></div>
<h2>Recent changes</h2>
<div class="table-wrap"><table><tr><th>When</th><th>Check</th><th>Change</th><th>Detail</th><th>Alert</th></tr>
{''.join(history) or '<tr><td colspan=5>None yet</td></tr>'}</table></div>
<h2>How the monitor works</h2>{how}
<h2>Settings</h2><p class="meta">From .env; change them there and restart the monitor. The ntfy topic and the key are
not shown: on ntfy.sh the topic works like a password.</p>
<div class="table-wrap"><table class="settings">{settings_rows}</table></div>
</body></html>"""


PAGE_CSS = """
:root { --bg: #fafaf8; --fg: #1d1d1b; --muted: #6b6b66; --line: #e2e2dc; --ok: #2f7d32; --warn: #a86400;
        --fail: #c62828; --unknown: #6b6b66; --off: #9a9a94; --btn: #efefea; --flash: #e8f1e8; }
@media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ececea; --muted: #9a9a94; --line: #2c2c2a;
        --ok: #66bb6a; --warn: #ffb74d; --fail: #ef5350; --unknown: #9a9a94; --off: #6b6b66; --btn: #262624;
        --flash: #1f2b1f; } }
body { background: var(--bg); color: var(--fg); font: 15px/1.45 system-ui, sans-serif; margin: 0 auto;
       max-width: 1040px; padding: 16px; }
h1 { font-size: 20px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; }
.meta { color: var(--muted); font-size: 13px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
td, th { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 500; }
.settings th { width: 140px; }
.s { font-weight: 600; text-transform: uppercase; font-size: 12px; white-space: nowrap; }
.ok { color: var(--ok); } .warn { color: var(--warn); } .fail { color: var(--fail); }
.unknown { color: var(--unknown); } .off { color: var(--off); }
.when { white-space: nowrap; color: var(--muted); }
details p { margin: 4px 0; max-width: 46em; color: var(--muted); } summary { cursor: pointer; }
form { display: inline; margin: 0 6px 6px 0; }
button { background: var(--btn); color: var(--fg); border: 1px solid var(--line); border-radius: 6px;
         padding: 5px 10px; font: inherit; font-size: 13px; cursor: pointer; }
button:hover { border-color: var(--muted); }
.bar { margin: 12px 0; } .ctl { white-space: nowrap; }
.flash { background: var(--flash); padding: 8px 12px; border-radius: 6px; }
code { font-size: 13px; }
"""


def make_handler(controls):
    db_path = controls.db_path

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 10   # seconds; a client that stops sending cannot hold a thread forever

        def host_ok(self):
            port = self.server.server_address[1]
            if self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return True
            self.reply(421, "text/plain", b"wrong host\n")
            return False

        def do_GET(self):
            if not self.host_ok():
                return
            url = urllib.parse.urlsplit(self.path)
            if url.path not in ("/", "/status.json", "/healthz"):
                return self.reply(404, "text/plain", b"not found\n")
            store = Store(db_path)   # one connection per request: sqlite3 connections stay in their own thread
            try:
                data = status_data(store, controls.interval, datetime.now(timezone.utc))
            finally:
                store.close()
            if url.path == "/healthz":   # for an outside uptime check of the monitor itself
                self.reply(200 if data["monitor_ok"] else 503, "text/plain",
                           b"ok\n" if data["monitor_ok"] else b"stale\n")
            elif url.path == "/status.json":
                self.reply(200, "application/json", json.dumps(data, indent=1).encode())
            else:
                flash = urllib.parse.parse_qs(url.query).get("done", [None])[0]
                self.reply(200, "text/html; charset=utf-8", render(data, controls, flash).encode())

        def do_POST(self):
            if not self.host_ok():
                return
            if urllib.parse.urlsplit(self.path).path != "/action":
                return self.reply(404, "text/plain", b"not found\n")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self.reply(400, "text/plain", b"bad request\n")
            if not 0 <= length <= 2048:
                return self.reply(413, "text/plain", b"too large\n")
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode(errors="replace")).items()}
            if not hmac.compare_digest(form.get("token", "").encode(), controls.token.encode()):   # bytes: any input
                return self.reply(403, "text/plain", b"missing or old token: reload the page\n")
            try:
                done = self.act(form)
            except ValueError:
                return self.reply(400, "text/plain", b"bad request\n")
            except sqlite3.OperationalError:   # database locked by the monitor loop for too long
                return self.reply(503, "text/plain", b"busy, try again\n")
            self.send_response(303)   # back to the page; a reload does not repeat the action
            self.send_header("Location", f"/?done={done}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def act(self, form):
            action, now = form.get("action"), datetime.now(timezone.utc)
            if action == "run":
                controls.run_done.clear()
                controls.run_now.set()
                return "ran" if controls.run_done.wait(controls.run_wait) else "run-queued"
            if action == "test":
                if not controls.cfg["ntfy_topic"]:
                    return "test-off"
                try:
                    controls.send(controls.cfg, "TEST mould-detect monitor",
                                  "Test notification from the status page. Alerts reach this phone.", "default", "bell")
                except NET_ERRORS as e:
                    print(f"test notification failed: {describe(e)}")
                    return "test-failed"
                return "test-sent"
            store = Store(db_path)
            try:
                if action in ("mute", "pause"):
                    hours = int(form.get("hours", ""))
                    if hours not in MUTE_HOURS:
                        raise ValueError(hours)
                    until = now + timedelta(hours=hours)
                if action in ("mute", "unmute"):
                    check = form.get("check", "")
                    if check not in {r["check_id"] for r in store.checks()}:
                        raise ValueError(check)
                    if action == "mute":
                        store.mute(check, until)
                    else:
                        store.unmute(check)
                    return action + "d"
                if action == "pause":
                    store.set_meta("paused_until", until.isoformat())
                    return "paused"
                if action == "resume":
                    store.set_meta("paused_until", now.isoformat())
                    return "resumed"
            finally:
                store.close()
            raise ValueError(action)

        def reply(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # no scripts at all; forms may only post back here; no framing (clickjacking on the buttons)
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):   # keep the terminal for check changes
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="one run, print all results, exit 1 if any check fails")
    parser.add_argument("--interval", type=int, default=60, help="seconds between runs (default 60)")
    parser.add_argument("--port", type=int, default=8100, help="status page port on 127.0.0.1 (0 = no page)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"state database (default {DEFAULT_DB})")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    try:
        load_env(REPO_ROOT / ".env")
    except OSError as e:
        print(f"cannot read .env ({e.strerror}); using the environment only")
    try:
        cfg = config()
    except KeyError as e:
        sys.exit(f"Set {e.args[0]} in .env")
    except ValueError as e:
        sys.exit(str(e))
    if cfg["ntfy_topic"] and len(cfg["ntfy_topic"]) < 20:
        print("warning: on ntfy.sh anyone who knows the topic name can read and post to it; "
              "use a long random one (python3 -c 'import secrets; print(secrets.token_urlsafe(18))')")
    args.db.parent.mkdir(exist_ok=True)
    store = Store(args.db, stale_after=timedelta(seconds=3 * args.interval))

    if args.once:
        results = run_once(cfg, store)
        for r in sorted(results, key=lambda r: (ORDER[r.status], r.check)):
            print(f"{r.status:8} {r.check:24} {r.message}")
        sys.exit(1 if any(r.status == FAIL for r in results) else 0)

    controls = Controls(cfg, args.interval, args.db)
    if args.port:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(controls))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Status page and controls on http://127.0.0.1:{args.port} (this Mac only)")
    print(f"Checking {', '.join(cfg['devices'])} every {args.interval} s; "
          f"alerts {'via ntfy' if cfg['ntfy_topic'] else 'printed only (NTFY_TOPIC not set)'}; Ctrl+C to stop")
    try:
        while True:
            started = time.monotonic()
            controls.run_now.clear()
            try:
                run_once(cfg, store)
            except Exception as e:   # a bug in one run must not stop the monitor; the page shows the stale run
                print(f"run failed: {describe(e)}")
            controls.run_done.set()
            # sleep until the next run is due, or until "Run checks now" on the page
            controls.run_now.wait(max(1, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
