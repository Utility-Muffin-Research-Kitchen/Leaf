#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-${WORKSPACE_DIR:-$(cd "$ROOT_DIR/.." && pwd)}}"
LAUNCHER_SWITCHER_DIR="${LAUNCHER_SWITCHER_DIR:-$WORKSPACE_DIR/miniloong-launcher-switcher}"
BUILD_DIR="$ROOT_DIR/build/adb-install"
INSTALLER="$BUILD_DIR/umrk-launcher-install.sh"
REMOTE_INSTALLER="/tmp/umrk-launcher-install.sh"
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

python3 "$LAUNCHER_SWITCHER_DIR/make_launcher_switcher_sd.py" --force "$BUILD_DIR" >/dev/null

echo "ADB safety preflight:"
"${ADB[@]}" shell 'printf "  /etc/.usb_config="; cat /etc/.usb_config 2>/dev/null || true; printf "  lsattr="; lsattr /etc/.usb_config 2>/dev/null || true'
echo "Installer will refuse unless /etc/.usb_config is usb_adb_en and immutable."

echo "Pushing installer to $REMOTE_INSTALLER"
"${ADB[@]}" push "$INSTALLER" "$REMOTE_INSTALLER" >/dev/null
"${ADB[@]}" shell "chmod 755 '$REMOTE_INSTALLER'"

echo "Running installer"
"${ADB[@]}" shell "sh '$REMOTE_INSTALLER'"

echo "Installer log:"
"${ADB[@]}" shell "tail -80 '$REMOTE_LOGS_PATH/umrk-launcher-install.log' 2>/dev/null || true"

echo
echo "Leaf init hook installed. Reboot to exercise the rcS interrupt path."
