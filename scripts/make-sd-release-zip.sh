#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-both}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}"

DEVICE="${DEVICE:-mlp1}"
STAGE_APPS="${STAGE_APPS-ssh-server Thing-File retroarch-builds}"
PUBLIC_ROOT_DIRS="${PUBLIC_ROOT_DIRS-Roms Images Apps BIOS Saves States Cheats}"
RELEASE_BUILD="${RELEASE_BUILD:-$LEAF_ROOT/build/release}"
STAGE_BUILD="${STAGE_BUILD:-$LEAF_ROOT/build/stage/mlp1}"
PAYLOAD_ROOT="${PAYLOAD_ROOT:-$STAGE_BUILD/package}"

CATASTROPHE_DIR="${CATASTROPHE_DIR:-$WORKSPACE_DIR/Catastrophe}"
JAWAKA_DIR="${JAWAKA_DIR:-$WORKSPACE_DIR/Jawaka}"
RETROARCH_BUILDS_DIR="${RETROARCH_BUILDS_DIR:-$WORKSPACE_DIR/retroarch-builds}"
CORES_SPRUCE_DIR="${CORES_SPRUCE_DIR:-$WORKSPACE_DIR/Cores-spruce}"
LAUNCHER_SWITCHER_DIR="${LAUNCHER_SWITCHER_DIR:-$WORKSPACE_DIR/miniloong-launcher-switcher}"
MLP1_RETROARCH_BIN="${MLP1_RETROARCH_BIN:-$RETROARCH_BUILDS_DIR/output/mlp1/bin/retroarch}"
MLP1_CORES_DIR="${MLP1_CORES_DIR:-$CORES_SPRUCE_DIR/output/mlp1/cores}"
MLP1_RETROARCH_PATCH_SET="${MLP1_RETROARCH_PATCH_SET:-portrait-rotation,command-menu,jawaka-load-content}"

usage() {
    cat >&2 <<'EOF'
usage: make-sd-release-zip.sh [both|install|recovery]

Environment:
  DEVICE=mlp1
  RELEASE_ID=<filesystem-safe id>
  LEAF_WORKSPACE_DIR=<workspace root>
  STAGE_APPS="ssh-server Thing-File retroarch-builds"
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

case "$MODE" in
    both|install|recovery) ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unsupported mode: $MODE" ;;
esac

[ "$DEVICE" = "mlp1" ] || die "release ZIP generation currently supports DEVICE=mlp1 only"
command -v zip >/dev/null 2>&1 || die "zip command not found"

derive_release_id() {
    local date_part sha_part
    date_part="$(date +%Y-%m-%d)"
    sha_part="$(git -C "$LEAF_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
    if [ -z "$sha_part" ]; then
        sha_part="nogit"
    fi
    printf '%s-g%s\n' "$date_part" "$sha_part"
}

