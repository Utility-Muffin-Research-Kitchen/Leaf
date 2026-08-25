#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-both}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}"

DEVICE="${DEVICE:-mlp1}"
STAGE_APPS="${STAGE_APPS-ssh-server Thing-File CentralScrutinizer Fugazi joes-calibrage retroarch-builds}"
STAGE_EMULATORS="${STAGE_EMULATORS-ppsspp drastic mupen64plus flycast}"
PUBLIC_ROOT_DIRS="${PUBLIC_ROOT_DIRS-Roms Images Videos Apps BIOS Saves States Cheats}"
RELEASE_BUILD="${RELEASE_BUILD:-$LEAF_ROOT/build/release}"
STAGE_BUILD="${STAGE_BUILD:-$LEAF_ROOT/build/stage/mlp1}"
PAYLOAD_ROOT="${PAYLOAD_ROOT:-$STAGE_BUILD/package}"

CATASTROPHE_DIR="${CATASTROPHE_DIR:-$WORKSPACE_DIR/Catastrophe}"
JAWAKA_DIR="${JAWAKA_DIR:-$WORKSPACE_DIR/Jawaka}"
PPSSPP_SPRUCE_DIR="${PPSSPP_SPRUCE_DIR:-$WORKSPACE_DIR/PPSSPP-spruce}"
STEWARD_NDS_DIR="${STEWARD_NDS_DIR:-$WORKSPACE_DIR/steward-fu-nds}"
N64_STANDALONE_DIR="${N64_STANDALONE_DIR:-$WORKSPACE_DIR/N64-standalone}"
FLYCAST_STANDALONE_DIR="${FLYCAST_STANDALONE_DIR:-$WORKSPACE_DIR/Flycast-standalone}"
RETROARCH_BUILDS_DIR="${RETROARCH_BUILDS_DIR:-$WORKSPACE_DIR/retroarch-builds}"
CORES_SPRUCE_DIR="${CORES_SPRUCE_DIR:-$WORKSPACE_DIR/Cores-spruce}"
LAUNCHER_SWITCHER_DIR="${LAUNCHER_SWITCHER_DIR:-$WORKSPACE_DIR/miniloong-launcher-switcher}"
UMRK_WORKSPACE_DIR="${UMRK_WORKSPACE_DIR:-$WORKSPACE_DIR/umrk-workspace}"
MLP1_CORE_REPORT_TOOL="${MLP1_CORE_REPORT_TOOL:-$CORES_SPRUCE_DIR/scripts/mlp1-core-report.py}"
MLP1_CORE_PROBE_RUNNER="${MLP1_CORE_PROBE_RUNNER:-$CORES_SPRUCE_DIR/probe-mlp1-cores-adb.sh}"
TOOLCHAIN_IMAGE="${TOOLCHAIN_IMAGE:-ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:local}"
MLP1_RETROARCH_BIN="${MLP1_RETROARCH_BIN:-$RETROARCH_BUILDS_DIR/output/mlp1/bin/retroarch}"
MLP1_RETROARCH_MANIFEST="${MLP1_RETROARCH_MANIFEST:-$RETROARCH_BUILDS_DIR/output/mlp1/build-manifest.json}"
MLP1_SHADERS_DIR="${MLP1_SHADERS_DIR:-$RETROARCH_BUILDS_DIR/output/mlp1/shaders}"
MLP1_SHADER_TOOL="${MLP1_SHADER_TOOL:-$RETROARCH_BUILDS_DIR/scripts/mlp1_shader_bundle.py}"
MLP1_ASSETS_DIR="${MLP1_ASSETS_DIR:-$RETROARCH_BUILDS_DIR/output/mlp1/assets}"
MLP1_ASSET_TOOL="${MLP1_ASSET_TOOL:-$RETROARCH_BUILDS_DIR/scripts/mlp1_asset_bundle.py}"
MLP1_CORES_DIR="${MLP1_CORES_DIR:-$CORES_SPRUCE_DIR/output/mlp1/cores}"
MLP1_CORES_REPORT="${MLP1_CORES_REPORT:-$CORES_SPRUCE_DIR/output/mlp1/build-report.json}"
MLP1_PPSSPP_PACKAGE="${MLP1_PPSSPP_PACKAGE:-$PPSSPP_SPRUCE_DIR/output/mlp1/ppsspp}"
MLP1_GRAPHICS_RUNTIME="${MLP1_GRAPHICS_RUNTIME:-$LEAF_ROOT/build/mlp1/runtime/graphics}"
MLP1_VULKAN_RUNTIME="${MLP1_VULKAN_RUNTIME:-$MLP1_GRAPHICS_RUNTIME/vulkan/rk3566-g52-g29p1}"
MLP1_DRASTIC_PACKAGE="${MLP1_DRASTIC_PACKAGE:-$LEAF_ROOT/build/drastic/mlp1/drastic}"
MLP1_MUPEN64PLUS_PACKAGE="${MLP1_MUPEN64PLUS_PACKAGE:-$N64_STANDALONE_DIR/output/mlp1/mupen64plus}"
MLP1_FLYCAST_PACKAGE="${MLP1_FLYCAST_PACKAGE:-$FLYCAST_STANDALONE_DIR/output/mlp1/flycast}"
# Read the canonical patch set rather than carrying a second copy of it. Two
# hand-maintained defaults drifted apart twice; the file is the single source.
MLP1_RETROARCH_PATCH_SET_FILE="${MLP1_RETROARCH_PATCH_SET_FILE:-$LEAF_ROOT/config/mlp1-retroarch-patch-set.txt}"
if [ -z "${MLP1_RETROARCH_PATCH_SET:-}" ]; then
    MLP1_RETROARCH_PATCH_SET="$(grep -v '^#' "$MLP1_RETROARCH_PATCH_SET_FILE" | grep -v '^$' | head -1)"
