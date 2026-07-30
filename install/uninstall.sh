#!/bin/bash
# Remove Pocket Clawd and put the console back exactly as it was.
#
#   ./uninstall.sh              remove everything
#   ./uninstall.sh --keep-data  leave the usage history behind
#
# Restores the es_systems.cfg backup taken at install time when it's still
# there; otherwise it cuts our <system> block out of the live file. Either way
# the theme folders it created are deleted and nothing of ours remains.

set -u

SYS="pocketclawd"
ES_CFG="${CLAWD_ES_CFG:-/etc/emulationstation/es_systems.cfg}"
BACKUP="$ES_CFG.pocketclawd-backup"
ROMS_ROOTS="${CLAWD_ROMS_ROOTS:-/roms /roms2 $HOME}"
THEME_ROOTS="${CLAWD_THEME_ROOTS:-/roms/themes /roms2/themes /etc/emulationstation/themes $HOME/.emulationstation/themes}"
HERE="$(cd "$(dirname "$0")" && pwd)"

KEEP_DATA=0
[ "${1:-}" = "--keep-data" ] && KEEP_DATA=1

say() { echo "  $*"; }

echo
echo "=== Removing Pocket Clawd ==="
echo

# --- carousel entry ---------------------------------------------------------
if [ -f "$ES_CFG" ] && grep -q "<name>$SYS</name>" "$ES_CFG"; then
    if [ -f "$BACKUP" ] && ! grep -q "<name>$SYS</name>" "$BACKUP"; then
        cp -f "$BACKUP" "$ES_CFG" && say "es_systems.cfg: restored from the backup"
        rm -f "$BACKUP"
    else
        # No usable backup: delete just our block, from <system> to </system>
        TMP=$(mktemp)
        awk -v sys="$SYS" '
            /<system>/ { buf = $0 "\n"; inblock = 1; ours = 0; next }
            inblock {
                buf = buf $0 "\n"
                if ($0 ~ "<name>" sys "</name>") ours = 1
                if ($0 ~ /<\/system>/) {
                    if (!ours) printf "%s", buf
                    inblock = 0
                }
                next
            }
            { print }
        ' "$ES_CFG" > "$TMP" && cat "$TMP" > "$ES_CFG"
        rm -f "$TMP"
        say "es_systems.cfg: our entry removed"
    fi
else
    say "es_systems.cfg: nothing of ours in it"
fi

# --- app folders ------------------------------------------------------------
for root in $ROMS_ROOTS; do
    target="$root/$SYS"
    [ -d "$target" ] || continue
    if [ "$KEEP_DATA" = "1" ] && [ -f "$target/app/usage_hist.jsonl" ]; then
        keep="$root/pocketclawd-history.jsonl"
        cp -f "$target/app/usage_hist.jsonl" "$keep" 2>/dev/null &&
            say "history kept at $keep"
    fi
    rm -rf "$target" && say "removed $target"
done

# --- theme folders ----------------------------------------------------------
removed=0
for root in $THEME_ROOTS; do
    [ -d "$root" ] || continue
    for dir in "$root"/*/"$SYS"; do
        [ -d "$dir" ] || continue
        rm -rf "$dir" && removed=$((removed + 1))
    done
done
say "themes: removed $removed folder(s)"

# --- running processes ------------------------------------------------------
pkill -f "$SYS/app/clawd.py" 2>/dev/null
pkill -f "$SYS/app/netd.py" 2>/dev/null
rm -f /tmp/pocket-clawd.json 2>/dev/null

echo
say "Restarting EmulationStation..."
sleep 1
if command -v systemctl > /dev/null 2>&1 && systemctl restart emulationstation 2>/dev/null; then
    :
else
    say "Could not restart it automatically -- reboot the console instead."
fi

echo
echo "Done. Pocket Clawd is gone."
echo
