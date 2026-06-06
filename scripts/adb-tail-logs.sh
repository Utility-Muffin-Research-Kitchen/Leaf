#!/usr/bin/env bash
set -euo pipefail

LINES="${1:-120}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"
case "$LINES" in
    ''|*[!0-9]*)
        echo "usage: $0 [line_count]" >&2
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
REMOTE_USERDATA_PATH="${REMOTE_USERDATA_PATH:-$REMOTE_PLATFORM_PATH/userdata}"
REMOTE_LOGS_PATH="${REMOTE_LOGS_PATH:-$REMOTE_USERDATA_PATH/logs}"

"${ADB[@]}" shell "
printf '== $REMOTE_LOGS_PATH/umrk-launcher.log ==\\n'
tail -n '$LINES' '$REMOTE_LOGS_PATH/umrk-launcher.log' 2>/dev/null || true
printf '\\n== $REMOTE_LOGS_PATH/umrk-launcher-install.log ==\\n'
tail -n '$LINES' '$REMOTE_LOGS_PATH/umrk-launcher-install.log' 2>/dev/null || true
printf '\\n== $REMOTE_LOGS_PATH/umrk-launcher-uninstall.log ==\\n'
tail -n '$LINES' '$REMOTE_LOGS_PATH/umrk-launcher-uninstall.log' 2>/dev/null || true
"
