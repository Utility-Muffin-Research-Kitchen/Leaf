#!/usr/bin/env bash
set -euo pipefail

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-yabasanshiro-stage.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

repo="$fixture/Yabasanshiro-standalone"
mkdir -p "$fixture/bin" "$repo"

cat >"$repo/Makefile" <<'EOF'
.PHONY: package-mlp1
package-mlp1:
	@test "$(TOOLCHAIN_IMAGE)" = fixture-toolchain
	@mkdir -p output/mlp1/yabasanshiro/bin
	@printf '#!/bin/sh\nexit 0\n' >output/mlp1/yabasanshiro/launch.sh
	@chmod 755 output/mlp1/yabasanshiro/launch.sh
EOF

cat >"$fixture/bin/adb" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$FAKE_ADB_LOG"
exit 0
EOF
chmod 755 "$fixture/bin/adb"

expected_url="https://github.com/Utility-Muffin-Research-Kitchen/Yabasanshiro-standalone.git"
actual_url="$(bash -c 'script="$1"; set --; source "$script"; url_for Yabasanshiro-standalone' _ "$LEAF_ROOT/scripts/bootstrap.sh")"
[ "$actual_url" = "$expected_url" ]

make -s -C "$LEAF_ROOT" status LEAF_WORKSPACE_DIR="$fixture" |
    grep '^Yabasanshiro-standalone ' >/dev/null

export PATH="$fixture/bin:$PATH"
export ADB_SERIAL="fixture-device"
export FAKE_ADB_LOG="$fixture/adb.log"

make -s -C "$LEAF_ROOT" stage-emulator \
    DEVICE=mlp1 \
    EMULATOR=yabasanshiro \
    LEAF_WORKSPACE_DIR="$fixture" \
    YABASANSHIRO_STANDALONE_DIR="$repo" \
    DEVICE_OVERLAY="$fixture/no-overlay" \
    REMOTE_SDCARD_PATH=/mnt/sdcard \
    TOOLCHAIN_IMAGE=fixture-toolchain >/dev/null

grep -Fq "push $repo/output/mlp1/yabasanshiro/. /mnt/sdcard/.system/leaf/platforms/mlp1/emulators/yabasanshiro/" \
    "$FAKE_ADB_LOG"

echo "PASS yabasanshiro-stage-policy-smoke"
