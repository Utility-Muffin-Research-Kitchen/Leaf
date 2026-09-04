#!/usr/bin/env python3
"""Self-contained policy tests for the Fun DraStic release validator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATOR = SCRIPT_DIR / "validate-fun-drastic-release.py"

LIBS = (
    "libSDL2-2.0.so.0",
    "libasound.so.2",
    "libfundrastic.so",
    "libwayland-cursor.so.0",
    "libxkbcommon.so.0",
)
HOOK_ASSETS = (
    "fonts/Nunito-Bold.ttf",
    "fonts/Translate.otf",
    "language/template.txt",
    "themes/custom.cfg",
    "res/cursor/1.png",
)
BUNDLED_BIOS = {"drastic_bios_arm7.bin": 16384, "drastic_bios_arm9.bin": 4096}
FORBIDDEN_BIOS = ("nds_bios_arm7.bin", "nds_bios_arm9.bin", "nds_firmware.bin")

BIOS_README = (
    "Fun DraStic includes DraStic's own free replacement BIOS.\n"
    "Put nds_bios_arm7.bin, nds_bios_arm9.bin and nds_firmware.bin in BIOS/NDS.\n"
)

LAUNCHER = """#!/usr/bin/env bash
set -euo pipefail
STATE_ROOT="${FUN_DRASTIC_STATE_ROOT:-$USERDATA_PATH/fun-drastic}"
LOG_FILE="$LOGS_PATH/fun-drastic.log"
export SDL_JOYSTICK_DISABLE_UDEV=1
exit 0
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_elf() -> bytes:
    data = bytearray(64)
    data[:7] = b"\x7fELF\x02\x01\x01"
    data[18:20] = (183).to_bytes(2, "little")
    return bytes(data)


