#!/bin/sh
# Handshake tests for leaf-xylem-session, run in a container by run.sh: the
# real session script against a fake jawakad that writes the power handoff
# with Jawaka's own power_request.h, a fake mount table, and stubbed sync,
# mount and busybox. Nothing here touches a real mount or the power state.
set -u
SESSION="${SESSION:?}"
FAKE="${FAKE:?}"
export POWER_REQUEST="${POWER_REQUEST:?}"
BASE="${TEST_BASE:-/tmp/leaf-xylem-test}"
rm -rf "$BASE"
mkdir -p "$BASE"
passed=0
failed=0
current=""

busybox 2>&1 | head -n 1

check() {
    desc="$1"
    shift
    if "$@"; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        echo "FAIL [$current] $desc"
    fi
}
has() { grep -q -- "$2" "$1" 2>/dev/null; }
lacks() { ! grep -q -- "$2" "$1" 2>/dev/null; }
same() { [ "$1" = "$2" ] || { printf '  got:  %s\n  want: %s\n' "$1" "$2" | tr '\n' '|'; echo; return 1; }; }
power_events() { grep -E '^(sync|mount|busybox)' "$fx/events" | sed 's/ *$//' | tr '\n' ';'; }
start_dir() { awk -v n="$1" '$1 == "start" && $2 == n { print $4 }' "$fx/events"; }
wait_for() {
    polls=0
    while ! grep -q -- "$2" "$1" 2>/dev/null; do
        [ "$polls" -lt $(($3 * 10)) ] || return 1
        sleep .1
        polls=$((polls + 1))
    done
}

# A fixture: the lab layout, a fake mount table (root and a vfat /boot are
# persistent), a fake uptime, and stubs that log to $fx/events. The barrier
# runs under env -i, so the stubs carry the fixture path themselves.
setup() {
    current="$1"
    fx="$BASE/$1"
    l="$fx/root/.system/leaf/platforms/mlp1/launcher"
    STATE="$fx/run/leaf-xylem"
    LOGF="$fx/root/.userdata/mlp1/logs/leaf-xylem-session.log"
    mkdir -p "$fx/run" "$fx/tmp" "$fx/stub" "$l/bin" "$l/lib" "$l/res/themes" "$l/res/assets"
    : >"$l/res/font.ttf"
    cp "$FAKE" "$l/bin/jawakad"
    printf '#!/bin/sh\nexit 0\n' >"$l/bin/jawaka-launcher"
    cp "$l/bin/jawaka-launcher" "$l/bin/jawaka-menu"
    chmod +x "$l/bin/jawakad" "$l/bin/jawaka-launcher" "$l/bin/jawaka-menu"
    printf '100.00 50.00\n' >"$fx/uptime"
    cat >"$fx/mountinfo" <<'EOF'
18 1 179:2 / / rw,relatime - ext4 /dev/root rw
19 18 0:5 / /dev rw,relatime - devtmpfs devtmpfs rw
21 18 0:20 / /run rw,nosuid,nodev - tmpfs tmpfs rw
22 18 0:21 / /tmp rw - tmpfs tmpfs rw
30 18 179:1 / /boot rw,relatime - vfat /dev/mmcblk1p1 rw
EOF
    : >"$fx/events"
    cat >"$fx/stub/common" <<'EOF'
fx=@FX@
alive() { s="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1; s="${s##*) }"; [ "${s%% *}" != Z ]; }
gone_check() {
    for p in $(cat "$fx/game.pid" "$fx/must-be-gone" 2>/dev/null); do
        ! alive "$p" || echo "ASSERT pid $p alive at $1" >>"$fx/events"
    done
}
EOF
    cat >"$fx/stub/sync" <<'EOF'
#!/bin/sh
. @FX@/stub/common
echo "sync $*" >>"$fx/events"
{
    echo "PATH=$PATH"
    echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}"
    echo "FIXTURE=${FIXTURE:-}"
    echo "cwd=$(pwd)"
    echo "parent=$(tr '\0' ' ' <"/proc/$PPID/cmdline")"
} >"$fx/barrier-env"
gone_check sync
EOF
    cat >"$fx/stub/mount" <<'EOF'
#!/bin/sh
. @FX@/stub/common
echo "mount $*" >>"$fx/events"
for point; do :; done
if [ "$(cat "$fx/busy-once" 2>/dev/null)" = "$point" ]; then
    rm -f "$fx/busy-once"
    echo "mount: $point: busy" >&2
    exit 1
fi
awk -v p="$point" '$5 == p { $6 = "ro"; $NF = "ro" } { print }' "$fx/mountinfo" >"$fx/mountinfo.new" &&
    mv "$fx/mountinfo.new" "$fx/mountinfo"
EOF
    cat >"$fx/stub/busybox" <<'EOF'
#!/bin/sh
. @FX@/stub/common
case "$1" in poweroff|reboot) ;; *) exec /bin/busybox "$@" ;; esac
echo "busybox $*" >>"$fx/events"
awk '$3 !~ /^0:/ && ($6 ~ /(^|,)rw(,|$)/ || $NF ~ /(^|,)rw(,|$)/) { bad = 1 } END { exit bad }' \
    "$fx/mountinfo" || echo "ASSERT writable mount at power" >>"$fx/events"