fi
MLP1_RETROARCH_VALIDATOR="${MLP1_RETROARCH_VALIDATOR:-$LEAF_ROOT/scripts/validate-mlp1-retroarch-build.py}"

usage() {
    cat >&2 <<'EOF'
usage: make-sd-release-zip.sh [both|install|recovery]

Environment:
  DEVICE=mlp1
  RELEASE_ID=<filesystem-safe id>
  LEAF_WORKSPACE_DIR=<workspace root>
  TOOLCHAIN_IMAGE=<MLP1 cross-compile Docker image>
  REBUILD_CORES=1  explicitly allow missing/stale stock-parity cores to compile
  FORCE_REBUILD_CORES=1  with REBUILD_CORES=1, bypass every valid core cache hit
  STAGE_APPS="ssh-server Thing-File CentralScrutinizer Fugazi joes-calibrage retroarch-builds"
  STAGE_EMULATORS="ppsspp drastic mupen64plus flycast"
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
UPDATE_MANIFEST="$RELEASE_BUILD/leaf-update.json"
SHA256SUMS_FILE="$RELEASE_BUILD/SHA256SUMS"
LEAF_RELEASE_CHANNEL="${LEAF_RELEASE_CHANNEL:-dev}"
LEAF_RELEASE_VERSION="${LEAF_RELEASE_VERSION:-${VERSION:-}}"
if [ -z "$LEAF_RELEASE_VERSION" ] && [ "$LEAF_RELEASE_CHANNEL" != "stable" ]; then
    LEAF_RELEASE_VERSION="$RELEASE_ID"
fi
LEAF_RELEASE_TAG="${LEAF_RELEASE_TAG:-}"
if [ -z "$LEAF_RELEASE_TAG" ] && [ "${GITHUB_REF_TYPE:-}" = "tag" ]; then
    LEAF_RELEASE_TAG="${GITHUB_REF_NAME:-}"
fi
if [ "$LEAF_RELEASE_CHANNEL" = "beta" ]; then
    DEFAULT_RELEASE_REPOSITORY="Utility-Muffin-Research-Kitchen/Leaf-beta"
else
    DEFAULT_RELEASE_REPOSITORY="Utility-Muffin-Research-Kitchen/Leaf"
fi
LEAF_RELEASE_REPOSITORY="${LEAF_RELEASE_REPOSITORY:-$DEFAULT_RELEASE_REPOSITORY}"
RELEASE_POLICY_TOOL="$LEAF_ROOT/scripts/validate-leaf-release.py"
PROVENANCE_PREFLIGHT="$RELEASE_BUILD/.components-$RELEASE_ID.preflight.json"
RELEASE_COMPONENT_ARGS=()
REQUIRED_COMPONENT_ARGS=()
BUILT_INSTALL=0
BUILT_RECOVERY=0

validate_json_scalar() {
    local name="$1"
    local value="$2"
    case "$value" in
        *'"'*|*\\*|*$'\n'*|*$'\r'*)
            die "$name contains characters unsupported by release metadata: $value"
            ;;
    esac
}

configure_release_components() {
    local app
    RELEASE_COMPONENT_ARGS=(
        --component "leaf=$LEAF_ROOT"
        --component "catastrophe=$CATASTROPHE_DIR"
        --component "launcher=$JAWAKA_DIR"
        --component "launcher-switcher=$LAUNCHER_SWITCHER_DIR"
    )
    REQUIRED_COMPONENT_ARGS=(
        --required-component "leaf"
        --required-component "catastrophe"
        --required-component "launcher"
        --required-component "launcher-switcher"
    )
    for app in $STAGE_APPS; do
        RELEASE_COMPONENT_ARGS+=(--component "app:$app=$WORKSPACE_DIR/$app")
        REQUIRED_COMPONENT_ARGS+=(--required-component "app:$app")
    done
}

write_component_provenance() {
    local output="$1"
    local clean_args=()
    if [ -n "$LEAF_RELEASE_TAG" ]; then
        clean_args+=(--require-clean)
    fi
    python3 "$RELEASE_POLICY_TOOL" provenance \
        --channel "$LEAF_RELEASE_CHANNEL" \
        --version "$LEAF_RELEASE_VERSION" \
        --tag "$LEAF_RELEASE_TAG" \
        --release-id "$RELEASE_ID" \
        "${clean_args[@]}" \
        "${RELEASE_COMPONENT_ARGS[@]}" \
        --output "$output"
}

