#!/bin/bash
# Put Pocket Clawd on the console's main carousel, next to the consoles.
#
#   ./install.sh                 install (safe to re-run)
#   ./install.sh --roms /roms2   install to the second SD card instead
#   ./install.sh --tools-only    just install the app; no carousel entry
#
# What it changes, and why it has to:
#
#   /roms/pocketclawd/                 the app itself and its launcher
#   /etc/emulationstation/es_systems.cfg   ONE <system> block appended
#   <each theme>/pocketclawd/          a folder with the logo in it
#
# EmulationStation on ArkOS has no drop-in mechanism for extra systems -- the
# config file is read once, from one path, with no merging -- so a carousel
# entry means editing that file. It is backed up first, the edit is skipped if
# it's already there, and uninstall.sh puts everything back.
#
# Some ArkOS updates replace es_systems.cfg wholesale. If Pocket Clawd vanishes
# from the carousel after an update, just run this again.

set -u

SYS="pocketclawd"
FULLNAME="Pocket Clawd"
LAUNCHER="Pocket Clawd.sh"
# These are overridable so the installer can be exercised in a sandbox before
# it is ever pointed at a real console.
ES_CFG="${CLAWD_ES_CFG:-/etc/emulationstation/es_systems.cfg}"
THEME_ROOTS="${CLAWD_THEME_ROOTS:-/roms/themes /roms2/themes /etc/emulationstation/themes $HOME/.emulationstation/themes}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

ROMS=""
TOOLS_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --roms) ROMS="$2"; shift 2 ;;
        --tools-only) TOOLS_ONLY=1; shift ;;
        -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
        *) echo "unknown option: $1"; exit 1 ;;
    esac
done