gone_check power
EOF
    sed -i "s|@FX@|$fx|g" "$fx/stub/common" "$fx/stub/sync" "$fx/stub/mount" "$fx/stub/busybox"
    chmod +x "$fx/stub/sync" "$fx/stub/mount" "$fx/stub/busybox"
    POWER_PATH_OVERRIDE=""
    POWER_STOP_OVERRIDE=""
    PROC_OVERRIDE=""
}

session() {
    env FIXTURE="$fx" TMPDIR="$fx/tmp" \
        LEAF_XYLEM_ROOT="$fx/root" LEAF_XYLEM_RUN_DIR="$fx/run" \
        LEAF_XYLEM_KMSG="$fx/kmsg" LEAF_XYLEM_UPTIME="$fx/uptime" \
        LEAF_XYLEM_MOUNTINFO="$fx/mountinfo" LEAF_XYLEM_PROC="${PROC_OVERRIDE:-/proc}" \
        LEAF_XYLEM_POWER_PATH="${POWER_PATH_OVERRIDE:-$fx/stub:/usr/sbin:/usr/bin:/sbin:/bin}" \
        LEAF_XYLEM_POWER_STOP="$POWER_STOP_OVERRIDE" \
        LEAF_XYLEM_COMPOSITOR_WAIT_S=0 LEAF_XYLEM_RESTART_DELAY_S=0 \
        LEAF_XYLEM_BARRIER_RETRY_S=1 \
        timeout 60 /bin/sh "$SESSION" "$@"
}

closed() { printf 'sync;mount -o remount,ro /boot;mount -o remount,ro /;sync;busybox %s -f;' "$1"; }

# ── A power-off: the whole handshake ────────────────────────────────────────
setup poweroff
echo poweroff >"$fx/plan"
session start
rc=$?
dir="$(start_dir 1)"
check "the session ends once the kernel call returns (a stub here)" [ "$rc" -eq 1 ]
check "sync, every persistent mount read-only (later mounts first), sync, power" \
    same "$(power_events)" "$(closed poweroff)"
check "the stubs saw nothing writable at power" lacks "$fx/events" ASSERT
check "the request directory is the session's, in the run dir" \
    same "${dir%.*}" "$fx/run/umrk-power"
