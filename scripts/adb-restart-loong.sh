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
    echo "Leaf init hook is installed; requesting reboot through jawakad."
    "${ADB[@]}" shell '
set -e
ctl=""
for root in /mnt/sdcard /media/sdcard1; do
    candidate="$root/.system/leaf/platforms/mlp1/launcher/bin/jawaka-platformctl"
    if [ -x "$candidate" ]; then
        ctl="$candidate"
        break
    fi
done
if [ -z "$ctl" ]; then
    echo "jawaka-platformctl not found on mounted SD cards" >&2
    exit 1
fi
if [ ! -S /tmp/jawaka-runtime/jawakad.sock ]; then
    echo "jawakad socket is not available" >&2
    exit 1
fi
"$ctl" --socket /tmp/jawaka-runtime/jawakad.sock request "{\"type\":\"platform-action\",\"action\":\"reboot\"}"
'
    echo "Waiting for device..."
    sleep 2
    "${ADB[@]}" wait-for-device
    for _ in $(seq 1 40); do
        if "${ADB[@]}" shell '[ -S /tmp/jawaka-runtime/jawakad.sock ]' >/dev/null 2>&1; then
            echo "Jawaka socket is ready."
            exit 0
        fi
        sleep 2
    done
    echo "Timed out waiting for Jawaka socket after reboot." >&2
    exit 1
fi

echo "Restarting Loong stack..."
"${ADB[@]}" shell "rm -f /tmp/leaf-restart-loong.log; sh -c '/etc/init.d/S50loong restart >/tmp/leaf-restart-loong.log 2>&1 &'"
sleep 3
"${ADB[@]}" shell "tail -80 /tmp/leaf-restart-loong.log 2>/dev/null || true"
