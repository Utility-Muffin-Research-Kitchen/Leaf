#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ACTION="${1:-status}"
REQUESTED_REMOTE_SDCARD_PATH="${REMOTE_SDCARD_PATH:-auto}"
PLATFORM_ID="${PLATFORM_ID:-${DEVICE:-mlp1}}"
COUNT="${COUNT:-1200}"
SMALL_COUNT="${SMALL_COUNT:-10}"
LARGE_SYSTEMS="${LARGE_SYSTEMS:-FC:nes,SFC:sfc}"
SMALL_SYSTEMS="${SMALL_SYSTEMS:-GB:gb}"
IMAGE_EVERY="${IMAGE_EVERY:-0}"
FORCE="${FORCE:-0}"
FIXTURE_TOKEN="${FIXTURE_TOKEN:-LeafStressFixture}"
FIXTURE_NAME="${FIXTURE_NAME:-large-library}"

usage() {
    cat >&2 <<EOF
usage: $0 create|clean|status

Environment:
  COUNT=1200                         fake ROMs per large system
  LARGE_SYSTEMS=FC:nes,SFC:sfc       comma-separated SYSTEM:extension specs
  SMALL_COUNT=10                     fake ROMs per small comparison system
  SMALL_SYSTEMS=GB:gb                comma-separated SYSTEM:extension specs
  IMAGE_EVERY=0                      create tiny valid PNG Images entries
                                     every N ROMs
  FORCE=0                            allow create to replace an old fixture;
                                     allow clean to purge by token if the
                                     manifest is missing
  REMOTE_SDCARD_PATH=auto            or explicit /mnt/sdcard /media/sdcard1
  ADB_SERIAL=<serial>                select a device
EOF
}

is_number() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

validate_specs() {
    local label="$1"
    local specs="$2"
    local old_ifs spec system ext

    old_ifs="$IFS"
    IFS=,
    # shellcheck disable=SC2086
    set -- $specs
    IFS="$old_ifs"

    if [ "$#" -eq 0 ]; then
        echo "$label must not be empty." >&2
        exit 1
    fi

    for spec in "$@"; do
        case "$spec" in
            *:*)
                system="${spec%%:*}"
                ext="${spec#*:}"
                ;;
            *)
                echo "$label entry must be SYSTEM:extension, got: $spec" >&2
                exit 1
                ;;
        esac
        case "$system" in
            ''|*[!A-Za-z0-9_-]*)
                echo "$label has unsupported system code: $system" >&2
                exit 1
                ;;
        esac
        case "$ext" in
            ''|*[!A-Za-z0-9]*)
                echo "$label has unsupported extension: $ext" >&2
                exit 1
                ;;
        esac
    done
}

remote_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

resolve_adb() {
    if [ -n "${ADB_SERIAL:-}" ]; then
        serial="$ADB_SERIAL"
    else
        serial="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
        if [ -z "${serial:-}" ]; then
            echo "No online adb device found." >&2
            exit 1
        fi
    fi
    ADB=(adb -s "$serial")
    echo "Using adb device: $("${ADB[@]}" get-serialno)"

    REMOTE_SDCARD_PATH="$(PLATFORM_ID="$PLATFORM_ID" \
        REMOTE_SDCARD_PATH="$REQUESTED_REMOTE_SDCARD_PATH" \
        ADB_SERIAL="$serial" \
        "$ROOT_DIR/scripts/adb-resolve-umrk-sd.sh")"
}

run_remote() {
    local remote_action="$1"
    "${ADB[@]}" shell sh -s -- \
        "$remote_action" \
        "$REMOTE_SDCARD_PATH" \
        "$PLATFORM_ID" \
        "$COUNT" \
        "$SMALL_COUNT" \
        "$IMAGE_EVERY" \
        "$LARGE_SYSTEMS" \
        "$SMALL_SYSTEMS" \
        "$FORCE" \
        "$FIXTURE_TOKEN" \
        "$FIXTURE_NAME" <<'REMOTE_SCRIPT'
set -eu

action="$1"
sd="$2"
platform="$3"
count="$4"
small_count="$5"
image_every="$6"
large_systems="$7"
small_systems="$8"
force="$9"
token="${10}"
fixture_name="${11}"
manifest_dir="$sd/.umrk/$platform/fixtures"
manifest="$manifest_dir/$fixture_name.manifest"
tmp_manifest="$manifest.tmp"

letter_for_index() {
    case "$1" in
        0) printf A ;;
        1) printf B ;;
        2) printf C ;;
        3) printf D ;;
        4) printf E ;;
        5) printf F ;;
        6) printf G ;;
        7) printf H ;;
        8) printf I ;;
        9) printf J ;;
        10) printf K ;;
        11) printf L ;;
        12) printf M ;;
        13) printf N ;;
        14) printf O ;;
        15) printf P ;;
        16) printf Q ;;
        17) printf R ;;
        18) printf S ;;
        19) printf T ;;
        20) printf U ;;
        21) printf V ;;
        22) printf W ;;
        23) printf X ;;
        24) printf Y ;;
        *) printf Z ;;
    esac
}