prepare_release_policy() {
    [ "$MODE" = "recovery" ] && return 0
    [ -f "$RELEASE_POLICY_TOOL" ] || die "missing Leaf release policy tool: $RELEASE_POLICY_TOOL"
    python3 "$RELEASE_POLICY_TOOL" identity \
        --channel "$LEAF_RELEASE_CHANNEL" \
        --version "$LEAF_RELEASE_VERSION" \
        --tag "$LEAF_RELEASE_TAG" \
        --release-id "$RELEASE_ID"
    configure_release_components
    write_component_provenance "$PROVENANCE_PREFLIGHT"
}

finalize_component_provenance() {
    local provenance_dir="$RELEASE_ROOT/provenance"
    local final="$provenance_dir/components.json"
    local candidate="$provenance_dir/components.json.candidate"
    mkdir -p "$provenance_dir"
    write_component_provenance "$candidate"
    cmp -s "$PROVENANCE_PREFLIGHT" "$candidate" || \
        die "release component revisions or worktree state changed during assembly"
    mv "$candidate" "$final"
    echo "Wrote $final"
}

validate_configured_source_consumers() {
    case " $STAGE_APPS " in
        *" CentralScrutinizer "*)
            echo "Validating bundled configured-source consumer"
            make -C "$WORKSPACE_DIR/CentralScrutinizer" \
                test-native TEST=tests/native/test_paths.c
            ;;
    esac
}

file_size() {
    wc -c <"$1" | tr -d '[:space:]'
}

file_sha256() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        die "shasum or sha256sum command not found"
    fi
}

tree_size() {
    find "$1" -type f -exec sh -c '
        for f do
            wc -c <"$f"
        done
    ' sh {} + | awk '{ total += $1 } END { print total + 0 }'
}

validate_managed_app_path() {
    local app="$1"
    local platform_dir app_name

    case "$app" in
        ''|'#'*|*\\*|/*|*//*|.|..|*'"'*)
            die "unsafe managed app path: $app"
            ;;
    esac
    platform_dir="${app%%/*}"
    app_name="${app#*/}"
    if [ "$platform_dir" = "$app" ] || [ -z "$platform_dir" ] || [ -z "$app_name" ]; then
        die "managed app path must be <platform>/<pak>: $app"
    fi
    case "$platform_dir" in
        .|..|.*|*/*) die "unsafe managed app platform: $app" ;;
    esac
    case "$app_name" in
        .|..|.*|*/*) die "unsafe managed app name: $app" ;;
    esac
}

write_managed_apps_json_items() {
    local file="$1"
    local first=1
    local app

    if [ ! -f "$file" ]; then
        return 0
    fi

    while IFS= read -r app || [ -n "$app" ]; do
        case "$app" in
            ''|'#'*) continue ;;
        esac
        validate_managed_app_path "$app"
        if [ "$first" -eq 0 ]; then
            printf ',\n'
        fi
        printf '        "%s"' "$app"
        first=0
    done <"$file"
}

sync_platform_managed_apps_manifest() {
    local manifest="$1"
    local managed_file="$2"

    [ -f "$manifest" ] || die "missing platform manifest: $manifest"
    [ -f "$managed_file" ] || die "missing managed apps file: $managed_file"

    python3 - "$manifest" "$managed_file" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
managed_path = Path(sys.argv[2])

with manifest_path.open("r", encoding="utf-8") as fp:
    manifest = json.load(fp)

managed = []
for raw in managed_path.read_text(encoding="utf-8").splitlines():
    app = raw.strip()
    if app and not app.startswith("#"):
        managed.append(app)

manifest["managed_apps"] = managed
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
}

write_checksum_line() {
    local path="$1"
    printf '%s  %s\n' "$(file_sha256 "$path")" "$(basename "$path")" >>"$SHA256SUMS_FILE"
}

write_release_manifest() {
    [ "$BUILT_INSTALL" -eq 1 ] || return 0

    validate_json_scalar "LEAF_RELEASE_VERSION" "$LEAF_RELEASE_VERSION"
    validate_json_scalar "LEAF_RELEASE_CHANNEL" "$LEAF_RELEASE_CHANNEL"
    validate_json_scalar "LEAF_RELEASE_REPOSITORY" "$LEAF_RELEASE_REPOSITORY"
    validate_json_scalar "RELEASE_ID" "$RELEASE_ID"

    local install_name recovery_name published_at install_size install_installed_size install_sha release_url_ref
    install_name="$(basename "$INSTALL_ZIP")"
    install_size="$(file_size "$INSTALL_ZIP")"
    install_installed_size="$(tree_size "$INSTALL_STAGE")"
    install_sha="$(file_sha256 "$INSTALL_ZIP")"
    published_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    release_url_ref="${LEAF_RELEASE_TAG:-$RELEASE_ID}"

    {
        cat <<EOF
{
  "schema": 1,
  "product": "leaf",
  "channel": "$LEAF_RELEASE_CHANNEL",
  "version": "$LEAF_RELEASE_VERSION",
  "release_id": "$RELEASE_ID",
  "published_at": "$published_at",
  "platforms": {
    "mlp1": {
      "min_installed_schema": 1,
      "managed_apps": [
EOF
        write_managed_apps_json_items "$MANAGED_APPS_FILE"
        cat <<EOF

      ],
      "migrations": [],
      "handoff": {
        "type": "stock_loong_upgrade",
        "completion": "reboot",
        "trigger_file": "loong_upgrade"
      },
      "artifact": {
        "kind": "sd_root_zip",
        "name": "$install_name",
        "size": $install_size,
        "installed_size": $install_installed_size,
        "sha256": "$install_sha"
EOF
        if [ "$BUILT_RECOVERY" -eq 1 ]; then
            recovery_name="$(basename "$RECOVERY_ZIP")"
            cat <<EOF
      },
      "recovery_zip": {
        "name": "$recovery_name",
        "size": $(file_size "$RECOVERY_ZIP"),
        "sha256": "$(file_sha256 "$RECOVERY_ZIP")"
      }
EOF
        else
            cat <<EOF
      }
EOF
        fi
        cat <<EOF
    }
  },
  "notes": {
    "summary": "Leaf $RELEASE_ID",
    "url": "https://github.com/$LEAF_RELEASE_REPOSITORY/releases/tag/$release_url_ref"
  }
}
EOF
    } >"$UPDATE_MANIFEST"

    echo "Wrote $UPDATE_MANIFEST"
}

