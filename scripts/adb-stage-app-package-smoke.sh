#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-pkg-quiesce.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/bin" "$fixture/local/bin"
printf '#!/bin/sh\nexit 0\n' >"$fixture/local/launch.sh"
printf '#!/bin/sh\nexit 0\n' >"$fixture/local/bin/service"
chmod 755 "$fixture/local/launch.sh" "$fixture/local/bin/service"

cat >"$fixture/bin/adb" <<'EOF'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >>"$FAKE_ADB_LOG"
case "$*" in
    *package-quiesce-begin*)
        if [ "${FAKE_ADB_BEGIN_ERROR:-0}" -eq 1 ]; then
            printf '%s\n' '{"type":"error","message":"stale-generation"}'
        else
            printf '%s\n' '{"type":"ok","action":"package-quiesce-begin"}'
        fi
        ;;
    *package-quiesce-end*)
        printf '%s\n' '{"type":"ok","action":"package-quiesce-end"}'
        ;;
    *scan-library*)
        if [ "${FAKE_ADB_SCAN_ERROR:-0}" -eq 1 ]; then
            printf '%s\n' '{"type":"error","message":"scan-failed"}'
        else
            printf '%s\n' '{"type":"ok","action":"scan-library started"}'
        fi
        ;;
    *' push '*)
        if [ "${FAKE_ADB_PUSH_ERROR:-0}" -eq 1 ]; then exit 1; fi
        ;;
    *'find "$1"'*) printf '%s\n' "/mnt/sdcard/Apps/mlp1/Joe's Calibrage.pak/pak.json" ;;
esac
exit 0
EOF
chmod 755 "$fixture/bin/adb"

export PATH="$fixture/bin:$PATH"
export ADB_SERIAL="fixture-device"
export PLATFORM_ID="mlp1"
export REMOTE_SDCARD_PATH="/mnt/sdcard"
export FAKE_ADB_LOG="$fixture/adb.log"
remote_dir="/mnt/sdcard/Apps/mlp1/Joe's Calibrage.pak"
remote_remove_marker="rm -rf -- \"\$1\""

line_for() {
    grep -F -n -m1 -- "$1" "$FAKE_ADB_LOG" | cut -d: -f1
}

: >"$FAKE_ADB_LOG"
"$ROOT_DIR/scripts/adb-stage-app-package.sh" "$fixture/local" "$remote_dir" \
    >/dev/null
begin_line="$(line_for package-quiesce-begin)"
remove_line="$(line_for "$remote_remove_marker")"
push_line="$(line_for ' push ')"
end_line="$(line_for package-quiesce-end)"
scan_line="$(line_for scan-library)"
[ "$begin_line" -lt "$remove_line" ]
[ "$remove_line" -lt "$push_line" ]
[ "$push_line" -lt "$end_line" ]
[ "$end_line" -lt "$scan_line" ]

: >"$FAKE_ADB_LOG"
if FAKE_ADB_PUSH_ERROR=1 \
    "$ROOT_DIR/scripts/adb-stage-app-package.sh" "$fixture/local" "$remote_dir" \
        >/dev/null 2>&1; then
    echo "expected a failed adb push to fail staging" >&2
    exit 1
fi
grep -Fq package-quiesce-begin "$FAKE_ADB_LOG"
grep -Fq ' push ' "$FAKE_ADB_LOG"
grep -Fq package-quiesce-end "$FAKE_ADB_LOG"
grep -Fq scan-library "$FAKE_ADB_LOG"

: >"$FAKE_ADB_LOG"
if FAKE_ADB_SCAN_ERROR=1 \
    "$ROOT_DIR/scripts/adb-stage-app-package.sh" "$fixture/local" "$remote_dir" \
        >/dev/null 2>&1; then
    echo "expected a rejected library scan to fail staging" >&2
    exit 1
fi
grep -Fq package-quiesce-end "$FAKE_ADB_LOG"
grep -Fq scan-library "$FAKE_ADB_LOG"

: >"$FAKE_ADB_LOG"
if FAKE_ADB_BEGIN_ERROR=1 \
    "$ROOT_DIR/scripts/adb-stage-app-package.sh" "$fixture/local" "$remote_dir" \
        >/dev/null 2>&1; then
    echo "expected a rejected quiesce to fail staging" >&2
    exit 1
fi
grep -Fq package-quiesce-begin "$FAKE_ADB_LOG"
grep -Fq package-quiesce-end "$FAKE_ADB_LOG"
if grep -Fq "$remote_remove_marker" "$FAKE_ADB_LOG" ||
   grep -Fq ' push ' "$FAKE_ADB_LOG"; then
    echo "staging mutated package bytes after a rejected quiesce" >&2
    exit 1
fi

echo "PASS adb-stage-app-package-smoke"
