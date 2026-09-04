#!/usr/bin/env python3
"""Validate the Fun DraStic catalog entry and packaged MLP1 payload.

Fun DraStic is a second Nintendo DS standalone over the same closed-source
drastic64 binary the primary DraStic package ships. Three things are easy to
get wrong and expensive to ship, so they are gated here rather than left to
review:

  * DraStic must stay the NDS default. Fun DraStic is an ordered alternate.
  * The Nintendo BIOS and firmware dumps must never appear, while DraStic's own
    free replacement BIOS must. Those are different files with confusingly
    similar names, and the gate has to tell them apart.
  * The two packages must stay independent on disk. A wrapper that stored state
    inside the release-managed emulator directory, or under the
    launcher-owned control-state tree, would lose it on the next update.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath


CORE_ID = "fun_drastic"
CORE_PATH = "emulators/fun-drastic/launch.sh"
PACKAGE_REL = Path("emulators/fun-drastic")
PRIMARY_CORE_ID = "drastic"
PRIMARY_PACKAGE_REL = Path("emulators/drastic")
SYSTEM_ID = "NDS"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Shipped in both NDS packages: DraStic's own free replacement BIOS.
BUNDLED_BIOS = {"drastic_bios_arm7.bin": 16384, "drastic_bios_arm9.bin": 4096}
# Never shipped, anywhere: the Nintendo dumps.
FORBIDDEN_BIOS = ("nds_bios_arm7.bin", "nds_bios_arm9.bin", "nds_firmware.bin")

REQUIRED_LIBS = (
    "libSDL2-2.0.so.0",
    "libasound.so.2",
    "libfundrastic.so",
    "libwayland-cursor.so.0",
    "libxkbcommon.so.0",
)

# The hook resolves these from FUN_DRASTIC_DIR with no fallback, so a package
# missing one boots to a menu that renders nothing.
REQUIRED_HOOK_ASSETS = (
    "fonts/Nunito-Bold.ttf",
    "fonts/Translate.otf",
    "language/template.txt",
    "themes/custom.cfg",
    "res/cursor/1.png",
)

REQUIRED_LICENSES = (
    "DISTRIBUTION-BASIS.md",
    "THIRD-PARTY-NOTICES.txt",
    # tenlevels' own licence and credits, shipped verbatim. The PolyForm
    # licence carries a required notice, so a release that drops it is not
    # one we may ship.
    "FUN-DRASTIC-LICENSE.txt",
    "CREDITS.md",
)

FORBIDDEN_TOP_LEVEL = {
    "backup",
    "savestates",
    "profiles",
    "unzip_cache",
    "input_record",
    "cheats",
    "slot2",
    "roms",
    "saves",
    "states",
    "bios",
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
        fail(f"could not read {path}: {exc}")
    if (
        len(header) < 20
        or header[:4] != b"\x7fELF"
        or header[4] != 2
        or header[5] != 1
        or int.from_bytes(header[18:20], "little") != 183
    ):
        fail(f"not a little-endian AArch64 ELF: {path}")


def safe_manifest_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail(f"invalid package manifest path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        fail(f"unsafe package manifest path: {value}")
    return value


def validate_catalog(platform_dir: Path) -> None:
    systems_path = platform_dir / "defaults/systems.json"
    cores_path = platform_dir / "defaults/cores.json"
    systems = rows(load_json(systems_path), "systems", systems_path)
    cores = rows(load_json(cores_path), "cores", cores_path)

    system_rows = [row for row in systems if row.get("id") == SYSTEM_ID]
    if len(system_rows) != 1:
        fail(f"systems.json must contain exactly one {SYSTEM_ID} system")
    system = system_rows[0]
    if system.get("default_core") != PRIMARY_CORE_ID:
        fail(f"{SYSTEM_ID} must keep {PRIMARY_CORE_ID} as its default core")
    alternates = system.get("alternate_cores")
    if not isinstance(alternates, list) or CORE_ID not in alternates:
        fail(f"{SYSTEM_ID} must list {CORE_ID} in alternate_cores")
    bios_notes = system.get("bios_notes")
    if not isinstance(bios_notes, list) or not bios_notes:
        fail(f"{SYSTEM_ID} must carry bios_notes naming the optional dumps")
    notes = " ".join(str(note) for note in bios_notes)
    for name in FORBIDDEN_BIOS:
        if name not in notes:
            fail(f"{SYSTEM_ID} bios_notes must name {name}")
    if "BIOS/NDS" not in notes:
        fail(f"{SYSTEM_ID} bios_notes must say where the dumps go (BIOS/NDS)")

    for core_id, core_path in (
        (CORE_ID, CORE_PATH),
        (PRIMARY_CORE_ID, "emulators/drastic/launch.sh"),
    ):
        core_rows = [row for row in cores if row.get("id") == core_id]
        if len(core_rows) != 1:
            fail(f"cores.json must contain exactly one {core_id} entry")
        core = core_rows[0]
        if core.get("type") != "path":
            fail(f"{core_id} must be a path core")
        if core.get("path") != core_path:
            fail(f"{core_id} path must be {core_path}")
        if core.get("status") != "packaged":
            fail(f"{core_id} must be marked packaged")

    fun_core = next(row for row in cores if row.get("id") == CORE_ID)
    if fun_core.get("requires_direct_drm"):
        fail("fun_drastic must not require direct DRM")
    if fun_core.get("display_name") != "Fun DraStic":
        fail("fun_drastic display name must be Fun DraStic")


def validate_package(platform_dir: Path) -> tuple[int, str]:
    launcher = platform_dir / CORE_PATH
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        fail(f"Fun DraStic launcher is missing or not executable: {launcher}")

    package_dir = platform_dir / PACKAGE_REL
    manifest_path = package_dir / "manifest.json"
    binary = package_dir / "bin/drastic64"

    required = [
        binary,
        package_dir / "launch.sh",
        package_dir / "manifest.json",
        package_dir / "README.txt",
        package_dir / "defaults/config.version",
        package_dir / "config/drastic.cfg",
        package_dir / "config/usrcheat.dat",
        package_dir / "game_database.xml",
        package_dir / "system/BIOS-README.txt",
    ]
    required += [package_dir / "lib" / name for name in REQUIRED_LIBS]
    required += [package_dir / name for name in REQUIRED_HOOK_ASSETS]
    required += [package_dir / "licenses" / name for name in REQUIRED_LICENSES]
    required += [package_dir / "system" / name for name in BUNDLED_BIOS]
    for path in required:
        if not path.is_file():
            fail(f"missing Fun DraStic package file: {path}")

    if not os.access(binary, os.X_OK):
        fail(f"Fun DraStic binary is not executable: {binary}")
    validate_aarch64_elf(binary)
    validate_aarch64_elf(package_dir / "lib/libfundrastic.so")

    # An overlay pack tree has to exist; its exact contents are user-extendable.
    if not any((package_dir / "Overlays").rglob("*.png")):
        fail("Fun DraStic package must ship at least one screen overlay")

    for name, expected_size in BUNDLED_BIOS.items():
        actual = (package_dir / "system" / name).stat().st_size
        if actual != expected_size:
            fail(f"{name} is {actual} bytes, expected {expected_size}")

    bios_readme = (package_dir / "system/BIOS-README.txt").read_text(encoding="utf-8")
    for name in FORBIDDEN_BIOS:
        if name not in bios_readme:
            fail(f"system/BIOS-README.txt must name {name}")

    for path in package_dir.rglob("*"):
        if path.is_symlink():
            fail(f"Fun DraStic package is not FAT32-safe; symlink found: {path}")
        relative = path.relative_to(package_dir)
        if relative.parts and relative.parts[0].casefold() in FORBIDDEN_TOP_LEVEL:
            fail(f"mutable/user content found in Fun DraStic package: {relative}")
        if path.name in {"fun-drastic.log", "fundrastic.log", "debug.txt"}:
            fail(f"runtime file found in Fun DraStic package: {relative}")

    launcher_text = launcher.read_text(encoding="utf-8")
    if re.search(r"/dev/input/event\d", launcher_text):
        fail("Fun DraStic launcher hardcodes a physical input node")
    if "SDL_JOYSTICK_DISABLE_UDEV=1" not in launcher_text:
        fail("Fun DraStic launcher must keep SDL_JOYSTICK_DISABLE_UDEV=1")
    # State belongs under USERDATA_PATH. UMRK_INTERNAL_DATA_PATH is
    # launcher-owned control state and may only be read, to find the primary
    # DraStic saves the two packages share.
    state_lines = [
        line
        for line in launcher_text.splitlines()
        if line.lstrip().startswith("STATE_ROOT=")
    ]
    if not state_lines:
        fail("Fun DraStic launcher must define STATE_ROOT")
    if not all("USERDATA_PATH/fun-drastic" in line for line in state_lines):
        fail("Fun DraStic launcher must root its state at USERDATA_PATH/fun-drastic")
    if any("UMRK_INTERNAL_DATA_PATH" in line for line in state_lines):
        fail(
            "Fun DraStic launcher must not store state under "
            "UMRK_INTERNAL_DATA_PATH, which is launcher-owned control state"
        )
    if "LOGS_PATH/fun-drastic.log" not in launcher_text:
        fail("Fun DraStic launcher must log to LOGS_PATH/fun-drastic.log")

    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        fail("Fun DraStic manifest must be a JSON object")
    expected_fields = {
        "id": CORE_ID,
        "platform": "mlp1",
        "kind": "standalone-emulator",
        "binary": "bin/drastic64",
        "entrypoint": "launch.sh",
        "sdl_video_driver": "wayland",
        "package_schema_version": 1,
    }
    for key, expected in expected_fields.items():
        if manifest.get(key) != expected:
            fail(f"Fun DraStic manifest {key} must be {expected!r}")
    # The hook is built from source now, so the release pins the source it came
    # from rather than a binary archive.
    if not SHA256_RE.fullmatch(str(manifest.get("source_funhook_sha256", ""))):
        fail("Fun DraStic manifest must pin the funhook.c it was built from")
    if manifest.get("hook_built_from_source") is not True:
        fail("Fun DraStic manifest must record that the hook was built from source")
    if not str(manifest.get("source_repo", "")).startswith("http"):
        fail("Fun DraStic manifest must record where the source came from")
    if manifest.get("authorization") != "licenses/DISTRIBUTION-BASIS.md":
        fail("Fun DraStic manifest must reference the recorded distribution basis")
    if manifest.get("license") != "PolyForm-Noncommercial-1.0.0":
        fail("Fun DraStic manifest must record the PolyForm Noncommercial licence")
    if manifest.get("distribution_status") != "noncommercial-license":
        fail("Fun DraStic manifest must record its noncommercial distribution status")
    if str(manifest.get("author", "")).lower() != "tenlevels":
        fail("Fun DraStic manifest must credit tenlevels as the author")
    exceptions = json.dumps(manifest.get("exceptions") or [])
    if "not built by UMRK" not in exceptions:
        fail("Fun DraStic manifest must record the prebuilt-binary exception")

    config_version_path = package_dir / "defaults/config.version"
    try:
        config_version = int(config_version_path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError, ValueError) as exc:
        fail(f"invalid Fun DraStic config version: {exc}")
    if manifest.get("config_schema_version") != config_version:
        fail("Fun DraStic manifest config schema does not match defaults/config.version")

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list) or not file_rows:
        fail("Fun DraStic manifest must contain a non-empty files array")
    expected_files: dict[str, str] = {}
    for row in file_rows:
        if not isinstance(row, dict):
            fail("Fun DraStic manifest file rows must be objects")
        relative = safe_manifest_path(row.get("path"))
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            fail(f"invalid checksum for Fun DraStic package path: {relative}")
        if relative == "manifest.json" or relative in expected_files:
            fail(f"duplicate or self-referential Fun DraStic path: {relative}")
        expected_files[relative] = expected_sha

    actual_files = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(expected_files) != actual_files:
        unlisted = sorted(actual_files - set(expected_files))
        missing = sorted(set(expected_files) - actual_files)
        fail(
            "Fun DraStic manifest inventory mismatch; "
            f"unlisted={unlisted}, missing={missing}"
        )
    for relative, expected_sha in expected_files.items():
        if sha256(package_dir / relative) != expected_sha:
            fail(f"Fun DraStic package checksum mismatch: {relative}")

    binary_sha = sha256(binary)
    if manifest.get("binary_sha256") != binary_sha:
        fail("Fun DraStic manifest binary checksum does not match bin/drastic64")

    return len(expected_files), binary_sha


def validate_coexistence(platform_dir: Path) -> None:
    """The primary DraStic package must survive, unchanged and separate."""
    primary_dir = platform_dir / PRIMARY_PACKAGE_REL
    primary_launcher = primary_dir / "launch.sh"
    if not primary_launcher.is_file() or not os.access(primary_launcher, os.X_OK):
        fail("the primary DraStic package must remain staged and executable")
    for name in BUNDLED_BIOS:
        if not (primary_dir / "share/system" / name).is_file():
            fail(f"the primary DraStic package must keep its free BIOS: {name}")

    fun_binary = platform_dir / PACKAGE_REL / "bin/drastic64"
    primary_binary = primary_dir / "bin/drastic64"
    if primary_binary.is_file() and sha256(primary_binary) != sha256(fun_binary):
        # Not fatal on its own, but the two packages are supposed to carry the
        # same prebuilt binary; a divergence means one of them was rebuilt.
        print(
            "warning: drastic64 differs between the DraStic and Fun DraStic "
            "packages; they are expected to be byte-identical"
        )


def validate_no_nintendo_bios(platform_dir: Path) -> None:
    hits = sorted(
        str(path.relative_to(platform_dir))
        for name in FORBIDDEN_BIOS
        for path in platform_dir.rglob(name)
    )
    if hits:
        fail("Nintendo DS BIOS or firmware must never ship: " + ", ".join(hits))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <mlp1-platform-dir>")
    platform_dir = Path(sys.argv[1])
    if not platform_dir.is_dir():
        fail(f"missing MLP1 platform directory: {platform_dir}")

    validate_catalog(platform_dir)
    file_count, binary_sha = validate_package(platform_dir)
    validate_coexistence(platform_dir)
    validate_no_nintendo_bios(platform_dir)

    print(
        "Fun DraStic release gate: "
        f"{CORE_PATH}, {file_count} checksummed files, binary {binary_sha}, "
        "DraStic still the NDS default, no Nintendo BIOS"
    )


if __name__ == "__main__":
    main()
