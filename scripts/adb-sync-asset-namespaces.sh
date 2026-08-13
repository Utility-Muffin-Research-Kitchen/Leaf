#!/usr/bin/env bash
# Copy the release-managed RetroArch menu asset bundle into the durable user
# assets tree RetroArch actually reads.
#
# RetroArch resolves assets_directory to ~/.config/retroarch/assets, which for
# Leaf is $SDCARD/.umrk/<platform>/retroarch/.config/retroarch/assets. That is
# deliberately NOT the release-managed platform tree: RetroArch's Online Updater
# has an "Update Assets" action that writes into assets_directory, and .system is
# replaced wholesale on every Leaf update. Same split, same reasoning as
# adb-sync-shader-namespaces.sh.
#
# Only the subtrees Leaf ships are replaced, so anything the updater adds
# alongside them (xmb/automatic, rgui, sounds, ...) is left alone.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_ID="${PLATFORM_ID:-mlp1}"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"

if [ "${1:-}" != "" ]; then
    echo "usage: $0" >&2
    exit 1
fi

if [ -n "${ADB_SERIAL:-}" ]; then
    serial="$ADB_SERIAL"
else
    serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
fi
[ -n "${serial:-}" ] || {
    echo "No online adb device found." >&2
    exit 1
}
ADB=(adb -s "$serial")

remote_sd="$(
    PLATFORM_ID="$PLATFORM_ID" \
    REMOTE_SDCARD_PATH="$REQUESTED_REMOTE_SDCARD_PATH" \
    ADB_SERIAL="$serial" \
        "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh"
)"
remote_system="${REMOTE_SYSTEM_PATH:-$remote_sd/.system/leaf}"
remote_platform="${REMOTE_PLATFORM_PATH:-$remote_system/platforms/$PLATFORM_ID}"
remote_bundle="$remote_platform/assets"
remote_user_assets="${UMRK_RETROARCH_USER_ASSETS_DIR:-$remote_sd/.umrk/$PLATFORM_ID/retroarch/.config/retroarch/assets}"

"${ADB[@]}" shell sh -s -- "$remote_bundle" "$remote_user_assets" <<'REMOTE_SH'
set -eu

bundle_root="$1"
user_root="$2"

sync_namespace() {
    namespace="$1"
    src="$bundle_root/$namespace"
    dst="$user_root/$namespace"
    tmp="$dst.tmp.$$"
    previous="$dst.previous.$$"
    [ -d "$src" ] || {
        echo "missing Leaf asset namespace: $src" >&2
        exit 1
    }
    mkdir -p "$(dirname "$dst")" || {
        echo "failed to create asset namespace parent for: $namespace" >&2
        exit 1
    }
    rm -rf "$tmp" "$previous" 2>/dev/null || true
    cp -R "$src" "$tmp"
    if [ -e "$dst" ]; then
        mv "$dst" "$previous"
    fi
    if ! mv "$tmp" "$dst"; then
        [ ! -e "$previous" ] || mv "$previous" "$dst" 2>/dev/null || true
        echo "failed to promote Leaf asset namespace: $namespace" >&2
        exit 1
    fi
    rm -rf "$previous" 2>/dev/null || true
}

mkdir -p "$user_root"
sync_namespace ozone
sync_namespace xmb/monochrome
sync_namespace pkg
echo "Synchronized Leaf menu asset namespaces at $user_root"
REMOTE_SH