write_release_checksums() {
    rm -f "$SHA256SUMS_FILE"

    if [ "$BUILT_INSTALL" -eq 1 ]; then
        write_checksum_line "$INSTALL_ZIP"
        [ -f "$UPDATE_MANIFEST" ] && write_checksum_line "$UPDATE_MANIFEST"
    fi
    if [ "$BUILT_RECOVERY" -eq 1 ]; then
        write_checksum_line "$RECOVERY_ZIP"
    fi

    [ -f "$SHA256SUMS_FILE" ] && echo "Wrote $SHA256SUMS_FILE"
}

write_release_metadata() {
    write_release_manifest
    write_release_checksums
}

# Release gate: every core marked "packaged" in cores.json must have its .so
# staged AND its verbatim license file present, or the release build fails.
# (v0.0.7 shipped 1 of 26 packaged cores because nothing checked this.)
validate_packaged_cores() {
    local release_root="$1"
    python3 - "$release_root" <<'EOF' || die "packaged-core validation failed"
import json, os, sys
root = sys.argv[1]
platform_dir = os.path.join(root, "platforms/mlp1")
cores_json = os.path.join(platform_dir, "defaults/cores.json")
cores_dir = os.path.join(platform_dir, "cores")
lic_dir = os.path.join(root, "licenses/cores")
data = json.load(open(cores_json))
entries = data if isinstance(data, list) else data.get("cores", [])
packaged = [e for e in entries if e.get("status") == "packaged"]
missing_bin, missing_lic, expected_sos = [], [], set()
for e in packaged:
    cid = e.get("id") or e.get("name")
    if e.get("type") == "path":
        target = os.path.join(platform_dir, e.get("path") or "")
        if not (e.get("path") and os.path.isfile(target)):
            missing_bin.append("%s (path: %s)" % (cid, e.get("path")))
    else:
        so = e.get("file_name") or (cid + "_libretro.so")
        expected_sos.add(so)
        if not os.path.isfile(os.path.join(cores_dir, so)):
            missing_bin.append("%s (%s)" % (cid, so))
    license_id = {
        "ppsspp_gles": "ppsspp",
        "flycast_standalone": "flycast",
    }.get(cid, cid)
    if not os.path.isfile(os.path.join(lic_dir, license_id + ".txt")):
        missing_lic.append(cid)
staged = sorted(f for f in os.listdir(cores_dir)
                if f.endswith("_libretro.so")) if os.path.isdir(cores_dir) else []
extra = [f for f in staged if f not in expected_sos]
if extra:
    print("warning: cores staged but not marked packaged in cores.json: "
          + " ".join(extra))
ok = True
if missing_bin:
    print("error: cores.json marks these packaged but the binary/launcher is "
          "not staged: " + " ".join(missing_bin))
    ok = False
if missing_lic:
    print("error: packaged cores missing a license file "
          "(stage/licenses/cores/<core>.txt): " + " ".join(missing_lic))
    ok = False
if not ok:
    sys.exit(1)
print("core gate: %d packaged entries verified (binary + license present)"
      % len(packaged))
EOF
}

validate_retroarch_contract() {
    local platform_dir="$1"
    local report="$platform_dir/cores/build-report.json"
    [ -f "$report" ] || die "missing MLP1 core build report: $report"
    python3 "$UMRK_WORKSPACE_DIR/scripts/retroarch_validate_package.py" \
        --metadata-dir "$UMRK_WORKSPACE_DIR/plans/retroarch/generated/mlp1" \
        --build-report "$report" \
        --package-root "$platform_dir" \
        || die "RetroArch runtime metadata contract validation failed"

    python3 - "$platform_dir" <<'EOF' || die "Amiga PUAE release validation failed"
import json
import pathlib
import sys

platform = pathlib.Path(sys.argv[1])
defaults = platform / "defaults"
cores = json.loads((defaults / "cores.json").read_text(encoding="utf-8"))["cores"]
systems = json.loads((defaults / "systems.json").read_text(encoding="utf-8"))["systems"]

amiga = [row for row in systems if row.get("id") == "AMIGA"]
if len(amiga) != 1:
    raise SystemExit(f"error: expected exactly one AMIGA system, found {len(amiga)}")
if amiga[0].get("default_core") != "puae" or amiga[0].get("alternate_cores") != []:
    raise SystemExit("error: AMIGA must use packaged puae with no alternate core")

puae = [row for row in cores if row.get("id") == "puae"]
if len(puae) != 1 or puae[0].get("status") != "packaged":
    raise SystemExit("error: puae must be present and packaged")
binary = puae[0].get("file_name", "puae_libretro.so")
if not (platform / "cores" / binary).is_file():
    raise SystemExit(f"error: missing packaged puae core: {binary}")
print("Amiga PUAE gate: catalog policy and packaged core verified")
EOF
}

