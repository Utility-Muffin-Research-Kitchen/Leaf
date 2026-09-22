#!/usr/bin/env python3
"""Device staging must refresh managed cores without erasing local extras.

A developer card carries experiment cores and info files beside the shipped
set. Replacing cores/ and info/ wholesale deletes them, so both the full stage
bundle and stage-retroarch refresh those directories by managed name. These
checks run the real staging script against a simulated device tree.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parent.parent
HELPER = LEAF_ROOT / "scripts" / "adb-replace-managed-files.sh"
BUNDLE_STAGER = LEAF_ROOT / "scripts" / "adb-stage-sd-bundle.sh"

REMOTE_SD = "/mnt/sdcard"
REMOTE_PLATFORM = f"{REMOTE_SD}/.system/leaf/platforms/mlp1"
EXPERIMENT_CORE = "flycast_2022uniformpgo_libretro.so"
EXPERIMENT_INFO = "flycast_2022uniformpgo_libretro.info"

# Minimal adb stand-in. It models the device as a directory tree so the staging
# scripts really delete and copy files, and it rewrites the card path into that
# tree so nothing touches a real device or a real mount point.
FAKE_ADB = r"""#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >>"$FAKE_ADB_LOG"
[ "${1:-}" = "-s" ] && shift 2
command="${1:-}"
shift || true
translate() {
    printf '%s' "${1//\/mnt\/sdcard/$FAKE_ADB_DEVICE/mnt/sdcard}"
}
case "$command" in
    get-serialno)
        printf 'fixture-device\n'
        ;;
    devices)
        printf 'List of devices attached\nfixture-device\tdevice\n'
        ;;
    push)
        source="$1"
        destination="$(translate "$2")"
        mkdir -p "$destination"
        cp -R "$source" "$destination/"
        ;;
    shell)
        case "$*" in
            *'/proc/mounts'*) exit 0 ;;
        esac
        sh -c "$(translate "$*")"
        ;;
