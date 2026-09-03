#!/usr/bin/env bash
set -euo pipefail

# Leaf dispatches Fun DraStic to the product repo and never reimplements the
# archive extraction. This proves the dispatch, the archive passthrough, and
# the deployment directory without touching a device or a real archive.

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-fun-drastic-stage.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

repo="$fixture/Fun-Drastic-standalone"
mkdir -p "$fixture/bin" "$repo"

# The reviewed archive is supplied explicitly and must reach the product repo
# unchanged; a dispatcher that dropped it would fail the build there, not here.
cat >"$repo/Makefile" <<'MAKEFILE'
.PHONY: package-mlp1
package-mlp1:
	@test "$(FUN_DRASTIC_ARCHIVE)" = /fixture/drastic.zip
	@mkdir -p output/mlp1/fun-drastic/bin
	@printf '#!/bin/sh\nexit 0\n' >output/mlp1/fun-drastic/launch.sh
	@chmod 755 output/mlp1/fun-drastic/launch.sh
MAKEFILE

cat >"$fixture/bin/adb" <<'ADB'
#!/bin/sh
printf '%s\n' "$*" >>"$FAKE_ADB_LOG"
exit 0
ADB
chmod 755 "$fixture/bin/adb"

expected_url="https://github.com/Utility-Muffin-Research-Kitchen/Fun-Drastic-standalone.git"
actual_url="$(bash -c 'script="$1"; set --; source "$script"; url_for Fun-Drastic-standalone' _ "$LEAF_ROOT/scripts/bootstrap.sh")"
[ "$actual_url" = "$expected_url" ]

export PATH="$fixture/bin:$PATH"
export ADB_SERIAL="fixture-device"
export FAKE_ADB_LOG="$fixture/adb.log"

make -s -C "$LEAF_ROOT" stage-emulator \
    DEVICE=mlp1 \
    EMULATOR=fun-drastic \
    LEAF_WORKSPACE_DIR="$fixture" \
    FUN_DRASTIC_STANDALONE_DIR="$repo" \
    FUN_DRASTIC_ARCHIVE=/fixture/drastic.zip \
    DEVICE_OVERLAY="$fixture/no-overlay" \
    REMOTE_SDCARD_PATH=/mnt/sdcard >/dev/null

grep -Fq "push $repo/output/mlp1/fun-drastic/. /mnt/sdcard/.system/leaf/platforms/mlp1/emulators/fun-drastic/" \
    "$FAKE_ADB_LOG"

# The default emulator must not be disturbed by staging the alternate.
if grep -Fq "emulators/drastic/" "$FAKE_ADB_LOG"; then
    echo "staging Fun DraStic touched the primary DraStic directory" >&2
    exit 1
fi

echo "PASS fun-drastic-stage-policy-smoke"
