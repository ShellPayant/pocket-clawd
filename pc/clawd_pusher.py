#!/usr/bin/env python3
"""Send your Claude usage to a Pocket Clawd console. Windows, macOS or Linux.

Run it and leave it running:

    python clawd_pusher.py

It finds the console by itself if the console has discovery on (the default),
so there is usually no address to configure. Otherwise:

    python clawd_pusher.py --device 192.168.1.42
    python clawd_pusher.py --serve            # for a console in "pull" mode
    python clawd_pusher.py --dry-run          # print the data, send nothing

Where the numbers come from: Claude Code stores an OAuth token on this machine
when you log in, and this asks Anthropic for your own usage with it. The token
never leaves your computer except in that request to Anthropic. Nothing is sent
anywhere else, and the console only ever receives percentages.

Standard library only -- nothing to install.
"""
import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

APP = "pocket-clawd"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"

FETCH_EVERY = 120     # ask Anthropic this often
PUSH_EVERY = 60       # send to the console this often, cached in between
RATE_BACKOFF = 300    # the usage endpoint 429s readily; wait this long
DISCOVERY_PORT = 8787
SERVE_PORT = 8789
LOCK_PORT = 8790      # a bound socket is a simpler mutex than a PID file

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
CRED_FILE = os.path.join(CLAUDE_DIR, ".credentials.json")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")


def log(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ----------------------------------------------------------------- token ---

def read_token():
    """Claude Code's OAuth access token. It lives in a file on Windows and
    Linux; on macOS it's in the login Keychain instead."""
    try:
        with open(CRED_FILE) as f:
            obj = json.load(f)
        tok = (obj.get("claudeAiOauth") or {}).get("accessToken")
        if tok:
            return tok
    except (OSError, ValueError):
        pass
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s",
                 "Claude Code-credentials", "-w"],
                capture_output=True, text=True, timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                obj = json.loads(out.stdout.strip())
                tok = (obj.get("claudeAiOauth") or obj).get("accessToken")
                if tok:
                    return tok
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return None


# ------------------------------------------------------------- API + fmt ---

def fmt_reset(iso):
    """'...T23:00:00Z' -> '23:00' if that's today, else 'THU 13:00'."""
    if not iso:
        return "?"
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        local = time.localtime(dt.timestamp())
    except (ValueError, OverflowError, OSError):
        return "?"
    if time.strftime("%Y%m%d", local) == time.strftime("%Y%m%d"):
        return time.strftime("%H:%M", local)
    return time.strftime("%a %H:%M", local).upper()


def project_name(dirname):
    """Claude Code encodes a project path as a dash-mangled folder name;
    the last segment is the bit a human would recognise."""
    parts = [p for p in dirname.replace("\\", "-").split("-") if p]
    return (parts[-1] if parts else dirname).upper()[:10]


def active_sessions(within=300, limit=3):
    """Projects touched in the last few minutes -- one aquarium friend each."""
    names, newest, newest_at = [], None, 0
    try:
        entries = os.listdir(PROJECTS_DIR)
    except OSError:
        return [], None
    for entry in entries:
        path = os.path.join(PROJECTS_DIR, entry)
        if not os.path.isdir(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > newest_at:
            newest_at, newest = mtime, entry
        try:
            recent = any(
                f.endswith(".jsonl")
                and time.time() - os.path.getmtime(os.path.join(path, f)) < within
                for f in os.listdir(path))
        except OSError:
            recent = False
        if recent:
            name = project_name(entry)
            if name not in names:
                names.append(name)
    return names[:limit], (project_name(newest) if newest else None)


def fetch_usage(token):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer %s" % token,
        "anthropic-beta": OAUTH_BETA,
        "User-Agent": "pocket-clawd-pusher",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read(256 * 1024).decode("utf-8", "replace"))


def build_payload(usage):
    five = usage.get("five_hour") or {}
    seven = usage.get("seven_day") or {}
    scoped_pct, scoped_label = 0, "SCOPED"
    for lim in usage.get("limits") or []:
        if lim.get("kind") == "weekly_scoped":
            scoped_pct = int(lim.get("percent") or 0)
            # the model this weekly limit applies to, as Anthropic names it
            model = ((lim.get("scope") or {}).get("model") or {})
            name = model.get("display_name") or model.get("id") or ""
            if name:
                scoped_label = str(name).split("-")[0].upper()[:9]
            break
    sessions, newest = active_sessions()
    return {
        "five_hour_pct": int(five.get("utilization") or 0),
        "five_hour_reset": fmt_reset(five.get("resets_at")),
        "seven_day_pct": int(seven.get("utilization") or 0),
        "seven_day_reset": fmt_reset(seven.get("resets_at")),
        "scoped_pct": scoped_pct,
        "scoped_label": scoped_label,
        "updated": time.strftime("%H:%M"),
        "epoch": int(time.time()),
        "note": ("LAST PROJECT: %s" % newest) if newest else None,
        "sessions": ",".join(sessions),
        "rl": 0,
    }


# --------------------------------------------------------------- network ---