check "ready holds 1 and a newline" same "$(od -An -c "$dir/ready" | tr -d ' ')" '1\n'
check "the request directory is mode 0700" same "$(stat -c %a "$dir")" 700
check "jawakad published poweroff" same "$(cat "$dir/request")" poweroff
check "jawakad published complete" [ -f "$dir/complete" ]
check "the request is kept" [ -f "$dir/reason" ]
check "SDCARD_PATH is the lab root" has "$fx/env.1" "^SDCARD_PATH=$fx/root\$"
check "both MLP1 slots" has "$fx/env.1" "^SDCARD_PATHS=$fx/root:/media/sdcard1\$"
check "PATH-2 version" has "$fx/env.1" "^UMRK_ENV_VERSION=2\$"
check "the launcher path" has "$fx/env.1" "^UMRK_LAUNCHER_PATH=$l\$"
check "control state under the lab root" has "$fx/env.1" "^UMRK_INTERNAL_DATA_PATH=$fx/root/.umrk/mlp1\$"
check "jawakad gets the request directory" has "$fx/env.1" "^UMRK_POWER_REQUEST_DIR=$dir\$"
check "Green Genes' Weston socket" has "$fx/env.1" '^WAYLAND_DISPLAY=wayland-1$'
check "the session's clean-exit sentinel" has "$fx/env.1" "^UMRK_CLEAN_EXIT_SENTINEL=$STATE/clean-exit\$"
check "the bundle's libraries" has "$fx/env.1" "^LD_LIBRARY_PATH=$l/lib"
check "jawakad starts in the bundle" same "$(cat "$fx/cwd.1")" "$l"
check "the barrier runs on the rootfs PATH" has "$fx/barrier-env" "^PATH=$fx/stub:/usr/sbin:/usr/bin:/sbin:/bin\$"
check "the barrier drops the bundle's libraries" has "$fx/barrier-env" '^LD_LIBRARY_PATH=$'
check "the barrier runs from /" has "$fx/barrier-env" '^cwd=/$'
check "the barrier is a fresh exec of the script" has "$fx/barrier-env" "^parent=/bin/sh $SESSION power-barrier poweroff \$"
check "with the session's environment cleared" has "$fx/barrier-env" '^FIXTURE=$'
check "the session log on the root says why" has "$LOGF" 'power: poweroff requested (reason=power-button, status=0)'
check "the tmpfs power log" has "$STATE/power.log" 'jawakad completed its shutdown'
check "the kernel log" has "$fx/kmsg" 'filesystems closed; poweroff'

# ── A clean restart, then a reboot ──────────────────────────────────────────
setup reboot
printf 'unavailable\nreboot\n' >"$fx/plan"
session start
rc=$?
check "the session ends once the kernel call returns" [ "$rc" -eq 1 ]
check "two generations" same "$(cat "$fx/starts")" 2
check "the first generation had the capability" has "$fx/events" 'capability offered'
check "each generation gets its own directory" [ "$(start_dir 1)" != "$(start_dir 2)" ]
check "the old generation's directory is gone" [ ! -e "$(start_dir 1)" ]
check "the reboot closes storage" same "$(power_events)" "$(closed reboot)"
check "the stubs saw nothing writable at power" lacks "$fx/events" ASSERT

# ── The crash guard ─────────────────────────────────────────────────────────
setup crash-guard
printf 'crash\ncrash\ncrash\npoweroff\n' >"$fx/plan"
session start
rc=$?
check "the guard stops the session with an error" [ "$rc" -eq 1 ]
check "three starts, no fourth" same "$(cat "$fx/starts")" 3
check "the guard says so" has "$LOGF" 'crash guard: 3 crashes in 120s; the session stops'
check "and in the kernel log" has "$fx/kmsg" 'crash guard tripped'
check "no power action" same "$(power_events)" ""
check "the session's pid file is gone" [ ! -e "$STATE/session.pid" ]

setup crash-spread
printf 'crash+61\ncrash+61\ncrash+61\ncrash+61\npoweroff\n' >"$fx/plan"
session start
check "crashes 61 s apart never trip the guard" lacks "$LOGF" 'crash guard'
check "five starts" same "$(cat "$fx/starts")" 5
check "then the power-off" same "$(power_events)" "$(closed poweroff)"

setup crash-reset
printf 'crash\ncrash\nclean\ncrash\ncrash\npoweroff\n' >"$fx/plan"
session start
check "a clean exit clears the count" lacks "$LOGF" 'crash guard'
check "six starts" same "$(cat "$fx/starts")" 6
check "then the power-off" same "$(power_events)" "$(closed poweroff)"

# ── jawakad could not prove a game stopped ──────────────────────────────────
setup game-left
echo game-left >"$fx/plan"
session start
check "the barrier waits for the recorded game" lacks "$fx/events" ASSERT
check "the pause reads the record" has "$STATE/power.log" 'did not complete its shutdown: reason=game-child'
check "it goes on once the game is gone" has "$STATE/power.log" 'every recorded item is gone; continuing'
check "then the power-off" same "$(power_events)" "$(closed poweroff)"

# ── jawakad died after its request: wait for the operator ───────────────────
setup request-crash
echo request-crash >"$fx/plan"
session start &
spid=$!
check "the pause names the override" wait_for "$STATE/power.log" 'no record to check' 10
sleep 1.5
check "no barrier without the override" same "$(power_events)" ""
: >"$STATE/power-override"
wait "$spid"
check "the override goes on" has "$STATE/power.log" 'override: continuing past an unverified stop'
check "then the reboot" same "$(power_events)" "$(closed reboot)"