validate_asset_bundle() {
    local platform_dir="$1"
    local license_root="$2"
    python3 "$MLP1_ASSET_TOOL" validate --output "$platform_dir/assets" ||
        die "MLP1 menu asset bundle release validation failed"
    [ -f "$license_root/ASSETS.md" ] ||
        die "missing asset license notice: $license_root/ASSETS.md"
}

validate_shader_bundle() {
    local platform_dir="$1"
    local license_root="$2"
    python3 "$MLP1_SHADER_TOOL" validate --output "$platform_dir/shaders" ||
        die "MLP1 shader bundle release validation failed"
    [ -f "$license_root/SHADERS.md" ] ||
        die "missing shader license notice: $license_root/SHADERS.md"
}

validate_portmaster_integration() {
    local release_root="$1"
    python3 - "$release_root" <<'EOF' || die "PortMaster integration validation failed"
import json
import os
import pathlib
import sys

release_root = pathlib.Path(sys.argv[1])
platform = release_root / "platforms" / "mlp1"

cores = json.load(open(platform / "defaults" / "cores.json", encoding="utf-8"))["cores"]
systems = json.load(open(platform / "defaults" / "systems.json", encoding="utf-8"))["systems"]

ports_rows = [row for row in cores if row.get("id") == "ports"]
if len(ports_rows) != 1:
    raise SystemExit(f"error: expected exactly one ports core, found {len(ports_rows)}")
expected_core = {
    "id": "ports",
    "display_name": "Ports",
    "type": "path",
    "libretro_name": None,
    "file_name": None,
    "config_folder": None,
    "info_name": None,
    "path": "emulators/ports/launch.sh",
    "supports_menu": False,
    "supports_savestate": False,
    "supports_disk_control": False,
    "needs_swap": False,
    "requires_direct_drm": False,
    "platforms": ["mlp1"],
    "status": "packaged",
}
if ports_rows[0] != expected_core:
    raise SystemExit(f"error: ports core does not match the OTA contract: {ports_rows[0]!r}")

system_rows = [row for row in systems if row.get("id") == "PORTS"]
if len(system_rows) != 1:
    raise SystemExit(f"error: expected exactly one PORTS system, found {len(system_rows)}")
expected_system = {
    "id": "PORTS",
    "name": "Ports",
    "patterns": ["PORTS", "ports"],
    "extensions": ["sh"],
    "archive_extensions": [],
    "archive_inner_extensions": [],
    "archive_mode": "pass_through",
    "file_names": [],
    "ignore_file_names": [],
    "playlist_extensions": [],
    "m3u_generation": "none",
    "default_core": "ports",
    "alternate_cores": [],
    "rom_root": "Roms/PORTS",
    "image_root": "Images/PORTS",
    "bios_notes": [],
}
if system_rows[0] != expected_system:
    raise SystemExit(f"error: PORTS system does not match the OTA contract: {system_rows[0]!r}")

launcher = platform / "emulators" / "ports" / "launch.sh"
icon = platform / "launcher" / "res" / "system_icons" / "PORTS.png"
license_path = release_root / "licenses" / "cores" / "ports.txt"
if not launcher.is_file() or not os.access(launcher, os.X_OK):
    raise SystemExit(f"error: packaged Ports launcher is missing or not executable: {launcher}")
if not icon.is_file() or icon.stat().st_size == 0:
    raise SystemExit(f"error: packaged Ports icon is missing or empty: {icon}")
if not license_path.is_file() or license_path.stat().st_size == 0:
    raise SystemExit(f"error: packaged Ports licence is missing or empty: {license_path}")

print("PortMaster OTA gate: packaged Ports integration verified")
EOF
}

validate_pakrat_owned_apps() {
    local release_root="$1"
    local package
    local pakrat_packages=()

    # shellcheck source=scripts/app-package-policy.sh
    . "$LEAF_ROOT/scripts/app-package-policy.sh"
    while IFS= read -r package; do
        [ -n "$package" ] && pakrat_packages+=("$package")
    done < <(leaf_pakrat_owned_package_names)
    python3 "$LEAF_ROOT/scripts/audit-pakrat-owned-apps.py" \
        "$release_root" "${pakrat_packages[@]}" || \
        die "Pak Rat ownership validation failed"
}

audit_mlp1_build_tuning() {
    local release_root="$1"
    local audit_script="$WORKSPACE_DIR/umrk-workspace/scripts/audit-mlp1-build-flags.py"

    if [ ! -f "$audit_script" ]; then
        echo "warning: MLP1 build tuning audit script not found: $audit_script"
        return 0
    fi

    python3 "$audit_script" "$release_root" || die "MLP1 build tuning audit failed"
}