esac
exit 0
"""


class FakeDevice:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.log = root / "adb.log"
        self.device = root / "device"
        self.bin.mkdir(parents=True)
        self.log.write_text("", encoding="utf-8")
        adb = self.bin / "adb"
        adb.write_text(FAKE_ADB, encoding="utf-8")
        adb.chmod(0o755)

    @property
    def platform(self) -> Path:
        return self.device / REMOTE_PLATFORM.lstrip("/")

    def env(self, **extra: str) -> dict:
        return dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            ADB_SERIAL="fixture-device",
            FAKE_ADB_LOG=str(self.log),
            FAKE_ADB_DEVICE=str(self.device),
            **extra,
        )

    def commands(self) -> list:
        return self.log.read_text(encoding="utf-8").splitlines()


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ManagedFileReplacementTests(unittest.TestCase):
    def test_removes_only_the_names_the_payload_manages(self):
        with tempfile.TemporaryDirectory() as raw:
            device = FakeDevice(Path(raw))
            local = Path(raw) / "local-cores"
            write(local / "alpha_libretro.so", b"new alpha\n")
            write(local / "beta_libretro.so", b"new beta\n")
            write(local / "notes.txt", b"not a core\n")
            (device.platform / "cores").mkdir(parents=True)

            subprocess.run(
                [
                    "bash",
                    str(HELPER),
                    f"{REMOTE_PLATFORM}/cores",
                    str(local),
                    "*_libretro.so",
                ],
                check=True,
                env=device.env(),
            )

            deletes = [line for line in device.commands() if "rm -f" in line]
            self.assertEqual(len(deletes), 1)
            self.assertIn(f"cd '{REMOTE_PLATFORM}/cores'", deletes[0])
            self.assertIn("'alpha_libretro.so'", deletes[0])
            self.assertIn("'beta_libretro.so'", deletes[0])
            self.assertNotIn("notes.txt", deletes[0])
            self.assertFalse(
                any("rm -rf" in line for line in device.commands()),
                device.commands(),
            )

    def test_skips_the_device_when_there_is_nothing_to_replace(self):
        with tempfile.TemporaryDirectory() as raw:
            device = FakeDevice(Path(raw))
            subprocess.run(
                [
                    "bash",
                    str(HELPER),
                    f"{REMOTE_PLATFORM}/info",
                    str(Path(raw) / "missing-info"),
                    "*_libretro.info",
                ],
                check=True,
                env=device.env(),
            )
            self.assertEqual(device.commands(), [])

    def test_creates_the_remote_directory_on_a_clean_card(self):
        with tempfile.TemporaryDirectory() as raw:
            device = FakeDevice(Path(raw))
            local = Path(raw) / "local-cores"
            write(local / "alpha_libretro.so", b"new alpha\n")

            subprocess.run(
                [
                    "bash",
                    str(HELPER),
                    f"{REMOTE_PLATFORM}/cores",
                    str(local),
                    "*_libretro.so",
                ],
                check=True,
                env=device.env(),
            )

            self.assertTrue((device.platform / "cores").is_dir())

    def test_rejects_a_filename_that_cannot_be_shell_quoted(self):
        with tempfile.TemporaryDirectory() as raw:
            device = FakeDevice(Path(raw))
            local = Path(raw) / "local-cores"
            write(local / "bad'quote_libretro.so", b"bad\n")

            result = subprocess.run(
                [
                    "bash",
                    str(HELPER),
                    f"{REMOTE_PLATFORM}/cores",
                    str(local),
                    "*_libretro.so",
                ],
                env=device.env(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(device.commands(), [])


class BundleStagingTests(unittest.TestCase):
    def stage_bundle(self, raw: str) -> FakeDevice:
        device = FakeDevice(Path(raw))
        bundle = Path(raw) / "bundle"
        platform = bundle / ".system/leaf/platforms/mlp1"
        write(platform / "launcher/bin/loong_pangu", b"#!/bin/sh\nexit 0\n")
        (platform / "launcher/bin/loong_pangu").chmod(0o755)
        write(platform / "cores/alpha_libretro.so", b"new alpha\n")
        write(platform / "info/alpha_libretro.info", b"new alpha info\n")
        write(platform / "defaults/cores.json", b'{"cores": []}\n')

        write(device.platform / "cores/alpha_libretro.so", b"old alpha\n")
        write(device.platform / "cores" / EXPERIMENT_CORE, b"experiment core\n")
        write(device.platform / "info/alpha_libretro.info", b"old alpha info\n")
        write(device.platform / "info" / EXPERIMENT_INFO, b"experiment info\n")
        write(device.platform / "bin/stale-runtime", b"stale\n")

        subprocess.run(
            ["bash", str(BUNDLE_STAGER)],
            check=True,
            env=device.env(
                BUNDLE_ROOT=str(bundle),
                PLATFORM_ID="mlp1",
                REMOTE_SDCARD_PATH=REMOTE_SD,
            ),
            capture_output=True,
        )
        return device

    def test_staging_keeps_local_experiment_cores_and_info(self):
        with tempfile.TemporaryDirectory() as raw:
            device = self.stage_bundle(raw)
            cores = device.platform / "cores"
            info = device.platform / "info"

            self.assertEqual(
                (cores / EXPERIMENT_CORE).read_bytes(), b"experiment core\n"
            )
            self.assertEqual(
                (info / EXPERIMENT_INFO).read_bytes(), b"experiment info\n"
            )
            # The managed core is replaced, and the release-owned runtime tree
            # is still replaced wholesale.
            self.assertEqual(
                (cores / "alpha_libretro.so").read_bytes(), b"new alpha\n"
            )
            self.assertEqual(
                (info / "alpha_libretro.info").read_bytes(), b"new alpha info\n"
            )
            self.assertFalse((device.platform / "bin/stale-runtime").exists())

    def test_staging_never_deletes_the_cores_or_info_directories(self):
        with tempfile.TemporaryDirectory() as raw:
            device = self.stage_bundle(raw)
            commands = device.commands()
            for directory in ("cores", "info"):
                self.assertFalse(
                    any(
                        "rm -rf" in line and f"{REMOTE_PLATFORM}/{directory}'" in line
                        for line in commands
                    ),
                    commands,
                )
            self.assertTrue(
                any(
                    "rm -f" in line and f"cd '{REMOTE_PLATFORM}/cores'" in line
                    for line in commands
                ),
                commands,
            )


class StageRetroarchWiringTests(unittest.TestCase):
    def test_stage_retroarch_refreshes_cores_and_info_by_managed_name(self):
        recipe = (LEAF_ROOT / "stage" / "mlp1.mk").read_text(encoding="utf-8")
        self.assertNotIn("rm -rf '$$remote_platform/cores'", recipe)
        self.assertNotIn("rm -rf '$$remote_platform/info'", recipe)
        self.assertEqual(recipe.count("adb-replace-managed-files.sh"), 2)

    def test_recipe_comments_never_continue_a_shell_block(self):
        # A comment line placed after a trailing backslash is joined into the
        # running shell command and fails as "@#: command not found".
        lines = (LEAF_ROOT / "stage" / "mlp1.mk").read_text(
            encoding="utf-8"
        ).splitlines()
        for index, line in enumerate(lines[1:], start=1):
            if line.strip().startswith("@#"):
                self.assertFalse(
                    lines[index - 1].rstrip().endswith("\\"),
                    f"stage/mlp1.mk:{index + 1} continues a shell block",
                )


if __name__ == "__main__":
    unittest.main()
