#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-}"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"

case "$MODE" in
    on|--on|enable|--enable)
        MODE="on"
        ;;
    off|--off|disable|--disable)
        MODE="off"
        ;;
    *)
        echo "usage: $0 on|off" >&2
        exit 1
        ;;
esac

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

echo "Using adb device: $("${ADB[@]}" get-serialno)"

REMOTE_SDCARD_PATH="$(PLATFORM_ID="$PLATFORM_ID" REMOTE_SDCARD_PATH="$REQUESTED_REMOTE_SDCARD_PATH" ADB_SERIAL="$serial" "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh")"
REMOTE_SYSTEM_PATH="${REMOTE_SYSTEM_PATH:-$REMOTE_SDCARD_PATH/.system/leaf}"
REMOTE_PLATFORM_PATH="${REMOTE_PLATFORM_PATH:-$REMOTE_SYSTEM_PATH/platforms/$PLATFORM_ID}"
MARKER="${UMRK_MARKER_PATH:-$REMOTE_PLATFORM_PATH/enabled}"

if [ "$MODE" = "on" ]; then
    "${ADB[@]}" shell "mkdir -p '${MARKER%/*}' && touch '$MARKER' && sync"
    echo "Marker enabled: $MARKER"
else
    "${ADB[@]}" shell "rm -f '$MARKER' && sync"
    echo "Marker disabled: $MARKER"
fi
