#!/usr/bin/env python3
"""Read release identity back out of built release artifacts.

Every other identity check in this repo runs on the INPUTS, before the build.
This one reads the artifact after the fact, which is the only way to catch an
environment variable that was never set: an unset LEAF_RELEASE_CHANNEL does not
fail anything, it quietly defaults to "dev" and ships.

Release ID is the exact artifact/filesystem/OTA identity. Version is the
installed display and compatibility identity, channel records build policy and
the default publication repository, and tag records the publication reference.
They are related, but none is a substitute for another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_release_block(zip_path: str, release_id: str) -> dict[str, object]:
    member = (
        f".system/leaf/releases/{release_id}/provenance/components.json"
    )
    try:
        with zipfile.ZipFile(zip_path) as zf:
            matches = [name for name in zf.namelist() if name == member]
            if not matches:
                fail(f"{zip_path}: no {member} inside the ZIP")
            if len(matches) > 1:
                fail(f"{zip_path}: {len(matches)} copies of {member}, expected 1")
            raw = zf.read(member)
    except SystemExit:
        raise
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        fail(f"{zip_path}: cannot read release provenance: {exc}")

    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{zip_path}: {member} is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        fail(f"{zip_path}: {member} must contain a JSON object")
    release = payload.get("release")
    if not isinstance(release, dict):
        fail(f"{zip_path}: provenance has no 'release' object")
    return release


def load_json_object(path: str, label: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"{path}: cannot read {label}: {exc}")
    if not isinstance(payload, dict):
        fail(f"{path}: {label} must contain a JSON object")
    return payload


def artifact_file_identity(
    path: Path,
    descriptor: dict[str, object] | None,
    label: str,
) -> dict[str, tuple[object, object]]:
    if not path.is_file():
        return {f"{label}.file": ("present", "missing")}

    try:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        fail(f"{path}: cannot inspect release artifact: {exc}")

    actual_digest = digest.hexdigest()
    recorded_size = descriptor.get("size") if descriptor else None
    recorded_digest = descriptor.get("sha256") if descriptor else None
    bad: dict[str, tuple[object, object]] = {}
    if recorded_size != size:
        bad[f"{label}.size"] = (size, recorded_size)
    if recorded_digest != actual_digest:
        bad[f"{label}.sha256"] = (actual_digest, recorded_digest)
    return bad


def manifest_identity(
    manifest_path: str,
    install_path: str,
    tag: str,
    channel: str,
    repository: str | None,
) -> dict[str, tuple[object, object]]:
    payload = load_json_object(manifest_path, "release manifest")
    version = tag[1:] if tag.startswith("v") else tag
    expected: dict[str, object] = {
        "channel": channel,
        "version": version,
        "release_id": tag,
        "artifact.name": f"leaf-mlp1-sd-{tag}.zip",
        "recovery_zip.name": f"leaf-mlp1-recovery-{tag}.zip",
    }
    if repository:
        expected["notes.url"] = (
            f"https://github.com/{repository}/releases/tag/{tag}"
        )

    platforms = payload.get("platforms")
    mlp1 = platforms.get("mlp1") if isinstance(platforms, dict) else None
    artifact = mlp1.get("artifact") if isinstance(mlp1, dict) else None
    recovery = mlp1.get("recovery_zip") if isinstance(mlp1, dict) else None
    notes = payload.get("notes")
    actual = {
        "channel": payload.get("channel"),
        "version": payload.get("version"),
        "release_id": payload.get("release_id"),
        "artifact.name": artifact.get("name") if isinstance(artifact, dict) else None,
        "recovery_zip.name": (
            recovery.get("name") if isinstance(recovery, dict) else None
        ),
        "notes.url": notes.get("url") if isinstance(notes, dict) else None,
    }
    bad = {
        key: (want, actual.get(key))
        for key, want in expected.items()
        if actual.get(key) != want
    }
    install = Path(install_path)
    if install.name != expected["artifact.name"]:
        bad["artifact.file_name"] = (expected["artifact.name"], install.name)
    bad.update(
        artifact_file_identity(
            install,
            artifact if isinstance(artifact, dict) else None,
            "artifact",
        )
    )
    recovery_path = (
        Path(manifest_path).parent / str(expected["recovery_zip.name"])
    )
    bad.update(
        artifact_file_identity(
            recovery_path,
            recovery if isinstance(recovery, dict) else None,
            "recovery_zip",
        )
    )
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zip", help="built SD release ZIP")
    ap.add_argument("--tag", required=True, help="the release tag, e.g. v0.8.0-beta.3")
    ap.add_argument("--channel", required=True, choices=("dev", "beta", "stable"))
    ap.add_argument("--manifest", help="optional leaf-update.json to verify")
    ap.add_argument(
        "--repository",
        help="expected owner/repository used by the manifest release-notes URL",
    )
    args = ap.parse_args()

    tag = args.tag
    expected = {
        "channel": args.channel,
        "version": tag[1:] if tag.startswith("v") else tag,
        "tag": tag,
        "release_id": tag,
    }

    release = load_release_block(args.zip, tag)
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
            "\nThese values come from RELEASE_ID, LEAF_RELEASE_CHANNEL, "
            "LEAF_RELEASE_VERSION, and LEAF_RELEASE_TAG.",
            file=sys.stderr,
        )
        return 1

    if args.manifest:
        manifest_bad = manifest_identity(
            args.manifest, args.zip, tag, args.channel, args.repository
        )
        if manifest_bad:
            print(
                f"\n{args.manifest}: release manifest does not match {tag}",
                file=sys.stderr,
            )
            for key, (want, got) in manifest_bad.items():
                print(
                    f"  {key}: expected {want!r}, got {got!r}",
                    file=sys.stderr,
                )
            return 1
        print(f"\nrelease manifest OK for {tag}")

    print(f"release identity OK for {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
