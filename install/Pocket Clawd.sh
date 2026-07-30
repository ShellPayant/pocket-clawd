#!/bin/bash
# Pocket Clawd launcher. EmulationStation runs this when you pick Pocket Clawd
# from the carousel. Exit with SELECT+START.
#
# It needs root for /dev/fb0 and /dev/input, which is why it re-runs itself
# under sudo. Everything else it does is optional and skipped if missing, so
# this should work on firmwares other than ArkOS too.

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

DIR="$(cd "$(dirname "$0")" && pwd)/app"
CURR_TTY="/dev/tty1"
LOG="$DIR/clawd.log"

export TERM=linux
export XDG_RUNTIME_DIR="/run/user/$(id -u)"

# blank the console and hide the cursor so nothing shows through the graphics
printf "\033c" > "$CURR_TTY" 2>/dev/null
printf "\e[?25l" > "$CURR_TTY" 2>/dev/null

cleanup() {
    printf "\033c" > "$CURR_TTY" 2>/dev/null
    printf "\e[?25h" > "$CURR_TTY" 2>/dev/null
    pkill -f "gptokeyb -1 Pocket Clawd.sh" 2>/dev/null
    exit 0
}
trap cleanup EXIT

# ArkOS's gamepad-to-keyboard shim, if this firmware has it. Pocket Clawd reads
# the gamepad itself, so this is only a safety net: it gives SELECT+START a
# second way to kill the app if something goes wrong.
if [ -x /opt/inttools/gptokeyb ]; then
    chmod 666 /dev/uinput 2>/dev/null
    export SDL_GAMECONTROLLERCONFIG_FILE="/opt/inttools/gamecontrollerdb.txt"
    pgrep -f gptokeyb | xargs -r kill -9 2>/dev/null
    /opt/inttools/gptokeyb -1 "Pocket Clawd.sh" -c "/opt/inttools/keys.gptk" \
        > /dev/null 2>&1 &
fi

# the network daemon keeps the usage file fresh; clawd.py also revives it, but
# starting it here means the data is already arriving by the time we draw
if ! pgrep -f "$DIR/netd.py" > /dev/null 2>&1; then
    setsid nohup python3 "$DIR/netd.py" >> "$LOG" 2>&1 &
fi

cd "$DIR" || exit 1
python3 "$DIR/clawd.py" 2>&1 | tee -a "$LOG" > "$CURR_TTY"
