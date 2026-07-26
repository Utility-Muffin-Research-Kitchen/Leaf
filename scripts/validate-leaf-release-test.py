#!/usr/bin/env python3

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).with_name("validate-leaf-release.py")
SPEC = importlib.util.spec_from_file_location("validate_leaf_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_executable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (path / "tracked.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)


class IdentityTests(unittest.TestCase):
    def test_stable_identity_requires_explicit_matching_version_and_tag(self):
        MODULE.validate_identity("stable", "0.7.0", "v0.7.0", "build-123")
        with self.assertRaisesRegex(MODULE.PolicyError, "LEAF_RELEASE_VERSION"):
            MODULE.validate_identity("stable", "", "v0.7.0", "build-123")
        with self.assertRaisesRegex(MODULE.PolicyError, "does not match"):
            MODULE.validate_identity("stable", "0.7.0", "v0.7.1", "build-123")
        with self.assertRaisesRegex(MODULE.PolicyError, "explicit LEAF_RELEASE_TAG"):
            MODULE.validate_identity("stable", "0.7.0", "", "build-123")

    def test_stable_identity_accepts_supported_ota_suffix(self):
        MODULE.validate_identity(
            "stable",
            "0.7.0-save-isolation-ota1",
            "v0.7.0-save-isolation-ota1",
            "build-123",
        )

    def test_nonstable_identity_may_use_build_identity_as_version(self):
        MODULE.validate_identity(
            "dev",
            "2026-07-20-gabc1234",
            "",
            "2026-07-20-gabc1234",
        )


class ProvenanceTests(unittest.TestCase):
    def test_provenance_records_exact_clean_commits(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            components = []
            for name in ("leaf", "launcher", "launcher-switcher"):
                repo = base / name
                init_repo(repo)
                components.append(f"{name}={repo}")
            app_repo = base / "Thing-File"
            init_repo(app_repo)
            components.append(f"app:Thing-File={app_repo}")
            args = SimpleNamespace(
                channel="stable",
                version="0.7.0",
                tag="v0.7.0",
                release_id="build-123",
                component=components,
                require_clean=True,
            )
            result = MODULE.build_provenance(args)
            rows = result["components"]
            self.assertEqual([row["name"] for row in rows], [
                "leaf",
                "launcher",
                "launcher-switcher",
                "app:Thing-File",
            ])
            self.assertTrue(all(len(row["commit"]) == 40 for row in rows))
            self.assertTrue(all(row["dirty"] is False for row in rows))

    def test_stable_provenance_rejects_dirty_component(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            components = []
            for name in ("leaf", "launcher", "launcher-switcher"):
                repo = base / name
                init_repo(repo)
                components.append(f"{name}={repo}")
            (base / "launcher" / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            args = SimpleNamespace(
                channel="stable",
                version="0.7.0",
                tag="v0.7.0",
                release_id="build-123",
                component=components,
                require_clean=True,
            )
            with self.assertRaisesRegex(MODULE.PolicyError, "stable component is dirty"):
                MODULE.build_provenance(args)


class CandidateTests(unittest.TestCase):
    def make_candidate(self, base: Path) -> SimpleNamespace:
        root = base / "release"
        install = base / "install"
        launcher = root / "platforms" / "mlp1" / "launcher"
        write_executable(
            launcher / "bin" / "loong_pangu",
            b"\x7fELF fixture relocate-games-v1 fixture\n",
        )
        write_executable(
            launcher / "bin" / "jawaka-inhibitctl",
            b"\x7fELF inhibit fixture\n",
        )
        env_lines = [
            "#!/bin/sh",
            "export UMRK_SECONDARY_SDCARD_PATH=/media/sdcard1",
        ]
        for name, values in MODULE.REQUIRED_PATH_LISTS.items():
            env_lines.append(f"export {name}={':'.join(values)}")
        env_path = launcher / "env.sh"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        autoconfig = root / "platforms" / "mlp1" / "autoconfig" / "Loong Gamepad.cfg"
        autoconfig.parent.mkdir(parents=True, exist_ok=True)
        autoconfig.write_text(
            'input_l3_btn = "7"\ninput_l3_btn_label = "L3"\n',
            encoding="utf-8",
        )
        defaults = root / "platforms" / "mlp1" / "defaults" / "retroarch.cfg"
        defaults.parent.mkdir(parents=True, exist_ok=True)
        defaults.write_text('input_player1_l3_btn = "7"\n', encoding="utf-8")

        provenance = {
            "schema": 1,
            "product": "leaf",
            "release": {
                "channel": "stable",
                "version": "0.7.0",
                "tag": "v0.7.0",
                "release_id": "build-123",
            },
            "components": [
                {"name": name, "commit": "a" * 40, "dirty": False, "remote": None}
                for name in (
                    "leaf",
                    "launcher",
                    "launcher-switcher",
                    "app:Thing-File",
                )
            ],
        }
        provenance_path = root / "provenance" / "components.json"
        provenance_path.parent.mkdir(parents=True)
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

        write_executable(
            install / "umrk-launcher-install.sh",
            (
                '#!/bin/sh\nRELEASE_ID="build-123"\nRELEASE_VERSION="0.7.0"\n'
                'cat <<EOF\n"version": "$RELEASE_VERSION"\n'
                '"release_id": "$RELEASE_ID"\nEOF\n'
            ).encode(),
        )
        return SimpleNamespace(
            release_root=root,
            install_stage=install,
            version="0.7.0",
            release_id="build-123",
            required_component=[
                "leaf",
                "launcher",
                "launcher-switcher",
                "app:Thing-File",
            ],
        )

    def test_candidate_accepts_required_capabilities_and_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            MODULE.validate_candidate(self.make_candidate(Path(raw)))

    def test_candidate_rejects_missing_launcher_capability(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.make_candidate(Path(raw))
            daemon = (
                args.release_root
                / "platforms"
                / "mlp1"
                / "launcher"
                / "bin"
                / "loong_pangu"
            )
            daemon.write_bytes(b"\x7fELF no feature\n")
            with self.assertRaisesRegex(MODULE.PolicyError, "relocate-games-v1"):
                MODULE.validate_candidate(args)

    def test_candidate_rejects_incomplete_configured_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.make_candidate(Path(raw))
            env_path = (
                args.release_root
                / "platforms"
                / "mlp1"
                / "launcher"
                / "env.sh"
            )
            text = env_path.read_text(encoding="utf-8")
            env_path.write_text(
                text.replace(
                    "export ROMS_PATHS=/mnt/sdcard/Roms:/media/sdcard1/Roms",
                    "export ROMS_PATHS=/mnt/sdcard/Roms",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.PolicyError, "ROMS_PATHS mismatch"):
                MODULE.validate_candidate(args)

    def test_candidate_rejects_incomplete_l3_autoconfig(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.make_candidate(Path(raw))
            config = (
                args.release_root
                / "platforms"
                / "mlp1"
                / "autoconfig"
                / "Loong Gamepad.cfg"
            )
            config.write_text('input_l3_btn = "7"\n', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PolicyError, "input_l3_btn_label"):
                MODULE.validate_candidate(args)

    def test_candidate_rejects_incomplete_l3_defaults(self):
        with tempfile.TemporaryDirectory() as raw:
            args = self.make_candidate(Path(raw))
            config = (
                args.release_root
                / "platforms"
                / "mlp1"
                / "defaults"
                / "retroarch.cfg"
            )
            config.write_text('input_player1_l3_btn = "nul"\n', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PolicyError, "input_player1_l3_btn"):
                MODULE.validate_candidate(args)


if __name__ == "__main__":
    unittest.main()
