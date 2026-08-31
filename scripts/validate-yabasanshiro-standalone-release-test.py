#!/usr/bin/env python3
"""Self-contained policy tests for the YabaSanshiro release validator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATOR = SCRIPT_DIR / "validate-yabasanshiro-standalone-release.py"
LICENSES = {
    "DISTRIBUTION-BASIS.md",
    "NanoGUI-BSD-3-Clause.txt",
    "Yabause-GPL-2.0.txt",
    "libchdr-BSD-3-Clause.txt",
    "nlohmann-json-MIT.txt",
    "pugixml-MIT.txt",
    "upstream-LICENSE.txt",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(package: Path, published: bool = True) -> None:
    files = [
        {"path": path.relative_to(package).as_posix(), "sha256": sha256(path)}
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]
    manifest = {
        "id": "yabasanshiro_standalone",
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "license": "GPL-2.0",
        "distribution_status": "release-owner-approved-gpl-2.0-basis",
        "distribution_basis": "licenses/DISTRIBUTION-BASIS.md",
        "binary": "bin/yabasanshiro",
        "binary_sha256": sha256(package / "bin/yabasanshiro"),
        "package_schema_version": 1,
        "corresponding_source": {
            "url": (
                "https://github.com/Utility-Muffin-Research-Kitchen/"
                "Yabasanshiro-standalone/releases/download/v1.0.0/"
                "yabasanshiro-standalone-1.11.beta3-mlp1-source.tar.gz"
            ),
            "archive": "yabasanshiro-standalone-1.11.beta3-mlp1-source.tar.gz",
            "sha256": "a" * 64 if published else None,
        },
        "files": files,
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def fixture(root: Path) -> Path:
    platform = root / "platforms/mlp1"
    package = platform / "emulators/yabasanshiro"
    for directory in (
        platform / "defaults",
        package / "bin",
        package / "defaults",
        package / "licenses",
        package / "provenance",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (platform / "defaults/systems.json").write_text(
        json.dumps({"systems": [{
            "id": "SATURN",
            "default_core": "yabasanshiro",
            "alternate_cores": ["yabasanshiro_standalone"],
        }]}), encoding="utf-8"
    )
    (platform / "defaults/cores.json").write_text(
        json.dumps({"cores": [{
            "id": "yabasanshiro_standalone",
            "type": "path",
            "path": "emulators/yabasanshiro/launch.sh",
            "requires_direct_drm": True,
            "supports_menu": True,
            "supports_savestate": False,
            "supports_disk_control": False,
            "status": "packaged",
        }]}), encoding="utf-8"
    )
    fake_elf = bytearray(64)
    fake_elf[:7] = b"\x7fELF\x02\x01\x01"
    fake_elf[18:20] = (183).to_bytes(2, "little")
    contents = {
        "bin/yabasanshiro": bytes(fake_elf),
        "launch.sh": b"#!/bin/sh\nexit 0\n",
        "README.txt": b"test\n",
        "defaults/config.version": b"2\n",
        "defaults/es_temporaryinput.cfg": b"test\n",
        "provenance/build-manifest.json": b"{}\n",
    }
    for relative, content in contents.items():
        (package / relative).write_bytes(content)
    for name in LICENSES:
        (package / "licenses" / name).write_text(f"{name}\n", encoding="utf-8")
    os.chmod(package / "bin/yabasanshiro", 0o755)
    os.chmod(package / "launch.sh", 0o755)
    write_manifest(package)
    return platform


def run_case(name: str, mutate, should_pass: bool, published: bool = True) -> None:
    with tempfile.TemporaryDirectory(prefix=f"leaf-yabasanshiro-{name}-") as temp:
        platform = fixture(Path(temp))
        mutate(platform)
        command = [sys.executable, str(VALIDATOR)]
        if published:
            command.append("--require-published-source")
        result = subprocess.run(
            [*command, str(platform)], text=True, capture_output=True, check=False
        )
        if (result.returncode == 0) != should_pass:
            print(result.stdout, result.stderr, file=sys.stderr)
            raise SystemExit(f"{name}: unexpected validator result")


def main() -> None:
    run_case("valid", lambda platform: None, True)

    def standalone_default(platform: Path) -> None:
        path = platform / "defaults/systems.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["systems"][0]["default_core"] = "yabasanshiro_standalone"
        path.write_text(json.dumps(data), encoding="utf-8")

    run_case("standalone-default", standalone_default, False)
    run_case(
        "corrupt-binary",
        lambda platform: (platform / "emulators/yabasanshiro/bin/yabasanshiro").write_bytes(b"bad"),
        False,
    )
    run_case(
        "missing-license",
        lambda platform: (platform / "emulators/yabasanshiro/licenses/DISTRIBUTION-BASIS.md").unlink(),
        False,
    )

    def missing_source_hash(platform: Path) -> None:
        package = platform / "emulators/yabasanshiro"
        write_manifest(package, published=False)

    run_case("missing-source-hash", missing_source_hash, False)
    run_case("development-source", missing_source_hash, True, published=False)
    print("YabaSanshiro standalone release policy checks passed")


if __name__ == "__main__":
    main()