# Shared with stage/mlp1.mk so staging and release make the same reuse decision.
mlp1_retroarch_reusable() {
    python3 "$MLP1_RETROARCH_VALIDATOR" \
        --binary "$MLP1_RETROARCH_BIN" \
        --manifest "$MLP1_RETROARCH_MANIFEST" \
        --expected-patch-set "$MLP1_RETROARCH_PATCH_SET"
}

build_missing_platform_bits() {
    if ! mlp1_retroarch_reusable; then
        echo "building MLP1 RetroArch in $RETROARCH_BUILDS_DIR"
        (cd "$RETROARCH_BUILDS_DIR" && MLP1_PATCH_SET="$MLP1_RETROARCH_PATCH_SET" ./build-mlp1.sh)
        mlp1_retroarch_reusable || die "MLP1 RetroArch still does not match $MLP1_RETROARCH_PATCH_SET after rebuild"
    fi

    make -C "$RETROARCH_BUILDS_DIR" shaders-mlp1 \
        MLP1_SHADER_OUTPUT="$MLP1_SHADERS_DIR"
    python3 "$MLP1_SHADER_TOOL" validate --output "$MLP1_SHADERS_DIR" ||
        die "MLP1 shader bundle validation failed"

    make -C "$RETROARCH_BUILDS_DIR" assets-mlp1 \
        MLP1_ASSET_OUTPUT="$MLP1_ASSETS_DIR"
    python3 "$MLP1_ASSET_TOOL" validate --output "$MLP1_ASSETS_DIR" ||
        die "MLP1 menu asset bundle validation failed"

    REBUILD_CORES="${REBUILD_CORES:-0}" \
    FORCE_REBUILD_CORES="${FORCE_REBUILD_CORES:-0}" \
    CORES_SPRUCE_DIR="$CORES_SPRUCE_DIR" \
    MLP1_CORES_DIR="$MLP1_CORES_DIR" \
    MLP1_CORES_REPORT="$MLP1_CORES_REPORT" \
    MLP1_CORE_REPORT_TOOL="$MLP1_CORE_REPORT_TOOL" \
        "$LEAF_ROOT/scripts/ensure-mlp1-cores.sh"

    if ! python3 "$MLP1_CORE_REPORT_TOOL" verify \
            --report "$MLP1_CORES_REPORT" \
            --cores-dir "$MLP1_CORES_DIR"; then
        echo "Probing exact MLP1 libretro library names on the selected device"
        "$MLP1_CORE_PROBE_RUNNER" \
            --report "$MLP1_CORES_REPORT" \
            --cores-dir "$MLP1_CORES_DIR" || \
            die "MLP1 core identity probe failed"
    fi

    python3 "$MLP1_CORE_REPORT_TOOL" verify \
        --report "$MLP1_CORES_REPORT" \
        --cores-dir "$MLP1_CORES_DIR" || \
        die "MLP1 core identity report is incomplete"
}

package_app() {
    local app="$1"
    local package_target package_platform package_dir package_name destination_platform supported_devices distribution

    # shellcheck source=scripts/app-package-policy.sh
    . "$LEAF_ROOT/scripts/app-package-policy.sh"
    leaf_app_policy "$app" "$WORKSPACE_DIR" "$DEVICE" || die "unsupported release app policy: $app for DEVICE=$DEVICE"
    [ "$distribution" = "release" ] || \
        die "Pak Rat-owned optional app cannot be packaged in a Leaf release: $app ($package_name)"

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

package_emulator() {
    local emulator="$1"
    local package_dir remote_name

    case "$emulator" in
        ppsspp)
            [ -d "$PPSSPP_SPRUCE_DIR" ] || die "missing PPSSPP repo: $PPSSPP_SPRUCE_DIR"
            make -C "$PPSSPP_SPRUCE_DIR" package-mlp1
            package_dir="$MLP1_PPSSPP_PACKAGE"
            remote_name="ppsspp"
            ;;
        drastic)
            [ -d "$STEWARD_NDS_DIR" ] || die "missing steward-fu-nds repo: $STEWARD_NDS_DIR (run: make bootstrap)"
            OUTPUT_DIR="$MLP1_DRASTIC_PACKAGE" \
            STEWARD_NDS_DIR="$STEWARD_NDS_DIR" \
            TOOLCHAIN_IMAGE="$TOOLCHAIN_IMAGE" \
                "$LEAF_ROOT/scripts/package-drastic-mlp1.sh"
            package_dir="$MLP1_DRASTIC_PACKAGE"
            remote_name="drastic"
            ;;
        mupen64plus)
            [ -d "$N64_STANDALONE_DIR" ] || die "missing N64 standalone repo: $N64_STANDALONE_DIR"
            make -C "$N64_STANDALONE_DIR" package-mlp1 TOOLCHAIN_IMAGE="$TOOLCHAIN_IMAGE"
            package_dir="$MLP1_MUPEN64PLUS_PACKAGE"
            remote_name="mupen64plus"
            ;;
        flycast)
            [ -d "$FLYCAST_STANDALONE_DIR" ] || die "missing Flycast standalone repo: $FLYCAST_STANDALONE_DIR"
            make -C "$FLYCAST_STANDALONE_DIR" package-mlp1 TOOLCHAIN_IMAGE="$TOOLCHAIN_IMAGE"
            package_dir="$MLP1_FLYCAST_PACKAGE"
            remote_name="flycast"
            ;;
        *)
            die "unsupported release emulator policy: $emulator for DEVICE=$DEVICE"
            ;;
    esac

    [ -d "$package_dir" ] || die "missing emulator package dir: $package_dir"
    mkdir -p "$RELEASE_ROOT/platforms/mlp1/emulators"
    rm -rf "$RELEASE_ROOT/platforms/mlp1/emulators/$remote_name"
    cp -R "$package_dir" "$RELEASE_ROOT/platforms/mlp1/emulators/$remote_name"
}

