#!/usr/bin/env bash
set -euo pipefail

# Leaf dispatches Fun DraStic to the product repo and never reimplements the
# build. This proves the dispatch, that the source checkout reaches the product
# repo, and the deployment directory, without touching a device or compiling
# anything.

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-fun-drastic-stage.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

repo="$fixture/Fun-Drastic-standalone"
src="$fixture/Fun-Drastic-src"
mkdir -p "$fixture/bin" "$repo" "$src/src"

# The hook is cross-built from tenlevels' source, so the source checkout is what
# has to reach the product repo; a dispatcher that dropped it would build from
# whatever happened to sit beside the product repo instead.
cat >"$repo/Makefile" <<MAKEFILE
.PHONY: package-mlp1
package-mlp1:
	@test "\$(FUN_DRASTIC_SRC_DIR)" = "$src"
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

for repo_name in Fun-Drastic-standalone Fun-Drastic-src; do
    expected_url="https://github.com/Utility-Muffin-Research-Kitchen/$repo_name.git"
    actual_url="$(bash -c 'script="$1"; name="$2"; set --; source "$script"; url_for "$name"' _ "$LEAF_ROOT/scripts/bootstrap.sh" "$repo_name")"
    [ "$actual_url" = "$expected_url" ] || {
        echo "bootstrap URL for $repo_name is $actual_url, expected $expected_url" >&2
        exit 1
    }
done

export PATH="$fixture/bin:$PATH"
export ADB_SERIAL="fixture-device"
export FAKE_ADB_LOG="$fixture/adb.log"

make -s -C "$LEAF_ROOT" stage-emulator \
    DEVICE=mlp1 \
    EMULATOR=fun-drastic \
    LEAF_WORKSPACE_DIR="$fixture" \
    FUN_DRASTIC_STANDALONE_DIR="$repo" \
    FUN_DRASTIC_SRC_DIR="$src" \
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
