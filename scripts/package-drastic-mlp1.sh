#!/usr/bin/env bash
set -euo pipefail

# Package DraStic for MLP1 using the steward-fu/nds custom-menu port.
#
# This builds the steward NDS SDL2 backend (the readable custom menu + the MLP1
# Wayland/xdg-shell video path) and bundles those libs with the prebuilt aarch64
# drastic64 binary from the local steward checkout.
#
# The custom-menu libs MUST be used (SDL_VIDEODRIVER=NDS + bundled lib/), not the
# device's system SDL2 — that is what makes the steward menu appear at all.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

STEWARD_NDS_DIR="${STEWARD_NDS_DIR:-$LEAF_ROOT/../steward-fu-nds}"
TOOLCHAIN_IMAGE="${TOOLCHAIN_IMAGE:-ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:local}"
OUTPUT_DIR="${OUTPUT_DIR:-$LEAF_ROOT/build/drastic/mlp1/drastic}"
# Set DRASTIC_BUILD=0 to package an already-built steward tree (skip docker).
DRASTIC_BUILD="${DRASTIC_BUILD:-1}"

# Steward libs that must come from the MLP1 build (not the device system libs).
STEWARD_LIBS=(libSDL2-2.0.so.0 libcommon.so libdtr.so libasound.so.2)

die() {
    echo "error: $*" >&2
    exit 1
}

build_steward() {
    if [ "$DRASTIC_BUILD" != "1" ]; then
        echo "DRASTIC_BUILD=0: skipping cross-build, using existing $STEWARD_NDS_DIR/drastic/lib" >&2
        return 0
    fi

    command -v docker >/dev/null 2>&1 ||
        die "docker not found (needed to cross-build the DraStic custom-menu libs)"

    echo "Building steward-fu-nds MLP1 libs via $TOOLCHAIN_IMAGE" >&2
    # configure.ac bakes in the /src path, so mount the repo there.
    docker run --rm \
        -v "$STEWARD_NDS_DIR":/src -w /src \
        "$TOOLCHAIN_IMAGE" \
        bash -lc 'export CROSS="$CROSS_COMPILE"; make -f Makefile.mlp1'
}

write_launch_script() {
    local path="$OUTPUT_DIR/launch.sh"
    cat >"$path" <<'EOF'
#!/bin/sh
set -eu

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ -f "$SELF_DIR/../../launcher/env.sh" ]; then
    . "$SELF_DIR/../../launcher/env.sh"
elif [ -n "${UMRK_ENV_FILE:-}" ] && [ -f "$UMRK_ENV_FILE" ]; then
    . "$UMRK_ENV_FILE"
fi

if [ "$#" -lt 1 ]; then
    echo "usage: launch.sh <rom-path>" >&2
    exit 64
fi

ROM_PATH="$1"
PLATFORM_ROOT="${UMRK_PLATFORM_PATH:-${SYSTEM_PATH:-$SELF_DIR/../..}}"
STATE_ROOT="${DRASTIC_STATE_ROOT:-$PLATFORM_ROOT/state/drastic}"
LOG_ROOT="${LOGS_PATH:-$PLATFORM_ROOT/userdata/logs}"

mkdir -p \
    "$STATE_ROOT" \
    "$STATE_ROOT/backup" \
    "$STATE_ROOT/savestates" \
    "$STATE_ROOT/profiles" \
    "$STATE_ROOT/unzip_cache" \
    "$STATE_ROOT/input_record" \
    "$STATE_ROOT/cheats" \
    "$STATE_ROOT/slot2" \
    "$STATE_ROOT/microphone" \
    "$STATE_ROOT/scripts" \
    "$LOG_ROOT"

copy_if_missing() {
    src="$1"
    dst="$2"
    if [ -e "$src" ] && [ ! -e "$dst" ]; then
        cp -R "$src" "$dst"
    fi
}

# Seed the per-game/runtime state tree from the packaged defaults on first run.
# res/ holds the steward menu assets (backgrounds, font) the custom SDL2 reads
# relative to the working directory.
copy_if_missing "$SELF_DIR/share/config" "$STATE_ROOT/config"
copy_if_missing "$SELF_DIR/share/system" "$STATE_ROOT/system"
copy_if_missing "$SELF_DIR/share/res" "$STATE_ROOT/res"
copy_if_missing "$SELF_DIR/share/game_database.xml" "$STATE_ROOT/game_database.xml"
copy_if_missing "$SELF_DIR/share/usrcheat.dat" "$STATE_ROOT/usrcheat.dat"
copy_if_missing "$SELF_DIR/share/drastic_logo_0.raw" "$STATE_ROOT/drastic_logo_0.raw"
copy_if_missing "$SELF_DIR/share/drastic_logo_1.raw" "$STATE_ROOT/drastic_logo_1.raw"
copy_if_missing "$SELF_DIR/share/icon.png" "$STATE_ROOT/icon.png"
copy_if_missing "$SELF_DIR/share/readme.txt" "$STATE_ROOT/readme.txt"

