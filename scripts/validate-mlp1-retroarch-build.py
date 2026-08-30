#!/usr/bin/env python3
"""Decide whether an existing MLP1 RetroArch build can be reused.

The build manifest records which patch set produced the binary. Reusing a binary
whose manifest does not match the patch set the caller wants is how a release or
a device ends up silently missing a patch it depends on, so every path that
copies, stages or packages the MLP1 RetroArch binary asks this one question:

    zero     - the artifact matches the requested patch set and may be reused
    non-zero - it is missing, stale or unverifiable; rebuild or fail

Order matters: patches are applied in the order they appear in the set string,
so a set with the right names in the wrong order is a different binary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"stale: {message}")


def parse_patch_set(value: str, label: str) -> list[str]:
    names = [entry.strip() for entry in value.split(",") if entry.strip()]
    if not names:
        fail(f"{label} patch set is empty")
    seen = set()
    for name in names:
        if name in seen:
            fail(f"{label} patch set repeats '{name}'")
        seen.add(name)
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--expected-patch-set", required=True)
    args = ap.parse_args()

    expected = parse_patch_set(args.expected_patch_set, "expected")

    if not args.binary.is_file():
        fail(f"no RetroArch binary at {args.binary}")
    if args.binary.stat().st_size == 0:
        fail(f"RetroArch binary is empty: {args.binary}")

    if not args.manifest.is_file():
        fail(f"no build manifest at {args.manifest}")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read build manifest {args.manifest}: {exc}")
    if not isinstance(manifest, dict):
        fail(f"build manifest is not a JSON object: {args.manifest}")

    flags = manifest.get("configure_flags")
    if (
        not isinstance(flags, list)
        or "--enable-ssl" not in flags
        or "--disable-ssl" in flags
    ):
        fail("RetroArch was not built with TLS support")

    controls = manifest.get("patch_controls")
    if not isinstance(controls, dict) or "MLP1_PATCH_SET" not in controls:
        fail("build manifest does not record patch_controls.MLP1_PATCH_SET")

    built = parse_patch_set(controls["MLP1_PATCH_SET"], "manifest")
    if built != expected:
        fail(
            "patch set mismatch\n"
            f"  expected: {','.join(expected)}\n"
            f"  built:    {','.join(built)}"
        )

    # The manifest carries no checksum today, so it identifies the build inputs
    # but not the binary sitting beside it. Adding one is tracked separately.
    print(f"reusable: RetroArch matches patch set {','.join(expected)}")


if __name__ == "__main__":
    main()
