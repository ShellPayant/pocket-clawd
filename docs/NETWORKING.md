# Getting the numbers onto the console

The console draws whatever it finds in one small JSON file. Everything below is
just a different way of keeping that file fresh. Pick one, set `"mode"` in
`config.json`, restart Pocket Clawd.

The chip in the top-left corner tells you which mode is actually running.

---

## push — a PC sends the numbers (default)

```
 your PC                              the console
 clawd_pusher.py  ── HTTP POST ────▶  netd.py :8788  ──▶  usage file
```

Nothing to configure. Run `python pc/clawd_pusher.py` (or double-click
`pc/Start Pocket Clawd.cmd` on Windows) and leave it running.

**How it finds the console.** The console broadcasts a small UDP packet on port
8787 every five seconds saying "a Pocket Clawd is here". The pusher listens for
it and starts sending. Nobody types an IP address. If your network blocks
broadcast traffic, or the two are on different subnets, name it by hand:

```sh
python pc/clawd_pusher.py --device 192.168.1.42
```

**Locking it down.** By default anything on your network can POST numbers to
the console. On a home network that is a nuisance at worst — the only thing it
can do is show you wrong percentages — but if you'd rather not:

```jsonc
// console: config.json
{ "secret": "something-only-you-know" }
```
```sh
python pc/clawd_pusher.py --secret "something-only-you-know"
```

You can also bind it to one interface with `"bind": "192.168.1.42"`.

---

## pull — the console fetches instead

```
 your PC                              the console
 clawd_pusher.py --serve  ◀── GET ──  netd.py  ──▶  usage file
      :8789
```

Same data, opposite direction. Worth switching to when:

* the console gets a different IP every time it connects, and you're naming it
  by hand because discovery doesn't work on your network;
* a firewall on the PC blocks outgoing connections to the console;
* you'd rather the console did the asking.

```jsonc
// console: config.json
{ "mode": "pull", "poll_seconds": 60 }
```
```sh
python pc/clawd_pusher.py --serve
```

Discovery still does the introductions: the console announces itself, the
pusher replies with its own address, and the console starts fetching. Set
`"pc_url": "http://192.168.1.10:8789/usage.json"` to skip that.

Note this mode needs the **Python** pusher — the PowerShell one only pushes.

---

## direct — no PC at all

```
 the console
 netd.py ── HTTPS ──▶ api.anthropic.com ──▶ usage file
```

The console asks Anthropic for your usage itself. Nothing else has to be
switched on, so this is the one that works on a train, on a phone hotspot, or
anywhere your PC isn't.

The catch is that it needs your Claude OAuth token on the console's SD card.

```sh
python pc/sync-token.py 192.168.1.42          # copies it over SSH
```
```jsonc
// console: config.json
{ "mode": "direct", "poll_seconds": 120 }
```

**Read this before you use it.**

* The token sits in `token.json` on the card, in plain text. Anyone who takes
  the card out and puts it in a reader can read it, and it is enough to spend
  your Claude quota. Don't do this on a console you lend to other people.
* **Access tokens are short-lived.** When yours expires the console shows
  `TOKEN EXPIRED - RESYNC IT` and the 401 pet, and you run `sync-token.py`
  again. In practice: sync it before you leave the house.
* Automatic refresh is *possible* but isn't shipped switched on. `netd.py` will
  perform a standard OAuth refresh if you fill in `oauth_refresh_url` and
  `oauth_client_id` in `config.json`, but I haven't verified what Claude Code
  actually uses for those, and shipping a guess that silently fails would be
  worse than shipping nothing. If you work them out, those two settings are all
  it takes.
* If you'd rather not have a token on the card at all, use push or pull.

---

## hotspot — when your home WiFi won't work

Not a data mode; a way to get the console onto a network at all.

Plenty of these handhelds use a cheap USB WiFi dongle that only speaks 2.4GHz
and WPA2. If your home network is 5GHz-only or WPA3-only, the console simply
can't join it. The workaround is to have the PC host a network for it:

1. Windows: Settings → Network & Internet → **Mobile hotspot**. Set it to
   **2.4 GHz**, switch it on, and join it from the console's WiFi settings.
2. Then start the pusher with the hotspot watchdog, which switches the hotspot
   back on when Windows turns it off for having no clients:

```
powershell -ExecutionPolicy Bypass -File pc\clawd-pusher.ps1 -Hotspot
```

On Linux, `nmcli device wifi hotspot ssid pocket-clawd password something`
does the same job. macOS has Internet Sharing in System Settings, though it
can't be scripted.

Once connected this is ordinary **push** mode — the hotspot is only about the
link.

> Windows may also stop the hotspot five minutes after the last client
> disconnects. If that keeps biting you, the `PeerlessTimeoutEnabled` value
> under `HKLM\SYSTEM\CurrentControlSet\Services\icssvc\Settings` set to `0`
> turns that behaviour off. That's a system registry change; make it only if
> you understand it.

---

## What actually gets sent

One flat JSON object, about 300 bytes:

```json
{
  "five_hour_pct": 63,
  "five_hour_reset": "16:09",
  "seven_day_pct": 4,
  "seven_day_reset": "THU 13:00",
  "scoped_pct": 4,
  "scoped_label": "OPUS",
  "updated": "15:40",
  "epoch": 1785451207,
  "note": "LAST PROJECT: SIDEQUEST",
  "sessions": "SIDEQUEST,PORTFOLIO",
  "rl": 0,
  "link": "push"
}
```

Percentages, reset times, and the names of the projects you have open — those
last two are what the aquarium friends and their signs are made of. No prompts,
no code, no token. Check for yourself with:

```sh
python pc/clawd_pusher.py --dry-run
```

The console keeps a history file (`usage_hist.jsonl`) next to the app with one
line per change, which is what the trend chart draws. It's capped at 12,000
lines and trimmed on startup.

## When it isn't working

| What you see | Usually means |
|---|---|
| `WAITING FOR USAGE DATA` | The pusher isn't running, or hasn't found the console. Check its window for `found a console at ...`. |
| `(STALE!)` next to the time | Data arrived once but has stopped. The link dropped — on WiFi after sleep, reconnecting the console usually fixes it. |
| Clawd asleep with Zs | Nothing for ten minutes. Same causes as above. |
| The 429 pet | Anthropic is rate-limiting the usage endpoint. Nothing is broken; it backs off for five minutes and the numbers stay as they were. |
| `credentials rejected` | Log in with Claude Code again on the PC. |
| Console never appears | Discovery blocked. Use `--device <ip>`. Find the IP in the console's WiFi settings. |
