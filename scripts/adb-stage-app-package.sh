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
    ''|*$'\n'*|*$'\r'*)
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
platform_id="${PLATFORM_ID:-${DEVICE:-mlp1}}"
remote_sd="$(
    PLATFORM_ID="$platform_id" \
    REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}" \
    ADB_SERIAL="$serial" \
        "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh"
)"
install_path="${remote_dir#*/Apps/}"
printf -v db_path_arg '%q' "$remote_sd/.umrk/$platform_id/library.db"
pakrat_installs="$("${ADB[@]}" shell \
    "sh -c '[ ! -f \"\$1\" ] || sqlite3 \"\$1\" \"SELECT store_id || char(9) || install_path FROM pakrat_installs;\"' sh $db_path_arg")"
pakrat_installs="${pakrat_installs//$'\r'/}"
while IFS=$'\t' read -r store_id owned_path; do
    if [ "$owned_path" = "$install_path" ]; then
        echo "refusing to overwrite Pak Rat-owned package $store_id at Apps/$install_path; uninstall it in Pak Rat before using stage-app" >&2
        exit 1
    fi
done <<<"$pakrat_installs"

# adb joins the remote command into one shell string. Quote the validated path
# as one remote-shell argument, then let the inner sh script use it only as $1.
# This supports legitimate package names such as Joe's Calibrage.pak without
# interpolating them into shell source.
printf -v remote_dir_arg '%q' "$remote_dir"

release_quiesce() {
    ADB_SERIAL="$serial" \
    PLATFORM_ID="$platform_id" \
    REMOTE_SDCARD_PATH="$remote_sd" \
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
    PLATFORM_ID="$platform_id" \
    REMOTE_SDCARD_PATH="$remote_sd" \
        "$ROOT_DIR/scripts/adb-package-quiesce.sh" begin "$operation_id"; then
    # A preflight refusal never latched the barrier; an unverified stop did.
    # A matching release is therefore a harmless best-effort cleanup in the
    # first case and preserves fail-closed ownership in the second case when
    # the survivor is still present.
    release_quiesce >/dev/null 2>&1 || true
    exit 1
fi
quiesced=1

"${ADB[@]}" shell \
    "sh -c 'rm -rf -- \"\$1\" && mkdir -p -- \"\$1\"' sh $remote_dir_arg"
"${ADB[@]}" push "$local_dir/." "$remote_dir/" >/dev/null
"${ADB[@]}" shell \
    "sh -c 'chmod 755 \"\$1/launch.sh\" \"\$1/bin/\"* 2>/dev/null || true' sh $remote_dir_arg"
"${ADB[@]}" shell \
    "sh -c 'find \"\$1\" -maxdepth 3 -type f | sort' sh $remote_dir_arg"

release_quiesce
quiesced=0
trap - EXIT
