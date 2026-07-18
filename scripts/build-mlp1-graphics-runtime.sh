#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK="${MLP1_MALI_LOCK:-$LEAF_ROOT/stage/mlp1-graphics/aarch64-mali.lock.json}"
WORK_DIR="${MLP1_GRAPHICS_WORK_DIR:-$LEAF_ROOT/workdir/mlp1/graphics}"
GRAPHICS_ROOT="${MLP1_GRAPHICS_RUNTIME_DIR:-$LEAF_ROOT/build/mlp1/runtime/graphics}"
RUNTIME_ID="rk3566-g52-g29p1"
RUNTIME_DIR="$GRAPHICS_ROOT/vulkan/$RUNTIME_ID"

read_lock() {
    python3 - "$LOCK" "$1" <<'PY'
import json
import sys

path, key = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as handle:
    value = json.load(handle)
for part in key.split("."):
    value = value[part]
print(value)
PY
}

download_checked() {
    local url="$1"
    local path="$2"
    local expected_size="$3"
    local expected_sha256="$4"

    mkdir -p "$(dirname "$path")"
    if [ ! -f "$path" ] ||
       [ "$(wc -c <"$path" | tr -d ' ')" != "$expected_size" ]; then
        local temporary="$path.tmp.$$"
        curl -fL --retry 3 --connect-timeout 20 -o "$temporary" "$url"
        mv "$temporary" "$path"
    fi

    local actual_sha256
    actual_sha256="$(shasum -a 256 "$path" | awk '{print $1}')"
    if [ "$actual_sha256" != "$expected_sha256" ]; then
        echo "sha256 mismatch for $(basename "$path")" >&2
        echo "expected: $expected_sha256" >&2
        echo "actual:   $actual_sha256" >&2
        exit 1
    fi
}

repo="$(read_lock release.repo)"
branch="$(read_lock release.branch)"
commit="$(read_lock release.commit)"
variant="$(read_lock name)"
architecture="$(read_lock architecture)"
asset_filename="$(read_lock asset.filename)"
asset_path="$(read_lock asset.path)"
asset_url="$(read_lock asset.url)"
asset_size="$(read_lock asset.size)"
asset_sha256="$(read_lock asset.sha256)"
icd_filename="$(read_lock icd.filename)"
icd_library_path="$(read_lock icd.library_path)"
icd_api_version="$(read_lock icd.api_version)"
license_filename="$(read_lock license.filename)"
license_url="$(read_lock license.url)"
license_size="$(read_lock license.size)"
license_sha256="$(read_lock license.sha256)"
packaging_reference="$(read_lock packaging_reference)"

asset="$WORK_DIR/$asset_filename"
license_source="$WORK_DIR/$license_filename"
download_checked "$asset_url" "$asset" "$asset_size" "$asset_sha256"
download_checked "$license_url" "$license_source" "$license_size" "$license_sha256"

rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR/lib" "$RUNTIME_DIR/share/vulkan/icd.d"
cp -f "$asset" "$RUNTIME_DIR/lib/libmali.so.1"
cp -f "$license_source" "$RUNTIME_DIR/LICENSE.txt"
chmod 755 "$RUNTIME_DIR/lib/libmali.so.1"
chmod 644 "$RUNTIME_DIR/LICENSE.txt"

cat >"$RUNTIME_DIR/share/vulkan/icd.d/$icd_filename" <<EOF
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "$icd_library_path",
    "api_version": "$icd_api_version"
  }
}
EOF
chmod 644 "$RUNTIME_DIR/share/vulkan/icd.d/$icd_filename"

installed_lib_sha256="$(shasum -a 256 "$RUNTIME_DIR/lib/libmali.so.1" | awk '{print $1}')"
installed_icd_sha256="$(shasum -a 256 "$RUNTIME_DIR/share/vulkan/icd.d/$icd_filename" | awk '{print $1}')"
installed_license_sha256="$(shasum -a 256 "$RUNTIME_DIR/LICENSE.txt" | awk '{print $1}')"

cat >"$RUNTIME_DIR/manifest.json" <<EOF
{
  "schema": 1,
  "id": "$RUNTIME_ID",
  "kind": "platform-vulkan-runtime",
  "platform": "mlp1",
  "producer": "Leaf",
  "packaging_reference": "$packaging_reference",
  "source": "https://github.com/$repo",
  "branch": "$branch",
  "commit": "$commit",
  "variant": "$variant",
  "architecture": "$architecture",
  "api_version": "$icd_api_version",
  "asset": {
    "filename": "$asset_filename",
    "path": "$asset_path",
    "url": "$asset_url",
    "size": $asset_size,
    "sha256": "$asset_sha256"
  },
  "files": [
    {
      "path": "lib/libmali.so.1",
      "sha256": "$installed_lib_sha256"
    },
    {
      "path": "share/vulkan/icd.d/$icd_filename",
      "sha256": "$installed_icd_sha256"
    },
    {
      "path": "LICENSE.txt",
      "sha256": "$installed_license_sha256"
    }
  ]
}
EOF
chmod 644 "$RUNTIME_DIR/manifest.json"

echo "MLP1 Vulkan runtime ready: $RUNTIME_DIR"
