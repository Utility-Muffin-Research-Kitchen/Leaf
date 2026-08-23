#!/usr/bin/env bash
set -euo pipefail

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}"

CORES_SPRUCE_DIR="${CORES_SPRUCE_DIR:-$WORKSPACE_DIR/Cores-spruce}"
MLP1_CORES_DIR="${MLP1_CORES_DIR:-$CORES_SPRUCE_DIR/output/mlp1/cores}"
MLP1_CORES_REPORT="${MLP1_CORES_REPORT:-$CORES_SPRUCE_DIR/output/mlp1/build-report.json}"
MLP1_CORE_REPORT_TOOL="${MLP1_CORE_REPORT_TOOL:-$CORES_SPRUCE_DIR/scripts/mlp1-core-report.py}"
MLP1_CORE_BUILDER="${MLP1_CORE_BUILDER:-$CORES_SPRUCE_DIR/build-mlp1.sh}"
REBUILD_CORES="${REBUILD_CORES:-0}"
FORCE_REBUILD_CORES="${FORCE_REBUILD_CORES:-0}"

for setting in REBUILD_CORES FORCE_REBUILD_CORES; do
    value="${!setting}"
    case "$value" in
        0|1) ;;
        *)
            echo "error: $setting must be 0 or 1, got: $value" >&2
            exit 2
            ;;
    esac
done

if [ "$FORCE_REBUILD_CORES" = "1" ] && [ "$REBUILD_CORES" != "1" ]; then
    echo "error: FORCE_REBUILD_CORES=1 also requires REBUILD_CORES=1" >&2
    exit 2
fi

[ -x "$MLP1_CORE_BUILDER" ] || {
    echo "error: missing core builder: $MLP1_CORE_BUILDER" >&2
    exit 2
}

core_report_valid() {
    local expected actual
    [ -d "$MLP1_CORES_DIR" ] || return 1
    expected="$("$MLP1_CORE_BUILDER" --list-stock-parity | sort)" || return 1
    actual="$(python3 "$MLP1_CORE_REPORT_TOOL" manifest \
        --report "$MLP1_CORES_REPORT" \
        --cores-dir "$MLP1_CORES_DIR" 2>/dev/null | cut -f1 | sort)" || return 1
    [ -n "$expected" ] && [ "$actual" = "$expected" ]
}

cache_preflight() {
    "$MLP1_CORE_BUILDER" --check-stock-parity-cache
}

cache_ok=0
if cache_preflight; then
    cache_ok=1
fi

if [ "$FORCE_REBUILD_CORES" = "0" ] && [ "$cache_ok" = "1" ] && core_report_valid; then
    echo "Reusing checksum-validated MLP1 core set: $MLP1_CORES_REPORT"
    exit 0
fi

if [ "$cache_ok" != "1" ] && [ "$REBUILD_CORES" != "1" ]; then
    echo "error: MLP1 core cache preflight reported one or more misses." >&2
    echo "Aborting before compilation; stable preparation requires 28 cache hits." >&2
    echo "Inspect the misses, or rebuild intentionally with REBUILD_CORES=1." >&2
    exit 2
fi

if [ "$FORCE_REBUILD_CORES" = "1" ]; then
    echo "FORCE_REBUILD_CORES=1: rebuilding every stock-parity core"
elif [ "$cache_ok" = "1" ]; then
    echo "Cache is complete; assembling a fresh full report without core compilation"
else
    echo "REBUILD_CORES=1: compiling only missing or stale stock-parity cores"
fi
(
    cd "$CORES_SPRUCE_DIR"
    FORCE_REBUILD_CORES="$FORCE_REBUILD_CORES" \
        "$MLP1_CORE_BUILDER" --stock-parity
)

cache_preflight || {
    echo "error: MLP1 core cache still has misses after the stock-parity run" >&2
    exit 1
}
core_report_valid || {
    echo "error: MLP1 core set still lacks a valid full stock-parity report" >&2
    exit 1
}

echo "Validated complete MLP1 core set: $MLP1_CORES_REPORT"
