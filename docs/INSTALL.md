# Installing

Two halves: the app on the console, and something on your PC that knows your
Claude usage. Do the console first.

Before you start, check the console can run it at all:
[docs/COMPATIBILITY.md](COMPATIBILITY.md).

---

## 1. Get the files onto the console

**Over the network**, if SSH is on (ArkOS: Options → *Enable Remote Services*):

```sh
scp -r pocket-clawd ark@<console-ip>:/roms/
```

**Or with the SD card in your PC**: copy the `pocket-clawd` folder onto the
card's ROMs partition, so you end up with `/roms/pocket-clawd/`.

## 2. Run the installer

On the console, over SSH or from a terminal:

```sh
cd /roms/pocket-clawd
./install.sh          # from the install/ folder: ./install/install.sh
```

You'll see roughly:

```
=== Pocket Clawd installer ===

  ROMs folder : /roms
  app         : /roms/pocketclawd/app (168 pet frames)
  carousel    : backed up to /etc/emulationstation/es_systems.cfg.pocketclawd-backup
  carousel    : entry added
  themes      : logo installed into 4 theme(s)

  Restarting EmulationStation so it picks up the new system...
```

EmulationStation restarts and **Pocket Clawd** appears on the main carousel with
its own logo. Pick it like any console.

### What it changed

| Path | What happened |
|---|---|
| `/roms/pocketclawd/` | The app, its launcher, and a `gamelist.xml` |
| `/etc/emulationstation/es_systems.cfg` | One `<system>` block added, after a backup |
| `<each theme>/pocketclawd/` | A folder holding the carousel logo |

It has to edit that config file directly: EmulationStation on ArkOS reads
systems from exactly one path with no merging, so there's no drop-in mechanism
to use instead. The file is backed up first, running the installer again is
harmless, and `./install/uninstall.sh` restores it.

### Options

```sh
./install.sh --roms /roms2      # install to the second SD card
./install.sh --tools-only       # skip the carousel entry entirely
```

Use `--tools-only` on firmware that isn't ArkOS-family. The app still works,
you just launch `/roms/pocketclawd/Pocket Clawd.sh` yourself, or add it to
whatever menu your firmware uses.

### If it doesn't appear on the carousel

* **Nothing changed at all.** The installer needs to write to `/etc`. Try
  `sudo ./install.sh`.
* **Still missing after the restart.** Reboot the console properly; some
  builds don't restart EmulationStation cleanly.
* **Everything else is gone too.** The config file is malformed. Restore it:
  `sudo cp /etc/emulationstation/es_systems.cfg.pocketclawd-backup /etc/emulationstation/es_systems.cfg`
  and open an issue with what happened.
* **You have "Parse gamelists only" switched on.** The installer writes a
  `gamelist.xml`, so this should be handled, but check Start → Advanced.
* **It vanished after a firmware update.** Some ArkOS updates replace
  `es_systems.cfg` wholesale. Run `./install.sh` again.

## 3. Start the PC side

**Windows, nothing installed:** double-click `pc\Start Pocket Clawd.cmd`.

**Any OS with Python:**

```sh
python pc/clawd_pusher.py
```

Within a few seconds it should say `found a console at http://...`, and the
console's bars fill in. If it doesn't, see
[docs/NETWORKING.md](NETWORKING.md). The short version is
`python pc/clawd_pusher.py --device <console-ip>`.

Leave it running. Closing the window stops the updates; the console will show
`(STALE!)` and then Clawd falls asleep.

### Or skip the PC entirely

```sh
python pc/sync-token.py <console-ip>
```

then set `"mode": "direct"` in `/roms/pocketclawd/app/config.json`. The console
then talks to Anthropic by itself, anywhere it has internet. Read the direct-mode
section of [docs/NETWORKING.md](NETWORKING.md) first. It puts a token on the SD
card, and there are consequences to that.

## 4. Make it yours

Everything worth changing is a plain file in `/roms/pocketclawd/app/`:

* `quips.txt`: the things Clawd says. One per line.
* `anthem.wav`: what L2 plays. Any `anthem.mp3` / `.ogg` / `.opus` replaces it.
* `config.json`: thresholds, button codes, network mode.

Changes take effect next time you launch it.

## Removing it

```sh
/roms/pocket-clawd/install/uninstall.sh
```

Restores the EmulationStation config, deletes the app and every theme folder it
created, and restarts the menu. `--keep-data` preserves the usage history first.

## Running it from a PC instead

You don't need a console to see it:

```sh
python tools/sim.py --state critical
python tools/sim.py --all --out-dir docs/screenshots
```

It renders the real display code to a GIF or PNG. Useful for changing the
layout, and it's how the screenshots in the README were made.
