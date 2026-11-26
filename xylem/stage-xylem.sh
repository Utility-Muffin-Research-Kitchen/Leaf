#!/bin/sh
# stage-xylem.sh: build Leaf's launcher payload for xylem (OS=xylem) and copy
# it to the card of a unit over SSH, where the OS starts it.
#
#   xylem/stage-xylem.sh [--no-build] [--no-wait] [--assemble-only] [HOST]
#
# HOST defaults to 10.61.0.1, Green Genes' MLP1 over the USB cable. The SSH
# key is LEAF_XYLEM_SSH_KEY, else GG_SSH_KEY, else ssh's own choice; there is
# no host-key pinning (xylem makes a new host key every boot, and the link is
# the cable).
#
# The payload is the launcher alone, in Leaf's card layout under the card's
# games partition (/mnt/sdcard), no games or emulators:
#
#   .system/leaf/platforms/mlp1/launcher/leaf-xylem-session   the entry point
#   .system/leaf/platforms/mlp1/launcher/bin/     jawakad and the other nine
#   .system/leaf/platforms/mlp1/launcher/res/     themes, icons, sounds, certs,
#                                                 fonts, Catastrophe's assets
#   .system/leaf/platforms/mlp1/                  the switcher's device/mlp1
#                                                 defaults (no boot animation),
#                                                 compiled i18n, platform.d
#   Themes/                                       the bundled user themes
#   Roms/ Images/ ... (empty)                     the public folders
#
# No launcher/lib: the image has the libraries (SDL2_ttf, SDL2_image,
# libcurl over OpenSSL 3, SQLite with FTS5). The script checks the unit for
# them first and stops if one is missing.
#
# On the unit it stops Leaf (/etc/init.d/leaf stop, Green Genes' boot hook),
# replaces the launcher and the platform files it stages (never .userdata,
# .umrk or anything else on the card), then lets the hook start it again and
# waits for the launcher to come up (--no-wait: doesn't wait). On an image
# without the hook it says how to start the session by hand.
#
# Builds with the sibling checkouts (JAWAKA_DIR, CATASTROPHE_DIR,
# LAUNCHER_SWITCHER_DIR; by default next to this repo, or under
# LEAF_WORKSPACE_DIR), Jawaka and Catastrophe on their xylem branches, in
# the MLP1 toolchain image (TOOLCHAIN_IMAGE). The payload is assembled in
# build/stage/mlp1-xylem/package.
set -eu

build=1
wait=1
send=1
host=
while [ $# -gt 0 ]; do
	case $1 in
	--no-build) build=0 ;;
	--no-wait) wait=0 ;;
	--assemble-only) send=0 ;;
	-h|--help) sed -n '2,/^set -eu/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 0 ;;
	-*) echo "stage-xylem: unknown option $1" >&2; exit 2 ;;
	*) host=$1 ;;
	esac
	shift
done
host=${host:-${LEAF_XYLEM_HOST:-10.61.0.1}}

leaf=$(cd "$(dirname "$0")/.." && pwd)
workspace=${LEAF_WORKSPACE_DIR:-$(cd "$leaf/.." && pwd)}
JAWAKA_DIR=${JAWAKA_DIR:-$workspace/Jawaka}
CATASTROPHE_DIR=${CATASTROPHE_DIR:-$workspace/Catastrophe}
LAUNCHER_SWITCHER_DIR=${LAUNCHER_SWITCHER_DIR:-$workspace/miniloong-launcher-switcher}
TOOLCHAIN_IMAGE=${TOOLCHAIN_IMAGE:-ghcr.io/utility-muffin-research-kitchen/mlp1-toolchain:local}
PLATFORM=mlp1
CARD=/mnt/sdcard
# A Jawaka build with OS=xylem goes to its own folder
JAWAKA_BUILD_DIR=${JAWAKA_XYLEM_BUILD_DIR:-$JAWAKA_DIR/build/mlp1-xylem}
OVERLAY=$LAUNCHER_SWITCHER_DIR/device/$PLATFORM

out=$leaf/build/stage/mlp1-xylem
pkg=$out/package
platform_dir=$pkg/.system/leaf/platforms/$PLATFORM
launcher=$platform_dir/launcher
BINS="jawakad jawaka-launcher jawaka-menu jawaka-osd jawaka-platformctl jawaka-inhibitctl jawaka-retroarchctl jawaka-retroarch-runner jawaka-update-runner jawaka-ledd"
PUBLIC_DIRS="Roms Images Videos Apps BIOS Saves States Cheats Themes"
# What the image must have instead of launcher/lib
LIBS="libSDL2-2.0.so.0 libSDL2_ttf-2.0.so.0 libSDL2_image-2.0.so.0 libcurl.so.4 libssl.so.3 libcrypto.so.3 libsqlite3.so.0 libwayland-client.so.0"