export HOME="$STATE_ROOT"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
# The steward custom menu lives in the bundled SDL2's "NDS" video driver — it must
# load the packaged libs, not the device's system SDL2.
export SDL_VIDEODRIVER="${DRASTIC_SDL_VIDEODRIVER:-NDS}"
export LD_LIBRARY_PATH="$SELF_DIR/lib"
DRASTIC_BIN="$SELF_DIR/bin/drastic64"

cd "$STATE_ROOT"
exec "$DRASTIC_BIN" "$ROM_PATH" >>"$LOG_ROOT/drastic.log" 2>&1
EOF
    chmod 755 "$path"
}

write_manifest() {
    local rel_ver
    rel_ver="$(git -C "$STEWARD_NDS_DIR" rev-parse --short=8 HEAD 2>/dev/null || echo unknown)"
    cat >"$OUTPUT_DIR/manifest.json" <<EOF
{
  "id": "drastic",
  "name": "DraStic",
  "platform": "mlp1",
  "kind": "standalone-emulator",
  "source_repo": "steward-fu/nds",
  "source_ref": "$rel_ver",
  "binary": "bin/drastic64",
  "entrypoint": "launch.sh",
  "menu": "steward-custom",
  "sdl_video_driver": "NDS",
  "bundled_libs": "libSDL2-2.0.so.0 libcommon.so libdtr.so libasound.so.2",
  "package_note": "Steward-fu/nds custom-menu port cross-built for MLP1 (Wayland/xdg-shell, queue_copy gameplay-throttle fix). Menu is opened by the hardware Menu key, passed through by jawakad."
}
EOF
}

main() {
    [ -d "$STEWARD_NDS_DIR" ] || die "missing steward-fu-nds repo at $STEWARD_NDS_DIR"

    build_steward

    local src="$STEWARD_NDS_DIR/drastic"
    [ -x "$src/drastic64" ] || die "missing drastic64 in $src"
    [ -f "$src/game_database.xml" ] || die "missing game_database.xml in $src"
    for lib in "${STEWARD_LIBS[@]}"; do
        [ -e "$src/lib/$lib" ] ||
            die "steward lib not built: $src/lib/$lib (build failed or DRASTIC_BUILD=0 with no prior build?)"
    done

    rm -rf "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR/bin" "$OUTPUT_DIR/lib" "$OUTPUT_DIR/share"

    cp -f "$src/drastic64" "$OUTPUT_DIR/bin/drastic64"
    chmod 755 "$OUTPUT_DIR/bin/drastic64"

    for lib in "${STEWARD_LIBS[@]}"; do
        cp -f "$src/lib/$lib" "$OUTPUT_DIR/lib/$lib"
        chmod 755 "$OUTPUT_DIR/lib/$lib"
    done

    for item in \
        config \
        system \
        res \
        game_database.xml \
        usrcheat.dat \
        drastic_logo_0.raw \
        drastic_logo_1.raw \
        icon.png \
        readme.txt; do
        if [ -e "$src/$item" ]; then
            cp -R "$src/$item" "$OUTPUT_DIR/share/$item"
        fi
    done

    write_launch_script
    write_manifest

    cat >"$OUTPUT_DIR/README.txt" <<EOF
DraStic standalone payload for UMRK MLP1 (steward-fu/nds custom menu).

Built from the local steward-fu-nds checkout:

  $STEWARD_NDS_DIR

The package bundles the MLP1-cross-built steward SDL2 backend (custom readable
menu + Wayland/xdg-shell video path) in lib/, and runs the prebuilt aarch64
drastic64 against it via SDL_VIDEODRIVER=NDS. Saves, states, config, cache, and
logs live under the Leaf platform runtime tree.

The in-emulator menu is opened with the hardware Menu key; jawakad passes that
key through to DraStic for a "drastic" standalone session instead of raising the
launcher overlay.
EOF

    find "$OUTPUT_DIR" -maxdepth 3 -type f | sort
}

main "$@"
