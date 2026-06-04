#!/usr/bin/env bash
# Preflight checks for workspace staging.
# Hard requirements (adb, docker) -> FAIL + non-zero exit. Others -> WARN.
set -uo pipefail

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-${WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}}"
TOOLCHAIN_IMAGE="${TOOLCHAIN_IMAGE:-ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:local}"
fail=0

pass() { printf "PASS  %s\n" "$1"; }
warn() { printf "WARN  %s\n" "$1"; }
die()  { printf "FAIL  %s\n" "$1"; fail=1; }

# adb (hard requirement for staging)
if command -v adb >/dev/null 2>&1; then
    pass "adb found ($(adb version 2>/dev/null | head -1))"
    serial="${ADB_SERIAL:-$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1; exit}')}"
    if [ -n "${serial:-}" ]; then
        pass "device online: $serial"
    else
        warn "no online adb device (connect the device before staging)"
    fi
else
    die "adb not found (install android-platform-tools)"
fi

# docker (hard requirement for cross-compile)
if command -v docker >/dev/null 2>&1; then
    pass "docker found"
    if docker image inspect "$TOOLCHAIN_IMAGE" >/dev/null 2>&1; then
        pass "toolchain image present: $TOOLCHAIN_IMAGE"
    else
        warn "toolchain image missing: $TOOLCHAIN_IMAGE (build it in mlp1-toolchain)"
    fi
else
    die "docker not found (needed for cross-compile)"
fi

if [ -d "$WORKSPACE_DIR/mlp1-toolchain/.git" ]; then
    pass "mlp1-toolchain repo present: $WORKSPACE_DIR/mlp1-toolchain"
else
    warn "mlp1-toolchain repo missing (run: make bootstrap)"
fi

exit $fail
