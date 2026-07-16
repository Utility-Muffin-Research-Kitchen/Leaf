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

audit_stage_apps_definitions() {
    local grep_bin="$1"
    shift
    local file definitions status

    command -v "$grep_bin" >/dev/null 2>&1 || {
        echo "STAGE_APPS audit command not found: $grep_bin" >&2
        return 1
    }
    for file in "$@"; do
        [ -f "$file" ] && [ -r "$file" ] || {
            echo "STAGE_APPS audit input is missing or unreadable: $file" >&2
            return 1
        }
        if definitions="$("$grep_bin" -E '^STAGE_APPS' "$file")"; then
            :
        else
            status=$?
            if [ "$status" -eq 1 ]; then
                echo "no STAGE_APPS definition found in $file" >&2
            else
                echo "failed to read STAGE_APPS definitions from $file (grep status $status)" >&2
            fi
            return 1
        fi
        if printf '%s\n' "$definitions" | \
            "$grep_bin" -qiE 'Leaf-Itchio|DiscoBoy|Nimbus|PortMaster'; then
            echo "Pak Rat-owned optional app leaked into STAGE_APPS in $file" >&2
            return 1
        else
            status=$?
            if [ "$status" -ne 1 ]; then
                echo "failed to inspect STAGE_APPS definitions from $file (grep status $status)" >&2
                return 1
            fi
        fi
    done
}

fixture="$(mktemp -d "${TMPDIR:-/tmp}/leaf-pakrat-policy.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT HUP INT TERM

stage_fixture="$fixture/stage-apps"
mkdir -p "$stage_fixture"
printf 'STAGE_APPS ?= ssh-server Thing-File\n' >"$stage_fixture/clean.mk"
printf 'STAGE_APPS="${STAGE_APPS-ssh-server Thing-File}"\n' >"$stage_fixture/clean.sh"
printf '# no default app list here\n' >"$stage_fixture/missing-definition.mk"
printf 'STAGE_APPS ?= ssh-server DiscoBoy\n' >"$stage_fixture/forbidden.mk"
printf 'STAGE_APPS ?= ssh-server\n' >"$stage_fixture/unreadable.mk"
printf '#!/bin/sh\nexit 2\n' >"$stage_fixture/grep-read-error"
chmod 700 "$stage_fixture/grep-read-error"
chmod 000 "$stage_fixture/unreadable.mk"

audit_stage_apps_definitions grep "$stage_fixture/clean.mk" "$stage_fixture/clean.sh" || {
    echo "STAGE_APPS fixture rejected clean definitions" >&2
    exit 1
}
if audit_stage_apps_definitions "$stage_fixture/missing-grep" \
    "$stage_fixture/clean.mk" "$stage_fixture/clean.sh" >/dev/null 2>&1; then
    echo "STAGE_APPS fixture accepted a missing grep command" >&2
    exit 1
fi
if audit_stage_apps_definitions "$stage_fixture/grep-read-error" \
    "$stage_fixture/clean.mk" "$stage_fixture/clean.sh" >/dev/null 2>&1; then
    echo "STAGE_APPS fixture accepted grep status 2" >&2
    exit 1
fi
if audit_stage_apps_definitions grep \
    "$stage_fixture/clean.mk" "$stage_fixture/missing-definition.mk" >/dev/null 2>&1; then
    echo "STAGE_APPS fixture accepted a missing definition" >&2
    exit 1
fi
if audit_stage_apps_definitions grep \
    "$stage_fixture/clean.mk" "$stage_fixture/missing.mk" >/dev/null 2>&1; then
    echo "STAGE_APPS fixture accepted a missing input file" >&2
    exit 1
fi
if [ ! -r "$stage_fixture/unreadable.mk" ]; then
    if audit_stage_apps_definitions grep \
        "$stage_fixture/clean.mk" "$stage_fixture/unreadable.mk" >/dev/null 2>&1; then
        echo "STAGE_APPS fixture accepted an unreadable input file" >&2
        exit 1
    fi
fi
chmod 600 "$stage_fixture/unreadable.mk"
if audit_stage_apps_definitions grep \
    "$stage_fixture/clean.mk" "$stage_fixture/forbidden.mk" >/dev/null 2>&1; then
    echo "STAGE_APPS fixture accepted a forbidden app" >&2
    exit 1
fi

audit_stage_apps_definitions grep \
    "$LEAF_ROOT/stage/mlp1.mk" "$SCRIPT_DIR/make-sd-release-zip.sh"

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
