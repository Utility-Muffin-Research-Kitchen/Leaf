#!/usr/bin/env python3
"""Read release identity back out of a built ZIP and check it against the tag.

Every other identity check in this repo runs on the INPUTS, before the build.
This one reads the artifact after the fact, which is the only way to catch an
environment variable that was never set: an unset LEAF_RELEASE_CHANNEL does not
fail anything, it quietly defaults to "dev" and ships.

That is not hypothetical. Five hand-run betas produced five different metadata
shapes -- one with channel "stable", two whose version could not tell beta.1
from beta.2 -- because release_id is the only field with visible consequences
when it is wrong, so the rest degraded unnoticed for weeks.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import zipfile


COMPONENTS_GLOB = ".system/leaf/releases/*/provenance/components.json"


def load_release_block(zip_path: str) -> dict[str, object]:
    with zipfile.ZipFile(zip_path) as zf:
        matches = [n for n in zf.namelist() if fnmatch.fnmatch(n, COMPONENTS_GLOB)]
        if not matches:
            raise SystemExit(f"{zip_path}: no {COMPONENTS_GLOB} inside the ZIP")
        if len(matches) > 1:
            raise SystemExit(
                f"{zip_path}: {len(matches)} provenance files, expected 1:\n  "
                + "\n  ".join(sorted(matches))
            )
        payload = json.loads(zf.read(matches[0]))
    release = payload.get("release")
    if not isinstance(release, dict):
        raise SystemExit(f"{zip_path}: provenance has no 'release' object")
    return release


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zip", help="built SD release ZIP")
    ap.add_argument("--tag", required=True, help="the release tag, e.g. v0.8.0-beta.3")
    ap.add_argument("--channel", required=True, choices=("dev", "beta", "stable"))
    args = ap.parse_args()

    tag = args.tag
    # The one asymmetry worth stating outright: version drops the leading "v",
    # the other three keep it. Getting this backwards is silent and cosmetic,
    # which is exactly why it went wrong repeatedly.
    expected = {
        "channel": args.channel,
        "version": tag[1:] if tag.startswith("v") else tag,
        "tag": tag,
        "release_id": tag,
    }

    release = load_release_block(args.zip)
    bad = {k: (v, release.get(k)) for k, v in expected.items() if release.get(k) != v}

    for key in ("channel", "version", "tag", "release_id"):
        got = release.get(key)
        mark = "  " if key not in bad else "->"
        print(f"{mark} {key:<11} {got!r}")

    if bad:
        print(f"\n{args.zip}: release identity does not match {tag}", file=sys.stderr)
        for key, (want, got) in bad.items():
            print(f"  {key}: expected {want!r}, got {got!r}", file=sys.stderr)
        print(
            "\nThese come from RELEASE_ID / LEAF_RELEASE_CHANNEL / "
            "LEAF_RELEASE_VERSION / LEAF_RELEASE_TAG.\n"
            "Set them as environment variables BEFORE make, not as make "
            "variables -- release-zips only forwards RELEASE_ID explicitly.",
            file=sys.stderr,
        )
        return 1

    print(f"\nrelease identity OK for {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
