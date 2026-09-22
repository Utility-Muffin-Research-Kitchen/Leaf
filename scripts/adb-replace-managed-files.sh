#!/usr/bin/env bash
# Replace only the files a payload manages inside a directory it shares with
# local extras.
#
# A developer card can carry cores and info files that are not part of the
# shipped set (the flycast_2022*pgo experiments, for one). Deleting the whole
# directory to refresh the managed set would erase them, so this removes just
# the names about to be pushed and leaves everything else on the card alone.
#
# usage: ADB_SERIAL=<serial> adb-replace-managed-files.sh REMOTE_DIR LOCAL_DIR PATTERN
set -euo pipefail

remote_dir="${1:-}"
local_dir="${2:-}"
pattern="${3:-}"

if [ -z "$remote_dir" ] || [ -z "$local_dir" ] || [ -z "$pattern" ]; then
    echo "usage: ADB_SERIAL=<serial> $0 REMOTE_DIR LOCAL_DIR PATTERN" >&2
    exit 2
fi

case "$remote_dir" in
    *"'"*|*$'\n'*)
        echo "unsupported remote directory: $remote_dir" >&2
        exit 2
        ;;
esac

[ -d "$local_dir" ] || exit 0

names=""
shopt -s nullglob
for entry in "$local_dir"/$pattern; do
    [ -f "$entry" ] || continue
    name="$(basename "$entry")"
    case "$name" in
        *"'"*|*$'\n'*)
            echo "unsupported managed filename: $name" >&2
            exit 2
            ;;
    esac
    names="$names '$name'"
done
[ -n "$names" ] || exit 0

if [ -n "${ADB_SERIAL:-}" ]; then
    serial="$ADB_SERIAL"
else
    serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
fi
[ -n "$serial" ] || {
    echo "No online adb device found." >&2
    exit 1
}

adb -s "$serial" shell "mkdir -p '$remote_dir' && cd '$remote_dir' && rm -f$names"
