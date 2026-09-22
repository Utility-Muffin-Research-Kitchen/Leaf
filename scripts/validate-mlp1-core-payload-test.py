#!/usr/bin/env python3
"""Focused checks for the MLP1 core payload gate."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate-mlp1-core-payload.py")
LEAF_ROOT = SCRIPT.parent.parent
SPEC = importlib.util.spec_from_file_location("validate_mlp1_core_payload", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CORE = "flycast_fast_umrk"
CORE_FILE = f"{CORE}_libretro.so"
INFO_FILE = f"{CORE}_libretro.info"
CONFIG_FOLDER = "FlyCast Fast UMRK"


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class PayloadTests(unittest.TestCase):
    def make_payload(self, base: Path) -> Path:
        platform = base / "platforms" / "mlp1"
        core_bytes = b"\x7fELF fixture core\n"
        write(platform / "cores" / CORE_FILE, core_bytes)
        write(platform / "info" / INFO_FILE, b"display_name = \"FlyCast Fast UMRK\"\n")
        write(
            platform / "defaults" / "cores.json",
            json.dumps(
                {
                    "cores": [
                        {
                            "id": CORE,
                            "display_name": "FlyCast Fast UMRK",
                            "type": "retroarch",
                            "libretro_name": CORE,
                            "file_name": CORE_FILE,
                            "config_folder": CONFIG_FOLDER,
                            "info_name": INFO_FILE,
                            "path": None,
                            "status": "packaged",
                        }
                    ]
                }
            ).encode(),
        )
        write(
            platform / "cores" / "build-report.json",
            json.dumps(
                {
                    "version": 2,
                    "platform": "mlp1",
                    "status": "passed",
                    "library_name_status": "complete",
                    "cores": [
                        {
                            "core": CORE,
                            "core_file": CORE_FILE,
                            "sha256": hashlib.sha256(core_bytes).hexdigest(),
                            "status": "built",
                            "library_name": "FlyCast Fast UMRK",
                            "library_name_source": "container",
                            "build_action": "compiled",
                        }
                    ],
                }
            ).encode(),
        )
        write(
            platform
            / "defaults"
            / "retroarch"
            / "core-options"
            / CONFIG_FOLDER
            / f"{CONFIG_FOLDER}.opt",
            b'reicast_internal_resolution = "640x480"\n',
        )
        return platform

    def validate(self, platform: Path) -> None:
        MODULE.validate_core(
            platform,
            platform / "cores",
            platform / "info",
            platform / "cores" / "build-report.json",
            CORE,
        )

    def test_accepts_a_complete_core_payload(self):
        with tempfile.TemporaryDirectory() as raw:
            self.validate(self.make_payload(Path(raw)))

    def test_rejects_missing_core_binary(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            (platform / "cores" / CORE_FILE).unlink()
            with self.assertRaisesRegex(MODULE.PayloadError, "core binary"):
                self.validate(platform)

    def test_rejects_missing_info_file(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            (platform / "info" / INFO_FILE).unlink()
            with self.assertRaisesRegex(MODULE.PayloadError, "info file"):
                self.validate(platform)

    def test_rejects_stale_binary_against_the_report(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            write(platform / "cores" / CORE_FILE, b"\x7fELF replaced core\n")
            with self.assertRaisesRegex(MODULE.PayloadError, "checksum"):
                self.validate(platform)

    def test_rejects_unverified_report(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            report_path = platform / "cores" / "build-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["library_name_status"] = "pending"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PayloadError, "not verified"):
                self.validate(platform)

    def test_rejects_missing_probe_source(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            report_path = platform / "cores" / "build-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            del report["cores"][0]["library_name_source"]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PayloadError, "probe source"):
                self.validate(platform)

    def test_rejects_catalog_entry_that_is_not_packaged(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            catalog_path = platform / "defaults" / "cores.json"
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog["cores"][0]["status"] = "available"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PayloadError, "not 'packaged'"):
                self.validate(platform)

    def test_rejects_missing_default_settings_template(self):
        with tempfile.TemporaryDirectory() as raw:
            platform = self.make_payload(Path(raw))
            (
                platform
                / "defaults"
                / "retroarch"
                / "core-options"
                / CONFIG_FOLDER
                / f"{CONFIG_FOLDER}.opt"
            ).unlink()
            with self.assertRaisesRegex(MODULE.PayloadError, "default settings"):
                self.validate(platform)


class WiringTests(unittest.TestCase):
    """The gate has to run before a device payload is replaced or a ZIP is cut."""

    def test_stage_retroarch_gates_before_replacing_the_device_payload(self):
        recipe = (LEAF_ROOT / "stage" / "mlp1.mk").read_text(encoding="utf-8")
        wipe = recipe.index("rm -rf '$$remote_platform/bin'")
        gate = recipe.rindex("validate-mlp1-core-payload.py")
        self.assertLess(gate, wipe)

    def test_release_zip_builder_gates_the_assembled_payload(self):
        script = (LEAF_ROOT / "scripts" / "make-sd-release-zip.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("validate-mlp1-core-payload.py", script)


if __name__ == "__main__":
    unittest.main()
