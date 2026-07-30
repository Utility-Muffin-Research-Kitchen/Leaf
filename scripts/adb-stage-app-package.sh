#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: $0 LOCAL_PACKAGE_DIR REMOTE_PACKAGE_DIR" >&2
    exit 2
fi
local_dir="$1"
remote_dir="$2"
[ -d "$local_dir" ] || { echo "missing package dir: $local_dir" >&2; exit 1; }
case "$remote_dir" in
    ''|*$'\n'*|*"'"*)
        echo "unsupported remote package path: $remote_dir" >&2
        exit 2
        ;;
esac
case "$remote_dir" in
    /*/Apps/*/*.pak) ;;
    *)
        echo "refusing destructive stage outside an Apps/<scope>/<name>.pak path: $remote_dir" >&2
        exit 2
        ;;
esac
case "$remote_dir/" in
    *'/../'*|*'/./'*|*'//'*)
        echo "refusing non-normalized remote package path: $remote_dir" >&2
        exit 2
        ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
operation_id="stage-app-$$"
quiesced=0

release_quiesce() {
    ADB_SERIAL="$serial" \
    PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}" \
    REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}" \
        "$ROOT_DIR/scripts/adb-package-quiesce.sh" end "$operation_id"
}

on_exit() {
    rc=$?
    trap - EXIT
    if [ "$quiesced" -eq 1 ] && ! release_quiesce; then
        echo "Package bytes may have changed, but Jawaka could not rescan/restore services." >&2
        if [ "$rc" -eq 0 ]; then rc=1; fi
    fi
    exit "$rc"
}
trap on_exit EXIT

if ! ADB_SERIAL="$serial" \
    PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}" \
    REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}" \
        "$ROOT_DIR/scripts/adb-package-quiesce.sh" begin "$operation_id"; then
    # A preflight refusal never latched the barrier; an unverified stop did.
    # A matching release is therefore a harmless best-effort cleanup in the
    # first case and preserves fail-closed ownership in the second case when
    # the survivor is still present.
    release_quiesce >/dev/null 2>&1 || true
    exit 1
fi
quiesced=1

"${ADB[@]}" shell "rm -rf '$remote_dir' && mkdir -p '$remote_dir'"
"${ADB[@]}" push "$local_dir/." "$remote_dir/" >/dev/null
"${ADB[@]}" shell "chmod 755 '$remote_dir/launch.sh' '$remote_dir/bin/'* 2>/dev/null || true"
"${ADB[@]}" shell "find '$remote_dir' -maxdepth 3 -type f | sort"

release_quiesce
quiesced=0
trap - EXIT