package_graphics_runtime() {
    MLP1_GRAPHICS_RUNTIME_DIR="$MLP1_GRAPHICS_RUNTIME" \
        "$LEAF_ROOT/scripts/build-mlp1-graphics-runtime.sh"

    [ -d "$MLP1_VULKAN_RUNTIME" ] || \
        die "missing shared Vulkan runtime: $MLP1_VULKAN_RUNTIME"

    local graphics_root="$RELEASE_ROOT/platforms/mlp1/runtime/graphics"
    rm -rf "$graphics_root/vulkan/rk3566-g52-g29p1"
    mkdir -p "$graphics_root/vulkan"
    cp -R "$MLP1_VULKAN_RUNTIME" \
        "$graphics_root/vulkan/rk3566-g52-g29p1"
    chmod 755 "$graphics_root/vulkan/rk3566-g52-g29p1/lib/libmali.so.1"
}

validate_ppsspp_vulkan_release() {
    local platform_dir="$RELEASE_ROOT/platforms/mlp1"
    python3 "$LEAF_ROOT/scripts/validate-ppsspp-vulkan-release.py" "$platform_dir" ||
        die "PPSSPP Vulkan release validation failed"
}

validate_standalone_n64_release() {
    local platform_dir="$RELEASE_ROOT/platforms/mlp1"

    python3 - "$platform_dir" <<'PY'
import json
import sys
from pathlib import Path

platform_dir = Path(sys.argv[1])
systems_path = platform_dir / "defaults" / "systems.json"
cores_path = platform_dir / "defaults" / "cores.json"

systems_data = json.loads(systems_path.read_text(encoding="utf-8"))
cores_data = json.loads(cores_path.read_text(encoding="utf-8"))
systems = systems_data.get("systems", []) if isinstance(systems_data, dict) else systems_data
cores = cores_data.get("cores", []) if isinstance(cores_data, dict) else cores_data

n64 = next((s for s in systems if s.get("id") == "N64"), None)
if not n64 or n64.get("default_core") != "mupen64plus_standalone":
    sys.exit(0)

core = next((c for c in cores if c.get("id") == "mupen64plus_standalone"), None)
if not core:
    raise SystemExit("error: N64 defaults to mupen64plus_standalone but cores.json has no matching core")
if core.get("type") != "path":
    raise SystemExit("error: mupen64plus_standalone must be a path core")

rel = core.get("path") or ""
target = platform_dir / rel
if not rel or not target.is_file():
    raise SystemExit(f"error: N64 standalone default points at missing release payload: {rel}")

print(f"N64 standalone release gate: {rel}")
PY
}

validate_standalone_flycast_release() {
    local platform_dir="$RELEASE_ROOT/platforms/mlp1"
    python3 "$LEAF_ROOT/scripts/validate-flycast-standalone-release.py" \
        "$platform_dir" ||
        die "Flycast standalone release validation failed"
}