def local_ip_towards(host):
    """Our address on whichever interface reaches `host`. No packets sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Discovery(threading.Thread):
    """Consoles shout "I'm here" on UDP; we listen, so nobody types an IP.
    A console in pull mode gets our address shouted back."""

    daemon = True

    def __init__(self, serve_port=None):
        threading.Thread.__init__(self)
        self.targets = {}          # ip -> ("http://ip:port/", last seen)
        self.serve_port = serve_port
        self.sock = None

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", DISCOVERY_PORT))
            s.settimeout(2.0)
            self.sock = s
        except OSError as exc:
            log("discovery off (%s) -- use --device to name the console" % exc)
            return
        while True:
            try:
                raw, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if msg.get("app") != APP:
                continue
            ip = addr[0]
            mode = msg.get("mode", "push")
            if mode == "pull":
                if self.serve_port:
                    url = "http://%s:%d/usage.json" % (
                        local_ip_towards(ip), self.serve_port)
                    try:
                        s.sendto(json.dumps({"app": APP + "-pc",
                                             "url": url}).encode("utf-8"), addr)
                    except OSError:
                        pass
                continue
            url = "http://%s:%d/" % (ip, int(msg.get("port", 8788)))
            if ip not in self.targets:
                log("found a console at %s" % url)
            self.targets[ip] = (url, time.time())

    def urls(self, max_age=90):
        now = time.time()
        return [u for (u, seen) in self.targets.values() if now - seen < max_age]


def push(url, payload, secret="", timeout=5):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Clawd-Secret"] = secret
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status == 200


class ServeHandler(BaseHTTPRequestHandler):
    payload = {"note": "STARTING UP"}

    def do_GET(self):
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start_server(port):
    srv = HTTPServer(("0.0.0.0", port), ServeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log("serving usage on http://0.0.0.0:%d/usage.json for pull mode" % port)
    return srv


def claim_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


# ------------------------------------------------------------------ main ---

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", action="append", default=[],
                    help="console address, e.g. 192.168.1.42 or "
                         "http://192.168.1.42:8788/ (repeatable)")
    ap.add_argument("--secret", default="", help="must match the console's")
    ap.add_argument("--serve", action="store_true",
                    help="also serve the data for consoles in pull mode")
    ap.add_argument("--serve-port", type=int, default=SERVE_PORT)
    ap.add_argument("--no-discovery", action="store_true")
    ap.add_argument("--interval", type=int, default=FETCH_EVERY,
                    help="seconds between Anthropic fetches (default 120)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch once, print the payload, send nothing")
    args = ap.parse_args()

    token = read_token()
    if not token:
        log("no Claude Code credentials found.")
        log("expected %s -- log in with Claude Code first." % CRED_FILE)
        return 1

    if args.dry_run:
        try:
            usage = fetch_usage(token)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log("fetch failed: %s" % exc)
            return 1
        print(json.dumps(build_payload(usage), indent=2, sort_keys=True))
        return 0

    lock = claim_single_instance()
    if lock is None:
        log("another pusher is already running; nothing to do.")
        return 0

    targets = []
    for d in args.device:
        targets.append(d if d.startswith("http") else "http://%s:8788/" % d)

    disco = None
    if not args.no_discovery:
        disco = Discovery(args.serve_port if args.serve else None)
        disco.start()
    if args.serve:
        start_server(args.serve_port)

    log("watching your Claude usage. Ctrl-C to stop.")
    if targets:
        log("configured console(s): %s" % ", ".join(targets))
    elif disco:
        log("looking for a console on the network...")

    cached = None
    rate_limited = 0
    next_fetch = 0.0
    next_push = 0.0
    known = set()
    while True:
        now = time.time()
        if now >= next_fetch:
            try:
                cached = build_payload(fetch_usage(token))
                rate_limited = 0
                next_fetch = now + max(30, args.interval)
                log("usage: 5h %d%%  7d %d%%  %s %d%%" % (
                    cached["five_hour_pct"], cached["seven_day_pct"],
                    cached["scoped_label"], cached["scoped_pct"]))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    rate_limited = 1
                    next_fetch = now + RATE_BACKOFF
                    log("rate limited by Anthropic; retrying in %ds"
                        % RATE_BACKOFF)
                elif exc.code in (401, 403):
                    log("credentials rejected (%d). Log in with Claude Code "
                        "again." % exc.code)
                    next_fetch = now + RATE_BACKOFF
                else:
                    log("HTTP %d" % exc.code)
                    next_fetch = now + 60
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log("fetch failed: %s" % exc)
                next_fetch = now + 60

        urls = list(targets) + (disco.urls() if disco else [])
        appeared = [u for u in urls if u not in known]
        # Send on the timer, but also the moment a console turns up -- waiting
        # out the full interval after discovery makes it look broken.
        if cached and (now >= next_push or appeared):
            known.update(urls)
            next_push = now + PUSH_EVERY
            # Keep sending the cached numbers between fetches. The console
            # treats the file's age as "is this link alive", so going quiet
            # would look like a dead connection rather than a quiet API.
            payload = dict(cached)
            payload["rl"] = rate_limited
            payload["updated"] = time.strftime("%H:%M")
            payload["epoch"] = int(time.time())
            payload["sessions"] = ",".join(active_sessions()[0])
            ServeHandler.payload = payload
            sent = 0
            for url in urls:
                try:
                    push(url, payload, args.secret)
                    sent += 1
                except (urllib.error.URLError, OSError) as exc:
                    log("could not reach %s (%s)" % (url, exc))
                    known.discard(url)
            if urls and not sent:
                log("no console reachable")
        time.sleep(2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
