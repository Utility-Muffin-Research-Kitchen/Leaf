#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_ID="${PLATFORM_ID:-mlp1}"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
MODE="all"

case "${1:-}" in
    "") ;;
    --migrate-only) MODE="migrate" ;;
    --sync-only) MODE="sync" ;;
    *)
        echo "usage: $0 [--migrate-only|--sync-only]" >&2
        exit 1
        ;;
esac

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
remote_bundle="$remote_platform/shaders"
remote_user_shaders="${UMRK_RETROARCH_USER_SHADERS_DIR:-$remote_sd/.umrk/$PLATFORM_ID/retroarch/.config/retroarch/shaders}"

"${ADB[@]}" shell sh -s -- "$remote_bundle" "$remote_user_shaders" "$MODE" <<'REMOTE_SH'
set -eu

bundle_root="$1"
user_root="$2"
mode="$3"

migrate_legacy_downloads() {
    legacy="$bundle_root/shaders_glsl"
    downloaded="$user_root/shaders_glsl"
    [ -d "$legacy" ] || return 0
    [ ! -e "$downloaded" ] || return 0
    preset_count="$(find "$legacy" -type f -name '*.glslp' 2>/dev/null |
        wc -l | tr -d ' ')"
    case "$preset_count" in
        ''|*[!0-9]*) return 0 ;;
    esac
    [ "$preset_count" -gt 11 ] || return 0
    mkdir -p "$user_root"
    tmp="$downloaded.tmp.$$"
    rm -rf "$tmp" 2>/dev/null || true
    cp -R "$legacy" "$tmp"
    mv "$tmp" "$downloaded"
    echo "Preserved $preset_count updater shader presets at $downloaded"
}

sync_namespace() {
    namespace="$1"
    src="$bundle_root/$namespace"
    dst="$user_root/$namespace"
    tmp="$dst.tmp.$$"
    previous="$dst.previous.$$"
    [ -d "$src" ] || {
        echo "missing Leaf shader namespace: $src" >&2
        exit 1
    }
    rm -rf "$tmp" "$previous" 2>/dev/null || true
    cp -R "$src" "$tmp"
    if [ -e "$dst" ]; then
        mv "$dst" "$previous"
    fi
    if ! mv "$tmp" "$dst"; then
        [ ! -e "$previous" ] || mv "$previous" "$dst" 2>/dev/null || true
        echo "failed to promote Leaf shader namespace: $namespace" >&2
        exit 1
    fi
    rm -rf "$previous" 2>/dev/null || true
}

case "$mode" in
    all|migrate) migrate_legacy_downloads ;;
esac
case "$mode" in
    all|sync)
        mkdir -p "$user_root/custom"
        sync_namespace leaf-bundled
        sync_namespace leaf-recommended
        echo "Synchronized Leaf shader namespaces at $user_root"
        ;;
esac
REMOTE_SH