# ── The root is busy once: log the writers, retry ───────────────────────────
setup busy-root
echo poweroff >"$fx/plan"
echo / >"$fx/busy-once"
p="$fx/proc/4242"
mkdir -p "$p/fdinfo" "$p/fd"
echo weston >"$p/comm"
printf 'pos:\t0\nflags:\t0100000\nmnt_id:\t18\n' >"$p/fdinfo/3"
ln -s /usr/share/weston/read-only.png "$p/fd/3"
printf 'pos:\t0\nflags:\t02100002\nmnt_id:\t18\n' >"$p/fdinfo/7"
ln -s /var/lib/gg/mesa-shader-cache/index "$p/fd/7"
printf 'pos:\t0\nflags:\t0100001\nmnt_id:\t21\n' >"$p/fdinfo/9"
ln -s /run/gg/weston.log "$p/fd/9"
cat >"$p/maps" <<'EOF'
ffff80000000-ffff80010000 r-xp 00000000 b3:02 1101 /usr/lib/libEGL.so.1.0.0
ffff90000000-ffff90001000 rw-s 00000000 b3:02 1234 /var/lib/gg/mesa-shader-cache/index
EOF
PROC_OVERRIDE="$fx/proc"
session start
check "the failure is named" has "$STATE/power.log" 'read-only remount failed: /$'
check "a write descriptor on the root is listed" \
    has "$STATE/power.log" 'writer: pid=4242 comm=weston fd /var/lib/gg/mesa-shader-cache/index'
check "a shared writable mapping on the root is listed" \
    has "$STATE/power.log" 'writer: pid=4242 comm=weston map /var/lib/gg/mesa-shader-cache/index'
check "a read-only descriptor is not" lacks "$STATE/power.log" 'read-only.png'
check "a tmpfs descriptor is not" lacks "$STATE/power.log" 'weston.log'
check "the retry closes storage" same "$(power_events)" \
    "sync;mount -o remount,ro /boot;mount -o remount,ro /;$(closed poweroff)"

# ── Processes stopped before the barrier ────────────────────────────────────
setup power-stop
echo poweroff >"$fx/plan"
printf '#!/bin/sh\nwhile :; do sleep 1; done\n' >"$fx/weston"
chmod +x "$fx/weston"
"$fx/weston" &
wpid=$!
echo "$wpid" >"$fx/must-be-gone"
POWER_STOP_OVERRIDE="weston"
session start
check "the listed process is stopped first" has "$STATE/power.log" "stopping weston: pids $wpid\$"
check "it was gone before the barrier" lacks "$fx/events" ASSERT
check "then the power-off" same "$(power_events)" "$(closed poweroff)"
kill "$wpid" 2>/dev/null
wait "$wpid" 2>/dev/null

# ── stop and status ─────────────────────────────────────────────────────────
setup stop
echo wait-term >"$fx/plan"
session start &
spid=$!
check "jawakad runs" wait_for "$fx/events" '^start 1 wait-term' 10
polls=0
while [ ! -e "$fx/running" ] && [ "$polls" -lt 100 ]; do sleep .1; polls=$((polls + 1)); done
session status >"$fx/status.out"
check "status names the session" has "$fx/status.out" '^session: pid [0-9]'
check "status names jawakad" has "$fx/status.out" '^jawakad: pid [0-9]'
session stop >"$fx/stop.out"
check "stop succeeds" [ $? -eq 0 ]
wait "$spid"
rc=$?
check "the session ends cleanly" [ "$rc" -eq 0 ]
check "jawakad got TERM" has "$fx/events" '^term$'
check "no power action" same "$(power_events)" ""
check "the generation's directory is gone" [ ! -e "$(start_dir 1)" ]
check "the session says it stopped" has "$LOGF" 'session stopped'

# ── No barrier tools: no capability; exit to stock ends the session ─────────
setup no-capability
printf 'unavailable\nexit-to-stock\n' >"$fx/plan"
POWER_PATH_OVERRIDE="$fx/no-tools"
session start
rc=$?
check "the session ends cleanly" [ "$rc" -eq 0 ]
check "Jawaka sees no capability" has "$fx/events" 'capability refused'
check "the session log says why" has "$LOGF" 'power requests are refused'
check "exit to stock stops the session" has "$LOGF" 'xylem has no stock UI, so the session stops'

echo "leaf-xylem-session: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
