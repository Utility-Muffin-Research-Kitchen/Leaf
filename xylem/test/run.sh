#!/bin/sh
# Runs the leaf-xylem-session handshake tests in containers. power-request is
# built from Jawaka's power_request.h (static, in gcc:14); suite.sh then runs
# in each of XYLEM_TEST_IMAGES. The default is busybox:1.36.1; a Green Genes
# rootfs image adds xylem's own BusyBox 1.37 (see the README).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
xylem="$(cd "$here/.." && pwd)"
jawaka="${JAWAKA_DIR:-$xylem/../../Jawaka}"
images="${XYLEM_TEST_IMAGES:-busybox:1.36.1}"
gcc_image="${XYLEM_TEST_GCC_IMAGE:-gcc:14}"
if [ ! -f "$jawaka/internal/platform/power_request.h" ]; then
    echo "run.sh: no Jawaka checkout at $jawaka (set JAWAKA_DIR)" >&2
    exit 2
fi
jawaka="$(cd "$jawaka" && pwd)"
out="$(mktemp -d "${TMPDIR:-/tmp}/leaf-xylem-test.XXXXXX")"
trap 'rm -rf "$out"' EXIT

docker run --rm --network none -v "$jawaka:/jawaka:ro" -v "$here:/test:ro" -v "$out:/out" \
    "$gcc_image" gcc -static -O2 -Wall -Werror -I/jawaka -o /out/power-request /test/power-request.c

status=0
for image in $images; do
    echo "== $image"
    docker run --rm --init --network none \
        -v "$xylem:/src/xylem:ro" -v "$out:/helper:ro" \
        -e SESSION=/src/xylem/leaf-xylem-session \
        -e FAKE=/src/xylem/test/fake-jawakad \
        -e POWER_REQUEST=/helper/power-request \
        "$image" /bin/sh /src/xylem/test/suite.sh || status=1
done
exit "$status"