say() { echo "stage-xylem: $*"; }
die() { echo "stage-xylem: $*" >&2; exit 1; }

for d in "$JAWAKA_DIR" "$CATASTROPHE_DIR" "$OVERLAY"; do
	[ -d "$d" ] || die "no checkout at $d (set JAWAKA_DIR, CATASTROPHE_DIR, LAUNCHER_SWITCHER_DIR)"
done
grep -q 'JW_OS_XYLEM' "$JAWAKA_DIR/Makefile" || die "$JAWAKA_DIR has no OS=xylem build: use Jawaka's xylem branch"

ssh_() {
	key=${LEAF_XYLEM_SSH_KEY:-${GG_SSH_KEY:-}}
	set -- -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no \
		-o LogLevel=ERROR -o BatchMode=yes -o ConnectTimeout=5 \
		-o ServerAliveInterval=5 -o ServerAliveCountMax=3 root@"$host" "$@"
	if [ -n "$key" ]; then
		ssh -i "$key" -o IdentitiesOnly=yes "$@"
	else
		ssh "$@"
	fi
}

# ── The unit first: reachable, the card mounted, the libraries there ────────
if [ "$send" = 1 ]; then
	say "checking $host"
	missing=$(ssh_ "mountpoint -q $CARD || echo card; for l in $LIBS; do [ -e /usr/lib/\$l ] || [ -e /lib/\$l ] || echo \$l; done; grep -q fts5 /usr/lib/libsqlite3.so.0 2>/dev/null || echo fts5") ||
		die "can't reach $host over SSH"
	case $missing in
	"") ;;
	card*) die "$host has nothing mounted at $CARD (xylem's games partition)" ;;
	*) die "$host's image lacks $(echo $missing | tr '\n' ' '): flash a newer image" ;;
	esac
fi

# ── Build ───────────────────────────────────────────────────────────────────
if [ "$build" = 1 ]; then
	say "building Jawaka (OS=xylem) in $JAWAKA_DIR"
	make -C "$JAWAKA_DIR" mlp1 OS=xylem \
		WORKSPACE_ROOT="$workspace" \
		CATASTROPHE_DIR="$CATASTROPHE_DIR" \
		MLP1_TOOLCHAIN_IMAGE="$TOOLCHAIN_IMAGE"
	make -C "$CATASTROPHE_DIR" assets
fi
for b in $BINS; do
	[ -f "$JAWAKA_BUILD_DIR/bin/$b" ] || die "missing $JAWAKA_BUILD_DIR/bin/$b (build without --no-build)"
done
for s in 1 2 3 4; do
	[ -f "$CATASTROPHE_DIR/res/assets/assets@${s}x.png" ] || die "missing Catastrophe's generated assets (make -C $CATASTROPHE_DIR assets)"
done

# ── Assemble ────────────────────────────────────────────────────────────────
say "assembling $pkg"
rm -rf "$pkg"
mkdir -p "$launcher/bin" "$launcher/res"
for b in $BINS; do
	cp -f "$JAWAKA_BUILD_DIR/bin/$b" "$launcher/bin/$b"
done
chmod 755 "$launcher/bin/"*
[ ! -f "$JAWAKA_BUILD_DIR/build-manifest.json" ] || cp -f "$JAWAKA_BUILD_DIR/build-manifest.json" "$launcher/"
for r in themes system_icons ui grid_wordmarks sounds; do
	[ ! -d "$JAWAKA_DIR/res/$r" ] || cp -Rf "$JAWAKA_DIR/res/$r" "$launcher/res/"
done
if [ -f "$JAWAKA_DIR/res/certs/cacert.pem" ]; then
	mkdir -p "$launcher/res/certs"
	cp -f "$JAWAKA_DIR/res/certs/cacert.pem" "$launcher/res/certs/"
fi
cp -Rf "$CATASTROPHE_DIR/res/fonts" "$launcher/res/"
cp -f "$CATASTROPHE_DIR/res/font.ttf" "$launcher/res/font.ttf"
cp -Rf "$CATASTROPHE_DIR/res/assets" "$launcher/res/assets"
# The platform's defaults, as stock's payload has them, without the boot
# animation, which nothing on xylem plays
(cd "$OVERLAY" && find . -path ./boot-animation -prune -o -type f -print) | while read -r f; do
	mkdir -p "$platform_dir/$(dirname "$f")"
	cp -f "$OVERLAY/$f" "$platform_dir/$f"
