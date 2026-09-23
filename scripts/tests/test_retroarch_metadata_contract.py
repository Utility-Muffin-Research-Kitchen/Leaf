#!/usr/bin/env python3
"""Contract tests for MLP1 RetroArch core identity and legacy ownership."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1]
LEAF_ROOT = SCRIPT_DIR.parent
UMRK_ROOT = LEAF_ROOT.parent
sys.path.insert(0, str(SCRIPT_DIR))

import retroarch_generate_metadata as generator  # noqa: E402
import retroarch_validate_package as validator  # noqa: E402


GENERATED_DIR = LEAF_ROOT / "config/retroarch/mlp1"
DEVICE_DEFAULTS_DIR = (
    Path(
        os.environ.get(
            "LAUNCHER_SWITCHER_DIR", UMRK_ROOT / "miniloong-launcher-switcher"
        )
    )
    / "device/mlp1/defaults"
)
FAST_UMRK_TEMPLATE = (
    DEVICE_DEFAULTS_DIR
    / "retroarch/core-options/FlyCast Fast UMRK/FlyCast Fast UMRK.opt"
)

# The exact first-launch profile requested for FlyCast Fast UMRK. The template is
# release-owned and must not carry keys from any other Flycast generation.
REQUESTED_FAST_UMRK_OPTIONS = {
    "reicast_internal_resolution": "640x480",
    "reicast_threaded_rendering": "enabled",
    "reicast_synchronous_rendering": "disabled",
    "reicast_alpha_sorting": "per-strip (fast, least accurate)",
    "reicast_enable_dsp": "disabled",
    "reicast_anisotropic_filtering": "disabled",
    "reicast_pvr2_filtering": "disabled",
    "reicast_texupscale": "1",
    "reicast_render_to_texture_upscaling": "1x",
    "reicast_enable_rttb": "disabled",
    "reicast_delay_frame_swapping": "disabled",
    "reicast_frame_skipping": "disabled",
    "reicast_framerate": "fullspeed",
    "reicast_div_matching": "auto",
    "reicast_mipmapping": "enabled",
    "reicast_fog": "enabled",
    "reicast_volume_modifier_enable": "enabled",
    "reicast_gdrom_fast_loading": "enabled",
    "reicast_digital_triggers": "disabled",
    "reicast_cable_type": "TV (Composite)",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def packaged_core_row(core_id: str, config_folder: str) -> dict:
    return {
        "id": core_id,
        "display_name": core_id,
        "type": "retroarch",
        "libretro_name": core_id,
        "file_name": f"{core_id}_libretro.so",
        "config_folder": config_folder,
        "info_name": f"{core_id}_libretro.info",
        "path": None,
        "supports_menu": True,
        "supports_savestate": True,
        "supports_disk_control": False,
        "needs_swap": False,
        "requires_direct_drm": False,
        "platforms": ["mlp1"],
        "status": "packaged",
    }


def parse_core_options(path: Path) -> dict[str, str]:
    options: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        assert separator, f"malformed core option line: {line!r}"
        options[key.strip()] = value.strip().strip('"')
    return options


class FolderPolicyFileTests(unittest.TestCase):
    def test_missing_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(generator, "leaf_repo_from_script", return_value=Path(directory)):
                with self.assertRaisesRegex(FileNotFoundError, "missing canonical system folder policy"):
                    generator.load_system_folder_policy()


class ConfigFolderTests(unittest.TestCase):
    def validate_rows(self, *rows: dict) -> list[str]:
        errors: list[str] = []
        validator.validate_packaged_config_folders(
            {"version": 2, "platform": "mlp1", "cores": list(rows)},
            "test cores",
            errors,
        )
        return errors

    def test_missing_and_unsafe_folders_are_rejected(self) -> None:
        missing = packaged_core_row("missing", "")
        unsafe = packaged_core_row("unsafe", "Core/../../States")
        errors = self.validate_rows(missing, unsafe)
        self.assertTrue(any("non-empty string" in error for error in errors), errors)
        self.assertTrue(any("invalid character U+002F" in error for error in errors), errors)

    def test_runtime_punctuation_is_allowed(self) -> None:
        errors = self.validate_rows(packaged_core_row("gw", "Game & Watch"))
        self.assertEqual([], errors)

    def test_casefold_collisions_are_rejected(self) -> None:
        errors = self.validate_rows(
            packaged_core_row("first", "Example Core"),
            packaged_core_row("second", "example core"),
        )
        self.assertTrue(any("collision" in error for error in errors), errors)

    def test_unpaired_unicode_surrogates_are_rejected_without_crashing(self) -> None:
        for value, codepoint in (("\ud800", "U+D800"), ("\udfff", "U+DFFF")):
            with self.subTest(codepoint=codepoint):
                error = generator.config_folder_error(value)
                self.assertIsNotNone(error)
                self.assertIn(codepoint, error or "")


class CanonicalCatalogTests(unittest.TestCase):
    def test_32x_uses_packaged_picodrive_exclusively(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        self.assertEqual("packaged", cores_by_id["picodrive"]["status"])
        self.assertEqual("PicoDrive", cores_by_id["picodrive"]["config_folder"])
        for system_id in ("32X", "MD32X"):
            self.assertEqual("picodrive", systems_by_id[system_id]["default_core"])
            self.assertEqual([], systems_by_id[system_id]["alternate_cores"])

    def test_32x_core_override_rejects_genesis_plus_gx(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        by_id = {row["id"]: row for row in systems["systems"]}
        by_id["32X"]["default_core"] = "genesis_plus_gx"
        errors = generator.validate_system_core_overrides(
            systems, {row["id"] for row in cores["cores"]}
        )
        self.assertTrue(
            any("32X: default_core must be 'picodrive'" in error for error in errors),
            errors,
        )

    def test_core_override_validator_allows_catalog_without_override_systems(
        self,
    ) -> None:
        systems = {"systems": [{"id": "NES", "default_core": "fceumm"}]}
        self.assertEqual(
            [],
            generator.validate_system_core_overrides(systems, {"fceumm"}),
        )

    def test_phase2_validator_rejects_inventory_core_id_drift(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        phase2_inventory = load_json(GENERATED_DIR / "phase-2-inventory.json")
        packaged_retroarch = [
            row
            for row in cores["cores"]
            if row.get("status") == "packaged" and row.get("type") == "retroarch"
        ]
        inventory = {
            "umrk": {
                "core_files": [row["file_name"] for row in packaged_retroarch],
                "info_files": [row["info_name"] for row in packaged_retroarch],
            }
        }

        for field in ("packaged_core_ids", "missing_core_ids"):
            with self.subTest(field=field):
                drifted = copy.deepcopy(phase2_inventory)
                drifted[field] = list(reversed(drifted[field]))
                errors, _ = validator.validate_phase2_metadata(
                    {
                        "cores": cores,
                        "systems": systems,
                        "phase2_inventory": drifted,
                    },
                    inventory,
                )
                self.assertTrue(
                    any(f"{field} does not match cores.json" in error for error in errors),
                    errors,
                )

    def test_dreamcast_has_standalone_direct_drm_alternate(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        standalone = cores_by_id["flycast_standalone"]
        self.assertEqual("path", standalone["type"])
        self.assertEqual("emulators/flycast/launch.sh", standalone["path"])
        self.assertTrue(standalone["supports_menu"])
        self.assertTrue(standalone["requires_direct_drm"])
        self.assertEqual("flycast_standalone", systems_by_id["DC"]["default_core"])
        self.assertEqual(
            ["flycast", "flycast_fast_umrk", "km_flycast_xtreme"],
            systems_by_id["DC"]["alternate_cores"],
        )

    def test_flycast_fast_umrk_joins_the_dreamcast_family(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        self.assertEqual(
            "FlyCast Fast UMRK",
            generator.MLP1_PACKAGED_CORE_LIBRARY_NAMES["flycast_fast_umrk"],
        )
        self.assertEqual(
            "FlyCast Fast UMRK", generator.humanize_core_id("flycast_fast_umrk")
        )
        self.assertIn("flycast_fast_umrk", generator.KNOWN_DISK_CONTROL_CORES)

        fast = cores_by_id["flycast_fast_umrk"]
        self.assertEqual("retroarch", fast["type"])
        self.assertEqual("FlyCast Fast UMRK", fast["display_name"])
        self.assertEqual("FlyCast Fast UMRK", fast["config_folder"])
        self.assertEqual("flycast_fast_umrk", fast["libretro_name"])
        self.assertEqual("flycast_fast_umrk_libretro.so", fast["file_name"])
        self.assertEqual("flycast_fast_umrk_libretro.info", fast["info_name"])
        self.assertFalse(fast["requires_direct_drm"])
        self.assertTrue(fast["supports_disk_control"])

        for system_id in ("DC", "ATOMISWAVE", "NAOMI"):
            with self.subTest(system=system_id):
                system = systems_by_id[system_id]
                self.assertEqual("flycast_standalone", system["default_core"])
                self.assertEqual(
                    ["flycast", "flycast_fast_umrk", "km_flycast_xtreme"],
                    system["alternate_cores"],
                )

        # Flat saves and states keep the historical libretro owner; the new
        # choice must never inherit them.
        self.assertEqual("flycast", generator.LEGACY_FLAT_CORE_BY_SYSTEM["DC"])
        self.assertEqual("flycast", systems_by_id["DC"]["legacy_flat_core"])

    def test_packaged_flycast_fast_umrk_meets_the_library_name_contract(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        promoted = copy.deepcopy(cores)
        for row in promoted["cores"]:
            if row["id"] == "flycast_fast_umrk":
                row["status"] = "packaged"

        errors = generator.validate_generated(promoted, systems, {})
        self.assertEqual(
            [],
            [error for error in errors if "flycast_fast_umrk" in error],
            errors,
        )

    def test_saturn_has_standalone_direct_drm_alternate(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        standalone = cores_by_id["yabasanshiro_standalone"]
        self.assertEqual("path", standalone["type"])
        self.assertEqual("emulators/yabasanshiro/launch.sh", standalone["path"])
        self.assertTrue(standalone["supports_menu"])
        self.assertTrue(standalone["requires_direct_drm"])
        self.assertEqual("yabasanshiro", systems_by_id["SATURN"]["default_core"])
        self.assertEqual(
            [
                "yabasanshiro_standalone",
                "yabasanshiro_a133p",
                "yabasanshiro_smartpros",
            ],
            systems_by_id["SATURN"]["alternate_cores"],
        )

    def test_pc98_atomiswave_and_naomi_catalog_contract(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        np2kai = cores_by_id["np2kai"]
        self.assertEqual("Neko Project II kai", np2kai["config_folder"])
        self.assertTrue(np2kai["supports_disk_control"])
        self.assertNotIn("nekop2", cores_by_id)

        pc98 = systems_by_id["PC98"]
        self.assertEqual("NEC PC-98", pc98["name"])
        self.assertEqual("np2kai", pc98["default_core"])
        self.assertEqual([], pc98["alternate_cores"])
        self.assertEqual("Roms/PC98", pc98["rom_root"])
        self.assertEqual("Images/PC98", pc98["image_root"])
        self.assertEqual(
            [
                "2hd",
                "88d",
                "98d",
                "cmd",
                "d88",
                "d98",
                "dup",
                "fdd",
                "fdi",
                "hdd",
                "hdi",
                "hdm",
                "hdn",
                "nhd",
                "tfd",
                "thd",
                "xdf",
            ],
            pc98["extensions"],
        )
        self.assertEqual(["zip"], pc98["archive_extensions"])
        self.assertEqual("pass_through", pc98["archive_mode"])
        self.assertEqual([], pc98["playlist_extensions"])
        self.assertEqual(
            ["PC98", "pc98", "necpc98", "NECPC98"],
            pc98["patterns"],
        )
        self.assertEqual(
            [
                "np2kai/font.bmp or np2kai/FONT.ROM "
                "(needed for text, place under BIOS)"
            ],
            pc98["bios_notes"],
        )

        for system_id in ("ATOMISWAVE", "NAOMI"):
            system = systems_by_id[system_id]
            self.assertTrue(system["name_map"])
            self.assertEqual("flycast_standalone", system["default_core"])
            self.assertEqual(
                ["flycast", "flycast_fast_umrk", "km_flycast_xtreme"],
                system["alternate_cores"],
            )
            self.assertEqual(f"Roms/{system_id}", system["rom_root"])
            self.assertEqual(f"Images/{system_id}", system["image_root"])
            self.assertEqual(
                ["cdi", "chd", "cue", "dat", "gdi", "iso"],
                system["extensions"],
            )
            self.assertEqual(["zip"], system["archive_extensions"])
            self.assertEqual("pass_through", system["archive_mode"])
            self.assertEqual(["m3u"], system["playlist_extensions"])
            self.assertEqual([system_id, system_id.lower()], system["patterns"])

        self.assertEqual("Atomiswave", systems_by_id["ATOMISWAVE"]["name"])
        self.assertEqual(
            ["dc/awbios.zip (user-supplied, place under BIOS)"],
            systems_by_id["ATOMISWAVE"]["bios_notes"],
        )
        self.assertEqual(
            [
                "dc/dc_boot.bin (optional/recommended, user-supplied, "
                "place under BIOS)"
            ],
            systems_by_id["DC"]["bios_notes"],
        )
        self.assertEqual("Sega Naomi", systems_by_id["NAOMI"]["name"])
        self.assertEqual(
            [
                "dc/naomi.zip for Naomi and Naomi GD-ROM "
                "(user-supplied, place under BIOS)",
                "dc/naomi2.zip for Naomi 2 "
                "(user-supplied, place under BIOS)",
                "dc/airlbios.zip, dc/f355bios.zip, dc/f355dlx.zip, or "
                "dc/hod2bios.zip when required by a game",
            ],
            systems_by_id["NAOMI"]["bios_notes"],
        )

    def test_amiga_puae_catalog_contract(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        puae = cores_by_id["puae"]
        self.assertEqual("packaged", puae["status"])
        self.assertEqual("PUAE", puae["config_folder"])
        self.assertTrue(puae["supports_disk_control"])
        puae2021 = cores_by_id["puae2021"]
        self.assertEqual("packaged", puae2021["status"])
        self.assertEqual("PUAE 2021", puae2021["config_folder"])
        self.assertTrue(puae2021["supports_disk_control"])

        amiga = systems_by_id["AMIGA"]
        self.assertEqual("Amiga", amiga["name"])
        self.assertEqual(
            ["AMIGA", "Amiga", "amiga", "amiga500", "amiga1200"],
            amiga["patterns"],
        )
        self.assertEqual("puae2021", amiga["default_core"])
        self.assertEqual(["puae"], amiga["alternate_cores"])
        self.assertEqual("Roms/AMIGA", amiga["rom_root"])
        self.assertEqual("Images/AMIGA", amiga["image_root"])
        self.assertEqual(
            [
                "adf",
                "adz",
                "ccd",
                "chd",
                "cue",
                "dms",
                "fdi",
                "hdf",
                "hdz",
                "iso",
                "lha",
                "mds",
                "nrg",
                "raw",
                "rp9",
                "uae",
            ],
            amiga["extensions"],
        )
        self.assertEqual(["7z", "zip"], amiga["archive_extensions"])
        self.assertEqual("pass_through", amiga["archive_mode"])
        self.assertEqual(["m3u"], amiga["playlist_extensions"])
        self.assertEqual("manual", amiga["m3u_generation"])
        self.assertEqual(
            [
                "puae/Kickstart ROMs and rom.key when required "
                "(user-supplied, place under BIOS)"
            ],
            amiga["bios_notes"],
        )
        for excluded in ("ipf", "slave", "info"):
            self.assertNotIn(excluded, amiga["extensions"])
            self.assertNotIn(excluded, amiga["archive_inner_extensions"])
        self.assertNotIn("PUAE", systems_by_id)

    def test_unrelated_upstream_alias_drift_is_not_swept_in(self) -> None:
        systems = load_json(GENERATED_DIR / "systems.json")
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        self.assertEqual(
            ["MD", "GENESIS", "md", "MEGADRIVE", "megadrive", "GEN"],
            systems_by_id["MD"]["patterns"],
        )
        self.assertEqual(
            ["MS", "MASTERSYSTEM", "ms", "SMS", "sms"],
            systems_by_id["MS"]["patterns"],
        )
        self.assertEqual(
            ["mame2003_plus"],
            systems_by_id["MAME"]["alternate_cores"],
        )
        self.assertNotIn("tg16", systems_by_id["PCE"]["patterns"])
        self.assertNotIn("snesna", systems_by_id["SFC"]["patterns"])

    def test_pattern_overrides_reject_unreviewed_upstream_aliases(self) -> None:
        known = generator.validate_system_pattern_override(
            "PC98",
            {"patterns": ["NINETYEIGHT", "PCNINETYEIGHT", "pc98"]},
            {
                "id": "PC98",
                "alternative_folder_names": ["necpc98", "NECPC98"],
            },
        )
        self.assertEqual([], known)

        errors = generator.validate_system_pattern_override(
            "PC98",
            {"patterns": ["NINETYEIGHT", "FUTUREPC98"]},
            None,
        )
        self.assertEqual(
            ["PC98: unreviewed upstream folder patterns: ['FUTUREPC98']"],
            errors,
        )

    def test_ppsspp_has_vulkan_default_and_gles_fallback(self) -> None:
        cores = load_json(GENERATED_DIR / "cores.json")
        systems = load_json(GENERATED_DIR / "systems.json")
        cores_by_id = {row["id"]: row for row in cores["cores"]}
        systems_by_id = {row["id"]: row for row in systems["systems"]}

        self.assertTrue(cores_by_id["ppsspp"]["requires_direct_drm"])
        self.assertEqual(
            "emulators/ppsspp/launch.sh", cores_by_id["ppsspp"]["path"]
        )
        self.assertFalse(cores_by_id["ppsspp_gles"]["requires_direct_drm"])
        self.assertEqual(
            "emulators/ppsspp/launch-gles.sh",
            cores_by_id["ppsspp_gles"]["path"],
        )
        self.assertEqual("ppsspp", systems_by_id["PSP"]["default_core"])
        self.assertIn(
            "ppsspp_gles", systems_by_id["PSP"]["alternate_cores"]
        )

    def test_seven_corrected_runtime_names_are_canonical(self) -> None:
        expected = {
            "dosbox_pure": "DOSBox-pure",
            "fake08": "fake-08",
            "gw": "Game & Watch",
            "mame": "MAME",
            "mame2010": "MAME 2010",
            "mupen64plus_next": "Mupen64Plus-Next",
            "pcsx_rearmed": "PCSX-ReARMed",
        }
        self.assertEqual(
            expected,
            {
                core_id: generator.MLP1_PACKAGED_CORE_LIBRARY_NAMES[core_id]
                for core_id in expected
            },
        )

        generated = load_json(GENERATED_DIR / "cores.json")
        generated_by_id = {row["id"]: row for row in generated["cores"]}
        self.assertEqual(
            expected,
            {core_id: generated_by_id[core_id]["config_folder"] for core_id in expected},
        )

    def test_generated_and_device_defaults_are_identical(self) -> None:
        for file_name in ("cores.json", "systems.json"):
            self.assertEqual(
                (GENERATED_DIR / file_name).read_bytes(),
                (DEVICE_DEFAULTS_DIR / file_name).read_bytes(),
                file_name,
            )

    def test_system_v2_owners_are_exact_and_ambiguous_systems_are_unset(self) -> None:
        systems = load_json(GENERATED_DIR / "systems.json")
        self.assertEqual(2, systems["version"])
        by_id = {row["id"]: row for row in systems["systems"]}
        actual = {
            system_id: row["legacy_flat_core"]
            for system_id, row in by_id.items()
            if "legacy_flat_core" in row
        }
        self.assertEqual(generator.LEGACY_FLAT_CORE_BY_SYSTEM, actual)
        for system_id in ("ARCADE", "GB", "GBC", "MAME", "NEOGEO", "PS"):
            self.assertNotIn("legacy_flat_core", by_id[system_id])


class FlycastFastUmrkDefaultsTests(unittest.TestCase):
    def test_template_carries_the_requested_twenty_settings(self) -> None:
        self.assertTrue(FAST_UMRK_TEMPLATE.is_file(), FAST_UMRK_TEMPLATE)
        options = parse_core_options(FAST_UMRK_TEMPLATE)
        self.assertEqual(20, len(options), sorted(options))
        self.assertEqual(REQUESTED_FAST_UMRK_OPTIONS, options)


class BuildReportContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        (self.root / "cores").mkdir()
        (self.root / "info").mkdir()
        self.core_bytes = b"MLP1 test core artifact\n"
        self.core_file = "test_core_libretro.so"
        (self.root / "cores" / self.core_file).write_bytes(self.core_bytes)
        (self.root / "info/test_core_libretro.info").write_text(
            "display_name = Test Core\n", encoding="utf-8"
        )
        self.sha256 = hashlib.sha256(self.core_bytes).hexdigest()
        self.core = packaged_core_row("test_core", "Test Core")
        self.metadata = {
            "cores": {"version": 2, "platform": "mlp1", "cores": [self.core]},
            "systems": {},
        }
        self.inventory = {
            "umrk": {
                "core_files": [self.core_file],
                "info_files": ["test_core_libretro.info"],
            }
        }
        self.report = {
            "version": 2,
            "platform": "mlp1",
            # Reports carry the identity of the builder that produced them; a
            # release gate compares it against the current build-mlp1.sh. The
            # fixture supplies one so these tests stay focused on their own
            # subject rather than tripping the staleness warning.
            "builder_script_sha256": "0" * 64,
            "builder_commit": "0" * 40,
            "status": "passed",
            "requested_count": 1,
            "built_count": 1,
            "failed_count": 0,
            "deferred_count": 0,
            "library_name_count": 1,
            "library_name_status": "complete",
            "cores": [
                {
                    "core": "test_core",
                    "status": "built",
                    "core_file": self.core_file,
                    "info_file": "test_core_libretro.info",
                    "reason": "",
                    "library_name": "Test Core",
                    "library_name_source": "container",
                    "sha256": self.sha256,
                }
            ],
        }

    def validate_report(self, report: dict) -> tuple[list[str], list[str]]:
        return validator.validate_build_report(
            self.root / "build-report.json",
            report,
            self.inventory,
            self.metadata,
        )

    def validate_generator_report(
        self, report: dict, core_doc: dict | None = None
    ) -> list[str]:
        report_path = self.root / "build-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return generator.validate_build_report_contract(
            report_path, core_doc or self.metadata["cores"]
        )

    def test_exact_runtime_name_and_checksum_pass(self) -> None:
        errors, warnings = self.validate_report(self.report)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual([], self.validate_generator_report(self.report))

    def test_report_rejects_missing_probe_source(self) -> None:
        report = copy.deepcopy(self.report)
        del report["cores"][0]["library_name_source"]
        errors, _ = self.validate_report(report)
        self.assertTrue(any("library_name_source" in error for error in errors), errors)

    def test_generator_rejects_every_identity_mismatch(self) -> None:
        cases = (
            ("core", "wrong_core", "unexpected core"),
            ("core_file", "wrong_libretro.so", "core_file mismatch"),
            ("info_file", "wrong_libretro.info", "info_file mismatch"),
            ("library_name", "Test Core Alias", "library_name mismatch"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report["cores"][0][field] = value
                errors = self.validate_generator_report(report)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_generator_rejects_partial_report(self) -> None:
        second = packaged_core_row("second_core", "Second Core")
        core_doc = copy.deepcopy(self.metadata["cores"])
        core_doc["cores"].append(second)
        errors = self.validate_generator_report(self.report, core_doc)
        self.assertTrue(
            any("missing packaged core: second_core" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("packaged core count" in error for error in errors),
            errors,
        )

    def test_generator_rejects_checksum_mismatch_against_actual_artifact(self) -> None:
        report = copy.deepcopy(self.report)
        report["cores"][0]["sha256"] = "0" * 64
        errors = self.validate_generator_report(report)
        self.assertTrue(any("checksum mismatch" in error for error in errors), errors)

    def test_generator_requires_v2_complete_passed_summary(self) -> None:
        cases = (
            ("version", 1, "version"),
            ("status", "failed", "status"),
            ("built_count", 0, "built_count"),
            ("library_name_count", 0, "library_name_count"),
            ("library_name_status", "pending", "library_name_status"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report[field] = value
                errors = self.validate_generator_report(report)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_generator_main_uses_default_report_and_writes_nothing_on_failure(self) -> None:
        output_dir = self.root / "generated"
        core_doc = self.metadata["cores"]
        system_doc = {"version": 2, "platform": "mlp1", "systems": []}
        expected_report = (
            self.root.resolve() / "Cores-spruce/output/mlp1/build-report.json"
        )
        with (
            mock.patch.object(generator.retroarch_inventory, "build_inventory", return_value={}),
            mock.patch.object(generator, "parse_stock_parity_cores", return_value=[]),
            mock.patch.object(generator, "build_core_catalog", return_value=core_doc),
            mock.patch.object(generator, "build_system_catalog", return_value=system_doc),
            mock.patch.object(generator, "validate_generated", return_value=[]),
            mock.patch.object(
                generator, "validate_system_pattern_overrides", return_value=[]
            ),
            mock.patch.object(
                generator,
                "validate_build_report_contract",
                return_value=["synthetic build-report failure"],
            ) as report_gate,
            mock.patch("sys.stderr", new=io.StringIO()),
        ):
            result = generator.main(
                [
                    "--umrk-root",
                    str(self.root),
                    "--allium-root",
                    str(self.root),
                    "--spruce-root",
                    str(self.root),
                    "--output-dir",
                    str(output_dir),
                ]
            )
        self.assertEqual(1, result)
        self.assertFalse(output_dir.exists())
        self.assertEqual(expected_report, report_gate.call_args.args[0])

    def test_runtime_name_mismatch_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["cores"][0]["library_name"] = "Test Core Alias"
        errors, _ = self.validate_report(report)
        self.assertTrue(any("library_name mismatch" in error for error in errors), errors)

    def test_checksum_mismatch_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["cores"][0]["sha256"] = "0" * 64
        errors, _ = self.validate_report(report)
        self.assertTrue(any("checksum mismatch" in error for error in errors), errors)

    def test_identity_summary_fields_are_required(self) -> None:
        cases = (
            ("built_count", 0, "built_count"),
            ("library_name_count", 0, "library_name_count"),
            ("library_name_status", "incomplete", "library_name_status"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report[field] = value
                errors, _ = self.validate_report(report)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

    def test_targeted_report_is_rejected_when_full_report_is_required(self) -> None:
        second = packaged_core_row("second_core", "Second Core")
        second_bytes = b"second MLP1 test core artifact\n"
        (self.root / "cores" / second["file_name"]).write_bytes(second_bytes)
        metadata = copy.deepcopy(self.metadata)
        metadata["cores"]["cores"].append(second)
        inventory = copy.deepcopy(self.inventory)
        inventory["umrk"]["core_files"].append(second["file_name"])
        inventory["umrk"]["info_files"].append(second["info_name"])

        errors, _ = validator.validate_build_report(
            self.root / "build-report.json",
            self.report,
            inventory,
            metadata,
            require_full=True,
        )
        self.assertTrue(
            any(
                error == f"full build report missing packaged core result: {second['file_name']}"
                for error in errors
            ),
            errors,
        )

    def test_partial_report_is_rejected_when_validating_full_package(self) -> None:
        core_doc = load_json(GENERATED_DIR / "cores.json")
        system_doc = load_json(GENERATED_DIR / "systems.json")
        metadata = {
            "cores": core_doc,
            "systems": system_doc,
            "phase2_inventory": {},
        }
        packaged = [
            row
            for row in core_doc["cores"]
            if row.get("type") == "retroarch" and row.get("status") == "packaged"
        ]
        package_root = self.root / "package"
        for directory in ("defaults", "bin", "cores", "info"):
            (package_root / directory).mkdir(parents=True, exist_ok=True)
        (package_root / "manifest.json").write_text(
            json.dumps({"platform": "mlp1"}), encoding="utf-8"
        )
        (package_root / "defaults/cores.json").write_text(
            json.dumps(core_doc), encoding="utf-8"
        )
        (package_root / "defaults/systems.json").write_text(
            json.dumps(system_doc), encoding="utf-8"
        )
        retroarch = package_root / "bin/retroarch"
        retroarch.write_text("#!/bin/sh\n", encoding="utf-8")
        retroarch.chmod(0o755)
        for row in packaged:
            (package_root / "cores" / row["file_name"]).write_bytes(b"")
            (package_root / "info" / row["info_name"]).write_bytes(b"")

        one = packaged[0]
        partial_report = {
            "requested_count": 1,
            "cores": [
                {
                    "core": one["id"],
                    "status": "built",
                    "core_file": one["file_name"],
                    "info_file": one["info_name"],
                    "library_name": one["config_folder"],
                    "library_name_source": "container",
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }
            ],
        }
        inventory = {
            "umrk": {
                "core_files": [row["file_name"] for row in packaged],
                "info_files": [row["info_name"] for row in packaged],
            }
        }
        errors, _ = validator.validate_package_root(
            package_root,
            inventory,
            metadata,
            partial_report,
        )
        missing = [
            error for error in errors if "package contract build report missing core" in error
        ]
        self.assertEqual(len(packaged) - 1, len(missing), errors)


class BuilderIdentityTests(unittest.TestCase):
    """The gate that detects artifacts left over from an earlier builder.

    Every other build-report check asks whether the report is internally
    consistent. A stale artifact satisfies all of them, so staleness is only
    visible by comparing the report against the builder that should have
    produced it.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.script = Path(self.tmp.name) / "build-mlp1.sh"
        self.script.write_text("#!/usr/bin/env bash\necho current\n")
        self.current = validator.sha256_file(self.script)

    def test_matching_identity_is_silent(self) -> None:
        errors, warnings = validator.validate_builder_identity(
            {"builder_script_sha256": self.current}, self.script, True
        )
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_stale_identity_fails_when_fresh_required(self) -> None:
        errors, warnings = validator.validate_builder_identity(
            {"builder_script_sha256": "0" * 64, "builder_commit": "deadbeef"},
            self.script,
            True,
        )
        self.assertEqual([], warnings)
        self.assertEqual(1, len(errors))
        self.assertIn("stale", errors[0])
        self.assertIn("deadbeef", errors[0])

    def test_stale_identity_only_warns_without_the_flag(self) -> None:
        errors, warnings = validator.validate_builder_identity(
            {"builder_script_sha256": "0" * 64}, self.script, False
        )
        self.assertEqual([], errors)
        self.assertEqual(1, len(warnings))
        self.assertIn("stale", warnings[0])

    def test_report_predating_identity_recording_fails_when_required(self) -> None:
        errors, warnings = validator.validate_builder_identity({}, self.script, True)
        self.assertEqual([], warnings)
        self.assertEqual(1, len(errors))
        self.assertIn("builder_script_sha256", errors[0])

    def test_report_predating_identity_recording_warns_otherwise(self) -> None:
        errors, warnings = validator.validate_builder_identity({}, self.script, False)
        self.assertEqual([], errors)
        self.assertEqual(1, len(warnings))

    def test_non_digest_is_always_an_error(self) -> None:
        errors, _ = validator.validate_builder_identity(
            {"builder_script_sha256": "nope"}, self.script, False
        )
        self.assertEqual(1, len(errors))
        self.assertIn("not a sha256 digest", errors[0])

    def test_missing_builder_script_is_an_error(self) -> None:
        errors, _ = validator.validate_builder_identity(
            {"builder_script_sha256": self.current},
            Path(self.tmp.name) / "absent.sh",
            True,
        )
        self.assertEqual(1, len(errors))
        self.assertIn("builder script missing", errors[0])

    def test_check_is_silent_when_not_requested_and_no_script_given(self) -> None:
        errors, warnings = validator.validate_builder_identity({}, None, False)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)


if __name__ == "__main__":
    unittest.main()
