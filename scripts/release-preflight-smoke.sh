#!/bin/bash
set -euo pipefail

leaf_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
public_workspace="$scratch/public-workspace"
mkdir -p "$public_workspace" "$scratch/bin"

# The preflight uses real Leaf files and minimal public-repo fixtures. No
# sibling checkout, Docker daemon, ADB device, or private repo is needed.
for repo in Catastrophe Jawaka PPSSPP-spruce steward-fu-nds N64-standalone \
        Flycast-standalone Yabasanshiro-standalone Fun-Drastic-standalone \
        Fun-Drastic-src retroarch-builds Cores-spruce mlp1-toolchain \
        miniloong-launcher-switcher ssh-server Thing-File CentralScrutinizer \
        Fugazi joes-calibrage; do
    mkdir -p "$public_workspace/$repo"
done

cat >"$public_workspace/Jawaka/Makefile" <<'EOF'
screenscraper-status:
	@echo false
EOF
for path in \
        miniloong-launcher-switcher/make_launcher_switcher_sd.py \
        retroarch-builds/build-mlp1-ffmpeg.py \
        retroarch-builds/build-mlp1-ffmpeg.sh \
        retroarch-builds/scripts/verify-mlp1-ffmpeg.sh \
        retroarch-builds/config/mlp1-ffmpeg-source-lock.json \
        retroarch-builds/scripts/mlp1_shader_bundle.py \
        retroarch-builds/scripts/mlp1_asset_bundle.py \
        Cores-spruce/build-mlp1.sh \
        Cores-spruce/scripts/mlp1-core-report.py \
        Cores-spruce/probe-mlp1-cores-container.sh; do
    mkdir -p "$(dirname "$public_workspace/$path")"
    : >"$public_workspace/$path"
done
mkdir -p "$public_workspace/mlp1-toolchain/flags"
printf 'fixture=1\n' >"$public_workspace/mlp1-toolchain/flags/mlp1-build-flags.env"
printf 'fixture=1\n' >"$public_workspace/mlp1-toolchain/flags/mlp1-build-flags.mk"

cat >"$scratch/bin/docker" <<'EOF'
#!/bin/sh
case "$1 $2" in
    'info ') exit 0 ;;
    'image inspect') printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; exit 0 ;;
    'run --rm') cat "$MOCK_TOOLCHAIN_FLAGS/${6##*/}"; exit $? ;;
esac
exit 1
EOF
chmod +x "$scratch/bin/docker"

export MOCK_TOOLCHAIN_FLAGS="$public_workspace/mlp1-toolchain/flags"
export PATH="$scratch/bin:$PATH"
export SCREENSCRAPER_ENV_FILE= SCREENSCRAPER_DEV_ID= SCREENSCRAPER_DEV_PASSWORD=

RELEASE_BUILD="$scratch/release" make -s -C "$leaf_root" release-preflight \
    LEAF_WORKSPACE_DIR="$public_workspace" >"$scratch/pass.log"
grep -q 'Release preflight passed' "$scratch/pass.log"
grep -q 'ScreenScraper credentials: unavailable' "$scratch/pass.log"
[ ! -e "$public_workspace/umrk-workspace" ]
[ ! -e "$scratch/release" ]

if MLP1_RETROARCH_VALIDATOR="$scratch/missing-validator.py" \
        LEAF_WORKSPACE_DIR="$public_workspace" \
        /bin/bash "$leaf_root/scripts/make-sd-release-zip.sh" preflight \
        >"$scratch/fail.log" 2>&1; then
    echo 'error: preflight accepted a missing release validator' >&2
    exit 1
fi
grep -q 'missing release input: .*missing-validator.py' "$scratch/fail.log"

if LEAF_WORKSPACE_DIR="$public_workspace" \
        /bin/bash "$leaf_root/scripts/make-sd-release-zip.sh" invalid-mode \
        >"$scratch/fail.log" 2>&1; then
    echo 'error: release entrypoint accepted an invalid mode' >&2
    exit 1
fi
grep -q 'unsupported mode: invalid-mode' "$scratch/fail.log"
echo 'Release preflight smoke passed'
