#!/usr/bin/env python3
"""Copy your Claude token to the console, for "direct" mode.

Direct mode is the one that works away from home: the console talks to
Anthropic itself, so no PC has to be involved. The cost is that a copy of your
OAuth access token lives on the SD card.

    python sync-token.py 192.168.1.42
    python sync-token.py 192.168.1.42 --user ark --dir /roms/pocketclawd/app

Read docs/NETWORKING.md before using this. In short: anyone who takes the card
out of the console can read the token, and it is enough to spend your Claude
quota. Don't do this on a console you lend out. Access tokens are also
short-lived, so expect to re-run this occasionally.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile

CRED_FILE = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
DEFAULT_DIR = "/roms/pocketclawd/app"


def read_credentials():
    try:
        with open(CRED_FILE) as f:
            obj = json.load(f)
        oauth = obj.get("claudeAiOauth")
        if oauth and oauth.get("accessToken"):
            return oauth
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
                oauth = obj.get("claudeAiOauth") or obj
                if oauth.get("accessToken"):
                    return oauth
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", help="the console's address")
    ap.add_argument("--user", default="ark",
                    help="SSH user (ArkOS uses 'ark', ROCKNIX uses 'root')")
    ap.add_argument("--dir", default=DEFAULT_DIR,
                    help="install folder on the console (default: %s)" % DEFAULT_DIR)
    ap.add_argument("--print-only", action="store_true",
                    help="write token.json here instead of copying it")
    args = ap.parse_args()

    oauth = read_credentials()
    if not oauth:
        print("No Claude Code credentials found (%s)." % CRED_FILE)
        print("Log in with Claude Code first.")
        return 1

    token = {"accessToken": oauth["accessToken"]}
    for extra in ("refreshToken", "expiresAt"):
        if oauth.get(extra):
            token[extra] = oauth[extra]

    if args.print_only:
        with open("token.json", "w") as f:
            json.dump(token, f)
        print("wrote token.json here -- copy it to %s on the console" % args.dir)
        return 0

    tmp = os.path.join(tempfile.mkdtemp(), "token.json")
    with open(tmp, "w") as f:
        json.dump(token, f)
    target = "%s@%s:%s/token.json" % (args.user, args.host, args.dir)
    print("copying to %s" % target)
    try:
        r = subprocess.run(["scp", tmp, target])
    except FileNotFoundError:
        print("scp not found. Install OpenSSH, or use --print-only and copy the")
        print("file onto the SD card by hand.")
        return 1
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if r.returncode:
        print("copy failed.")
        return r.returncode
    print("done. Set \"mode\": \"direct\" in the console's config.json,")
    print("then restart Pocket Clawd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
