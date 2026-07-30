#!/usr/bin/env python3
"""Pocket Clawd's network daemon: keeps the usage file fresh, however it can.

Three ways to get data, chosen by "mode" in config.json:

  push    A PC sends us the numbers. We listen on :8788 and also shout a UDP
          beacon so the PC can find us without anyone typing an IP address.
  pull    We fetch from a PC instead. Useful when our address keeps changing
          or the PC's firewall blocks outbound connections.
  direct  We talk to Anthropic ourselves, using a token copied onto the card.
          No PC involved, so it works away from home.

Whatever the mode, the result is the same: a small JSON file that clawd.py
reads, plus one line appended to a history log per real change, which is what
the trend chart is drawn from.

Standard library only -- several handheld firmwares ship a read-only /usr with
no pip.
"""
import http.server
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clawd_config  # noqa: E402

CFG = clawd_config.load_config()
DATA = clawd_config.data_path(CFG)
HIST = clawd_config.hist_path(CFG)

HIST_MAX = 12000   # lines; trimmed from the front on startup
HEARTBEAT = 600    # log an unchanged sample at least this often, so gaps show
MAX_BODY = 64 * 1024

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"

_last = [None, 0.0]   # last (fh, sd, fb, rl) logged, and when


def log(msg):
    print("[netd] %s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# --------------------------------------------------------------- history ---

def trim_hist():
    try:
        with open(HIST) as f:
            lines = f.readlines()
    except OSError:
        return
    if len(lines) <= HIST_MAX:
        return
    tmp = HIST + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.writelines(lines[-HIST_MAX:])
        os.replace(tmp, HIST)
    except OSError:
        pass


def log_hist(d):
    """Append {t, fh, sd, fb} for this sample. The same numbers arrive
    repeatedly between API fetches, so only changes are logged -- plus a
    heartbeat line every HEARTBEAT seconds, which is what makes a real gap
    (PC asleep, console off) distinguishable from a genuinely flat window.

    Timestamps are device time, not the sender's `epoch`: readers compare them
    against their own clock, so a skewed device clock has to be consistently
    wrong rather than half-wrong."""
    key = (int(d.get("five_hour_pct", 0) or 0),
           int(d.get("seven_day_pct", 0) or 0),
           int(d.get("scoped_pct", d.get("fable_pct", 0)) or 0),
           int(bool(d.get("rl"))))
    now = time.time()
    if key == _last[0] and now - _last[1] < HEARTBEAT:
        return
    _last[0], _last[1] = key, now
    rec = {"t": int(now), "fh": key[0], "sd": key[1], "fb": key[2]}
    if key[3]:
        rec["rl"] = 1
    try:
        parent = os.path.dirname(HIST)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(HIST, "a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError as exc:
        log("cannot write history: %s" % exc)


def store(payload, link):
    """Write the usage file the display reads. Everything funnels through here
    so the file is always valid JSON, whatever produced it."""
    if not isinstance(payload, dict):
        return False
    payload = dict(payload)
    payload.setdefault("link", link)
    tmp = DATA + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, DATA)
    except OSError as exc:
        log("cannot write %s: %s" % (DATA, exc))
        return False
    log_hist(payload)
    return True


# ------------------------------------------------------------- discovery ---

class Beacon:
    """Announces "a console is here" on the local network, so nobody has to
    find and type an IP address. In pull mode the PC answers with its own
    address, which is how we learn where to fetch from."""

    def __init__(self, cfg):
        self.enabled = bool(cfg.get("discovery", True))
        self.port = int(cfg.get("discovery_port", 8787))
        self.mode = cfg.get("mode", "push")
        self.listen_port = int(cfg.get("port", 8788))
        self.sock = None
        self.next_send = 0.0
        self.pc_url = None
        if not self.enabled:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setblocking(False)
            s.bind(("", 0))
            self.sock = s
        except OSError as exc:
            log("discovery unavailable: %s" % exc)

    def tick(self):
        if self.sock is None:
            return
        now = time.time()
        if now >= self.next_send:
            self.next_send = now + 5
            msg = json.dumps({
                "app": clawd_config.APP,
                "mode": self.mode,
                "port": self.listen_port,
                "host": socket.gethostname(),
            }).encode("utf-8")
            for target in ("255.255.255.255", "<broadcast>"):
                try:
                    self.sock.sendto(msg, (target, self.port))
                    break
                except OSError:
                    continue
        while True:
            try:
                raw, addr = self.sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                return
            try:
                reply = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            url = reply.get("url")
            if url and reply.get("app") == clawd_config.APP + "-pc":
                if url != self.pc_url:
                    log("found a pusher at %s (%s)" % (url, addr[0]))
                self.pc_url = url


# ------------------------------------------------------------ push mode ----

class Handler(http.server.BaseHTTPRequestHandler):
    secret = ""

    def _deny(self, code, why):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()
        log("rejected %s: %s" % (self.client_address[0], why))

    def do_POST(self):
        if self.secret and self.headers.get("X-Clawd-Secret", "") != self.secret:
            return self._deny(403, "bad secret")
        try:
            n = int(self.headers.get("content-length", 0))
        except ValueError:
            return self._deny(400, "bad content-length")
        # the sender is not necessarily friendly: cap it before reading
        if n <= 0 or n > MAX_BODY:
            return self._deny(413, "body of %d bytes" % n)
        body = self.rfile.read(n)
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return self._deny(400, "not JSON")
        if not isinstance(payload, dict):
            return self._deny(400, "not a JSON object")
        store(payload, payload.get("link") or "push")
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        try:
            with open(DATA, "rb") as f:
                body = f.read()
            self.send_response(200)
        except OSError:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def run_push(cfg, beacon):
    Handler.secret = cfg.get("secret", "")
    srv = http.server.HTTPServer((cfg.get("bind", "0.0.0.0"),
                                  int(cfg.get("port", 8788))), Handler)
    srv.timeout = 1.0
    log("listening on %s:%s%s" % (cfg.get("bind", "0.0.0.0"), cfg.get("port"),
                                  " (secret required)" if Handler.secret else ""))
    while True:
        srv.handle_request()      # returns after srv.timeout even with no client
        beacon.tick()


# ------------------------------------------------------------ pull mode ----

def http_get_json(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(MAX_BODY).decode("utf-8", "replace"))


def run_pull(cfg, beacon):
    every = max(15, int(cfg.get("poll_seconds", 60)))
    configured = cfg.get("pc_url", "")
    log("pull mode, every %ds%s" % (every, (", from " + configured) if configured
                                    else ", waiting for a pusher to announce itself"))
    next_poll = 0.0
    while True:
        beacon.tick()
        now = time.time()
        url = configured or beacon.pc_url
        if url and now >= next_poll:
            next_poll = now + every
            try:
                payload = http_get_json(url)
                store(payload, "pull")
                log("fetched from %s" % url)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                log("fetch failed: %s" % exc)
        time.sleep(1)


# ---------------------------------------------------------- direct mode ----

def read_token(cfg):
    """Accepts either a copy of Claude Code's credentials file or a plain
    {"accessToken": "..."} written by hand."""
    path = cfg.get("token_path") or os.path.join(clawd_config.HERE, "token.json")
    try:
        with open(path) as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None, path
    if isinstance(obj, dict) and "claudeAiOauth" in obj:
        obj = obj["claudeAiOauth"]
    if isinstance(obj, dict) and obj.get("accessToken"):
        return obj, path
    return None, path


def refresh_token(cfg, tok, path):
    """Optional, and off unless you fill in oauth_refresh_url and
    oauth_client_id yourself. Access tokens are short-lived, so without this
    direct mode needs the token re-copied when it expires -- see
    docs/NETWORKING.md, which explains why these aren't shipped filled in."""
    url = cfg.get("oauth_refresh_url", "")
    client_id = cfg.get("oauth_client_id", "")
    if not (url and client_id and tok.get("refreshToken")):
        return None
    body = json.dumps({"grant_type": "refresh_token",
                       "refresh_token": tok["refreshToken"],
                       "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            got = json.loads(r.read(MAX_BODY).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log("token refresh failed: %s" % exc)
        return None
    access = got.get("access_token") or got.get("accessToken")
    if not access:
        return None
    tok = dict(tok)
    tok["accessToken"] = access
    if got.get("refresh_token"):
        tok["refreshToken"] = got["refresh_token"]
    if got.get("expires_in"):
        tok["expiresAt"] = int((time.time() + int(got["expires_in"])) * 1000)
    try:
        with open(path, "w") as f:
            json.dump(tok, f)
    except OSError:
        pass
    log("token refreshed")
    return tok


def fmt_reset(iso):
    """'2026-07-30T23:00:00Z' -> '23:00' today, 'THU 13:00' otherwise."""
    if not iso:
        return "?"
    txt = str(iso).replace("Z", "+00:00")
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(txt)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        local = time.localtime(dt.timestamp())
    except (ValueError, OverflowError, OSError):
        return "?"
    if time.strftime("%Y%m%d", local) == time.strftime("%Y%m%d"):
        return time.strftime("%H:%M", local)
    return time.strftime("%a %H:%M", local).upper()


def build_payload(usage, rl=0):
    five = usage.get("five_hour") or {}
    seven = usage.get("seven_day") or {}
    scoped_pct, scoped_label = 0, "SCOPED"
    for lim in usage.get("limits") or []:
        if lim.get("kind") == "weekly_scoped":
            scoped_pct = int(lim.get("percent") or 0)
            model = ((lim.get("scope") or {}).get("model") or {})
            name = model.get("display_name") or model.get("id") or ""
            if name:
                scoped_label = str(name).split("-")[0].upper()[:9]
            break
    return {
        "five_hour_pct": int(five.get("utilization") or 0),
        "five_hour_reset": fmt_reset(five.get("resets_at")),
        "seven_day_pct": int(seven.get("utilization") or 0),
        "seven_day_reset": fmt_reset(seven.get("resets_at")),
        "scoped_pct": scoped_pct,
        "scoped_label": scoped_label,
        "updated": time.strftime("%H:%M"),
        "epoch": int(time.time()),
        "sessions": "",
        "rl": rl,
    }


def run_direct(cfg, beacon):
    every = max(60, int(cfg.get("poll_seconds", 120)))
    backoff = 0.0
    log("direct mode, polling Anthropic every %ds" % every)
    while True:
        beacon.tick()
        tok, path = read_token(cfg)
        if not tok:
            store({"five_hour_pct": 0, "seven_day_pct": 0, "scoped_pct": 0,
                   "updated": time.strftime("%H:%M"), "auth": "missing",
                   "note": "NO TOKEN ON THE CARD"}, "direct")
            log("no usable token at %s -- see docs/NETWORKING.md" % path)
            time.sleep(30)
            continue
        if time.time() < backoff:
            time.sleep(2)
            continue
        headers = {"Authorization": "Bearer %s" % tok["accessToken"],
                   "anthropic-beta": OAUTH_BETA,
                   "User-Agent": "pocket-clawd"}
        try:
            usage = http_get_json(USAGE_URL, headers)
            store(build_payload(usage), "direct")
            log("fetched usage")
            time.sleep(every)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                log("rate limited; backing off 5 minutes")
                backoff = time.time() + 300
                # keep showing the last good numbers, just flagged as limited
                try:
                    with open(DATA) as f:
                        prev = json.load(f)
                    prev["rl"] = 1
                    prev["updated"] = time.strftime("%H:%M")
                    store(prev, "direct")
                except (OSError, ValueError):
                    pass
            elif exc.code in (401, 403):
                fresh = refresh_token(cfg, tok, path)
                if fresh is None:
                    log("token rejected (%d) -- re-copy it with pc/sync-token"
                        % exc.code)
                    store({"five_hour_pct": 0, "seven_day_pct": 0,
                           "scoped_pct": 0, "updated": time.strftime("%H:%M"),
                           "auth": "expired",
                           "note": "TOKEN EXPIRED - RESYNC IT"}, "direct")
                    time.sleep(120)
            else:
                log("HTTP %d" % exc.code)
                time.sleep(30)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log("fetch failed: %s" % exc)
            time.sleep(30)


# ------------------------------------------------------------------ main ---

def main():
    mode = (CFG.get("mode") or "push").lower()
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1].lower()
    trim_hist()
    log("mode=%s data=%s hist=%s" % (mode, DATA, HIST))
    beacon = Beacon(CFG)
    if mode == "pull":
        run_pull(CFG, beacon)
    elif mode == "direct":
        run_direct(CFG, beacon)
    else:
        run_push(CFG, beacon)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