def write_manifest(package: Path) -> None:
    files = [
        {"path": path.relative_to(package).as_posix(), "sha256": sha256(path)}
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    ]
    manifest = {
        "id": "fun_drastic",
        "name": "Fun DraStic",
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "author": "tenlevels",
        "package_schema_version": 1,
        "config_schema_version": 1,
        "source_archive": "drastic.zip",
        "source_funhook_sha256": "6" * 64,
        "hook_built_from_source": True,
        "source_repo": "https://github.com/Utility-Muffin-Research-Kitchen/Fun-Drastic-src",
        "license": "PolyForm-Noncommercial-1.0.0",
        "binary": "bin/drastic64",
        "binary_sha256": sha256(package / "bin/drastic64"),
        "entrypoint": "launch.sh",
        "sdl_video_driver": "wayland",
        "bundled_bios": [f"system/{name}" for name in BUNDLED_BIOS],
        "authorization": "licenses/DISTRIBUTION-BASIS.md",
        "distribution_status": "noncommercial-license",
        "exceptions": [
            {
                "artifact": "bin/drastic64",
                "reason": "prebuilt closed-source DraStic binary; not built by UMRK",
            }
        ],
        "files": files,
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def fixture(root: Path) -> Path:
    platform = root / "platforms/mlp1"
    package = platform / "emulators/fun-drastic"
    primary = platform / "emulators/drastic"
    for directory in (
        platform / "defaults",
        package / "bin",
        package / "lib",
        package / "config",
        package / "defaults",
        package / "fonts",
        package / "language",
        package / "themes",
        package / "res/cursor",
        package / "system",
        package / "licenses",
        package / "Overlays/960x720/Template",
        primary / "bin",
        primary / "share/system",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (platform / "defaults/systems.json").write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "id": "NDS",
                        "default_core": "drastic",
                        "alternate_cores": ["fun_drastic"],
                        "bios_notes": [
                            "Both Nintendo DS emulators bundle DraStic's own free "
                            "replacement BIOS.",
                            "Put nds_bios_arm7.bin, nds_bios_arm9.bin and "
                            "nds_firmware.bin in BIOS/NDS.",
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (platform / "defaults/cores.json").write_text(
        json.dumps(
            {
                "cores": [
                    {
                        "id": "drastic",
                        "display_name": "DraStic",
                        "type": "path",
                        "path": "emulators/drastic/launch.sh",
                        "requires_direct_drm": False,
                        "status": "packaged",
                    },
                    {
                        "id": "fun_drastic",
                        "display_name": "Fun DraStic",
                        "type": "path",
                        "path": "emulators/fun-drastic/launch.sh",
                        "requires_direct_drm": False,
                        "status": "packaged",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    (package / "bin/drastic64").write_bytes(fake_elf())
    for name in LIBS:
        (package / "lib" / name).write_bytes(
            fake_elf() if name == "libfundrastic.so" else b"lib\n"
        )
    (package / "launch.sh").write_text(LAUNCHER, encoding="utf-8")
    (package / "README.txt").write_text("Fun DraStic by tenlevels\n", encoding="utf-8")
    (package / "defaults/config.version").write_text("1\n", encoding="utf-8")
    (package / "config/drastic.cfg").write_text("unzip_roms = 1\n", encoding="utf-8")
    (package / "config/usrcheat.dat").write_bytes(b"cheats\n")
    (package / "game_database.xml").write_bytes(b"<db/>\n")
    (package / "system/BIOS-README.txt").write_text(BIOS_README, encoding="utf-8")
    for name in HOOK_ASSETS:
        (package / name).write_bytes(b"asset\n")
    for name, size in BUNDLED_BIOS.items():
        (package / "system" / name).write_bytes(b"\x00" * size)
    (package / "Overlays/960x720/Template/aspect_single.png").write_bytes(b"png\n")
    for name in (
        "DISTRIBUTION-BASIS.md",
        "THIRD-PARTY-NOTICES.txt",
        "FUN-DRASTIC-LICENSE.txt",
        "CREDITS.md",
    ):
        (package / "licenses" / name).write_text(name + "\n", encoding="utf-8")

    os.chmod(package / "bin/drastic64", 0o755)
    os.chmod(package / "launch.sh", 0o755)
    write_manifest(package)

    # The primary DraStic package, which must survive alongside it.
    (primary / "launch.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(primary / "launch.sh", 0o755)
    (primary / "bin/drastic64").write_bytes(fake_elf())
    for name, size in BUNDLED_BIOS.items():
        (primary / "share/system" / name).write_bytes(b"\x00" * size)

    return platform


def run_case(name: str, mutate, should_pass: bool) -> None:
    with tempfile.TemporaryDirectory(prefix=f"leaf-fun-drastic-{name}-") as temp:
        platform = fixture(Path(temp))
        mutate(platform)
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(platform)],
            text=True,
            capture_output=True,
            check=False,
        )
        if (result.returncode == 0) != should_pass:
            print(result.stdout, result.stderr, file=sys.stderr)
            raise SystemExit(f"{name}: unexpected validator result")


def rewrite_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def main() -> None:
    package_rel = "emulators/fun-drastic"

    run_case("valid", lambda platform: None, True)

    # DraStic stays the Nintendo DS default; Fun DraStic is an alternate.
    run_case(
        "fun-drastic-as-default",
        lambda platform: rewrite_json(
            platform / "defaults/systems.json",
            lambda data: data["systems"][0].update(default_core="fun_drastic"),
        ),
        False,
    )
    run_case(
        "not-an-alternate",
        lambda platform: rewrite_json(
            platform / "defaults/systems.json",
            lambda data: data["systems"][0].update(alternate_cores=[]),
        ),
        False,
    )

    # The Nintendo dumps must never ship, wherever they are hidden.
    for bios_name in FORBIDDEN_BIOS:
        run_case(
            f"nintendo-bios-{bios_name}",
            lambda platform, name=bios_name: (
                platform / package_rel / "system" / name
            ).write_bytes(b"\x00" * 16384),
            False,
        )
    run_case(
        "nintendo-bios-elsewhere",
        lambda platform: (platform / "nds_firmware.bin").write_bytes(b"\x00"),
        False,
    )

    # DraStic's own free BIOS must ship, in the right size, in both packages.
    run_case(
        "missing-free-bios",
        lambda platform: (
            platform / package_rel / "system/drastic_bios_arm7.bin"
        ).unlink(),
        False,
    )
    run_case(
        "truncated-free-bios",
        lambda platform: (
            platform / package_rel / "system/drastic_bios_arm7.bin"
        ).write_bytes(b"\x00" * 1024),
        False,
    )
    run_case(
        "primary-drastic-removed",
        lambda platform: (platform / "emulators/drastic/launch.sh").unlink(),
        False,
    )

    # The hook resolves these from disk with no fallback.
    for asset in HOOK_ASSETS:
        run_case(
            f"missing-hook-asset-{Path(asset).name}",
            lambda platform, name=asset: (platform / package_rel / name).unlink(),
            False,
        )

    # Wrapper contract.
    def hardcode_event(platform: Path) -> None:
        launcher = platform / package_rel / "launch.sh"
        launcher.write_text(
            LAUNCHER.replace(
                "export SDL_JOYSTICK_DISABLE_UDEV=1",
                'export SDL_JOYSTICK_DEVICE=/dev/input/event5',
            ),
            encoding="utf-8",
        )
        write_manifest(platform / package_rel)

    run_case("hardcoded-input-node", hardcode_event, False)

    def state_in_control_tree(platform: Path) -> None:
        launcher = platform / package_rel / "launch.sh"
        launcher.write_text(
            LAUNCHER.replace(
                'STATE_ROOT="${FUN_DRASTIC_STATE_ROOT:-$USERDATA_PATH/fun-drastic}"',
                'STATE_ROOT="$UMRK_INTERNAL_DATA_PATH/fundrastic"',
            ),
            encoding="utf-8",
        )
        write_manifest(platform / package_rel)

    run_case("state-in-launcher-control-tree", state_in_control_tree, False)

    # Provenance and integrity.
    run_case(
        "unpinned-archive",
        lambda platform: rewrite_json(
            platform / package_rel / "manifest.json",
            lambda data: data.update(source_funhook_sha256=""),
        ),
        False,
    )
    run_case(
        "missing-authorization",
        lambda platform: rewrite_json(
            platform / package_rel / "manifest.json",
            lambda data: data.update(authorization=None),
        ),
        False,
    )
    run_case(
        "claims-umrk-built-the-binary",
        lambda platform: rewrite_json(
            platform / package_rel / "manifest.json",
            lambda data: data.update(
                exceptions=[{"artifact": "bin/drastic64", "reason": "built here"}]
            ),
        ),
        False,
    )
    run_case(
        "missing-license-notice",
        lambda platform: (
            platform / package_rel / "licenses/DISTRIBUTION-BASIS.md"
        ).unlink(),
        False,
    )
    run_case(
        "checksum-drift",
        lambda platform: (platform / package_rel / "config/drastic.cfg").write_text(
            "unzip_roms = 0\n", encoding="utf-8"
        ),
        False,
    )
    run_case(
        "unlisted-file",
        lambda platform: (platform / package_rel / "extra.bin").write_bytes(b"x"),
        False,
    )
    run_case(
        "corrupt-binary",
        lambda platform: (platform / package_rel / "bin/drastic64").write_bytes(b"bad"),
        False,
    )

    print("Fun DraStic release policy checks passed")


if __name__ == "__main__":
    main()
