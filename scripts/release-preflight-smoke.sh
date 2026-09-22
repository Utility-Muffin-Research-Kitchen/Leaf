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

mkdir "$scratch/public-workspace"
for repo in Catastrophe Jawaka PPSSPP-spruce steward-fu-nds N64-standalone \
        Flycast-standalone Yabasanshiro-standalone Fun-Drastic-standalone \
        Fun-Drastic-src retroarch-builds Cores-spruce mlp1-toolchain \
        miniloong-launcher-switcher ssh-server Thing-File CentralScrutinizer \
        Fugazi joes-calibrage; do
    ln -s "$leaf_root/../$repo" "$scratch/public-workspace/$repo"
done

PATH="$scratch:$PATH" RELEASE_BUILD="$scratch/release" \
    make -s -C "$leaf_root" release-preflight \
        LEAF_WORKSPACE_DIR="$scratch/public-workspace" >"$scratch/pass.log"
grep -q 'Release preflight passed' "$scratch/pass.log"
[ ! -e "$scratch/public-workspace/umrk-workspace" ]
[ ! -e "$scratch/release" ]

if PATH="$scratch:$PATH" MLP1_RETROARCH_VALIDATOR="$scratch/missing-validator.py" \
        LEAF_WORKSPACE_DIR="$scratch/public-workspace" \
        /bin/bash "$leaf_root/scripts/make-sd-release-zip.sh" preflight \
        >"$scratch/fail.log" 2>&1; then
    echo 'error: preflight accepted a missing release validator' >&2
    exit 1
fi
grep -q 'missing release input: .*missing-validator.py' "$scratch/fail.log"
echo 'Release preflight smoke passed'
