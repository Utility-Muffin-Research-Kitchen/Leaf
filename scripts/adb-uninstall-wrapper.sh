#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"

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
REMOTE_LAUNCHER_PATH="${REMOTE_LAUNCHER_PATH:-$REMOTE_PLATFORM_PATH/launcher}"
# Durable data roots live at the SD root, not under the release-managed .system tree
# (see umrk-env.sh): .userdata/<platform> + .umrk/<platform>.
REMOTE_USERDATA_PATH="${REMOTE_USERDATA_PATH:-$REMOTE_SDCARD_PATH/.userdata/$PLATFORM_ID}"
REMOTE_LOGS_PATH="${REMOTE_LOGS_PATH:-$REMOTE_USERDATA_PATH/logs}"
REMOTE_INTERNAL_DATA_PATH="${REMOTE_INTERNAL_DATA_PATH:-$REMOTE_SDCARD_PATH/.umrk/$PLATFORM_ID}"
REMOTE_MARKER_PATH="${UMRK_MARKER_PATH:-$REMOTE_PLATFORM_PATH/enabled}"
REMOTE_ADB_MARKER_PATH="${UMRK_ADB_MARKER_PATH:-$REMOTE_INTERNAL_DATA_PATH/adb-enabled}"

"${ADB[@]}" shell '
if [ -x /usr/bin/umrk-launcher-switcher-uninstall.sh ]; then
    PLATFORM='"'$PLATFORM_ID'"' DEVICE='"'$PLATFORM_ID'"' SDCARD_PATH='"'$REMOTE_SDCARD_PATH'"' SYSTEM_PATH='"'$REMOTE_PLATFORM_PATH'"' UMRK_PLATFORM_PATH='"'$REMOTE_PLATFORM_PATH'"' UMRK_LAUNCHER_PATH='"'$REMOTE_LAUNCHER_PATH'"' UMRK_ENV_FILE='"'$REMOTE_LAUNCHER_PATH/env.sh'"' USERDATA_PATH='"'$REMOTE_USERDATA_PATH'"' LOGS_PATH='"'$REMOTE_LOGS_PATH'"' UMRK_INTERNAL_DATA_PATH='"'$REMOTE_INTERNAL_DATA_PATH'"' UMRK_MARKER_PATH='"'$REMOTE_MARKER_PATH'"' UMRK_ADB_MARKER_PATH='"'$REMOTE_ADB_MARKER_PATH'"' /usr/bin/umrk-launcher-switcher-uninstall.sh
elif [ -f /loong/loong_pangu.stock.umrk ]; then
    cp -p /loong/loong_pangu.stock.umrk /loong/loong_pangu
    chmod 755 /loong/loong_pangu
    sync
    echo restored stock loong_pangu
else
    echo "no uninstaller or stock backup found" >&2
    exit 1
fi
'

echo "Uninstall log:"
"${ADB[@]}" shell "tail -80 '$REMOTE_LOGS_PATH/umrk-launcher-uninstall.log' 2>/dev/null || true"

echo
echo "Leaf init hook removed. Reboot to use stock boot cleanly."
