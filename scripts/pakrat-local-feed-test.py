#!/usr/bin/env python3
"""Host tests for the multi-app Pak Rat local-feed generator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import warnings
import zipfile


LEAF_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = LEAF_ROOT / "scripts" / "pakrat-local-feed.py"
OUTPUT_BASE = LEAF_ROOT / "build" / "pakrat-local"
MATCH_METADATA = object()


class LocalFeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="leaf-pakrat-apps.")
        self.apps_root = Path(self.temp.name)
        self.output = OUTPUT_BASE / f"test-{uuid.uuid4().hex}"

    def tearDown(self) -> None:
        shutil.rmtree(self.output, ignore_errors=True)
        self.temp.cleanup()

    def write_app(
        self,
        directory: str,
        app_id: str,
        install_name: str,
        artifact_name: str,
        version: str = "1.0.0",
        min_leaf_version: str | None = None,
        runtime_min_leaf_version: str | None | object = MATCH_METADATA,
        kind: str | None = None,
        provides: dict | None = None,
        platform: str = "mlp1",
    ) -> Path:
        app_dir = self.apps_root / directory
        package_dir = app_dir / "build" / "mlp1" / "package" / install_name
        package_dir.mkdir(parents=True)
        runtime = {
            "name": directory,
            "icon": "res/icon.png",
            "platform": "mlp1",
            "pak_version": version,
        }
        runtime_minimum = (
            min_leaf_version
            if runtime_min_leaf_version is MATCH_METADATA
            else runtime_min_leaf_version
        )
        if runtime_minimum is not None:
            runtime["min_leaf_version"] = runtime_minimum
        if provides is not None:
            runtime["provides"] = provides
        (package_dir / "pak.json").write_text(
            json.dumps(runtime) + "\n", encoding="utf-8"
        )
        (package_dir / "payload.bin").write_bytes(f"payload-{app_id}".encode())
        metadata = {
            "schema": 1,
            "id": app_id,
            "name": directory,
            "summary": f"{directory} summary",
            "description": f"{directory} description",
            "author": "Test",
            "repo_url": f"https://example.invalid/{directory}",
            "categories": ["test"],
            "leaf": {
                "packages": [
                    {
                        "platform": platform,
                        "version": version,
                        "artifact_name": artifact_name,
                        "install_name": install_name,
                        "runtime_manifest_path": "pak.json",
                        "package_dir": str(package_dir.relative_to(app_dir)),
                        "build_command": ["false"],
                    }
                ]
            },
        }
        if min_leaf_version is not None:
            metadata["leaf"]["packages"][0]["min_leaf_version"] = min_leaf_version
        if kind is not None:
            metadata["kind"] = kind
        (app_dir / "pakrat.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return app_dir

    def update_app(
        self,
        app_dir: Path,
        version: str,
        min_leaf_version: str | None,
        *,
        runtime_min_leaf_version: str | None | object = MATCH_METADATA,
        payload: bytes | None = None,
    ) -> None:
        metadata_path = app_dir / "pakrat.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        package = metadata["leaf"]["packages"][0]
        package["version"] = version
        if min_leaf_version is None:
            package.pop("min_leaf_version", None)
        else:
            package["min_leaf_version"] = min_leaf_version
        metadata_path.write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )

        package_dir = app_dir / package["package_dir"]
        runtime_path = package_dir / package["runtime_manifest_path"]
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["pak_version"] = version
        runtime_minimum = (
            min_leaf_version
            if runtime_min_leaf_version is MATCH_METADATA
            else runtime_min_leaf_version
        )
        if runtime_minimum is None:
            runtime.pop("min_leaf_version", None)
        else:
            runtime["min_leaf_version"] = runtime_minimum
        runtime_path.write_text(json.dumps(runtime) + "\n", encoding="utf-8")
        if payload is not None:
            (package_dir / "payload.bin").write_bytes(payload)

    def run_feed(
        self,
        app_dirs: list[Path],
        *extra: str,
        expected_ok: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(self.output),
            "--base-url",
            "http://127.0.0.1:8765/pakrat/v1/",
            "--skip-build",
        ]
        for app_dir in app_dirs:
            command.extend(["--app-dir", str(app_dir)])
        command.extend(extra)
        result = subprocess.run(command, text=True, capture_output=True)
        if expected_ok and result.returncode != 0:
            self.fail(f"feed failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        if not expected_ok and result.returncode == 0:
            self.fail(f"feed unexpectedly passed:\n{result.stdout}")
        return result

    def catalog(self) -> dict:
        return json.loads(
            (self.output / "pakrat" / "v1" / "storefront.json").read_text(
                encoding="utf-8"
            )
        )

    # ---- STORE-CONTENT-1: the content[] lane -------------------------------

    SCUMMVM_PROVIDES = {
        "schema": 1,
        "systems": [
            {
                "id": "SCUMMVM",
                "name": "ScummVM",
                "patterns": ["SCUMMVM"],
                "extensions": ["scummvm"],
                "rom_root": "Roms/SCUMMVM",
                "image_root": "Images/SCUMMVM",
                "default_core": "scummvm",
                "icon_flat": "art/SCUMMVM.png",
            }
        ],
        "cores": [],
        "system_extensions": [],
    }

    def test_content_package_publishes_with_no_ungated_floor(self) -> None:
        """The case that forced a separate lane: every version is gated, so
        there is no ungated safe floor and the apps[] rule could never be
        satisfied."""
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        self.run_feed([app])
        catalog = self.catalog()
        self.assertEqual(catalog["apps"], [])
        self.assertEqual(len(catalog["content"]), 1)
        entry = catalog["content"][0]
        self.assertEqual(entry["id"], "org.umrk.scummvm")
        package = entry["packages"][0]
        self.assertEqual(package["min_leaf_version"], "0.11.0")
        self.assertTrue(
            all("min_leaf_version" in v for v in package["versions"]),
            "a content package needs no ungated floor",
        )

    def test_gate_unaware_client_sees_only_apps(self) -> None:
        """A client that predates this contract parses apps[], ignores the
        unknown content key, and never learns a content pak exists."""
        plain = self.write_app(
            "Plain", "org.umrk.plain", "Plain.pak", "Plain.mlp1.pak.zip"
        )
        content = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        self.run_feed([plain, content])
        catalog = self.catalog()
        self.assertEqual([a["id"] for a in catalog["apps"]], ["org.umrk.plain"])
        self.assertEqual(
            [a["id"] for a in catalog["content"]], ["org.umrk.scummvm"]
        )
        self.assertEqual(catalog["schema"], 1, "the schema must not bump")

    def test_content_key_is_absent_when_no_content_package_exists(self) -> None:
        """Every storefront published before this contract stays byte-shaped
        exactly as it was."""
        app = self.write_app(
            "Plain", "org.umrk.plain", "Plain.pak", "Plain.mlp1.pak.zip"
        )
        self.run_feed([app])
        self.assertNotIn("content", self.catalog())

    def test_content_artifact_without_provides_is_rejected(self) -> None:
        """The lane is a claim; the built .pak is the fact."""
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("declares no `provides`", result.stderr)

    def test_ungated_content_package_is_rejected(self) -> None:
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("every content version must declare min_leaf_version",
                      result.stderr)

    def test_provides_artifact_in_apps_lane_is_rejected(self) -> None:
        """The mirror rule: a provides pak is gated on this contract by
        construction, so the gate-unaware lane is the wrong home for it."""
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            provides=self.SCUMMVM_PROVIDES,
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("belongs in the content lane", result.stderr)

    def test_shared_platform_content_package_is_rejected(self) -> None:
        """D16: cores and standalone emulators are platform-specific."""
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
            platform="shared",
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("shared", result.stderr)

    def test_id_cannot_appear_in_both_lanes(self) -> None:
        """S-3: both lanes resolve to the same install_path."""
        app = self.write_app(
            "Plain", "org.umrk.dual", "Plain.pak", "Plain.mlp1.pak.zip"
        )
        twin = self.write_app(
            "Twin",
            "org.umrk.dual",
            "Twin.pak",
            "Twin.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        result = self.run_feed([app, twin], expected_ok=False)
        self.assertIn("duplicate app id", result.stderr)

    def test_content_history_stays_immutable_and_append_only(self) -> None:
        """The safe-floor exemption is the ONE rule content[] relaxes."""
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        self.run_feed([app])
        first = self.catalog()["content"][0]["packages"][0]["versions"][0]

        self.update_app(app, "1.1.0", "0.11.0")
        self.run_feed([app])
        versions = self.catalog()["content"][0]["packages"][0]["versions"]
        self.assertEqual([v["version"] for v in versions], ["1.1.0", "1.0.0"])
        self.assertEqual(
            versions[1], first, "a published content version is frozen"
        )
        # The legacy fields mirror the NEWEST entry, gate included, because in
        # this lane there is no ungated floor for them to mirror instead.
        package = self.catalog()["content"][0]["packages"][0]
        self.assertEqual(package["version"], "1.1.0")
        self.assertEqual(package["min_leaf_version"], "0.11.0")

    def test_package_cannot_change_lanes_once_published(self) -> None:
        app = self.write_app(
            "ScummVM",
            "org.umrk.scummvm",
            "ScummVM.pak",
            "ScummVM.mlp1.pak.zip",
            min_leaf_version="0.11.0",
            kind="content",
            provides=self.SCUMMVM_PROVIDES,
        )
        self.run_feed([app])
        metadata_path = app / "pakrat.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("kind")
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n",
                                 encoding="utf-8")
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("belongs in the content lane", result.stderr)


    def test_multiple_explicit_apps(self) -> None:
        first = self.write_app(
            "First", "org.example.first", "First.pak", "First.pak.zip"
        )
        second = self.write_app(
            "Second", "org.example.second", "Second.pak", "Second.pak.zip"
        )
        self.run_feed([first, second])
        catalog = self.catalog()
        self.assertEqual(
            [app["id"] for app in catalog["apps"]],
            ["org.example.first", "org.example.second"],
        )
        for app in catalog["apps"]:
            artifact = app["packages"][0]["artifact"]
            package = app["packages"][0]
            self.assertEqual(package["version"], "1.0.0")
            self.assertEqual(package["versions"][0]["version"], "1.0.0")
            artifact_path = (
                self.output
                / "pakrat"
                / "v1"
                / "artifacts"
                / app["id"]
                / "1.0.0"
                / artifact["name"]
            )
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(artifact["size"], artifact_path.stat().st_size)
            self.assertEqual(
                artifact["sha256"],
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            )

    def test_duplicate_id_and_install_name_are_rejected(self) -> None:
        first = self.write_app(
            "First", "org.example.same", "First.pak", "First.pak.zip"
        )
        duplicate_id = self.write_app(
            "Second", "org.example.same", "Second.pak", "Second.pak.zip"
        )
        result = self.run_feed([first, duplicate_id], expected_ok=False)
        self.assertIn("duplicate app id", result.stderr)

        duplicate_install = self.write_app(
            "Third", "org.example.third", "First.pak", "Third.pak.zip"
        )
        result = self.run_feed([first, duplicate_install], expected_ok=False)
        self.assertIn("duplicate install name", result.stderr)

    def test_exact_artifact_override_is_copied_byte_for_byte(self) -> None:
        app = self.write_app(
            "Exact", "org.example.exact", "Exact.pak", "Exact.pak.zip"
        )
        exact = self.apps_root / "Exact.pak.zip"
        runtime = json.dumps(
            {
                "name": "Exact",
                "icon": "res/icon.png",
                "platform": "mlp1",
                "pak_version": "1.0.0",
            }
        ).encode()
        payload = b"exact-release-payload"
        with zipfile.ZipFile(exact, "w") as archive:
            archive.writestr("Exact.pak/pak.json", runtime)
            archive.writestr("Exact.pak/exact.bin", payload)

        self.run_feed(
            [app],
            "--artifact",
            f"org.example.exact={exact}",
        )
        copied = (
            self.output
            / "pakrat"
            / "v1"
            / "artifacts"
            / "org.example.exact"
            / "1.0.0"
            / exact.name
        )
        self.assertEqual(copied.read_bytes(), exact.read_bytes())
        package = self.catalog()["apps"][0]["packages"][0]
        self.assertEqual(package["artifact"]["installed_size"], len(runtime) + len(payload))

    def test_gated_version_requires_ungated_history(self) -> None:
        app = self.write_app(
            "Gated",
            "org.example.gated",
            "Gated.pak",
            "Gated.pak.zip",
            version="2.0.0",
            min_leaf_version="0.7.0",
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("requires explicit history with an ungated safe floor", result.stderr)

    def test_repeated_generation_merges_history_and_pins_safe_floor(self) -> None:
        app = self.write_app(
            "History",
            "org.example.history",
            "History.pak",
            "History.pak.zip",
        )
        self.run_feed([app])
        floor_path = (
            self.output
            / "pakrat"
            / "v1"
            / "artifacts"
            / "org.example.history"
            / "1.0.0"
            / "History.pak.zip"
        )
        floor_bytes = floor_path.read_bytes()

        self.update_app(
            app,
            "2.0.0",
            "0.7.0",
            payload=b"new-version-payload",
        )
        self.run_feed([app])
        catalog = self.catalog()
        catalog_app = catalog["apps"][0]
        package = catalog_app["packages"][0]
        self.assertEqual(catalog_app["version"], "1.0.0")
        self.assertEqual(package["version"], "1.0.0")
        self.assertEqual(
            [entry["version"] for entry in package["versions"]],
            ["2.0.0", "1.0.0"],
        )
        self.assertEqual(package["versions"][0]["min_leaf_version"], "0.7.0")
        self.assertEqual(package["artifact"], package["versions"][1]["artifact"])
        self.assertEqual(floor_path.read_bytes(), floor_bytes)
        self.assertTrue(
            (
                self.output
                / "pakrat"
                / "v1"
                / "artifacts"
                / "org.example.history"
                / "2.0.0"
                / "History.pak.zip"
            ).is_file()
        )

    def test_explicit_history_materializes_prior_artifact(self) -> None:
        app = self.write_app(
            "Explicit",
            "org.example.explicit",
            "Explicit.pak",
            "Explicit.pak.zip",
        )
        self.run_feed([app])
        history_root = self.apps_root / "history-feed"
        shutil.copytree(self.output / "pakrat" / "v1", history_root)
        shutil.rmtree(self.output)

        self.update_app(app, "2.0.0", "0.7.0", payload=b"explicit-new")
        self.run_feed(
            [app],
            "--history",
            str(history_root / "storefront.json"),
        )
        package = self.catalog()["apps"][0]["packages"][0]
        self.assertEqual(
            [entry["version"] for entry in package["versions"]],
            ["2.0.0", "1.0.0"],
        )
        self.assertTrue(
            (
                self.output
                / "pakrat"
                / "v1"
                / "artifacts"
                / "org.example.explicit"
                / "1.0.0"
                / "Explicit.pak.zip"
            ).is_file()
        )

    def test_published_version_facts_are_immutable(self) -> None:
        app = self.write_app(
            "Immutable",
            "org.example.immutable",
            "Immutable.pak",
            "Immutable.pak.zip",
        )
        self.run_feed([app])
        before = self.catalog()
        self.update_app(app, "1.0.0", None, payload=b"changed-without-version-bump")
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("immutable history conflict", result.stderr)
        self.assertEqual(self.catalog(), before)

    def test_history_cannot_exceed_client_version_limit(self) -> None:
        app = self.write_app(
            "HistoryLimit",
            "org.example.history-limit",
            "HistoryLimit.pak",
            "HistoryLimit.pak.zip",
        )
        self.run_feed([app])
        history = self.catalog()
        package = history["apps"][0]["packages"][0]
        floor = package["versions"][0]
        package["versions"] = [
            {
                "version": f"{major}.0.0",
                **({"min_leaf_version": "0.7.0"} if major > 1 else {}),
                "artifact": {
                    **floor["artifact"],
                    "url": (
                        "https://example.invalid/artifacts/"
                        f"org.example.history-limit/{major}.0.0/"
                        "HistoryLimit.pak.zip"
                    ),
                },
            }
            for major in range(17, 0, -1)
        ]
        history_path = self.apps_root / "too-much-history.json"
        history_path.write_text(json.dumps(history), encoding="utf-8")
        self.update_app(app, "18.0.0", "0.7.0")
        result = self.run_feed(
            [app],
            "--history",
            str(history_path),
            expected_ok=False,
        )
        self.assertIn("16-entry client limit", result.stderr)

    def test_existing_history_cannot_be_silently_dropped(self) -> None:
        first = self.write_app(
            "KeepFirst",
            "org.example.keep-first",
            "KeepFirst.pak",
            "KeepFirst.pak.zip",
        )
        second = self.write_app(
            "KeepSecond",
            "org.example.keep-second",
            "KeepSecond.pak",
            "KeepSecond.pak.zip",
        )
        self.run_feed([first, second])
        before = self.catalog()
        result = self.run_feed([first], expected_ok=False)
        self.assertIn("history contains a package that was not regenerated", result.stderr)
        self.assertEqual(self.catalog(), before)

    def test_runtime_minimum_must_match_authored_gate(self) -> None:
        app = self.write_app(
            "Mismatch",
            "org.example.mismatch",
            "Mismatch.pak",
            "Mismatch.pak.zip",
            version="2.0.0",
            min_leaf_version="0.7.0",
            runtime_min_leaf_version="0.8.0",
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("runtime min_leaf_version", result.stderr)

    def test_package_versions_are_exact_numeric_triples(self) -> None:
        app = self.write_app(
            "BadVersion",
            "org.example.bad-version",
            "BadVersion.pak",
            "BadVersion.pak.zip",
            version="v1.0.0",
        )
        result = self.run_feed([app], expected_ok=False)
        self.assertIn("exact MAJOR.MINOR.PATCH", result.stderr)

    def test_unsafe_exact_artifact_is_rejected(self) -> None:
        app = self.write_app(
            "Unsafe", "org.example.unsafe", "Unsafe.pak", "Unsafe.pak.zip"
        )
        unsafe = self.apps_root / "Unsafe.pak.zip"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr(
                "Unsafe.pak/pak.json",
                json.dumps({"pak_version": "1.0.0"}),
            )
            archive.writestr("../escape", b"no")
        result = self.run_feed(
            [app],
            "--artifact",
            f"org.example.unsafe={unsafe}",
            expected_ok=False,
        )
        self.assertIn("unsafe or unexpected archive path", result.stderr)

    def test_duplicate_exact_artifact_path_is_rejected(self) -> None:
        app = self.write_app(
            "Duplicate", "org.example.duplicate", "Duplicate.pak", "Duplicate.pak.zip"
        )
        duplicate = self.apps_root / "Duplicate.pak.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr(
                    "Duplicate.pak/pak.json",
                    json.dumps({"pak_version": "1.0.0"}),
                )
                archive.writestr("Duplicate.pak/payload.bin", b"first")
                archive.writestr("Duplicate.pak/payload.bin", b"second")
        result = self.run_feed(
            [app],
            "--artifact",
            f"org.example.duplicate={duplicate}",
            expected_ok=False,
        )
        self.assertIn("duplicate archive path", result.stderr)


if __name__ == "__main__":
    unittest.main()
