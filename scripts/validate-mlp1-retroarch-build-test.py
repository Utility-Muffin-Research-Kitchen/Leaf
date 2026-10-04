#!/usr/bin/env python3
"""Check MLP1 RetroArch reuse decisions against the build manifest."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).with_name("validate-mlp1-retroarch-build.py")
PATCHES = {
    "one": "mlp1/0001-one.patch",
    "two": "common/0002-two.patch",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RetroarchReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.builds = root / "retroarch-builds"
        self.binary = self.builds / "output/mlp1/bin/retroarch"
        self.manifest_path = self.builds / "output/mlp1/build-manifest.json"
        self.stamp = self.builds / "output/mlp1/ffmpeg/input-stamp.json"
        for label in PATCHES.values():
            patch = self.builds / "patches" / label
            patch.parent.mkdir(parents=True, exist_ok=True)
            patch.write_text(f"--- a/{label}\n+++ b/{label}\n", encoding="utf-8")
        for script in ("build-mlp1.sh", "fetch-retroarch.sh"):
            (self.builds / script).write_text(f"#!/bin/sh\n# {script}\n", encoding="utf-8")
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"retroarch fixture")
        self.stamp.parent.mkdir(parents=True)
        self.stamp.write_text('{"source_lock_sha256":"test"}\n', encoding="utf-8")
        url = "https://github.com/libretro/RetroArch.git"
        self.manifest = {
            "retroarch_version": "v1.22.2",
            "retroarch_upstream_url": url,
            "source_defaults": {
                "retroarch_version": "v1.22.2",
                "retroarch_upstream_url": url,
            },
            "configure_flags": ["--enable-ssl", "--enable-ffmpeg"],
            "patches_applied": list(PATCHES.values()),
            "patches_sha256": {
                label: sha256(self.builds / "patches" / label)
                for label in PATCHES.values()
            },
            "patch_controls": {"MLP1_PATCH_SET": ",".join(PATCHES)},
            "build_inputs_sha256": {
                script: sha256(self.builds / script)
                for script in ("build-mlp1.sh", "fetch-retroarch.sh")
            },
            "ffmpeg_input_stamp_sha256": sha256(self.stamp),
            "output_binary_sha256": sha256(self.binary),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def check(self) -> subprocess.CompletedProcess[str]:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return subprocess.run([
            sys.executable, str(TOOL), "--binary", str(self.binary),
            "--manifest", str(self.manifest_path),
            "--expected-patch-set", ",".join(PATCHES),
            "--retroarch-builds-dir", str(self.builds),
            "--require-ffmpeg", "--ffmpeg-stamp", str(self.stamp),
        ], text=True, capture_output=True, check=False)

    def assertReusable(self) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reusable:", result.stdout)

    def assertStale(self, reason: str) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stderr.startswith("stale: "), result.stderr)
        self.assertIn(reason, result.stderr)

    def test_current_build_is_reusable(self) -> None:
        self.assertReusable()

    def test_required_ffmpeg_stamp_controls_reuse(self) -> None:
        self.manifest["configure_flags"] = ["--enable-ssl", "--disable-ffmpeg"]
        self.assertStale("recording support")
        self.manifest["configure_flags"] = ["--enable-ssl", "--enable-ffmpeg"]
        self.stamp.write_text('{"source_lock_sha256":"changed"}\n', encoding="utf-8")
        self.assertStale("stamp does not match")

    def test_patch_edited_in_place_is_stale(self) -> None:
        # retroarch-builds #17 and #18 grew command-menu without renaming it.
        patch = self.builds / "patches" / PATCHES["one"]
        patch.write_text(patch.read_text(encoding="utf-8") + "+LOAD_STATE_SYNC\n",
                         encoding="utf-8")
        self.assertStale(f"patch {PATCHES['one']} changed since")

    def test_manifest_from_before_input_hashing_is_stale(self) -> None:
        for key in ("patches_sha256", "build_inputs_sha256", "source_defaults",
                    "output_binary_sha256"):
            del self.manifest[key]
        self.assertStale("does not record patches_sha256; it predates input hashing")

    def test_each_recorded_hash_is_required(self) -> None:
        for key, reason in (
            ("build_inputs_sha256", "does not record build_inputs_sha256"),
            ("source_defaults", "does not record source_defaults"),
            ("output_binary_sha256", "does not record output_binary_sha256"),
        ):
            with self.subTest(key=key):
                value = self.manifest.pop(key)
                self.assertStale(reason)
                self.manifest[key] = value

    def test_malformed_hash_records_are_stale(self) -> None:
        for key, value, reason in (
            ("patches_sha256", list(PATCHES.values()), "does not record patches_sha256"),
            ("patches_sha256", {PATCHES["one"]: "x"}, "does not cover patches_applied"),
            ("patches_sha256", {label: None for label in PATCHES.values()},
             "no patches_sha256 entry"),
            ("patches_applied", [PATCHES["one"]], "patches_applied does not match"),
            ("patches_applied", [PATCHES["one"], 2], "patches_applied does not match"),
            ("build_inputs_sha256", {"fetch-retroarch.sh": "x"}, "build-mlp1.sh hash"),
            ("source_defaults", "v1.22.2", "does not record source_defaults"),
            ("source_defaults", {"retroarch_version": "v1.22.2"},
             "source_defaults.retroarch_upstream_url"),
            ("output_binary_sha256", 7, "does not record output_binary_sha256"),
        ):
            with self.subTest(key=key, value=value):
                saved = self.manifest[key]
                self.manifest[key] = value
                self.assertStale(reason)
                self.manifest[key] = saved

    def test_missing_patch_file_is_stale(self) -> None:
        (self.builds / "patches" / PATCHES["two"]).unlink()
        self.assertStale(f"patch {PATCHES['two']} is missing")

    def test_patch_outside_the_checkout_is_stale(self) -> None:
        escape = "../build-mlp1.sh"
        self.manifest["patches_applied"][1] = escape
        self.manifest["patches_sha256"] = {
            PATCHES["one"]: self.manifest["patches_sha256"][PATCHES["one"]],
            escape: sha256(self.builds / "build-mlp1.sh"),
        }
        self.assertStale("outside the checkout")

    def test_build_script_change_is_stale(self) -> None:
        for script in ("build-mlp1.sh", "fetch-retroarch.sh"):
            with self.subTest(script=script):
                path = self.builds / script
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "# edited\n", encoding="utf-8")
                self.assertStale(f"build input {script} changed since")
                path.write_text(original, encoding="utf-8")

    def test_overridden_retroarch_source_is_stale(self) -> None:
        self.manifest["retroarch_version"] = "master"
        self.assertStale("built from retroarch_version 'master', not the pinned 'v1.22.2'")
        self.manifest["retroarch_version"] = "v1.22.2"
        self.manifest["retroarch_upstream_url"] = "https://example.invalid/RetroArch.git"
        self.assertStale("retroarch_upstream_url")

    def test_binary_replaced_after_build_is_stale(self) -> None:
        self.binary.write_bytes(b"a different retroarch")
        self.assertStale("binary does not match its build manifest")

    def test_missing_checkout_is_stale(self) -> None:
        for script in ("build-mlp1.sh", "fetch-retroarch.sh"):
            (self.builds / script).unlink()
        for label in PATCHES.values():
            (self.builds / "patches" / label).unlink()
        self.assertStale("is missing from")


if __name__ == "__main__":
    unittest.main()
