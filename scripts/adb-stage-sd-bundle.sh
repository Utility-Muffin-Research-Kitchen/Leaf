#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Payload location. Defaults to this repo's own build output, but the workspace
# orchestrator overrides it to stage a centrally-assembled payload.
BUNDLE_ROOT="${BUNDLE_ROOT:-$ROOT_DIR/build/package}"
SYSTEM_DIR="$BUNDLE_ROOT/.system/leaf"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
MARKER_MODE="keep"
PLATFORM_MODE="replace"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"
PLATFORM_DIR="$SYSTEM_DIR/platforms/$PLATFORM_ID"
BUNDLE_DIR="$PLATFORM_DIR/launcher"

case "$PLATFORM_ID" in
    mlp1|tg5040|tg5050|my355|mac) ;;
    *)
        echo "unsupported PLATFORM_ID: $PLATFORM_ID" >&2
        exit 1
        ;;
esac

while [ "$#" -gt 0 ]; do
    case "$1" in
        --marker)
            MARKER_MODE="on"
            ;;
        --no-marker)
            MARKER_MODE="off"
            ;;
        --merge-platform)
            PLATFORM_MODE="merge"
            ;;
        *)
            echo "usage: PLATFORM_ID=<id> $0 [--marker|--no-marker] [--merge-platform]" >&2
            exit 1
            ;;
    esac
    shift
done

if [ ! -x "$BUNDLE_DIR/bin/loong_pangu" ]; then
    echo "missing launcher bundle: $BUNDLE_DIR" >&2
    echo "run: make DEVICE=$PLATFORM_ID assemble-jawaka" >&2
    exit 1
fi

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

echo "Using adb device: $("${ADB[@]}" get-serialno)"

REMOTE_SDCARD_PATH="$(PLATFORM_ID="$PLATFORM_ID" REMOTE_SDCARD_PATH="$REQUESTED_REMOTE_SDCARD_PATH" ADB_SERIAL="$serial" "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh")"
REMOTE_SYSTEM_PATH="${REMOTE_SYSTEM_PATH:-${REMOTE_LEAF_SYSTEM:-$REMOTE_SDCARD_PATH/.system/leaf}}"
REMOTE_PLATFORM_ROOT="${REMOTE_PLATFORM_ROOT:-$REMOTE_SYSTEM_PATH/platforms}"
REMOTE_PLATFORM_PATH="${REMOTE_PLATFORM_PATH:-$REMOTE_PLATFORM_ROOT/$PLATFORM_ID}"
REMOTE_LAUNCHER_PATH="${REMOTE_LAUNCHER_PATH:-${REMOTE_BUNDLE:-$REMOTE_PLATFORM_PATH/launcher}}"
MARKER="${UMRK_MARKER_PATH:-$REMOTE_PLATFORM_PATH/enabled}"
SHADER_PAYLOAD="$PLATFORM_DIR/shaders"

if [ "$PLATFORM_ID" = "mlp1" ] &&
   [ -d "$SHADER_PAYLOAD/leaf-bundled" ] &&
   [ -d "$SHADER_PAYLOAD/leaf-recommended" ]; then
    ADB_SERIAL="$serial" \
    PLATFORM_ID="$PLATFORM_ID" \
    REMOTE_SDCARD_PATH="$REMOTE_SDCARD_PATH" \
    REMOTE_SYSTEM_PATH="$REMOTE_SYSTEM_PATH" \
    REMOTE_PLATFORM_PATH="$REMOTE_PLATFORM_PATH" \
        "$ROOT_DIR/scripts/adb-sync-shader-namespaces.sh" --migrate-only
fi

echo "Deploying bundle to $REMOTE_LAUNCHER_PATH"
"${ADB[@]}" shell "mkdir -p '$REMOTE_PLATFORM_PATH' && rm -rf '$REMOTE_LAUNCHER_PATH' && mkdir -p '$REMOTE_LAUNCHER_PATH'"
"${ADB[@]}" push "$BUNDLE_DIR/." "$REMOTE_LAUNCHER_PATH/" >/dev/null
"${ADB[@]}" shell "chmod 755 '$REMOTE_LAUNCHER_PATH/bin/loong_pangu' 2>/dev/null || true"

if [ -d "$PLATFORM_DIR" ]; then
    echo "Deploying platform payload to $REMOTE_PLATFORM_PATH ($PLATFORM_MODE)"
    "${ADB[@]}" shell "mkdir -p '$REMOTE_PLATFORM_PATH'"
    if [ "$PLATFORM_MODE" = "replace" ]; then
        for name in bin cores info defaults platform.d autoconfig boot-animation shaders manifest.json; do
            "${ADB[@]}" shell "rm -rf '$REMOTE_PLATFORM_PATH/$name'"
        done
    fi
    shopt -s nullglob
    for entry in "$PLATFORM_DIR"/*; do
        name="$(basename "$entry")"
        case "$name" in
            launcher|state|userdata|enabled)
                continue
                ;;
        esac
        remote_entry="$REMOTE_PLATFORM_PATH/$name"
        if [ -d "$entry" ]; then
            "${ADB[@]}" shell "mkdir -p '$remote_entry'"
            "${ADB[@]}" push "$entry/." "$remote_entry/" >/dev/null
        elif [ -f "$entry" ]; then
            "${ADB[@]}" push "$entry" "$remote_entry" >/dev/null
        fi
    done
fi

if [ "$PLATFORM_ID" = "mlp1" ] &&
   [ -d "$SHADER_PAYLOAD/leaf-bundled" ] &&
   [ -d "$SHADER_PAYLOAD/leaf-recommended" ]; then
    ADB_SERIAL="$serial" \
    PLATFORM_ID="$PLATFORM_ID" \
    REMOTE_SDCARD_PATH="$REMOTE_SDCARD_PATH" \
    REMOTE_SYSTEM_PATH="$REMOTE_SYSTEM_PATH" \
    REMOTE_PLATFORM_PATH="$REMOTE_PLATFORM_PATH" \
        "$ROOT_DIR/scripts/adb-sync-shader-namespaces.sh" --sync-only
fi

case "$MARKER_MODE" in
    on)
        "${ADB[@]}" shell "mkdir -p '${MARKER%/*}'"
        "${ADB[@]}" shell "touch '$MARKER'"
        echo "Marker enabled: $MARKER"
        ;;
    off)
        "${ADB[@]}" shell "rm -f '$MARKER'"
        echo "Marker removed: $MARKER"
        ;;
    keep)
        echo "Marker unchanged."
        ;;
esac

"${ADB[@]}" shell sync
echo "SD bundle staged."
