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
    ) -> Path:
        app_dir = self.apps_root / directory
        package_dir = app_dir / "build" / "mlp1" / "package" / install_name
        package_dir.mkdir(parents=True)
        (package_dir / "pak.json").write_text(
            json.dumps(
                {
                    "name": directory,
                    "icon": "res/icon.png",
                    "platform": "mlp1",
                    "pak_version": version,
                }
            )
            + "\n",
            encoding="utf-8",
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
                        "platform": "mlp1",
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
        (app_dir / "pakrat.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return app_dir

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
            artifact_path = (
                self.output / "pakrat" / "v1" / "artifacts" / artifact["name"]
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
        copied = self.output / "pakrat" / "v1" / "artifacts" / exact.name
        self.assertEqual(copied.read_bytes(), exact.read_bytes())
        package = self.catalog()["apps"][0]["packages"][0]
        self.assertEqual(package["artifact"]["installed_size"], len(runtime) + len(payload))

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
