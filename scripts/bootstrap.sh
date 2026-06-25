#!/usr/bin/env bash
# Clone any missing sibling repos into Leaf's parent workspace.
# Usage: LEAF_WORKSPACE_DIR=/path scripts/bootstrap.sh <repo> [<repo> ...] [--optional <repo> ...]
set -euo pipefail

LEAF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_DIR="${LEAF_WORKSPACE_DIR:-${WORKSPACE_DIR:-$(cd "$LEAF_ROOT/.." && pwd)}}"

# repo name -> clone URL
url_for() {
    case "$1" in
        umrk-workspace)              echo "https://github.com/Utility-Muffin-Research-Kitchen/umrk-workspace.git" ;;
        Catastrophe)                 echo "https://github.com/Helaas/Catastrophe.git" ;;
        Jawaka)                      echo "https://github.com/Helaas/Jawaka.git" ;;
        Thing-File)                  echo "https://github.com/Utility-Muffin-Research-Kitchen/Thing-File.git" ;;
        ssh-server)                  echo "https://github.com/Helaas/ssh-server.git" ;;
        CentralScrutinizer)          echo "https://github.com/Utility-Muffin-Research-Kitchen/CentralScrutinizer.git" ;;
        Fugazi)                      echo "https://github.com/Utility-Muffin-Research-Kitchen/Fugazi.git" ;;
        joes-calibrage)              echo "https://github.com/Utility-Muffin-Research-Kitchen/joes-calibrage.git" ;;
        PPSSPP-spruce)               echo "https://github.com/Utility-Muffin-Research-Kitchen/PPSSPP-spruce.git" ;;
        steward-fu-nds)              echo "https://github.com/Helaas/nds.git" ;;
        retroarch-builds)            echo "https://github.com/Utility-Muffin-Research-Kitchen/retroarch-builds.git" ;;
        Cores-spruce)                echo "https://github.com/Utility-Muffin-Research-Kitchen/Cores-spruce.git" ;;
        mlp1-toolchain)              echo "https://github.com/Utility-Muffin-Research-Kitchen/mlp1-toolchain.git" ;;
        miniloong-launcher-switcher) echo "https://github.com/Helaas/miniloong-launcher-switcher.git" ;;
        miniloong-adb-keeper)        echo "https://github.com/Helaas/miniloong-adb-keeper.git" ;;
        *) echo "" ;;
    esac
}

required_repos=()
optional_repos=()
mode="required"

for arg in "$@"; do
    case "$arg" in
        --optional)
            mode="optional"
            ;;
        --required)
            mode="required"
            ;;
        *)
            if [ "$mode" = "optional" ]; then
                optional_repos+=("$arg")
            else
                required_repos+=("$arg")
            fi
            ;;
    esac
done

clone_repo() {
    local repo="$1"
    local optional="$2"
    local dest url

    dest="$WORKSPACE_DIR/$repo"
    if [ -d "$dest/.git" ]; then
        echo "ok      $repo (present)"
        return 0
    fi
    if [ -e "$dest" ]; then
        echo "warn    $repo ($dest exists but is not a git repo; leaving untouched)" >&2
        return 0
    fi
    url="$(url_for "$repo")"
    if [ -z "$url" ]; then
        if [ "$optional" = "1" ]; then
            return 0
        fi
        echo "error   $repo (no known remote)" >&2
        return 1
    fi
    if [ "$optional" = "1" ]; then
        if ! GIT_TERMINAL_PROMPT=0 git ls-remote "$url" HEAD >/dev/null 2>&1; then
            return 0
        fi
    fi
    echo "clone   $repo <- $url"
    git clone "$url" "$dest"
}

for repo in "${required_repos[@]}"; do
    clone_repo "$repo" 0
done

for repo in "${optional_repos[@]}"; do
    clone_repo "$repo" 1
done
