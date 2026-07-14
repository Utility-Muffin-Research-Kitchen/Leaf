#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$LEAF_ROOT/.." && pwd)"

# shellcheck source=scripts/app-package-policy.sh
. "$SCRIPT_DIR/app-package-policy.sh"

assert_policy() {
    local app="$1"
    local expected_package="$2"
    local expected_distribution="$3"

    leaf_app_policy "$app" "$WORKSPACE_ROOT" mlp1
    [ "$package_name" = "$expected_package" ] || {
        echo "unexpected package for $app: $package_name" >&2
        exit 1
    }
    [ "$distribution" = "$expected_distribution" ] || {
        echo "unexpected distribution for $app: $distribution" >&2
        exit 1
    }
}

assert_policy Leaf-Itchio-Pak Itch-io.pak pakrat
assert_policy DiscoBoy DiscoBoy.pak pakrat
assert_policy Nimbus Nimbus.pak pakrat
assert_policy PortMaster-mlp1 PortMaster.pak pakrat
assert_policy ssh-server SSHServer.pak release

# Use grep (always present) rather than rg: a missing tool under `pipefail`
# silently skips this leak check yet still lets the script report PASS.
stage_apps_defs="$(grep -hE '^STAGE_APPS' \
    "$LEAF_ROOT/stage/mlp1.mk" "$SCRIPT_DIR/make-sd-release-zip.sh" || true)"
[ -n "$stage_apps_defs" ] || {
    echo "no STAGE_APPS definition found to audit -- cannot verify the default list" >&2
    exit 1
}
if printf '%s\n' "$stage_apps_defs" | grep -qiE 'Leaf-Itchio|DiscoBoy|Nimbus|PortMaster'; then
    echo "Pak Rat-owned optional app leaked into default STAGE_APPS" >&2
    exit 1
fi

fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-pakrat-policy.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT HUP INT TERM
mkdir -p "$fixture/platforms/mlp1" "$fixture/Apps/mlp1"
printf '{"managed_apps": []}\n' >"$fixture/platforms/mlp1/manifest.json"
: >"$fixture/managed-apps.txt"

pakrat_packages=()
while IFS= read -r package; do
    [ -n "$package" ] && pakrat_packages+=("$package")
done < <(leaf_pakrat_owned_package_names)
python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" "$fixture" "${pakrat_packages[@]}" >/dev/null

for package in "${pakrat_packages[@]}"; do
    printf 'mlp1/%s\n' "$package" >"$fixture/managed-apps.txt"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${pakrat_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted managed $package" >&2
        exit 1
    fi
    : >"$fixture/managed-apps.txt"

    printf '{"managed_apps": ["mlp1/%s"]}\n' "$package" \
        >"$fixture/platforms/mlp1/manifest.json"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${pakrat_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted manifest-owned $package" >&2
        exit 1
    fi
    printf '{"managed_apps": []}\n' >"$fixture/platforms/mlp1/manifest.json"

    mkdir -p "$fixture/Apps/mlp1/$package"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${pakrat_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted staged $package" >&2
        exit 1
    fi
    rmdir "$fixture/Apps/mlp1/$package"
done

echo "app-package-policy-smoke: PASS"
