#!/usr/bin/env python3
"""Validate the standalone Flycast catalog entry and packaged MLP1 payload."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath


CORE_ID = "flycast_standalone"
CORE_PATH = "emulators/flycast/launch.sh"
PACKAGE_REL = Path("emulators/flycast")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_LICENSES = {
    "Boost-Nowide-BSL-1.0.txt",
    "Breakpad-BSD-3-Clause.txt",
    "DreamPicoPort-MIT.txt",
    "Flycast-GPL-2.0.txt",
    "GLM-License.txt",
    "THIRD-PARTY-NOTICES.txt",
    "WebSocketpp-BSD-3-Clause.txt",
    "Zstandard-BSD-3-Clause.txt",
    "libchdr-BSD-3-Clause.txt",
    "libjuice-MPL-2.0.txt",
    "libusb-LGPL-2.1.txt",
    "libzip-BSD-3-Clause.txt",
    "miniupnpc-BSD-3-Clause.txt",
    "picoTCP-GPL-2.0.txt",
    "rcheevos-MIT.txt",
    "xBRZ-GPL-3.0.txt",
    "xxHash-BSD-2-Clause.txt",
}
FORBIDDEN_TOP_LEVEL = {
    "bios",
    "roms",
    "saves",
    "states",
    "userdata",
    ".userdata",
}


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing JSON file: {path}")
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
    try:
        header = path.read_bytes()[:20]
    except OSError as exc:
        fail(f"could not read Flycast binary {path}: {exc}")
    if (
        len(header) < 20
        or header[:4] != b"\x7fELF"
        or header[4] != 2
        or header[5] != 1
        or int.from_bytes(header[18:20], "little") != 183
    ):
        fail(f"Flycast binary is not a little-endian AArch64 ELF: {path}")


def safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"invalid package manifest path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        fail(f"unsafe package manifest path: {value}")
    return value


def validate(platform_dir: Path) -> None:
    systems_path = platform_dir / "defaults/systems.json"
    cores_path = platform_dir / "defaults/cores.json"
    systems = rows(load_json(systems_path), "systems", systems_path)
    cores = rows(load_json(cores_path), "cores", cores_path)

    dc_rows = [row for row in systems if row.get("id") == "DC"]
    if len(dc_rows) != 1:
        fail("systems.json must contain exactly one DC system")
    dc = dc_rows[0]
    alternates = dc.get("alternate_cores")
    if not isinstance(alternates, list):
        fail("DC alternate_cores must be an array")
    references = [dc.get("default_core"), *alternates]
    if CORE_ID not in references:
        fail("DC must expose flycast_standalone as a default or alternate")

    core_rows = [row for row in cores if row.get("id") == CORE_ID]
    if len(core_rows) != 1:
        fail("cores.json must contain exactly one flycast_standalone entry")
    core = core_rows[0]
    if core.get("type") != "path":
        fail("flycast_standalone must be a path core")
    if core.get("path") != CORE_PATH:
        fail(f"flycast_standalone path must be {CORE_PATH}")
    if core.get("requires_direct_drm") is not True:
        fail("flycast_standalone must require direct DRM")

    launcher = platform_dir / CORE_PATH
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        fail(f"Flycast launcher is missing or not executable: {launcher}")

    package_dir = platform_dir / PACKAGE_REL
    binary = package_dir / "bin/flycast"
    manifest_path = package_dir / "manifest.json"
    config_version_path = package_dir / "defaults/config.version"
    for required in (
        binary,
        package_dir / "launch.sh",
        package_dir / "defaults/emu.cfg",
        package_dir / "defaults/SDL_Loong Gamepad.cfg",
        config_version_path,
        package_dir / "provenance/build-manifest.json",
        manifest_path,
    ):
        if not required.is_file():
            fail(f"missing Flycast package file: {required}")
    if not os.access(binary, os.X_OK):
        fail(f"Flycast binary is not executable: {binary}")
    validate_aarch64_elf(binary)

    for path in package_dir.rglob("*"):
        if path.is_symlink():
            fail(f"Flycast package is not FAT32-safe; symlink found: {path}")
        relative = path.relative_to(package_dir)
        if relative.parts and relative.parts[0].casefold() in FORBIDDEN_TOP_LEVEL:
            fail(f"mutable/user content found in Flycast package: {relative}")
        if path.name in {"flycast.log", "emu.cfg.save"}:
            fail(f"mutable/user file found in Flycast package: {relative}")

    license_dir = package_dir / "licenses"
    missing_licenses = sorted(
        name for name in REQUIRED_LICENSES if not (license_dir / name).is_file()
    )
    if missing_licenses:
        fail("missing Flycast license notices: " + ", ".join(missing_licenses))

    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        fail("Flycast manifest must be a JSON object")
    expected_fields = {
        "id": CORE_ID,
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "package_schema_version": 1,
    }
    for key, expected in expected_fields.items():
        if manifest.get(key) != expected:
            fail(f"Flycast manifest {key} must be {expected!r}")
    if not isinstance(manifest.get("config_schema_version"), int):
        fail("Flycast manifest config_schema_version must be an integer")
    try:
        config_version = int(config_version_path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError, ValueError) as exc:
        fail(f"invalid Flycast config version: {exc}")
    if manifest["config_schema_version"] != config_version:
        fail("Flycast manifest config schema does not match defaults/config.version")
    if not isinstance(manifest.get("upstream_tag"), str) or not manifest["upstream_tag"]:
        fail("Flycast manifest must record an upstream tag")
    if not isinstance(manifest.get("upstream_sha"), str) or not GIT_SHA_RE.fullmatch(
        manifest["upstream_sha"]
    ):
        fail("Flycast manifest must record a full lowercase upstream SHA")
    dependencies = manifest.get("dynamic_dependencies")
    if not isinstance(dependencies, list) or not dependencies or not all(
        isinstance(item, str) and item for item in dependencies
    ):
        fail("Flycast manifest must record dynamic dependencies")

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list) or not file_rows:
        fail("Flycast manifest must contain a non-empty files array")
    expected_files: dict[str, str] = {}
    for row in file_rows:
        if not isinstance(row, dict):
            fail("Flycast manifest file rows must be objects")
        relative = safe_manifest_path(row.get("path"))
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            fail(f"invalid checksum for Flycast package path: {relative}")
        if relative == "manifest.json" or relative in expected_files:
            fail(f"duplicate or self-referential Flycast manifest path: {relative}")
        expected_files[relative] = expected_sha

    actual_files = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(expected_files) != actual_files:
        missing = sorted(actual_files - set(expected_files))
        extra = sorted(set(expected_files) - actual_files)
        fail(f"Flycast manifest inventory mismatch; unlisted={missing}, missing={extra}")
    for relative, expected_sha in expected_files.items():
        actual_sha = sha256(package_dir / relative)
        if actual_sha != expected_sha:
            fail(f"Flycast package checksum mismatch: {relative}")

    binary_sha = sha256(binary)
    if manifest.get("binary") != "bin/flycast":
        fail("Flycast manifest binary path must be bin/flycast")
    if manifest.get("binary_sha256") != binary_sha:
        fail("Flycast manifest binary checksum does not match bin/flycast")

    print(
        "Flycast standalone release gate: "
        f"{CORE_PATH}, {len(expected_files)} checksummed files, binary {binary_sha}"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <mlp1-platform-dir>")
    platform_dir = Path(sys.argv[1])
    if not platform_dir.is_dir():
        fail(f"missing MLP1 platform directory: {platform_dir}")
    validate(platform_dir)


if __name__ == "__main__":
    main()
