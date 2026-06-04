#!/usr/bin/env bash
set -euo pipefail

# Resolve the mounted MLP1 SD card that owns the Leaf launcher payload.
#
# By default this refuses to guess between multiple mounted cards. It accepts an
# explicit REMOTE_SDCARD_PATH for first-time or otherwise intentional staging.

REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
REMOTE_SDCARD_CANDIDATES="${REMOTE_SDCARD_CANDIDATES:-/mnt/sdcard /media/sdcard1}"

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

validate_remote_path() {
    case "$1" in
        ''|*$'\n'*|*"'"*)
            echo "Unsupported remote SD path: $1" >&2
            exit 1
            ;;
    esac
}

is_mounted() {
    path="$1"
    validate_remote_path "$path"
    "${ADB[@]}" shell "awk -v p='$path' '\$2 == p { found = 1; exit } END { exit found ? 0 : 1 }' /proc/mounts" >/dev/null 2>&1
}

has_marker() {
    path="$1"
    validate_remote_path "$path"
    "${ADB[@]}" shell "[ -e '$path/.system/leaf/enabled' ]" >/dev/null 2>&1
}

has_bundle() {
    path="$1"
    validate_remote_path "$path"
    "${ADB[@]}" shell "[ -f '$path/.system/leaf/launcher/bin/loong_pangu' ]" >/dev/null 2>&1
}

join_paths() {
    local IFS=' '
    printf '%s' "$*"
}

if [ -n "$REQUESTED_REMOTE_SDCARD_PATH" ] && [ "$REQUESTED_REMOTE_SDCARD_PATH" != "auto" ]; then
    validate_remote_path "$REQUESTED_REMOTE_SDCARD_PATH"
    if ! is_mounted "$REQUESTED_REMOTE_SDCARD_PATH"; then
        echo "$REQUESTED_REMOTE_SDCARD_PATH is not mounted on the device." >&2
        exit 1
    fi
    printf '%s\n' "$REQUESTED_REMOTE_SDCARD_PATH"
    exit 0
fi

mounted=()
ready=()
marked=()
bundled=()

for path in $REMOTE_SDCARD_CANDIDATES; do
    validate_remote_path "$path"
    if ! is_mounted "$path"; then
        continue
    fi

    mounted+=("$path")
    marker=0
    bundle=0
    if has_marker "$path"; then
        marker=1
        marked+=("$path")
    fi
    if has_bundle "$path"; then
        bundle=1
        bundled+=("$path")
    fi
    if [ "$marker" -eq 1 ] && [ "$bundle" -eq 1 ]; then
        ready+=("$path")
    fi
done

case "${#ready[@]}" in
    1)
        printf '%s\n' "${ready[0]}"
        exit 0
        ;;
    0)
        ;;
    *)
        echo "Ambiguous active Leaf SD: marker and launcher bundle found on: $(join_paths "${ready[@]}")" >&2
        echo "Set REMOTE_SDCARD_PATH=/mnt/sdcard or REMOTE_SDCARD_PATH=/media/sdcard1." >&2
        exit 2
        ;;
esac

case "${#marked[@]}" in
    1)
        echo "warning: using SD with UMRK marker but incomplete launcher bundle: ${marked[0]}" >&2
        printf '%s\n' "${marked[0]}"
        exit 0
        ;;
    0)
        ;;
    *)
        echo "Ambiguous Leaf SD: marker found on: $(join_paths "${marked[@]}")" >&2
        echo "Set REMOTE_SDCARD_PATH=/mnt/sdcard or REMOTE_SDCARD_PATH=/media/sdcard1." >&2
        exit 2
        ;;
esac

case "${#bundled[@]}" in
    1)
        echo "warning: using SD with UMRK launcher bundle but no marker: ${bundled[0]}" >&2
        printf '%s\n' "${bundled[0]}"
        exit 0
        ;;
    0)
        ;;
    *)
        echo "Ambiguous Leaf SD: launcher bundle found on: $(join_paths "${bundled[@]}")" >&2
        echo "Set REMOTE_SDCARD_PATH=/mnt/sdcard or REMOTE_SDCARD_PATH=/media/sdcard1." >&2
        exit 2
        ;;
esac

case "${#mounted[@]}" in
    1)
        echo "warning: no UMRK marker or launcher bundle found; using only mounted SD: ${mounted[0]}" >&2
        printf '%s\n' "${mounted[0]}"
        exit 0
        ;;
    0)
        echo "No MLP1 SD card is mounted at any candidate path: $REMOTE_SDCARD_CANDIDATES" >&2
        exit 1
        ;;
    *)
        echo "Could not identify active Leaf SD. Mounted candidates: $(join_paths "${mounted[@]}")" >&2
        echo "Expected exactly one mounted card with .system/leaf/enabled and/or .system/leaf/launcher/bin/loong_pangu." >&2
        echo "Set REMOTE_SDCARD_PATH=/mnt/sdcard or REMOTE_SDCARD_PATH=/media/sdcard1." >&2
        exit 3
        ;;
esac
