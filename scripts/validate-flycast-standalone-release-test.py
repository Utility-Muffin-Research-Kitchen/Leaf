#!/usr/bin/env python3
"""Self-contained policy tests for the Flycast standalone release validator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATOR = SCRIPT_DIR / "validate-flycast-standalone-release.py"
LICENSES = {
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(package: Path) -> None:
    files = []
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "path": path.relative_to(package).as_posix(),
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "id": "flycast_standalone",
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "package_schema_version": 1,
        "config_schema_version": 1,
        "upstream_tag": "v2.6",
        "upstream_sha": "392a429e8b040b3e5bf6696cb4f984274fc44123",
        "dynamic_dependencies": ["libSDL2-2.0.so.0"],
        "binary": "bin/flycast",
        "binary_sha256": sha256(package / "bin/flycast"),
        "files": files,
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def fixture(root: Path) -> Path:
    platform = root / "platforms/mlp1"
    package = platform / "emulators/flycast"
    for directory in (
        platform / "defaults",
        package / "bin",
        package / "defaults",
        package / "licenses",
        package / "provenance",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    cores = {
        "cores": [
            {
                "id": "flycast_standalone",
                "type": "path",
                "path": "emulators/flycast/launch.sh",
                "requires_direct_drm": True,
                "status": "packaged",
            }
        ]
    }
    systems = {
        "systems": [
            {
                "id": "DC",
                "default_core": "flycast",
                "alternate_cores": ["flycast_standalone"],
            }
        ]
    }
    (platform / "defaults/cores.json").write_text(
        json.dumps(cores), encoding="utf-8"
    )
    (platform / "defaults/systems.json").write_text(
        json.dumps(systems), encoding="utf-8"
    )

    fake_aarch64_elf = bytearray(64)
    fake_aarch64_elf[:7] = b"\x7fELF\x02\x01\x01"
    fake_aarch64_elf[18:20] = (183).to_bytes(2, "little")
    files = {
        "bin/flycast": bytes(fake_aarch64_elf),
        "launch.sh": b"#!/bin/sh\nexec \"$(dirname \"$0\")/bin/flycast\" \"$@\"\n",
        "defaults/emu.cfg": b"[config]\npvr.rend = 0\n",
        "defaults/config.version": b"1\n",
        "defaults/SDL_Loong Gamepad.cfg": b"[emulator]\nmapping_name=Loong\n",
        "provenance/build-manifest.json": b"{}\n",
    }
    for relative, content in files.items():
        (package / relative).write_bytes(content)
    for name in LICENSES:
        (package / "licenses" / name).write_text(f"{name}\n", encoding="utf-8")
    os.chmod(package / "bin/flycast", 0o755)
    os.chmod(package / "launch.sh", 0o755)
    write_manifest(package)
    return platform


def run_case(name: str, mutate, should_pass: bool) -> None:
    with tempfile.TemporaryDirectory(prefix=f"leaf-flycast-{name}-") as temp:
        platform = fixture(Path(temp))
        mutate(platform)
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(platform)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        passed = result.returncode == 0
        if passed != should_pass:
            print(result.stdout, end="", file=sys.stderr)
            print(result.stderr, end="", file=sys.stderr)
            raise SystemExit(
                f"{name}: validator {'passed' if passed else 'failed'}, "
                f"expected {'pass' if should_pass else 'failure'}"
            )


def main() -> None:
    run_case("valid", lambda platform: None, True)
    run_case(
        "corrupt-binary",
        lambda platform: (platform / "emulators/flycast/bin/flycast").write_bytes(
            b"corrupt\n"
        ),
        False,
    )
    run_case(
        "missing-license",
        lambda platform: (
            platform / "emulators/flycast/licenses/THIRD-PARTY-NOTICES.txt"
        ).unlink(),
        False,
    )

    def add_mutable_content(platform: Path) -> None:
        package = platform / "emulators/flycast"
        mutable = package / "Saves/user-vmu.bin"
        mutable.parent.mkdir()
        mutable.write_bytes(b"user data")
        write_manifest(package)

    run_case("mutable-content", add_mutable_content, False)

    def disable_direct_drm(platform: Path) -> None:
        path = platform / "defaults/cores.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cores"][0]["requires_direct_drm"] = False
        path.write_text(json.dumps(data), encoding="utf-8")

    run_case("shared-drm-catalog", disable_direct_drm, False)
    run_case(
        "non-executable-launcher",
        lambda platform: os.chmod(platform / "emulators/flycast/launch.sh", 0o644),
        False,
    )
    print("Flycast standalone release policy checks passed")


if __name__ == "__main__":
    main()