validate_release_id() {
    local value="$1"
    [ -n "$value" ] || die "RELEASE_ID must not be empty"
    case "$value" in
        .|..|*/*|*\\*|*' '*|*$'\t'*|*:*|*'?'*|*'"'*|*'<'*|*'>'*|*'|'*)
            die "RELEASE_ID is not filesystem-safe: $value"
            ;;
    esac
}

RELEASE_ID="${RELEASE_ID:-$(derive_release_id)}"
validate_release_id "$RELEASE_ID"

INSTALL_STAGE="$RELEASE_BUILD/sd-$RELEASE_ID"
RECOVERY_STAGE="$RELEASE_BUILD/recovery-$RELEASE_ID"
INSTALL_ZIP="$RELEASE_BUILD/leaf-mlp1-sd-$RELEASE_ID.zip"
RECOVERY_ZIP="$RELEASE_BUILD/leaf-mlp1-recovery-$RELEASE_ID.zip"

build_missing_platform_bits() {
    if [ ! -f "$MLP1_RETROARCH_BIN" ]; then
        echo "MLP1 RetroArch missing; building in $RETROARCH_BUILDS_DIR"
        (cd "$RETROARCH_BUILDS_DIR" && MLP1_PATCH_SET="$MLP1_RETROARCH_PATCH_SET" ./build-mlp1.sh)
    fi

    if ! ( [ -d "$MLP1_CORES_DIR" ] && find "$MLP1_CORES_DIR" -maxdepth 1 -type f -name '*_libretro.so' | grep -q . ); then
        echo "MLP1 cores missing; building in $CORES_SPRUCE_DIR"
        (cd "$CORES_SPRUCE_DIR" && ./build-mlp1.sh)
    fi
}

package_app() {
    local app="$1"
    local package_target package_platform package_dir package_name destination_platform supported_devices

    # shellcheck source=scripts/app-package-policy.sh
    . "$LEAF_ROOT/scripts/app-package-policy.sh"
    leaf_app_policy "$app" "$WORKSPACE_DIR" "$DEVICE" || die "unsupported release app policy: $app for DEVICE=$DEVICE"

    [ -d "$WORKSPACE_DIR/$app" ] || die "missing app repo: $WORKSPACE_DIR/$app"
    local make_args=("$package_target")
    if [ -n "${package_platform:-}" ]; then
        make_args+=("PLATFORM=$package_platform")
    fi
    make -C "$WORKSPACE_DIR/$app" "${make_args[@]}"
    [ -d "$package_dir" ] || die "missing package dir: $package_dir"

    mkdir -p "$RELEASE_APPS_DIR/$destination_platform"
    rm -rf "$RELEASE_APPS_DIR/$destination_platform/$package_name"
    cp -R "$package_dir" "$RELEASE_APPS_DIR/$destination_platform/$package_name"
    printf '%s/%s\n' "$destination_platform" "$package_name" >>"$MANAGED_APPS_FILE"
}

write_install_readme() {
    cat > "$INSTALL_STAGE/LEAF-INSTALL.txt" <<EOF
Leaf MLP1 SD installer
======================

This ZIP is for Miniloong Pocket 1.

1. Extract the contents of this ZIP to the root of a FAT32 or ext4 SD card.
2. Do not use exFAT. The stock loong_daemon update path ignores exFAT media.
3. Insert the SD card and boot the MLP1.
4. The stock update screen appears while the Leaf installer runs.
5. The progress indicator may sit at 50 percent while files are copying.
6. Wait for the device to reboot by itself.
7. Boot normally with the SD card inserted. Leaf should start automatically.

The installer renames loong_upgrade to loong_upgrade.used when it runs.
ADB is not enabled automatically. You can enable ADB later from Leaf/Jawaka
settings if needed.

Logs are written under:

  .system/leaf/userdata/mlp1/logs/

To return to stock boot, extract the matching Leaf recovery ZIP to the SD-card
root and boot the device once with that card inserted.
EOF
}

write_recovery_readme() {
    cat > "$RECOVERY_STAGE/LEAF-RECOVERY.txt" <<'EOF'
Leaf MLP1 recovery
==================

This ZIP is for Miniloong Pocket 1 systems with the Leaf init hook installed.

1. Extract the contents of this ZIP to the root of the SD card.
2. Insert the SD card and boot the MLP1.
3. The stock update screen appears while recovery runs.
4. The progress indicator may sit at 50 percent while recovery runs.
5. Wait for the device to reboot by itself.
6. Boot normally to return to stock.

Recovery disables Leaf and removes the installed hook/session. It preserves SD
card content such as ROMs, BIOS files, saves, states, logs, settings, and apps.
EOF
}

zip_stage() {
    local stage_dir="$1"
    local zip_path="$2"

    rm -f "$zip_path"
    (
        cd "$stage_dir"
        zip -qr "$zip_path" .
    )
    echo "Wrote $zip_path"
}

build_install_zip() {
    echo "Building Leaf MLP1 install ZIP release=$RELEASE_ID"
    build_missing_platform_bits

    make -C "$LEAF_ROOT" DEVICE=mlp1 assemble-jawaka
    [ -d "$PAYLOAD_ROOT/.system/leaf/launcher" ] || die "missing assembled launcher payload"
    [ -d "$PAYLOAD_ROOT/.system/leaf/platforms/mlp1" ] || die "missing assembled MLP1 platform payload"

    rm -rf "$INSTALL_STAGE"
    mkdir -p "$INSTALL_STAGE/.system/leaf/releases/$RELEASE_ID/platforms" "$INSTALL_STAGE/Apps"
    for dir in $PUBLIC_ROOT_DIRS; do
        mkdir -p "$INSTALL_STAGE/$dir"
    done

    RELEASE_ROOT="$INSTALL_STAGE/.system/leaf/releases/$RELEASE_ID"
    RELEASE_APPS_DIR="$RELEASE_ROOT/Apps"
    MANAGED_APPS_FILE="$RELEASE_ROOT/managed-apps.txt"
    : >"$MANAGED_APPS_FILE"

    cp -R "$PAYLOAD_ROOT/.system/leaf/launcher" "$RELEASE_ROOT/launcher"
    cp -R "$PAYLOAD_ROOT/.system/leaf/platforms/mlp1" "$RELEASE_ROOT/platforms/mlp1"

    for app in $STAGE_APPS; do
        package_app "$app"
    done

    python3 "$LAUNCHER_SWITCHER_DIR/make_launcher_switcher_sd.py" \
        --force \
        --mode managed-install \
        --release-id "$RELEASE_ID" \
        --no-require-adb-pinned \
        --completion-action reboot \
        "$INSTALL_STAGE"

    write_install_readme
    zip_stage "$INSTALL_STAGE" "$INSTALL_ZIP"
}

build_recovery_zip() {
    echo "Building Leaf MLP1 recovery ZIP release=$RELEASE_ID"
    rm -rf "$RECOVERY_STAGE"
    mkdir -p "$RECOVERY_STAGE"

    python3 "$LAUNCHER_SWITCHER_DIR/make_launcher_switcher_sd.py" \
        --force \
        --mode recovery \
        --completion-action reboot \
        "$RECOVERY_STAGE"

    write_recovery_readme
    zip_stage "$RECOVERY_STAGE" "$RECOVERY_ZIP"
}

mkdir -p "$RELEASE_BUILD"

case "$MODE" in
    both)
        build_install_zip
        build_recovery_zip
        ;;
    install)
        build_install_zip
        ;;
    recovery)
        build_recovery_zip
        ;;
esac
