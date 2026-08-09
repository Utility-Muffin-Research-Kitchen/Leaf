#!/usr/bin/env bash
set -euo pipefail

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}"

CORES_SPRUCE_DIR="${CORES_SPRUCE_DIR:-$WORKSPACE_DIR/Cores-spruce}"
MLP1_CORES_DIR="${MLP1_CORES_DIR:-$CORES_SPRUCE_DIR/output/mlp1/cores}"
MLP1_CORES_REPORT="${MLP1_CORES_REPORT:-$CORES_SPRUCE_DIR/output/mlp1/build-report.json}"
MLP1_CORE_REPORT_TOOL="${MLP1_CORE_REPORT_TOOL:-$CORES_SPRUCE_DIR/scripts/mlp1-core-report.py}"
REBUILD_CORES="${REBUILD_CORES:-0}"

case "$REBUILD_CORES" in
    0|1) ;;
    *)
        echo "error: REBUILD_CORES must be 0 or 1, got: $REBUILD_CORES" >&2
        exit 2
        ;;
esac

core_report_valid() {
    [ -d "$MLP1_CORES_DIR" ] &&
        find "$MLP1_CORES_DIR" -maxdepth 1 -type f -name '*_libretro.so' -print -quit | grep -q . &&
        python3 "$MLP1_CORE_REPORT_TOOL" manifest \
            --report "$MLP1_CORES_REPORT" \
            --cores-dir "$MLP1_CORES_DIR" >/dev/null 2>&1
}

if core_report_valid; then
    echo "Reusing checksum-validated MLP1 core set: $MLP1_CORES_REPORT"
    exit 0
fi

if [ "$REBUILD_CORES" != "1" ]; then
    echo "error: MLP1 cores are missing or their build report is invalid." >&2
    echo "Refusing to start the long stock-parity core build implicitly." >&2
    echo "Inspect the report, or rerun intentionally with REBUILD_CORES=1." >&2
    exit 2
fi

[ -x "$CORES_SPRUCE_DIR/build-mlp1.sh" ] || {
    echo "error: missing core builder: $CORES_SPRUCE_DIR/build-mlp1.sh" >&2
    exit 2
}

echo "REBUILD_CORES=1: building the complete MLP1 stock-parity core set"
(
    cd "$CORES_SPRUCE_DIR"
    ./build-mlp1.sh --stock-parity
)

core_report_valid || {
    echo "error: rebuilt MLP1 core set still has an invalid report" >&2
    exit 1
}

echo "Built and validated MLP1 core set: $MLP1_CORES_REPORT"
