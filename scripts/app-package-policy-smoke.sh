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
assert_policy Leaf-Syncthing-Pak Syncthing.pak pakrat
assert_policy Leaf-RAOfflineProxy-Pak RAOfflineProxy.pak pakrat
assert_policy DiscoBoy DiscoBoy.pak pakrat
assert_policy VideoFromHell VideoFromHell.pak pakrat
assert_policy Nimbus Nimbus.pak pakrat
assert_policy PortMaster-mlp1 PortMaster.pak pakrat
assert_policy ssh-server SSHServer.pak release

# The audits below derive their patterns from leaf_pakrat_owned_repos, so this
# is the one place drift can hide: a repo missing from that list would quietly
# narrow the STAGE_APPS and bootstrap checks rather than fail anything. Tie it
# to the policy table, which is what the rest of the build actually consults.
pakrat_repos=()
while IFS= read -r repo; do
    [ -n "$repo" ] && pakrat_repos+=("$repo")
done < <(leaf_pakrat_owned_repos)

[ "${#pakrat_repos[@]}" -gt 0 ] || {
    echo "leaf_pakrat_owned_repos is empty" >&2
    exit 1
}

pakrat_repo_packages=()
for repo in "${pakrat_repos[@]}"; do
    leaf_app_policy "$repo" "$WORKSPACE_ROOT" mlp1 || {
        echo "leaf_pakrat_owned_repos lists an unknown repo: $repo" >&2
        exit 1
    }
    [ "$distribution" = "pakrat" ] || {
        echo "leaf_pakrat_owned_repos lists a non-Pak Rat repo: $repo" >&2
        exit 1
    }
    pakrat_repo_packages+=("$package_name")
done

# The two lists must agree in BOTH directions. Each covers audits the other
# does not -- repo names drive STAGE_APPS and bootstrap, package names drive
# the release-ZIP and managed-app ownership audit -- so a name in one and not
# the other leaves an app audited by half the checks and silently exempt from
# the rest. Checking one direction only was itself the bug here: a repo added
# without its package name passed.
pakrat_package_names=()
while IFS= read -r package; do
    [ -n "$package" ] && pakrat_package_names+=("$package")
done < <(leaf_pakrat_owned_package_names)

for package in "${pakrat_package_names[@]}"; do
    case " ${pakrat_repo_packages[*]} " in
        *" $package "*) ;;
        *)
            echo "Pak Rat package $package has no repo in leaf_pakrat_owned_repos" >&2
            exit 1
            ;;
    esac
done

for package in "${pakrat_repo_packages[@]}"; do
    case " ${pakrat_package_names[*]} " in
        *" $package "*) ;;
        *)
            echo "$package is owned by a repo in leaf_pakrat_owned_repos but is" \
                 "missing from leaf_pakrat_owned_package_names" >&2
            exit 1
            ;;
    esac
done

# STAGE_APPS entries are repo names, fed to leaf_app_policy. This is a
# SUBSTRING match, deliberately: a leak is worth catching however it is
# written -- quoted, path-qualified, or appended to another variable -- and a
# false positive here is a loud failure a contributor can read, while a miss
# ships an optional app inside the release image.
#
# Metacharacters are escaped so the breadth stays deliberate rather than
# accidental: today's names are alphanumeric and hyphenated, but a future repo
# with a "." would otherwise match any character in that position.
pakrat_repo_patterns=()
for repo in "${pakrat_repos[@]}"; do
    pakrat_repo_patterns+=("$(printf '%s' "$repo" | sed 's/[][^$.*+?(){}|\\]/\\&/g')")
done
PAKRAT_REPO_RE="$(IFS='|'; printf '%s' "${pakrat_repo_patterns[*]}")"

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
            "$grep_bin" -qiE "$PAKRAT_REPO_RE"; then
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
printf 'STAGE_APPS ?= ssh-server VideoFromHell\n' >"$stage_fixture/forbidden.mk"
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

