#!/usr/bin/env bash
set -euo pipefail

leaf_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

# Only Docker is mocked: the rest of the checks use the actual workspace.
cat >"$scratch/docker" <<'EOF'
#!/bin/sh
case "$1" in
    info) exit 0 ;;
    image) printf '%s\n' 'sha256:preflight-smoke'; exit 0 ;;
esac
exit 1
EOF
chmod +x "$scratch/docker"

PATH="$scratch:$PATH" RELEASE_BUILD="$scratch/release" \
    /bin/bash "$leaf_root/scripts/make-sd-release-zip.sh" preflight >"$scratch/pass.log"
grep -q 'Release preflight passed' "$scratch/pass.log"
[ ! -e "$scratch/release" ]

if PATH="$scratch:$PATH" MLP1_RETROARCH_VALIDATOR="$scratch/missing-validator.py" \
        /bin/bash "$leaf_root/scripts/make-sd-release-zip.sh" preflight \
        >"$scratch/fail.log" 2>&1; then
    echo 'error: preflight accepted a missing release validator' >&2
    exit 1
fi
grep -q 'missing release input: .*missing-validator.py' "$scratch/fail.log"
echo 'Release preflight smoke passed'
