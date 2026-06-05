#!/usr/bin/env bash
set -euo pipefail

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
if "${ADB[@]}" shell '[ -x /etc/init.d/S50leaf ]' >/dev/null 2>&1; then
    echo "Leaf init hook is installed; refusing to restart S50loong directly."
    echo "Reboot the device to exercise the init-hook path:"
    echo "  adb reboot"
    exit 0
fi

echo "Restarting Loong stack..."
"${ADB[@]}" shell "rm -f /tmp/leaf-restart-loong.log; sh -c '/etc/init.d/S50loong restart >/tmp/leaf-restart-loong.log 2>&1 &'"
sleep 3
"${ADB[@]}" shell "tail -80 /tmp/leaf-restart-loong.log 2>/dev/null || true"
