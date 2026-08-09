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

mkdir -p "$CORES_DIR" "$CORES_REPO/scripts"
touch "$CORES_DIR/test_libretro.so" "$REPORT"

cat >"$REPORT_TOOL" <<'PY'
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

valid = os.environ.get("FAKE_REPORT_VALID") == "1"
build_log = os.environ.get("BUILD_LOG")
sys.exit(0 if valid or (build_log and Path(build_log).is_file()) else 1)
PY
chmod +x "$REPORT_TOOL"

cat >"$CORES_REPO/build-mlp1.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$BUILD_LOG"
touch output/mlp1/cores/test_libretro.so output/mlp1/build-report.json
SH
chmod +x "$CORES_REPO/build-mlp1.sh"

run_gate() {
    CORES_SPRUCE_DIR="$CORES_REPO" \
    MLP1_CORES_DIR="$CORES_DIR" \
    MLP1_CORES_REPORT="$REPORT" \
    MLP1_CORE_REPORT_TOOL="$REPORT_TOOL" \
    BUILD_LOG="$BUILD_LOG" \
    "$SCRIPT_DIR/ensure-mlp1-cores.sh"
}

FAKE_REPORT_VALID=1 run_gate >/dev/null
[ ! -e "$BUILD_LOG" ] || {
    echo "valid report unexpectedly rebuilt cores" >&2
    exit 1
}

set +e
FAKE_REPORT_VALID=0 run_gate >"$TEST_ROOT/refusal.out" 2>&1
status=$?
set -e
[ "$status" -eq 2 ] || {
    echo "invalid report returned $status instead of 2" >&2
    exit 1
}
grep -q 'REBUILD_CORES=1' "$TEST_ROOT/refusal.out"
[ ! -e "$BUILD_LOG" ] || {
    echo "invalid report rebuilt cores without authorization" >&2
    exit 1
}

FAKE_REPORT_VALID=0 REBUILD_CORES=1 run_gate >/dev/null
[ "$(wc -l <"$BUILD_LOG" | tr -d '[:space:]')" = "1" ]
grep -qx -- '--stock-parity' "$BUILD_LOG"

echo "ensure-mlp1-cores-test: PASS"