clean_from_manifest() {
    removed=0
    if [ ! -f "$manifest" ]; then
        return 1
    fi

    while IFS= read -r path || [ -n "$path" ]; do
        case "$path" in
            "$sd"/Roms/*|"$sd"/Images/*)
                rm -f "$path"
                removed=$((removed + 1))
                ;;
            *)
                printf 'Refusing manifest path outside fixture roots: %s\n' "$path" >&2
                ;;
        esac
    done < "$manifest"

    rm -f "$manifest" "$tmp_manifest"
    rmdir "$manifest_dir" 2>/dev/null || true
    printf 'Removed %s manifest-listed fixture files.\n' "$removed"
    return 0
}

purge_by_token_for_specs() {
    specs="$1"
    old_ifs="$IFS"
    IFS=,
    # shellcheck disable=SC2086
    set -- $specs
    IFS="$old_ifs"

    for spec do
        system="${spec%%:*}"
        ext="${spec#*:}"
        rom_dir="$sd/Roms/$system"
        image_dir="$sd/Images/$system"
        if [ -d "$rom_dir" ]; then
            find "$rom_dir" -maxdepth 1 -type f -name "*-$token-$system-*.$ext" -exec rm -f {} \; 2>/dev/null || true
        fi
        if [ -d "$image_dir" ]; then
            find "$image_dir" -maxdepth 1 -type f -name "*-$token-$system-*.png" -exec rm -f {} \; 2>/dev/null || true
        fi
    done
}

create_system() {
    system="$1"
    ext="$2"
    system_count="$3"
    rom_dir="$sd/Roms/$system"
    image_dir="$sd/Images/$system"

    mkdir -p "$rom_dir"
    if [ "$image_every" -gt 0 ]; then
        mkdir -p "$image_dir"
    fi

    i=1
    while [ "$i" -le "$system_count" ]; do
        letter_index=$(( (i - 1) * 26 / system_count ))
        letter="$(letter_for_index "$letter_index")"
        number="$(printf '%04d' "$i")"
        base="$letter-$token-$system-$number"
        rom="$rom_dir/$base.$ext"

        printf 'leaf large-library fixture: %s %s\n' "$system" "$number" > "$rom"
        printf '%s\n' "$rom" >> "$tmp_manifest"

        if [ "$image_every" -gt 0 ] && [ $((i % image_every)) -eq 0 ]; then
            image="$image_dir/$base.png"
            write_tiny_png "$image"
            printf '%s\n' "$image" >> "$tmp_manifest"
        fi

        i=$((i + 1))
    done

    printf 'Created %s fake %s ROMs in %s\n' "$system_count" "$system" "$rom_dir"
}

write_tiny_png() {
    printf '\211\120\116\107\015\012\032\012\000\000\000\015\111\110\104\122\000\000\000\001\000\000\000\001\010\004\000\000\000\265\034\014\002\000\000\000\013\111\104\101\124\170\332\143\374\377\037\000\003\003\002\000\357\277\247\333\000\000\000\000\111\105\116\104\256\102\140\202' > "$1"
}

create_specs() {
    specs="$1"
    spec_count="$2"
    old_ifs="$IFS"
    IFS=,
    # shellcheck disable=SC2086
    set -- $specs
    IFS="$old_ifs"

    for spec do
        create_system "${spec%%:*}" "${spec#*:}" "$spec_count"
    done
}

count_files() {
    dir="$1"
    pattern="$2"
    if [ ! -d "$dir" ]; then
        printf 0
        return
    fi
    find "$dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | wc -l | tr -d ' '
}

status_specs() {
    specs="$1"
    old_ifs="$IFS"
    IFS=,
    # shellcheck disable=SC2086
    set -- $specs
    IFS="$old_ifs"

    for spec do
        system="${spec%%:*}"
        ext="${spec#*:}"
        rom_dir="$sd/Roms/$system"
        image_dir="$sd/Images/$system"
        total="$(count_files "$rom_dir" '*')"
        fixture="$(count_files "$rom_dir" "*-$token-$system-*.$ext")"
        images="$(count_files "$image_dir" "*-$token-$system-*.png")"
        printf '%s: rom files=%s fixture roms=%s fixture images=%s\n' \
            "$system" "$total" "$fixture" "$images"
    done
}

case "$action" in
    create)
        mkdir -p "$manifest_dir"
        if [ -f "$manifest" ]; then
            if [ "$force" = "1" ]; then
                clean_from_manifest || true
            else
                printf 'Fixture manifest already exists: %s\n' "$manifest" >&2
                printf 'Run clean first, or use FORCE=1 to replace it.\n' >&2
                exit 1
            fi
        fi

        : > "$tmp_manifest"
        create_specs "$large_systems" "$count"
        create_specs "$small_systems" "$small_count"
        mv "$tmp_manifest" "$manifest"
        sync
        printf 'Fixture manifest: %s\n' "$manifest"
        ;;
    clean)
        if clean_from_manifest; then
            sync
            exit 0
        fi
        if [ "$force" = "1" ]; then
            printf 'No manifest found; purging matching fixture token files.\n'
            purge_by_token_for_specs "$large_systems"
            purge_by_token_for_specs "$small_systems"
            rm -f "$tmp_manifest"
            sync
            exit 0
        fi
        printf 'No fixture manifest found: %s\n' "$manifest"
        printf 'Use FORCE=1 only if you need token-based cleanup fallback.\n'
        ;;
    status)
        printf 'SD card: %s\n' "$sd"
        if [ -f "$manifest" ]; then
            printf 'Manifest: %s (%s paths)\n' "$manifest" "$(wc -l < "$manifest" | tr -d ' ')"
        else
            printf 'Manifest: missing (%s)\n' "$manifest"
        fi
        status_specs "$large_systems"
        status_specs "$small_systems"
        ;;
    *)
        printf 'unsupported remote action: %s\n' "$action" >&2
        exit 1
        ;;
esac
REMOTE_SCRIPT
}

print_db_counts() {
    local remote_db db_tmp systems_sql old_ifs spec system

    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "Host sqlite3 not found; skipping library.db counts."
        return
    fi

    remote_db="$REMOTE_SDCARD_PATH/.umrk/$PLATFORM_ID/library.db"
    if ! "${ADB[@]}" shell "[ -f $(remote_quote "$remote_db") ]" >/dev/null 2>&1; then
        echo "No library.db found at $remote_db"
        return
    fi

    db_tmp="$(mktemp "${TMPDIR:-/tmp}/leaf-large-library-db.XXXXXX")"
    trap 'rm -f "$db_tmp"' RETURN
    "${ADB[@]}" pull "$remote_db" "$db_tmp" >/dev/null

    systems_sql=""
    old_ifs="$IFS"
    IFS=,
    # shellcheck disable=SC2086
    set -- $LARGE_SYSTEMS,$SMALL_SYSTEMS
    IFS="$old_ifs"
    for spec in "$@"; do
        system="${spec%%:*}"
        if [ -n "$systems_sql" ]; then
            systems_sql="$systems_sql,"
        fi
        systems_sql="${systems_sql}'$system'"
    done

    echo "library.db game counts:"
    sqlite3 -header -column "$db_tmp" \
        "SELECT system, COUNT(*) AS games FROM games WHERE system IN ($systems_sql) GROUP BY system ORDER BY system;"
}

case "$ACTION" in
    help|-h|--help)
        usage
        exit 0
        ;;
    create|clean|status)
        ;;
    *)
        usage
        exit 1
        ;;
esac

is_number "$COUNT" || { echo "COUNT must be a non-negative integer." >&2; exit 1; }
is_number "$SMALL_COUNT" || { echo "SMALL_COUNT must be a non-negative integer." >&2; exit 1; }
is_number "$IMAGE_EVERY" || { echo "IMAGE_EVERY must be a non-negative integer." >&2; exit 1; }
case "$FORCE" in
    0|1) ;;
    *) echo "FORCE must be 0 or 1." >&2; exit 1 ;;
esac
case "$FIXTURE_TOKEN" in
    ''|*[!A-Za-z0-9_-]*)
        echo "FIXTURE_TOKEN must contain only letters, numbers, underscore, or dash." >&2
        exit 1
        ;;
esac
case "$FIXTURE_NAME" in
    ''|*[!A-Za-z0-9_-]*)
        echo "FIXTURE_NAME must contain only letters, numbers, underscore, or dash." >&2
        exit 1
        ;;
esac
validate_specs LARGE_SYSTEMS "$LARGE_SYSTEMS"
validate_specs SMALL_SYSTEMS "$SMALL_SYSTEMS"

resolve_adb
run_remote "$ACTION"

if [ "$ACTION" = "status" ]; then
    print_db_counts
fi