write_install_readme() {
    cat > "$INSTALL_STAGE/LEAF-INSTALL.txt" <<EOF
Leaf MLP1 SD installer / updater
================================

This ZIP installs Leaf on a Miniloong Pocket 1, and is also how you update an
existing Leaf install. The same steps apply either way.

1. Extract the contents of this ZIP to the root of a FAT32 or ext4 SD card.
2. Do not use exFAT. The stock loong_daemon update path ignores exFAT media.
3. Insert the SD card and boot the MLP1.
4. The stock update screen appears while the Leaf installer runs.
5. The progress indicator may sit at 50 percent while files are copying.
6. Wait for the device to reboot by itself.
7. Boot normally with the SD card inserted. Leaf should start automatically.

Safe to run over an existing install. The installer only refreshes the
release-managed firmware under .system/leaf and never touches your data: games,
saves, states, and app/control data live at the card root (Roms/, Saves/,
States/, and the .userdata/ and .umrk/ folders) and are left as they are. On the
first compatible-core launch, Jawaka may non-destructively copy recognized
legacy flat save/state files into that core's folder when the historical owner
is unambiguous; the original files remain in place. Ambiguous files are left
flat and produce a warning. Re-extracting this ZIP onto an existing Leaf card
is an in-place upgrade.

The installer renames loong_upgrade to loong_upgrade.used when it runs.
ADB is not enabled automatically. You can enable ADB later from Leaf/Jawaka
settings if needed.

Logs are written under:

  .userdata/mlp1/logs/

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

# A manual-install ZIP must never carry mutable user/state roots: a desktop
# drag-extract would merge them over the user's own data. Only the versioned
# release payload + root helper files belong in the install ZIP. Fail loudly if
# any active/durable root slipped into the stage.
validate_install_stage_clean() {
    local stage="$1"
    local bad=""
    [ -d "$stage/.system/leaf/platforms" ] && bad="$bad .system/leaf/platforms (active payload; only releases/ ships)"
    [ -d "$stage/.system/leaf/shared/userdata" ] && bad="$bad .system/leaf/shared/userdata"
    [ -e "$stage/.userdata" ] && bad="$bad .userdata"
    [ -e "$stage/.umrk" ] && bad="$bad .umrk"
    local hit
    hit="$(find "$stage" -type d \( -path '*/platforms/*/state' -o -path '*/platforms/*/userdata' \) 2>/dev/null)"
    [ -n "$hit" ] && bad="$bad $(echo $hit)"
    if [ -n "$bad" ]; then
        die "install ZIP would ship forbidden mutable roots:$bad"
    fi
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
    validate_configured_source_consumers
    build_missing_platform_bits

    make -C "$LEAF_ROOT" \
        DEVICE=mlp1 \
        MLP1_RETROARCH_BIN="$MLP1_RETROARCH_BIN" \
        MLP1_RETROARCH_MANIFEST="$MLP1_RETROARCH_MANIFEST" \
        MLP1_SHADERS_DIR="$MLP1_SHADERS_DIR" \
        MLP1_ASSETS_DIR="$MLP1_ASSETS_DIR" \
        MLP1_CORES_DIR="$MLP1_CORES_DIR" \
        MLP1_CORES_REPORT="$MLP1_CORES_REPORT" \
        assemble-jawaka
    [ -d "$PAYLOAD_ROOT/.system/leaf/platforms/mlp1/launcher" ] || die "missing assembled launcher payload"
    [ -d "$PAYLOAD_ROOT/.system/leaf/platforms/mlp1" ] || die "missing assembled MLP1 platform payload"

    rm -rf "$INSTALL_STAGE"
    mkdir -p "$INSTALL_STAGE/.system/leaf/releases/$RELEASE_ID/platforms"
    # Public root dirs (Roms/Images/Apps/...) are NOT shipped as empty folders:
    # the installer creates any that are missing from public-dirs.txt, so a
    # desktop drag-extract can never merge over existing user content.

    RELEASE_ROOT="$INSTALL_STAGE/.system/leaf/releases/$RELEASE_ID"
    RELEASE_APPS_DIR="$RELEASE_ROOT/Apps"
    MANAGED_APPS_FILE="$RELEASE_ROOT/managed-apps.txt"
    : >"$MANAGED_APPS_FILE"
    # Public content roots the installer creates if missing (one per line).
    printf '%s\n' $PUBLIC_ROOT_DIRS > "$RELEASE_ROOT/public-dirs.txt"

    cp -R "$PAYLOAD_ROOT/.system/leaf/platforms/mlp1" "$RELEASE_ROOT/platforms/mlp1"

    package_graphics_runtime
    for emulator in $STAGE_EMULATORS; do
        package_emulator "$emulator"
    done
    validate_standalone_n64_release
    validate_standalone_flycast_release
    validate_ppsspp_vulkan_release

    cp -R "$LEAF_ROOT/stage/licenses" "$RELEASE_ROOT/licenses"
    validate_packaged_cores "$RELEASE_ROOT"
    validate_retroarch_contract "$RELEASE_ROOT/platforms/mlp1"
    validate_shader_bundle "$RELEASE_ROOT/platforms/mlp1" "$RELEASE_ROOT/licenses"
    validate_asset_bundle "$RELEASE_ROOT/platforms/mlp1" "$RELEASE_ROOT/licenses"

    for app in $STAGE_APPS; do
        package_app "$app"
    done
    sync_platform_managed_apps_manifest "$RELEASE_ROOT/platforms/mlp1/manifest.json" "$MANAGED_APPS_FILE"
    validate_pakrat_owned_apps "$RELEASE_ROOT"
    validate_portmaster_integration "$RELEASE_ROOT"
    audit_mlp1_build_tuning "$RELEASE_ROOT"
    finalize_component_provenance

    local release_version_args=()
    if [ "$LEAF_RELEASE_CHANNEL" = "stable" ] || \
            [ "$LEAF_RELEASE_VERSION" != "$RELEASE_ID" ]; then
        release_version_args+=(--release-version "$LEAF_RELEASE_VERSION")
    fi
    python3 "$LAUNCHER_SWITCHER_DIR/make_launcher_switcher_sd.py" \
        --force \
        --mode managed-install \
        --release-id "$RELEASE_ID" \
        "${release_version_args[@]}" \
        --no-require-adb-pinned \
        --completion-action reboot \
        "$INSTALL_STAGE"

    python3 "$RELEASE_POLICY_TOOL" candidate \
        --release-root "$RELEASE_ROOT" \
        --install-stage "$INSTALL_STAGE" \
        --version "$LEAF_RELEASE_VERSION" \
        --release-id "$RELEASE_ID" \
        "${REQUIRED_COMPONENT_ARGS[@]}"
    validate_install_stage_clean "$INSTALL_STAGE"
    write_install_readme
    zip_stage "$INSTALL_STAGE" "$INSTALL_ZIP"
    BUILT_INSTALL=1
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
    BUILT_RECOVERY=1
}

mkdir -p "$RELEASE_BUILD"
prepare_release_policy

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

write_release_metadata
