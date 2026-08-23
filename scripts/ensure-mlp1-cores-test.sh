#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

CORES_REPO="$TEST_ROOT/Cores-spruce"
CORES_DIR="$CORES_REPO/output/mlp1/cores"
REPORT="$CORES_REPO/output/mlp1/build-report.json"
REPORT_TOOL="$CORES_REPO/scripts/mlp1-core-report.py"
BUILD_LOG="$TEST_ROOT/build.log"
BUILD_MARKER="$TEST_ROOT/build.done"

mkdir -p "$CORES_DIR" "$CORES_REPO/scripts"
touch "$CORES_DIR/alpha_libretro.so" "$CORES_DIR/beta_libretro.so" "$REPORT"

cat >"$REPORT_TOOL" <<'PY'
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

valid = os.environ.get("FAKE_REPORT_VALID") == "1"
build_marker = os.environ.get("BUILD_MARKER")
if valid or (build_marker and Path(build_marker).is_file()):
    print("alpha\talpha_libretro.so\t" + "a" * 64)
    print("beta\tbeta_libretro.so\t" + "b" * 64)
    sys.exit(0)
sys.exit(1)
PY
chmod +x "$REPORT_TOOL"

cat >"$CORES_REPO/build-mlp1.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    --list-stock-parity)
        printf 'alpha\nbeta\n'
        ;;
    --check-stock-parity-cache)
        printf 'check\n' >>"$BUILD_LOG"
        if [ "${FAKE_CACHE_OK:-0}" = "1" ] || [ -f "$BUILD_MARKER" ]; then
            echo 'cache: 2 reused / 0 misses'
        else
            echo 'miss beta input fingerprint changed'
            echo 'cache: 1 reused / 1 misses'
            exit 1
        fi
        ;;
    --stock-parity)
        printf 'stock force=%s\n' "${FORCE_REBUILD_CORES:-0}" >>"$BUILD_LOG"
        touch "$BUILD_MARKER"
        ;;
    *)
        echo "unexpected fake builder arguments: $*" >&2
        exit 2
        ;;
esac
SH
chmod +x "$CORES_REPO/build-mlp1.sh"

run_gate() {
    CORES_SPRUCE_DIR="$CORES_REPO" \
    MLP1_CORES_DIR="$CORES_DIR" \
    MLP1_CORES_REPORT="$REPORT" \
    MLP1_CORE_REPORT_TOOL="$REPORT_TOOL" \
    MLP1_CORE_BUILDER="$CORES_REPO/build-mlp1.sh" \
    BUILD_LOG="$BUILD_LOG" \
    BUILD_MARKER="$BUILD_MARKER" \
    "$SCRIPT_DIR/ensure-mlp1-cores.sh"
}

FAKE_CACHE_OK=1 FAKE_REPORT_VALID=1 run_gate >/dev/null
grep -qx check "$BUILD_LOG"

: >"$BUILD_LOG"

set +e
FAKE_CACHE_OK=0 FAKE_REPORT_VALID=1 run_gate >"$TEST_ROOT/refusal.out" 2>&1
status=$?
set -e
[ "$status" -eq 2 ] || {
    echo "cache miss returned $status instead of 2" >&2
    exit 1
}
grep -q 'REBUILD_CORES=1' "$TEST_ROOT/refusal.out"
grep -qx check "$BUILD_LOG"

: >"$BUILD_LOG"
FAKE_CACHE_OK=1 FAKE_REPORT_VALID=0 run_gate >/dev/null
[ "$(grep -c '^stock ' "$BUILD_LOG")" = "1" ]
[ "$(grep -c '^check$' "$BUILD_LOG")" = "2" ]

rm -f "$BUILD_MARKER"
: >"$BUILD_LOG"
FAKE_CACHE_OK=0 FAKE_REPORT_VALID=1 REBUILD_CORES=1 run_gate >/dev/null
[ "$(grep -c '^stock ' "$BUILD_LOG")" = "1" ]
[ "$(grep -c '^check$' "$BUILD_LOG")" = "2" ]

rm -f "$BUILD_MARKER"
: >"$BUILD_LOG"
FAKE_CACHE_OK=1 FAKE_REPORT_VALID=1 REBUILD_CORES=1 FORCE_REBUILD_CORES=1 \
    run_gate >/dev/null
grep -qx 'stock force=1' "$BUILD_LOG"

set +e
FAKE_CACHE_OK=1 FAKE_REPORT_VALID=1 FORCE_REBUILD_CORES=1 run_gate \
    >"$TEST_ROOT/force-without-auth.out" 2>&1
status=$?
set -e
[ "$status" -eq 2 ]
grep -q 'also requires REBUILD_CORES=1' "$TEST_ROOT/force-without-auth.out"

set +e
FAKE_CACHE_OK=1 FAKE_REPORT_VALID=1 REBUILD_CORES=maybe run_gate \
    >"$TEST_ROOT/bad-setting.out" 2>&1
status=$?
set -e
[ "$status" -eq 2 ]
grep -q 'REBUILD_CORES must be 0 or 1' "$TEST_ROOT/bad-setting.out"

echo "ensure-mlp1-cores-test: PASS"
