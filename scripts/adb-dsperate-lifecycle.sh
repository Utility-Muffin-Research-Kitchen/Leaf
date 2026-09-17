#!/usr/bin/env bash
# DSperate MLP1 Pak Rat install/lifecycle harness.
#
# Drives the real store code on the device over adb, using Jawaka's
# `jawaka-pakrat-smoke` helper (the same jw_pakrat_* code jawakad runs) against
# a local Pak Rat feed served from this host:
#
#   install -> reinstall -> picker choice -> catalog invalidation -> uninstall
#   -> recovery, with retained userdata/saves and release-payload checks.
#
#   CONFIRM_DS_LIFECYCLE=1 scripts/adb-dsperate-lifecycle.sh
#
# It changes the device's Pak Rat catalog URL and its DSperate install. The
# script restores the catalog URL and (by default) leaves DSperate installed
# from the feed. Set DS_FINAL_STATE=uninstalled to end with it removed, or
# DS_FINAL_STATE=manual to restore any manually staged pak instead.
#
# Env:
#   CONFIRM_DS_LIFECYCLE  must be 1 (this mutates a live card)
#   ADB_SERIAL            device serial (default: first online device)
#   DS_PAK_DIR            DSperate-pak checkout (default: sibling repo)
#   DS_ACCEPT_OUT         evidence dir (default: Leaf/build/dsperate-lifecycle)
#   DS_SKIP_BUILD         1 to skip `make -C Jawaka mlp1-pakrat-smoke`
#   DS_SMOKE_BIN          prebuilt jawaka-pakrat-smoke to push
#   DS_PORT               host feed port (default 8765)
#   DS_FEED_DIR           feed output (default Leaf/build/pakrat-local/dsperate-lifecycle)
#   DS_FINAL_STATE        installed (default) | uninstalled | manual
set -euo pipefail

: "${CONFIRM_DS_LIFECYCLE:?set CONFIRM_DS_LIFECYCLE=1 to run this against a live card}"
[ "$CONFIRM_DS_LIFECYCLE" = 1 ] || { echo "refusing: CONFIRM_DS_LIFECYCLE must be 1" >&2; exit 2; }

LEAF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${LEAF_WORKSPACE_DIR:-$(cd "$LEAF/.." && pwd)}"
PAK_REPO="${DS_PAK_DIR:-$WORKSPACE/DSperate-pak}"
JAWAKA="$WORKSPACE/Jawaka"
OUT="${DS_ACCEPT_OUT:-$LEAF/build/dsperate-lifecycle}"
PORT="${DS_PORT:-8765}"
FEED_DIR="${DS_FEED_DIR:-$LEAF/build/pakrat-local/dsperate-lifecycle}"
FINAL_STATE="${DS_FINAL_STATE:-installed}"
STORE_ID="org.umrk.dsperate"
STORE_VERSION="2.0.0"
FEED_ZIP="$PAK_REPO/build/dist/DSperate.mlp1.pak.zip"

log() { printf 'lifecycle: %s\n' "$*" >&2; }
fail() { log "FAIL: $*"; exit 1; }
pass() { printf 'ok   %s\n' "$*"; }

[ -f "$PAK_REPO/pakrat.json" ] || fail "missing DSperate-pak at $PAK_REPO (set DS_PAK_DIR)"

mkdir -p "$OUT"
# Everything below is mirrored to the evidence log while still reaching the
# terminal. This is a whole-script redirect, so steps run in this shell and the
# cleanup trap still sees the variables they set.
exec > >(tee "$OUT/run.log") 2>&1

# --- device ------------------------------------------------------------------
if [ -n "${ADB_SERIAL:-}" ]; then
    SERIAL="$ADB_SERIAL"
else
    SERIAL="$(adb devices | awk 'NR>1 && $2=="device"{print $1; exit}')"
    [ -n "${SERIAL:-}" ] || fail "no online adb device"
fi
ADB=(adb -s "$SERIAL")
"${ADB[@]}" shell 'getprop ro.board.platform >/dev/null 2>&1; mountpoint -q /mnt/sdcard' \
    || fail "device $SERIAL does not look like an MLP1"
