#!/usr/bin/env bash
set -euo pipefail

REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-/mnt/sdcard}"
REMOTE_USERDATA_PATH="${REMOTE_USERDATA_PATH:-$REMOTE_SDCARD_PATH/.system/leaf/userdata/mlp1}"
REMOTE_LOGS_PATH="${REMOTE_LOGS_PATH:-$REMOTE_USERDATA_PATH/logs}"

if [ -n "${ADB_SERIAL:-}" ]; then
    ADB=(adb -s "$ADB_SERIAL")
else
    serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
    if [ -z "${serial:-}" ]; then
        echo "No online adb device found." >&2
        exit 1
    fi
    ADB=(adb -s "$serial")
fi

echo "Using adb device: $("${ADB[@]}" get-serialno)"

"${ADB[@]}" shell '
if [ -x /usr/bin/umrk-launcher-switcher-uninstall.sh ]; then
    /usr/bin/umrk-launcher-switcher-uninstall.sh
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
