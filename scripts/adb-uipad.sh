#!/usr/bin/env bash
set -euo pipefail

# Drive a Leaf app's UI on the MLP1 with a synthetic gamepad, over adb.
#
#   scripts/adb-uipad.sh install         cross-compile and push the pad
#   scripts/adb-uipad.sh start           create the pad and keep it alive
#   scripts/adb-uipad.sh send A          press buttons (repeatable, in order)
#   scripts/adb-uipad.sh send LEFT LEFT A
#   scripts/adb-uipad.sh stop            destroy the pad and clean up
#
# Order matters: `start` must run BEFORE the app under test launches. SDL
# enumerates joysticks once at init, so a pad created afterwards is invisible to
# that process and the presses go to the launcher instead. See devtools/uipad.c.
#
# The launcher is a live Wayland client that also consumes pad input; when
# driving an app directly, suspend it first:
#
#   adb shell pkill -STOP -x loong_pangu     # ... run the test ...
#   adb shell pkill -CONT  -x loong_pangu
#
# Note loong_pangu is also the daemon, so jawakad IPC will not answer while it
# is stopped. For device IPC use the on-device jawaka-platformctl instead of
# rolling a client:
#
#   jawaka-platformctl --socket /tmp/jawaka-runtime/jawakad.sock request JSON
#
# and for reboot use scripts/adb-restart-loong.sh (`adb reboot` is a no-op here).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LEAF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF_DIR/.." && pwd)}"
TOOLCHAIN_IMAGE="${TOOLCHAIN_IMAGE:-ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:latest}"

REMOTE_BIN=/tmp/uipad
REMOTE_FIFO=/tmp/uipad.fifo
REMOTE_LOG=/tmp/uipad.log

if [ -n "${ADB_SERIAL:-}" ]; then
    serial="$ADB_SERIAL"
else
    serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
    if [ -z "${serial:-}" ]; then
        echo "No online adb device found." >&2
        exit 1
    fi
fi
ADB=(adb -s "$serial")

cmd="${1:-}"
shift || true

case "$cmd" in
install)
    out="$LEAF_DIR/build/uipad"
    mkdir -p "$LEAF_DIR/build"
    # The container sees the workspace at /workspace, matching the other lanes.
    docker run --rm -v "$WORKSPACE_DIR":/workspace -w /workspace "$TOOLCHAIN_IMAGE" \
        /opt/mlp1-toolchain/bin/aarch64-buildroot-linux-gnu-gcc \
        -std=gnu11 -Wall -Wextra -O2 -static \
        -o /workspace/Leaf/build/uipad \
        /workspace/Leaf/scripts/devtools/uipad.c
    "${ADB[@]}" push "$out" "$REMOTE_BIN" >/dev/null
    "${ADB[@]}" shell "chmod +x $REMOTE_BIN"
    rm -f "$out"
    echo "Installed $REMOTE_BIN on $serial"
    ;;

start)
    # pkill -x matches the process NAME. Do not use pkill -f with the binary
    # path: the adb shell's own command line contains that path, so -f kills
    # this shell before the rest of the line runs.
    "${ADB[@]}" shell "pkill -x uipad" >/dev/null 2>&1 || true
    "${ADB[@]}" shell "rm -f $REMOTE_FIFO $REMOTE_LOG && mkfifo $REMOTE_FIFO && test -p $REMOTE_FIFO" \
        || { echo "Could not create $REMOTE_FIFO on the device." >&2; exit 1; }
    # serve opens the fifo O_RDWR itself, so no holder process is needed.
    "${ADB[@]}" shell "setsid sh -c '$REMOTE_BIN --serve $REMOTE_FIFO > $REMOTE_LOG 2>&1' \
                       </dev/null >/dev/null 2>&1 & exit 0" >/dev/null 2>&1
    sleep 3
    if "${ADB[@]}" shell "cat $REMOTE_LOG 2>/dev/null" | tr -d '\r' | grep -q ready; then
        echo "Pad ready. Launch the app under test now."
    else
        echo "Pad did not come up; check $REMOTE_LOG on the device." >&2
        exit 1
    fi
    ;;

send)
    if [ "$#" -eq 0 ]; then
        echo "usage: $0 send BUTTON [BUTTON ...]" >&2
        exit 1
    fi
    "${ADB[@]}" shell "echo '$*' > $REMOTE_FIFO"
    ;;

stop)
    "${ADB[@]}" shell "echo quit > $REMOTE_FIFO 2>/dev/null" >/dev/null 2>&1 || true
    sleep 1
    "${ADB[@]}" shell "pkill -x uipad; rm -f $REMOTE_FIFO $REMOTE_LOG" >/dev/null 2>&1 || true
    echo "Pad stopped."
    ;;

*)
    sed -n '3,28p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