log "device $SERIAL"

SD="$(PLATFORM_ID=mlp1 REMOTE_SDCARD_PATH=auto ADB_SERIAL="$SERIAL" \
        "$LEAF/scripts/adb-resolve-umrk-sd.sh")"
[ -n "$SD" ] || fail "could not resolve the active card"
STATE_DIR="$SD/.umrk/mlp1"
DB="$STATE_DIR/library.db"
CURRENT="$STATE_DIR/catalog/current"
DEV_CATALOG="$STATE_DIR/store/dev-catalog-url"
PAK_DIR="$SD/Apps/mlp1/DSperate.pak"
USERDATA="$SD/.userdata/mlp1/dsperate"
SAVES="$SD/Saves/DSperate"
STATES="$SD/States/DSperate"
LIBS="$SD/.system/leaf/platforms/mlp1/launcher/lib"
log "active card $SD"

rsh() { "${ADB[@]}" shell "$@"; }

# --- runtime library path for the pushed helper ------------------------------
[ "$(rsh "test -d '$LIBS' && echo yes")" = yes ] && RLIBS="$LIBS:/lib:/usr/lib" || RLIBS="/lib:/usr/lib"
SMOKE() { rsh "PLATFORM=mlp1 SDCARD_PATH='$SD' UMRK_INTERNAL_DATA_PATH='$STATE_DIR' \
    UMRK_PLATFORM_PATH='$SD/.system/leaf/platforms/mlp1' \
    JAWAKA_SOCKET_PATH='$UMRK_SOCKET' LD_LIBRARY_PATH='$RLIBS' /tmp/jawaka-pakrat-smoke $*"; }

UMRK_SOCKET="$(rsh 'ls -d /tmp/jawaka-runtime/jawakad.sock 2>/dev/null || true')"
[ -n "$UMRK_SOCKET" ] || UMRK_SOCKET="/tmp/jawaka-runtime/jawakad.sock"

# --- feed --------------------------------------------------------------------
command -v python3 >/dev/null || fail "python3 required"
make_feed() {
    [ -f "$FEED_ZIP" ] || (cd "$PAK_REPO" && make dist-pakrat >/dev/null)
    rm -rf "$FEED_DIR"
    (cd "$LEAF" && python3 scripts/pakrat-local-feed.py \
        --app-dir "$PAK_REPO" \
        --artifact "$STORE_ID=$FEED_ZIP" \
        --skip-build --output "$FEED_DIR" >/dev/null)
}

