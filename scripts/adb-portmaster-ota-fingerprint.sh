#!/bin/bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: adb-portmaster-ota-fingerprint.sh capture OUTPUT
       adb-portmaster-ota-fingerprint.sh verify BASELINE

Captures stable PortMaster pak/manager fingerprints and the installed-port file
inventory from the active MLP1 Leaf SD. Logs and other expected volatile files
are intentionally excluded.
EOF
}

MODE="${1:-}"
BASELINE="${2:-}"
case "$MODE" in
    capture|verify) ;;
    *) usage; exit 2 ;;
esac
test -n "$BASELINE" || { usage; exit 2; }

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LEAF_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

if [ -n "${ADB_SERIAL:-}" ]; then
    SERIAL="$ADB_SERIAL"
else
    SERIAL="$(adb devices | awk 'NR > 1 && $2 == "device" { print $1; exit }')"
fi
test -n "$SERIAL" || { echo "No online adb device found." >&2; exit 1; }

SDCARD_PATH="$(PLATFORM_ID=mlp1 REMOTE_SDCARD_PATH=auto ADB_SERIAL="$SERIAL" \
    "$LEAF_DIR/scripts/adb-resolve-umrk-sd.sh")"

capture_to() {
    local output="$1"
    mkdir -p "$(dirname -- "$output")"
    adb -s "$SERIAL" shell "
set -eu
SD='$SDCARD_PATH'
for rel in \
  Apps/mlp1/PortMaster.pak/pak.json \
  Apps/mlp1/PortMaster.pak/launch.sh \
  Apps/mlp1/PortMaster.pak/bin/portmaster-mlp1 \
  Apps/mlp1/PortMaster.pak/res/icon.png \
  Apps/mlp1/PortMaster.pak/leaf-platforms/mlp1/emulators/ports/launch.sh \
  .userdata/mlp1/portmaster/.leaf/manifest.json \
  .userdata/mlp1/portmaster/PortMaster/PortMaster.sh \
  .userdata/mlp1/portmaster/PortMaster/pugwash \
  .userdata/mlp1/portmaster/PortMaster/control.txt \
  .userdata/mlp1/portmaster/runtime/bin/python3; do
    path=\"\$SD/\$rel\"
    if [ -f \"\$path\" ]; then
      size=\$(stat -c %s \"\$path\")
      hash=\$(sha256sum \"\$path\" | awk '{print \$1}')
      printf 'critical|%s|%s|%s\\n' \"\$rel\" \"\$size\" \"\$hash\"
    else
      printf 'critical|%s|MISSING|-\\n' \"\$rel\"
    fi
  done

ports=\"\$SD/Roms/PORTS\"
if [ -d \"\$ports\" ]; then
  find \"\$ports\" -type f | sort | while IFS= read -r path; do
    rel=\${path#\"\$SD/\"}
    size=\$(stat -c %s \"\$path\")
    printf 'port-file|%s|%s\\n' \"\$rel\" \"\$size\"
  done
else
  printf 'port-tree|Roms/PORTS|MISSING\\n'
fi
" | tr -d '\r' >"$output"
}

if [ "$MODE" = "capture" ]; then
    capture_to "$BASELINE"
    echo "Captured PortMaster OTA fingerprint: $BASELINE"
    exit 0
fi

test -f "$BASELINE" || { echo "Baseline not found: $BASELINE" >&2; exit 1; }
CURRENT="$(mktemp "${TMPDIR:-/tmp}/portmaster-ota-current.XXXXXX")"
trap 'rm -f "$CURRENT"' EXIT
capture_to "$CURRENT"
if ! cmp -s "$BASELINE" "$CURRENT"; then
    echo "PortMaster OTA preservation check failed:" >&2
    diff -u "$BASELINE" "$CURRENT" >&2 || true
    exit 1
fi

echo "PortMaster OTA preservation fingerprint matches"