say() { echo "  $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

echo
echo "=== Pocket Clawd installer ==="
echo

# --- 1. where do the ROMs live? --------------------------------------------
# Whichever card EmulationStation actually reads is the one that has to hold
# the app. On a two-card setup that is often /roms2, even though the app files
# might be sitting on /roms -- so ask the config rather than guess, by seeing
# which root the existing systems use.
if [ -z "$ROMS" ] && [ -f "$ES_CFG" ]; then
    # note: grep -c prints "0" *and* exits non-zero when nothing matches, so
    # "grep -c ... || echo 0" yields two lines, not one
    n1=$(grep -c '<path>/roms/' "$ES_CFG" 2>/dev/null | head -1)
    n2=$(grep -c '<path>/roms2/' "$ES_CFG" 2>/dev/null | head -1)
    [ -n "$n1" ] || n1=0
    [ -n "$n2" ] || n2=0
    if [ "$n2" -gt "$n1" ] && [ -d /roms2 ]; then
        ROMS="/roms2"
        say "detected  : EmulationStation reads /roms2 ($n2 systems there)"
    elif [ "$n1" -gt 0 ] && [ -d /roms ]; then
        ROMS="/roms"
        say "detected  : EmulationStation reads /roms ($n1 systems there)"
    fi
fi
if [ -z "$ROMS" ]; then
    case "$REPO" in
        /roms2/*) ROMS="/roms2" ;;
        /roms/*)  ROMS="/roms" ;;
        *) if [ -d /roms ]; then ROMS="/roms"; else ROMS="$HOME/roms"; fi ;;
    esac
fi
[ -d "$ROMS" ] || die "$ROMS does not exist. Pass --roms /path/to/roms."
say "ROMs folder : $ROMS"

TARGET="$ROMS/$SYS"
APP="$TARGET/app"

# --- 2. copy the app --------------------------------------------------------
mkdir -p "$APP/pets" || die "cannot write to $TARGET"
cp -f "$REPO/device/"*.py "$APP/" || die "cannot copy the app"
cp -f "$REPO/device/quips.txt" "$APP/" 2>/dev/null
cp -f "$REPO/device/pets/"*.raw "$APP/pets/" 2>/dev/null
[ -f "$REPO/device/anthem.wav" ] && cp -f "$REPO/device/anthem.wav" "$APP/"
# never overwrite settings the user has already edited
if [ ! -f "$APP/config.json" ]; then
    cp -f "$REPO/device/config.example.json" "$APP/config.json" 2>/dev/null
fi
cp -f "$HERE/$LAUNCHER" "$TARGET/$LAUNCHER" || die "cannot copy the launcher"
chmod +x "$TARGET/$LAUNCHER"
say "app         : $APP ($(ls "$APP"/pets 2>/dev/null | wc -l) pet frames)"

# A system whose folder is empty is DELETED at load time by EmulationStation,
# not merely hidden -- this gamelist plus the .sh above is what makes it appear.
cat > "$TARGET/gamelist.xml" <<XML
<?xml version="1.0"?>
<gameList>
	<game>
		<path>./$LAUNCHER</path>
		<name>$FULLNAME</name>
		<desc>A Claude usage pet that lives on your handheld.</desc>
	</game>
</gameList>
XML

if [ "$TOOLS_ONLY" = "1" ]; then
    echo
    say "Installed without a carousel entry."
    say "Run it with: $TARGET/$LAUNCHER"
    exit 0
fi

# --- 3. the carousel entry --------------------------------------------------
if [ ! -f "$ES_CFG" ]; then
    echo
    say "No $ES_CFG on this firmware."
    say "The app is installed; run it with: $TARGET/$LAUNCHER"
    say "(This step is for ArkOS-family firmware. See docs/INSTALL.md.)"
    exit 0
fi

if grep -q "<name>$SYS</name>" "$ES_CFG"; then
    say "carousel    : already present, left alone"
else
    BACKUP="$ES_CFG.pocketclawd-backup"
    [ -f "$BACKUP" ] || cp -p "$ES_CFG" "$BACKUP" || die "cannot back up $ES_CFG"
    say "carousel    : backed up to $BACKUP"

    BLOCK=$(mktemp)
    # <path> is written as /roms/... in ArkOS's own house style even when
    # installing to /roms2, because ArkOS's dual-card switch rewrites exactly
    # that string. If we're on /roms2 already, fix it up after.
    cat > "$BLOCK" <<XML
	<system>
		<name>$SYS</name>
		<fullname>$FULLNAME</fullname>
		<path>$TARGET/</path>
		<extension>.sh .SH</extension>
		<command>sudo chmod 666 /dev/tty1; %ROM% 2&gt;&amp;1 &gt; /dev/tty1; printf "\033c" &gt;&gt; /dev/tty1</command>
		<platform>ignore</platform>
		<theme>$SYS</theme>
	</system>
XML
    # insert before the closing tag rather than appending after it
    if ! sed -i "/<\/systemList>/e cat $BLOCK" "$ES_CFG" 2>/dev/null; then
        # busybox sed has no 'e' command; do it the portable way
        TMP=$(mktemp)
        awk -v blockfile="$BLOCK" '
            /<\/systemList>/ && !done {
                while ((getline line < blockfile) > 0) print line
                done = 1
            }
            { print }
        ' "$ES_CFG" > "$TMP" && cat "$TMP" > "$ES_CFG"
        rm -f "$TMP"
    fi
    rm -f "$BLOCK"
    if grep -q "<name>$SYS</name>" "$ES_CFG"; then
        say "carousel    : entry added"
    else
        die "could not edit $ES_CFG (are you root? try: sudo $0)"
    fi
fi

# --- 4. the logo, in every theme the console has ----------------------------
themed=0
seen_roots=""
for root in $THEME_ROOTS; do
    [ -d "$root" ] || continue
    # /etc/emulationstation/themes is often a symlink to /roms/themes; doing
    # the same folder twice is harmless but the count reads as a lie
    real=$(cd "$root" 2>/dev/null && pwd -P) || continue
    case " $seen_roots " in *" $real "*) continue ;; esac
    seen_roots="$seen_roots $real"
    for set_dir in "$root"/*/; do
        [ -d "$set_dir" ] || continue
        [ -f "$set_dir/theme.xml" ] || continue
        dest="$set_dir$SYS"
        mkdir -p "$dest" 2>/dev/null || continue
        # Clone whatever this theme does for an existing system, so the include
        # chain, sizing and background all match -- then swap in our art.
        donor=""
        for cand in ports retropie tools options snes; do
            if [ -f "$set_dir$cand/theme.xml" ]; then donor="$set_dir$cand"; break; fi
        done
        if [ -n "$donor" ]; then
            cp -f "$donor"/* "$dest/" 2>/dev/null
        else
            cat > "$dest/theme.xml" <<'XML'
<theme>
	<formatVersion>4</formatVersion>
	<include>./../theme.xml</include>
	<view name="system">
		<image name="logo">
			<path>./system.png</path>
		</image>
	</view>
</theme>
XML
        fi
        # overwrite every image the donor brought with ours, keeping its names
        for img in "$dest"/*.png "$dest"/*.svg "$dest"/*.jpg; do
            [ -f "$img" ] || continue
            case "$(basename "$img")" in
                system.*|logo.*|*_logo.*) cp -f "$HERE/theme/system.png" "$img" 2>/dev/null ;;
            esac
        done
        cp -f "$HERE/theme/system.png" "$dest/system.png" 2>/dev/null
        cp -f "$HERE/theme/logo.png" "$dest/logo.png" 2>/dev/null
        themed=$((themed + 1))
    done
done
say "themes      : logo installed into $themed theme(s)"

# --- 5. restart EmulationStation -------------------------------------------
echo
say "Restarting EmulationStation so it picks up the new system..."
sleep 1
# needs root, and we may not be root; -n so a password prompt can't hang us
if systemctl restart emulationstation 2>/dev/null    || sudo -n systemctl restart emulationstation 2>/dev/null; then
    say "EmulationStation restarted."
else
    say "Could not restart it automatically. Reboot the console, or run:"
    say "    sudo systemctl restart emulationstation"
fi

echo
echo "Done. Look for '$FULLNAME' on the main carousel."
echo "Next: start the pusher on your PC (see the README), or set"
echo "\"mode\": \"direct\" in $APP/config.json to skip the PC entirely."
echo