SERVER_PID=""
SHOT=0
PRIOR_CATALOG=""
MANUAL_BAK=""
cleanup() {
    local status=$?
    set +e
    if [ "$SHOT" = 1 ] && [ -n "$PRIOR_CATALOG" ]; then
        rsh "printf '%s\n' '$PRIOR_CATALOG' > '$DEV_CATALOG'" >/dev/null 2>&1
    elif [ "$SHOT" = 1 ]; then
        rsh "rm -f '$DEV_CATALOG'" >/dev/null 2>&1
    fi
    if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1; wait "$SERVER_PID" >/dev/null 2>&1; fi
    "${ADB[@]}" reverse --remove "tcp:$PORT" >/dev/null 2>&1
    rsh "rm -f /tmp/jawaka-pakrat-smoke /tmp/series-lifecycle-*.txt" >/dev/null 2>&1
    if [ "$status" -ne 0 ] && [ -n "$MANUAL_BAK" ]; then
        rsh "rm -rf '$PAK_DIR'; mv '$MANUAL_BAK' '$PAK_DIR'" >/dev/null 2>&1
    fi
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

make_feed
log "serving $FEED_DIR on port $PORT"
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$FEED_DIR" >"$OUT/feed.log" 2>&1 &
SERVER_PID=$!
"${ADB[@]}" reverse "tcp:$PORT" "tcp:$PORT" >/dev/null
PRIOR_CATALOG="$(rsh "cat '$DEV_CATALOG' 2>/dev/null | tr -d '\r'")"
rsh "mkdir -p '$STATE_DIR/store'" >/dev/null
SHOT=1
rsh "printf '%s\n' 'http://127.0.0.1:$PORT/pakrat/v1/' > '$DEV_CATALOG'"
# Reachability from the device, through the reverse tunnel.
rsh "wget -q -O /tmp/storefront.json 'http://127.0.0.1:$PORT/pakrat/v1/storefront.json'" \
    || fail "device cannot reach the feed"
pass "feed reachable from device"

# --- smoke helper ------------------------------------------------------------
if [ -n "${DS_SMOKE_BIN:-}" ]; then
    SMOKE_BIN="$DS_SMOKE_BIN"
elif [ "${DS_SKIP_BUILD:-0}" = 1 ]; then
    SMOKE_BIN="$JAWAKA/build/mlp1/bin/jawaka-pakrat-smoke"
else
    make -C "$JAWAKA" mlp1-pakrat-smoke >"$OUT/build.log" 2>&1
    SMOKE_BIN="$JAWAKA/build/mlp1/bin/jawaka-pakrat-smoke"
fi
[ -x "$SMOKE_BIN" ] || fail "missing jawaka-pakrat-smoke at $SMOKE_BIN"
"${ADB[@]}" push "$SMOKE_BIN" /tmp/jawaka-pakrat-smoke >/dev/null
rsh "chmod 755 /tmp/jawaka-pakrat-smoke"
pass "pushed smoke helper ($SMOKE_BIN)"

# --- helpers -----------------------------------------------------------------
games_count() { SMOKE rescan 2>/dev/null | sed -n 's/^rescan: games=\([0-9]*\).*/\1/p' | tail -1 || true; }
catalog_gen() { rsh "cat '$CURRENT' 2>/dev/null | tr -d '\r'" || true; }
catalog_has() {  # catalog_has <core-id>
    local gen; gen="$(catalog_gen)"
    [ -n "$gen" ] || return 1
    rsh "grep -q '\"$1\"' '$STATE_DIR/catalog/$gen/cores.json' 2>/dev/null"
}
ownership_row() { rsh "sqlite3 '$DB' \"select version from pakrat_installs where store_id='$STORE_ID';\"" 2>/dev/null | tr -d '\r' || true; }

echo "device=$SERIAL card=$SD"
echo "=== baseline ==="
BASE_GAMES="$(games_count)"; echo "games=$BASE_GAMES"
BASE_GEN="$(catalog_gen)"; echo "catalog=$BASE_GEN"
echo "dsperate pak dir: $(rsh "test -d '$PAK_DIR' && echo present || echo absent")"
echo "userdata: $(rsh "test -d '$USERDATA' && echo present || echo absent")"
echo "saves: $(rsh "test -d '$SAVES' && echo present || echo absent")"
echo "--- list ---"; SMOKE list || true

# --- 1. install --------------------------------------------------------------
echo "=== install ==="
if [ "$(rsh "test -d '$PAK_DIR' && echo present || echo absent")" = present ]; then
    MANUAL_BAK="/tmp/ds-manual-pak.$$"
    rsh "rm -rf '$MANUAL_BAK'; mv '$PAK_DIR' '$MANUAL_BAK'"
    log "moved a manually staged pak aside to $MANUAL_BAK"
fi
SMOKE install "$STORE_ID" | tee -a "$OUT/install.txt"
[ "$(ownership_row)" = "$STORE_VERSION" ] || fail "ownership row not at $STORE_VERSION"
rsh "test -x '$PAK_DIR/scripts/run.sh'" || fail "installed wrapper missing"
rsh "test ! -e '$PAK_DIR/launch.sh'" || fail "content pak must not have launch.sh"
catalog_has dsperate || fail "catalog did not gain the dsperate core"
pass "install: core in catalog, no Apps entry"

# --- 2. reinstall (same version) --------------------------------------------
echo "=== reinstall ==="
SMOKE install "$STORE_ID" | tee -a "$OUT/reinstall.txt"
[ "$(ownership_row)" = "$STORE_VERSION" ] || fail "reinstall changed the ownership row"
catalog_has dsperate || fail "reinstall lost the core"
pass "reinstall idempotent"

# --- 3. picker persistence ---------------------------------------------------
echo "=== picker persistence ==="
rsh "sqlite3 '$DB' \"insert into system_settings(system,key,value,updated_at) values('NDS','core_id','dsperate',strftime('%s','now')) on conflict(system,key) do update set value='dsperate',updated_at=strftime('%s','now');\""
SMOKE rescan >/dev/null 2>&1 || true
[ "$(rsh "sqlite3 '$DB' \"select value from system_settings where system='NDS' and key='core_id';\"")" = dsperate ] || fail "saved NDS choice was not retained"
catalog_has dsperate || fail "core vanished after rescan"
pass "per-system choice retained across rescan"

# --- 4. uninstall + invalidation --------------------------------------------
echo "=== uninstall ==="
SMOKE uninstall "$STORE_ID" | tee -a "$OUT/uninstall.txt"
rsh "test ! -d '$PAK_DIR'" || fail "pak directory survived uninstall"
[ -z "$(ownership_row)" ] || fail "ownership row survived uninstall"
if catalog_has dsperate; then fail "catalog still advertises dsperate after uninstall"; fi
rsh "test -d '$USERDATA'" || fail "uninstall removed userdata"
rsh "test -d '$SAVES'" || fail "uninstall removed saves"
rsh "test -d '$STATES'" || fail "uninstall removed states"
AFTER_GAMES="$(games_count)"
[ "$AFTER_GAMES" = "$BASE_GAMES" ] || log "note: games $BASE_GAMES -> $AFTER_GAMES"
pass "uninstall retracted pak/ownership/core; user data retained"

# --- 5. recovery -------------------------------------------------------------
# The saved choice is still 'dsperate' and no longer exists; the launcher must
# fall back. The NDS entry in the effective systems catalog names the target.
SYSJSON="$STATE_DIR/catalog/$(catalog_gen)/systems.json"
DEFAULT_CORE="$(rsh "grep -o '\"default_core\":\"[^\"]*\"[^}]*\"id\":\"NDS\"' '$SYSJSON' | head -1 | sed 's/.*\"default_core\":\"\([^\"]*\)\".*/\1/'")"
[ -n "$DEFAULT_CORE" ] || fail "could not read the NDS default core"
[ "$DEFAULT_CORE" = drastic ] || fail "unexpected NDS default after uninstall: $DEFAULT_CORE"
[ "$(rsh "sqlite3 '$DB' \"select value from system_settings where system='NDS' and key='core_id';\"")" = dsperate ] \
    || fail "the saved dsperate choice was cleared instead of falling back"
pass "recovery: saved dsperate choice invalid, NDS default is $DEFAULT_CORE"

# --- 6. final state ----------------------------------------------------------
case "$FINAL_STATE" in
    installed)
        SMOKE install "$STORE_ID" | tee -a "$OUT/final-install.txt"
        catalog_has dsperate || fail "final reinstall did not restore the core"
        if [ -n "$MANUAL_BAK" ]; then rsh "rm -rf '$MANUAL_BAK'"; MANUAL_BAK=""; fi
        pass "final state: installed from feed"
        ;;
    manual)
        SMOKE uninstall "$STORE_ID" >/dev/null 2>&1 || true
        if [ -n "$MANUAL_BAK" ]; then
            rsh "rm -rf '$PAK_DIR'; mv '$MANUAL_BAK' '$PAK_DIR'"
            MANUAL_BAK=""
        fi
        SMOKE rescan >/dev/null 2>&1 || true
        pass "final state: manual pak restored"
        ;;
    uninstalled)
        # The manual pak is the same feed build; reinstalling from the store
        # replaces it. Drop the aside copy rather than restoring by hand.
        if [ -n "$MANUAL_BAK" ]; then rsh "rm -rf '$MANUAL_BAK'"; MANUAL_BAK=""; fi
        pass "final state: uninstalled"
        ;;
    *) fail "unknown DS_FINAL_STATE=$FINAL_STATE" ;;
esac
echo "=== done ==="

log "evidence: $OUT/run.log"
