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

Names are not enough on their own. Patches are edited in place (the synchronous
save and load commands both landed in command-menu without renaming it), so the
manifest's patch, build script and binary hashes are compared against the
retroarch-builds checkout too. A manifest written before those hashes existed
is stale by definition and forces one rebuild.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def fail(message: str) -> None:
    raise SystemExit(f"stale: {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def recorded_hashes(manifest: dict, key: str) -> dict[str, str]:
    value = manifest.get(key)
    if not isinstance(value, dict) or not value:
        fail(f"build manifest does not record {key}; it predates input hashing")
    for name, digest in value.items():
        if not isinstance(digest, str) or not digest:
            fail(f"build manifest has no {key} entry for {name}")
    return value


def check_input(root: Path, name: str, recorded: str, what: str) -> None:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        fail(f"build manifest names {what} outside the checkout: {name}")
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        fail(f"{what} {name} is missing from {root}")
    if sha256(path) != recorded:
        fail(f"{what} {name} changed since this RetroArch was built")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--expected-patch-set", required=True)
    ap.add_argument(
        "--retroarch-builds-dir",
        required=True,
        type=Path,
        help="checkout whose patches and build scripts the build must match",
    )
    ap.add_argument("--require-ffmpeg", action="store_true")
    ap.add_argument("--ffmpeg-stamp", type=Path)
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

    if args.require_ffmpeg:
        if "--enable-ffmpeg" not in flags or "--disable-ffmpeg" in flags:
            fail("RetroArch was not built with FFmpeg recording support")
        if args.ffmpeg_stamp is None or not args.ffmpeg_stamp.is_file():
            fail("MLP1 FFmpeg input stamp is missing")
        stamp_sha256 = sha256(args.ffmpeg_stamp)
        if manifest.get("ffmpeg_input_stamp_sha256") != stamp_sha256:
            fail("FFmpeg input stamp does not match RetroArch build manifest")

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

    builds_dir = args.retroarch_builds_dir
    if not builds_dir.is_dir():
        fail(f"no retroarch-builds checkout at {builds_dir}")

    # build-mlp1.sh appends one patches_applied entry per non-empty set name,
    # in set order, so the two lists pair up by position.
    applied = manifest.get("patches_applied")
    if (
        not isinstance(applied, list)
        or not all(isinstance(entry, str) for entry in applied)
        or len(applied) != len(expected)
    ):
        fail("build manifest patches_applied does not match its patch set")
    patch_hashes = recorded_hashes(manifest, "patches_sha256")
    if set(patch_hashes) != set(applied):
        fail("build manifest patches_sha256 does not cover patches_applied")
    for label in applied:
        check_input(builds_dir / "patches", label, patch_hashes[label], "patch")

    # The patch name to file mapping and the RetroArch defaults live in
    # build-mlp1.sh, so an unchanged script also pins those.
    input_hashes = recorded_hashes(manifest, "build_inputs_sha256")
    if "build-mlp1.sh" not in input_hashes:
        fail("build manifest does not record the build-mlp1.sh hash")
    for name, digest in sorted(input_hashes.items()):
        check_input(builds_dir, name, digest, "build input")

    defaults = manifest.get("source_defaults")
    if not isinstance(defaults, dict):
        fail("build manifest does not record source_defaults")
    for key in ("retroarch_version", "retroarch_upstream_url"):
        pinned = defaults.get(key)
        if not isinstance(pinned, str) or not pinned:
            fail(f"build manifest does not record source_defaults.{key}")
        if manifest.get(key) != pinned:
            fail(
                f"RetroArch was built from {key} {manifest.get(key)!r}, "
                f"not the pinned {pinned!r}"
            )

    binary_sha256 = manifest.get("output_binary_sha256")
    if not isinstance(binary_sha256, str) or not binary_sha256:
        fail("build manifest does not record output_binary_sha256")
    if sha256(args.binary) != binary_sha256:
        fail(f"RetroArch binary does not match its build manifest: {args.binary}")

    print(
        f"reusable: RetroArch matches patch set {','.join(expected)} "
        "and its recorded patch, build script and binary hashes"
    )


if __name__ == "__main__":
    main()
