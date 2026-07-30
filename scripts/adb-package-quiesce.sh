#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "usage: $0 begin|end OPERATION_ID" >&2
    exit 2
}

[ "$#" -eq 2 ] || usage
action="$1"
operation_id="$2"
case "$action" in
    begin|end) ;;
    *) usage ;;
esac
case "$operation_id" in
    ''|*[!A-Za-z0-9._-]*)
        echo "invalid package operation id: $operation_id" >&2
        exit 2
        ;;
esac
if [ "${#operation_id}" -gt 63 ]; then
    echo "package operation id is longer than 63 bytes" >&2
    exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"
if [ -n "${ADB_SERIAL:-}" ]; then
    serial="$ADB_SERIAL"
else
    serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
fi
if [ -z "${serial:-}" ]; then
    echo "No online adb device found." >&2
    exit 1
fi
ADB=(adb -s "$serial")

remote_sd="$(
    PLATFORM_ID="$PLATFORM_ID" \
    REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}" \
    ADB_SERIAL="$serial" \
    "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh"
)"
case "$remote_sd" in
    ''|*$'\n'*|*"'"*)
        echo "unsupported resolved SD path: $remote_sd" >&2
        exit 1
        ;;
esac

request_type="package-quiesce-$action"
request="{\"type\":\"$request_type\",\"operation_id\":\"$operation_id\"}"
reply="$("${ADB[@]}" shell "
set -eu
env_file='$remote_sd/.system/leaf/platforms/$PLATFORM_ID/launcher/env.sh'
[ -f \"\$env_file\" ] || { echo 'Leaf runtime env is missing' >&2; exit 1; }
. \"\$env_file\"
ctl=\"\$UMRK_LAUNCHER_PATH/bin/jawaka-platformctl\"
[ -x \"\$ctl\" ] || { echo 'jawaka-platformctl is missing' >&2; exit 1; }
[ -S \"\$UMRK_DAEMON_SOCKET\" ] || { echo 'jawakad socket is unavailable' >&2; exit 1; }
\"\$ctl\" --socket \"\$UMRK_DAEMON_SOCKET\" request '$request'
")"
reply="${reply//$'\r'/}"
printf '%s\n' "$reply"
case "$reply" in
    *'"type":"ok"'*) ;;
    *)
        echo "Jawaka rejected package quiesce $action." >&2
        exit 1
        ;;
esac
