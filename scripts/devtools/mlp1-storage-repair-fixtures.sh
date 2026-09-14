#!/usr/bin/env bash
# Phase 0 device groundwork for SD card read-only detection and reboot repair.
#
# Builds disposable FAT32 and exFAT images on MLP1 internal storage, attaches
# them only to verified loop devices, injects damage offline, and records the
# installed fsck tools' exit codes and output for clean, damaged, repaired and
# check-only runs. It also mounts one damaged image to observe an error-induced
# read-only flip through /proc and statvfs.
#
# Never touches a production card: every device it operates on is a /dev/loopN
# whose backing file is under the fixture directory, checked before each use.
#
#   scripts/devtools/mlp1-storage-repair-fixtures.sh [out-dir]
#
# Honors ADB_SERIAL. Results land in out-dir (default
# build/storage-repair-fixtures/<timestamp>).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEAF_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT_DIR="${1:-$LEAF_DIR/build/storage-repair-fixtures/$(date +%Y%m%d-%H%M%S)}"
REMOTE_DIR="/userdata/umrk/fixtures/storage-repair"
ADB=(adb)
if [[ -n "${ADB_SERIAL:-}" ]]; then
    ADB=(adb -s "$ADB_SERIAL")
fi

model="$("${ADB[@]}" shell 'cat /proc/device-tree/model 2>/dev/null' | tr -d '\0\r')"
case "$model" in
    *RK3566*) ;;
    *) echo "refusing: not an MLP1 (model: ${model:-unknown})" >&2; exit 1 ;;
esac

mkdir -p "$OUT_DIR"
device_script="$(mktemp "${TMPDIR:-/tmp}/storage-repair-fixtures.XXXXXX.sh")"
trap 'rm -f "$device_script"' EXIT

