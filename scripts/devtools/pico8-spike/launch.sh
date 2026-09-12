#!/bin/sh
# Private MLP1 feasibility app, not the production PICO-8 integration.
# Install only on the primary card. Jawaka supplies the Apps launch environment.
set -eu
[ "${PLATFORM:-}" = mlp1 ] || { echo 'This spike requires MLP1.' >&2; exit 1; }
spike="${UMRK_RUNTIME_PATH:?}/pico8-spike"
primary_sd=${SDCARD_PATHS%%:*}
[ -n "$primary_sd" ] && [ "$primary_sd" = "${SDCARD_PATH:?}" ] || exit 1
# An Apps launch is primary here. Refuse a source-rebound environment instead
# of accidentally testing a secondary runtime/home as though it were primary.
[ "${BIOS_PATHS%%:*}" = "${BIOS_PATH:?}" ] || exit 1
[ "${USERDATA_PATHS%%:*}" = "${USERDATA_PATH:?}" ] || exit 1
[ "${ROMS_PATHS%%:*}" = "${ROMS_PATH:?}" ] || exit 1
native_home="$USERDATA_PATH/pico8"
root="$ROMS_PATH/PICO8"
set -- -splore
if [ -f "$spike/cart-path" ]; then
    IFS= read -r cart < "$spike/cart-path"
    # Select only a configured, mounted library source. Do not treat an empty
    # firmware mountpoint directory as an available card.
    remaining_roots=$ROMS_PATHS
    remaining_cards=$SDCARD_PATHS
    found=0
    while [ -n "$remaining_roots" ] && [ -n "$remaining_cards" ]; do
        candidate=${remaining_roots%%:*}
        card=${remaining_cards%%:*}
        case "$cart" in
            "$candidate/PICO8/"*)
                mountpoint -q "$card" || exit 1
                root="$candidate/PICO8"
                found=1
                break ;;
        esac
        case "$remaining_roots" in *:*) remaining_roots=${remaining_roots#*:} ;; *) break ;; esac
        case "$remaining_cards" in *:*) remaining_cards=${remaining_cards#*:} ;; *) break ;; esac
    done
    [ "$found" = 1 ] && [ -f "$cart" ] || exit 1
    case "$cart" in */../*|*/./*) exit 1 ;; esac
    set -- -run "$cart"
fi
mountpoint -q "$primary_sd" || exit 1
[ -x "$BIOS_PATH/PICO8/pico8_64" ] && [ -s "$BIOS_PATH/PICO8/pico8.dat" ] || exit 1
mkdir -p "$native_home" "$root" "${RECORDINGS_PATH:?}/PICO8"
export SDL_VIDEODRIVER=wayland
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/var/run}"
export PATH="$spike/bin:$PATH"
cd "$BIOS_PATH/PICO8"
exec ./pico8_64 -home "$native_home/" -root_path "$root/" \
    -desktop "$RECORDINGS_PATH/PICO8/" -windowed 0 "$@" >> "$spike/launch.log" 2>&1
