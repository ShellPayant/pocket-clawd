#!/usr/bin/env python3
"""Settings and paths shared by clawd.py (the display) and netd.py (the network
daemon). Both are deployed to the same folder and must agree on where the usage
file lives, so this is the one place that decides."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
APP = "pocket-clawd"

DEFAULT_CONFIG = {
    # --- display ---
    "fb": "/dev/fb0",
    "input_dir": "/dev/input",
    "warn_pct": 60,
    "crit_pct": 85,
    "fps": 20,
    "buttons": {},          # action name -> [event codes]; see --map-buttons

    # --- where the data lands ---
    "data_path": "",        # "" -> /tmp/pocket-clawd.json
    "hist_path": "",        # "" -> <state dir>/usage_hist.jsonl

    # --- networking (see docs/NETWORKING.md) ---
    "mode": "push",         # push | pull | direct
    "port": 8788,           # push: the port we listen on
    "bind": "0.0.0.0",      # push: interface to listen on
    "secret": "",           # push: if set, senders must match X-Clawd-Secret
    "discovery": True,      # announce ourselves so the PC needs no IP
    "discovery_port": 8787,
    "pc_url": "",           # pull: where to fetch from; "" -> use discovery
    "poll_seconds": 60,     # pull/direct: how often to refresh
    "token_path": "",       # direct: "" -> token.json next to this file
    "oauth_refresh_url": "",   # direct: optional, see docs/NETWORKING.md
    "oauth_client_id": "",
}


def _first_writable(*paths):
    for p in paths:
        if not p:
            continue
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".clawd-write-test")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return p
        except OSError:
            pass
    return None


def state_dir():
    """Somewhere durable for the trend history. The install folder is on the SD
    card and survives reboots, which is what we want; the rest are fallbacks for
    read-only or unusual installs."""
    return _first_writable(
        HERE,
        os.path.join(os.path.expanduser("~"), ".local", "share", APP),
        os.path.join("/tmp", APP),
    ) or "/tmp"


def config_path():
    return os.environ.get("CLAWD_CONFIG") or os.path.join(HERE, "config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path()) as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update(user)
    except (OSError, ValueError):
        pass
    return cfg


def data_path(cfg):
    return cfg.get("data_path") or os.path.join("/tmp", APP + ".json")


def hist_path(cfg):
    return cfg.get("hist_path") or os.path.join(state_dir(), "usage_hist.jsonl")
