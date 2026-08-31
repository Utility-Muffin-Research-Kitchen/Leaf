#!/usr/bin/env python3
"""Validate the standalone YabaSanshiro catalog entry and MLP1 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath


CORE_ID = "yabasanshiro_standalone"
CORE_PATH = "emulators/yabasanshiro/launch.sh"
PACKAGE_REL = Path("emulators/yabasanshiro")
ARCHIVE = "yabasanshiro-standalone-1.11.beta3-mlp1-source.tar.gz"
SOURCE_URL_RE = re.compile(
    r"^https://github\.com/Utility-Muffin-Research-Kitchen/"
    rf"Yabasanshiro-standalone/releases/download/[^/]+/{re.escape(ARCHIVE)}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_LICENSES = {
    "DISTRIBUTION-BASIS.md",
    "NanoGUI-BSD-3-Clause.txt",
    "Yabause-GPL-2.0.txt",
    "libchdr-BSD-3-Clause.txt",
    "nlohmann-json-MIT.txt",
    "pugixml-MIT.txt",
    "upstream-LICENSE.txt",
}
FORBIDDEN_TOP_LEVEL = {"bios", "roms", "saves", "states", "userdata", ".userdata"}


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON file {path}: {exc}")


def rows(data: object, key: str, path: Path) -> list[dict[str, object]]:
    value = data.get(key) if isinstance(data, dict) else data
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        fail(f"{path} must contain a {key} array")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_aarch64_elf(path: Path) -> None:
    header = path.read_bytes()[:20]
    if (
        len(header) < 20
        or header[:4] != b"\x7fELF"
        or header[4] != 2
        or header[5] != 1
        or int.from_bytes(header[18:20], "little") != 183
    ):
        fail(f"YabaSanshiro binary is not a little-endian AArch64 ELF: {path}")


def safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"invalid package manifest path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        fail(f"unsafe package manifest path: {value}")
    return value


def validate(platform_dir: Path, require_published_source: bool) -> None:
    systems_path = platform_dir / "defaults/systems.json"
    cores_path = platform_dir / "defaults/cores.json"
    systems = rows(load_json(systems_path), "systems", systems_path)
    cores = rows(load_json(cores_path), "cores", cores_path)

    saturn_rows = [row for row in systems if row.get("id") == "SATURN"]
    if len(saturn_rows) != 1:
        fail("systems.json must contain exactly one SATURN system")
    saturn = saturn_rows[0]
    if saturn.get("default_core") != "yabasanshiro":
        fail("SATURN must retain RetroArch YabaSanshiro as its default")
    alternates = saturn.get("alternate_cores")
    if not isinstance(alternates, list) or CORE_ID not in alternates:
        fail("SATURN must expose standalone YabaSanshiro as an alternate")

    core_rows = [row for row in cores if row.get("id") == CORE_ID]
    if len(core_rows) != 1:
        fail("cores.json must contain exactly one standalone YabaSanshiro entry")
    core = core_rows[0]
    required_core_fields = {
        "type": "path",
        "path": CORE_PATH,
        "requires_direct_drm": True,
        "supports_menu": True,
        "supports_savestate": False,
        "supports_disk_control": False,
        "status": "packaged",
    }
    for key, expected in required_core_fields.items():
        if core.get(key) != expected:
            fail(f"standalone YabaSanshiro {key} must be {expected!r}")

    package = platform_dir / PACKAGE_REL
    binary = package / "bin/yabasanshiro"
    manifest_path = package / "manifest.json"
    required_files = (
        binary,
        package / "launch.sh",
        package / "README.txt",
        package / "defaults/config.version",
        package / "defaults/es_temporaryinput.cfg",
        package / "provenance/build-manifest.json",
        manifest_path,
    )
    for required in required_files:
        if not required.is_file():
            fail(f"missing YabaSanshiro package file: {required}")
    if not os.access(package / "launch.sh", os.X_OK) or not os.access(binary, os.X_OK):
        fail("YabaSanshiro launcher and binary must be executable")
    validate_aarch64_elf(binary)

    for path in package.rglob("*"):
        if path.is_symlink():
            fail(f"YabaSanshiro package is not FAT32-safe; symlink found: {path}")
        relative = path.relative_to(package)
        if relative.parts and relative.parts[0].casefold() in FORBIDDEN_TOP_LEVEL:
            fail(f"mutable/user content found in YabaSanshiro package: {relative}")

    missing_licenses = sorted(
        name for name in REQUIRED_LICENSES if not (package / "licenses" / name).is_file()
    )
    if missing_licenses:
        fail("missing YabaSanshiro license notices: " + ", ".join(missing_licenses))

    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        fail("YabaSanshiro manifest must be a JSON object")
    expected_fields = {
        "id": CORE_ID,
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "license": "GPL-2.0",
        "distribution_status": "release-owner-approved-gpl-2.0-basis",
        "distribution_basis": "licenses/DISTRIBUTION-BASIS.md",
        "binary": "bin/yabasanshiro",
        "package_schema_version": 1,
    }
    for key, expected in expected_fields.items():
        if manifest.get(key) != expected:
            fail(f"YabaSanshiro manifest {key} must be {expected!r}")

    source = manifest.get("corresponding_source")
    if not isinstance(source, dict) or source.get("archive") != ARCHIVE:
        fail("YabaSanshiro manifest must identify its corresponding source archive")
    source_url = source.get("url")
    source_sha = source.get("sha256")
    if not isinstance(source_url, str) or not source_url:
        fail("YabaSanshiro manifest must provide a corresponding source URL")
    if source_sha is not None and (
        not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha)
    ):
        fail("YabaSanshiro corresponding source checksum is invalid")
    if require_published_source and (
        not SOURCE_URL_RE.fullmatch(source_url)
        or not isinstance(source_sha, str)
        or not SHA256_RE.fullmatch(source_sha)
    ):
        fail("tagged release must link a checksummed UMRK source release asset")

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list) or not file_rows:
        fail("YabaSanshiro manifest must contain a non-empty files array")
    expected_files: dict[str, str] = {}
    for row in file_rows:
        if not isinstance(row, dict):
            fail("YabaSanshiro manifest file rows must be objects")
        relative = safe_manifest_path(row.get("path"))
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            fail(f"invalid checksum for YabaSanshiro package path: {relative}")
        if relative == "manifest.json" or relative in expected_files:
            fail(f"duplicate or self-referential manifest path: {relative}")
        expected_files[relative] = expected_sha

    actual_files = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(expected_files) != actual_files:
        fail("YabaSanshiro manifest inventory does not match the package")
    for relative, expected_sha in expected_files.items():
        if sha256(package / relative) != expected_sha:
            fail(f"YabaSanshiro package checksum mismatch: {relative}")
    binary_sha = sha256(binary)
    if manifest.get("binary_sha256") != binary_sha:
        fail("YabaSanshiro manifest binary checksum does not match bin/yabasanshiro")

    print(
        "YabaSanshiro standalone release gate: "
        f"{CORE_PATH}, {len(expected_files)} checksummed files, binary {binary_sha}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-published-source", action="store_true")
    parser.add_argument("platform_dir", type=Path)
    args = parser.parse_args()
    if not args.platform_dir.is_dir():
        fail(f"missing MLP1 platform directory: {args.platform_dir}")
    validate(args.platform_dir, args.require_published_source)


if __name__ == "__main__":
    main()