# Pak Rat owns these apps end to end, so bootstrap must neither require them
# nor probe for them: a contributor without the repo must still be able to
# build and stage a release. Checked against every optional repo rather than
# just Syncthing, so adding one to REQUIRED_REPOS or OPTIONAL_PRIVATE_REPOS
# fails here instead of shipping.
audit_bootstrap_repos() {
    local file="$1" repo

    [ -f "$file" ] && [ -r "$file" ] || {
        echo "bootstrap repo audit input is missing or unreadable: $file" >&2
        return 1
    }
    for repo in "${pakrat_repos[@]}"; do
        if grep -q -- "$repo" "$file"; then
            echo "$repo leaked into bootstrap repos in $file" >&2
            return 1
        fi
    done
}

bootstrap_fixture="$fixture/bootstrap"
mkdir -p "$bootstrap_fixture"
printf 'REQUIRED_REPOS := Catastrophe Jawaka ssh-server\nOPTIONAL_PRIVATE_REPOS := umrk-workspace\n' \
    >"$bootstrap_fixture/clean.mk"

audit_bootstrap_repos "$bootstrap_fixture/clean.mk" || {
    echo "bootstrap fixture rejected a clean repo list" >&2
    exit 1
}
if audit_bootstrap_repos "$bootstrap_fixture/missing.mk" >/dev/null 2>&1; then
    echo "bootstrap fixture accepted a missing input file" >&2
    exit 1
fi

# One case per optional repo, in both lists: the invariant has to hold for each
# of them, not merely for whichever one happened to be written into the check.
for repo in "${pakrat_repos[@]}"; do
    printf 'REQUIRED_REPOS := Catastrophe Jawaka %s\nOPTIONAL_PRIVATE_REPOS := umrk-workspace\n' \
        "$repo" >"$bootstrap_fixture/required.mk"
    if audit_bootstrap_repos "$bootstrap_fixture/required.mk" >/dev/null 2>&1; then
        echo "bootstrap fixture accepted required $repo" >&2
        exit 1
    fi

    printf 'REQUIRED_REPOS := Catastrophe Jawaka\nOPTIONAL_PRIVATE_REPOS := umrk-workspace %s\n' \
        "$repo" >"$bootstrap_fixture/optional.mk"
    if audit_bootstrap_repos "$bootstrap_fixture/optional.mk" >/dev/null 2>&1; then
        echo "bootstrap fixture accepted optional $repo" >&2
        exit 1
    fi
done

audit_bootstrap_repos "$LEAF_ROOT/stage/common.mk"

mkdir -p "$fixture/platforms/mlp1" "$fixture/Apps/mlp1"
printf '{"managed_apps": []}\n' >"$fixture/platforms/mlp1/manifest.json"
: >"$fixture/managed-apps.txt"

release_forbidden_packages=()
while IFS= read -r package; do
    [ -n "$package" ] && release_forbidden_packages+=("$package")
done < <(leaf_pakrat_owned_package_names)
python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" "$fixture" "${release_forbidden_packages[@]}" >/dev/null

for package in "${release_forbidden_packages[@]}"; do
    printf 'mlp1/%s\n' "$package" >"$fixture/managed-apps.txt"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${release_forbidden_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted managed $package" >&2
        exit 1
    fi
    : >"$fixture/managed-apps.txt"

    printf '{"managed_apps": ["mlp1/%s"]}\n' "$package" \
        >"$fixture/platforms/mlp1/manifest.json"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${release_forbidden_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted manifest-owned $package" >&2
        exit 1
    fi
    printf '{"managed_apps": []}\n' >"$fixture/platforms/mlp1/manifest.json"

    mkdir -p "$fixture/Apps/mlp1/$package"
    if python3 "$SCRIPT_DIR/audit-pakrat-owned-apps.py" \
        "$fixture" "${release_forbidden_packages[@]}" >/dev/null 2>&1; then
        echo "ownership audit accepted staged $package" >&2
        exit 1
    fi
    rmdir "$fixture/Apps/mlp1/$package"
done

echo "app-package-policy-smoke: PASS"