done
rm -f "$platform_dir/platform.d/02-boot-animation.sh"
[ -f "$platform_dir/defaults/systems.json" ] && [ -f "$platform_dir/defaults/cores.json" ] ||
	die "missing $OVERLAY/defaults/systems.json or cores.json"
# Compiled UI translations, as stage/mlp1.mk does: a table with no reviewed
# entries isn't shipped
mkdir -p "$platform_dir/i18n"
for po in "$JAWAKA_DIR"/i18n/*.po; do
	[ -f "$po" ] || continue
	code=$(basename "$po" .po)
	python3 "$JAWAKA_DIR/tools/i18n-compile.py" "$po" -o "$platform_dir/i18n/$code.jwi" > /dev/null
	[ "$(wc -c < "$platform_dir/i18n/$code.jwi")" -gt 25 ] || rm -f "$platform_dir/i18n/$code.jwi"
done
mkdir -p "$platform_dir/platform.d"
if [ -d "$JAWAKA_DIR/platform/$PLATFORM/platform.d" ]; then
	cp -Rf "$JAWAKA_DIR/platform/$PLATFORM/platform.d/." "$platform_dir/platform.d/"
fi
find "$platform_dir/platform.d" -type f -exec chmod 755 {} +
for d in $PUBLIC_DIRS; do mkdir -p "$pkg/$d"; done
[ ! -d "$JAWAKA_DIR/res/user_themes" ] || cp -Rf "$JAWAKA_DIR/res/user_themes/." "$pkg/Themes/"
cp -f "$leaf/xylem/leaf-xylem-session" "$launcher/leaf-xylem-session"
chmod 755 "$launcher/leaf-xylem-session"
{
	echo "Leaf's launcher for xylem ($PLATFORM), staged $(date -u +%Y-%m-%dT%H:%MZ)"
	echo "leaf $(git -C "$leaf" rev-parse --short HEAD 2>/dev/null || echo unknown)"
	echo "jawaka $(git -C "$JAWAKA_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
	echo "catastrophe $(git -C "$CATASTROPHE_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
} > "$launcher/README.txt"
size=$(du -sk "$pkg" | cut -f1)
files=$(find "$pkg" -type f | wc -l | tr -d ' ')
say "payload: $files files, $((size / 1024)) MiB"
[ "$send" = 1 ] || exit 0

# ── Send ────────────────────────────────────────────────────────────────────
# Leaf stopped first: its binaries and this session run from the card, and
# a file replaced under a running one would keep the card from closing at
# power-off. The hook holds it stopped until `leaf start`.
hook=$(ssh_ '[ -x /etc/init.d/leaf ] && echo yes || echo no')
rel=.system/leaf/platforms/$PLATFORM
if [ "$hook" = yes ]; then
	say "stopping Leaf on $host"
	ssh_ /etc/init.d/leaf stop
else
	ssh_ "[ ! -f $CARD/$rel/launcher/leaf-xylem-session ] || sh $CARD/$rel/launcher/leaf-xylem-session stop" || true
fi
# Replaced: the launcher and what this stages into the platform folder. The
# rest of the card (saves, the library, user themes) stays as it is.
stale="$rel/launcher"
for f in "$platform_dir"/*; do stale="$stale $rel/${f##*/}"; done
say "copying to $host:$CARD"
t0=$(date +%s)
# Owned by root, as everything on the card is (exFAT keeps no owners), and
# without macOS's ._ files
COPYFILE_DISABLE=1 tar -C "$pkg" --uid 0 --gid 0 -cf - . |
	ssh_ "cd $CARD && rm -rf $stale && tar -xof - && sync"
say "copied in $(($(date +%s) - t0)) s"
if [ "$hook" != yes ]; then
	say "this image has no Leaf boot hook; start the session by hand:"
	say "  setsid sh $CARD/$rel/launcher/leaf-xylem-session </dev/null >/dev/null 2>&1 &"
	exit 0
fi
ssh_ /etc/init.d/leaf start > /dev/null
[ "$wait" = 1 ] || { say "Leaf starts within a few seconds"; exit 0; }
say "waiting for the launcher"
i=0
while [ $i -lt 60 ]; do
	if ssh_ '/etc/init.d/leaf status' 2> /dev/null | grep -q 'launcher up'; then
		say "the launcher is up"
		exit 0
	fi
	sleep 1
	i=$((i + 1))
done
die "no launcher after 60 s: see /etc/init.d/leaf status and $CARD/.userdata/$PLATFORM/logs on $host"