cat >"$device_script" <<'DEVICE'
#!/bin/sh
set -u
DIR=/userdata/umrk/fixtures/storage-repair
MNT="$DIR/mnt"
RESULTS="$DIR/results"
mkdir -p "$DIR" "$MNT" "$RESULTS"
rm -f "$RESULTS"/* 2>/dev/null

note() { printf '%s\n' "$*" | tee -a "$RESULTS/summary.txt"; }

loop_dev=""
attach() {
    image="$1"
    loop_dev="$(losetup -f 2>/dev/null)"
    case "$loop_dev" in /dev/loop[0-9]*) ;; *) note "no free loop device"; exit 1 ;; esac
    losetup "$loop_dev" "$image" || { note "losetup failed for $image"; exit 1; }
    verify_loop "$loop_dev" "$image"
}

# The only safety interlock: the device is a loop device backed by our file.
verify_loop() {
    case "$1" in /dev/loop[0-9]*) ;; *) note "refusing non-loop device $1"; exit 1 ;; esac
    backing="$(cat "/sys/block/${1##*/}/loop/backing_file" 2>/dev/null)"
    case "$backing" in
        "$DIR"/*) ;;
        *) note "refusing $1: backing file '$backing' is outside $DIR"; exit 1 ;;
    esac
}

detach() {
    [ -n "$loop_dev" ] || return 0
    umount "$MNT" 2>/dev/null
    losetup -d "$loop_dev" 2>/dev/null
    loop_dev=""
}
trap detach EXIT

run_fsck() {
    label="$1"; shift
    verify_loop "$loop_dev" "$image"
    LC_ALL=C "$@" "$loop_dev" >"$RESULTS/$label.log" 2>&1
    rc=$?
    note "$label: exit=$rc $(grep -c '' "$RESULTS/$label.log") lines"
    return 0
}

le16() { od -An -tu2 -j "$2" -N2 "$1" | tr -d ' '; }
le32() { od -An -tu4 -j "$2" -N4 "$1" | tr -d ' '; }
poke_zero() { dd if=/dev/zero of="$1" bs=1 seek="$2" count="$3" conv=notrunc 2>/dev/null; }
poke_byte() { printf "\\$(printf '%03o' "$3")" | dd of="$1" bs=1 seek="$2" count=1 conv=notrunc 2>/dev/null; }

populate() {
    mount -t vfat -o rw,noatime "$loop_dev" "$MNT" || { note "mount failed"; return 1; }
    mkdir -p "$MNT/Images/GBA" "$MNT/Roms/PSX/Final Fantasy VII" "$MNT/Saves/GBA"
    i=0
    while [ "$i" -lt 12 ]; do
        dd if=/dev/urandom of="$MNT/Images/GBA/game-$i.png" bs=1024 count=48 2>/dev/null
        i=$((i + 1))
    done
    dd if=/dev/urandom of="$MNT/Saves/GBA/game-0.sav" bs=1024 count=64 2>/dev/null
    sync
    umount "$MNT"
}

note "fsck.fat: $(/usr/sbin/fsck.fat --help 2>&1 | head -n 1)"
note "exfatfsck: $(/usr/sbin/exfatfsck -V 2>&1 | head -n 1)"

# ── FAT32: clean baseline ──────────────────────────────────────────────────
image="$DIR/fat32.img"
rm -f "$image"
dd if=/dev/zero of="$image" bs=1M count=64 2>/dev/null
/usr/sbin/mkfs.fat -F 32 -n FIXTURE "$image" >/dev/null 2>&1 || note "mkfs.fat failed"
attach "$image"
populate
run_fsck fat32-clean-check /usr/sbin/fsck.fat -n
detach

# ── FAT32: damage offline, then check, repair, verify ──────────────────────
reserved="$(le16 "$image" 14)"
fat_offset=$((reserved * 512))
fsinfo_sector="$(le16 "$image" 48)"
# Dirty bit (offset 65), a wrong free-cluster count, and zeroed FAT entries
# for the first files: chains that were never written, as in the incident.
poke_byte "$image" 65 1
poke_zero "$image" $((fsinfo_sector * 512 + 488)) 4
poke_zero "$image" $((fat_offset + 4 * 8)) $((4 * 6))
cp "$image" "$DIR/fat32-damaged.img"
attach "$image"
run_fsck fat32-damaged-check /usr/sbin/fsck.fat -n
run_fsck fat32-damaged-check-again /usr/sbin/fsck.fat -n
run_fsck fat32-repair /usr/sbin/fsck.fat -a -v
sync
run_fsck fat32-verify-after-repair /usr/sbin/fsck.fat -n
run_fsck fat32-repair-again /usr/sbin/fsck.fat -a -v
mount -t vfat -o ro "$loop_dev" "$MNT" && {
    ls -la "$MNT" "$MNT/Images/GBA" >"$RESULTS/fat32-after-repair-listing.txt" 2>&1
    ls "$MNT" | grep -c '^FSCK' | sed 's/^/recovered FSCK files: /' | tee -a "$RESULTS/summary.txt"
    umount "$MNT"
}
detach

# ── FAT32: error-induced read-only flip on a mounted disposable image ─────
cp "$DIR/fat32-damaged.img" "$image"
attach "$image"
# Never clear the ring buffer: it may hold the evidence for a real card.
dmesg_before="$(dmesg | wc -l)"
if mount -t vfat -o rw,noatime,errors=remount-ro "$loop_dev" "$MNT"; then
    # A damaged mount can answer with EIO; keep each probe in a subshell so a
    # failed redirection cannot end the run.
    ( exec 9>>"$MNT/Saves/GBA/game-0.sav" 2>/dev/null && echo opened >"$RESULTS/flip-old-fd-open.txt"
      cat "$MNT"/Images/GBA/* >/dev/null 2>&1
      rm -f "$MNT"/Images/GBA/game-2.png "$MNT"/Images/GBA/game-3.png 2>/dev/null
      dd if=/dev/urandom of="$MNT/Images/GBA/new.png" bs=1024 count=512 2>/dev/null
      sync
      if printf 'x' >&9 2>"$RESULTS/flip-old-fd-write.txt"; then
          echo "write on a descriptor opened before the flip: succeeded" >>"$RESULTS/flip-old-fd-write.txt"
      fi ) 2>>"$RESULTS/flip-errors.txt"
    grep " $MNT " /proc/mounts >"$RESULTS/flip-proc-mounts.txt"
    grep " $MNT " /proc/self/mountinfo >>"$RESULTS/flip-proc-mounts.txt"
    ( : >"$MNT/after-flip.txt" ) 2>"$RESULTS/flip-new-file.txt" &&
        echo "new file after flip: created" >>"$RESULTS/flip-new-file.txt"
    dmesg | tail -n +$((dmesg_before + 1)) | grep -i 'fat-fs' >"$RESULTS/flip-dmesg.txt"
    note "flip: $(awk '{ split($4, o, ","); print o[1]; exit }' "$RESULTS/flip-proc-mounts.txt") after damaged-image writes"
    umount "$MNT"
fi
detach

# ── exFAT: independent qualification ───────────────────────────────────────
image="$DIR/exfat.img"
rm -f "$image"
dd if=/dev/zero of="$image" bs=1M count=64 2>/dev/null
if /usr/sbin/mkfs.exfat -n FIXTURE "$image" >/dev/null 2>&1; then
    attach "$image"
    run_fsck exfat-clean-check /usr/sbin/exfatfsck -n
    detach
    # Zero part of the allocation bitmap region to make the checker complain.
    cp "$image" "$DIR/exfat-damaged.img"
    poke_zero "$image" $((1024 * 1024 + 4096)) 4096
    attach "$image"
    run_fsck exfat-damaged-check /usr/sbin/exfatfsck -n
    run_fsck exfat-repair /usr/sbin/exfatfsck -p
    sync
    run_fsck exfat-verify-after-repair /usr/sbin/exfatfsck -n
    detach
else
    note "mkfs.exfat failed; exFAT not qualified"
fi

# ── Durable writes on internal storage with GNU sync operands ──────────────
probe="$DIR/sync-probe"
printf 'state=pending\n' >"$probe.tmp" && sync "$probe.tmp" && mv -f "$probe.tmp" "$probe" && sync "$DIR"
note "GNU sync file+directory operands: exit=$?"
timeout -k 1 1 sleep 5
note "timeout -k on a sleeping process: exit=$?"

rm -f "$DIR"/*.img
note "done"
DEVICE

"${ADB[@]}" shell "mkdir -p $REMOTE_DIR"
"${ADB[@]}" push "$device_script" "$REMOTE_DIR/run.sh" >/dev/null
"${ADB[@]}" shell "sh $REMOTE_DIR/run.sh" || echo "device run reported failure; pulling partial results" >&2
"${ADB[@]}" pull "$REMOTE_DIR/results" "$OUT_DIR" >/dev/null
echo "results: $OUT_DIR/results"
