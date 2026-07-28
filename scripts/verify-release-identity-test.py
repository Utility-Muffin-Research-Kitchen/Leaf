#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-release-identity.py"
BETA_REPOSITORY = "Utility-Muffin-Research-Kitchen/Leaf-beta"


def release_payload(tag: str, channel: str = "beta") -> dict[str, object]:
    return {
        "schema": 1,
        "product": "leaf",
        "release": {
            "channel": channel,
            "version": tag[1:],
            "tag": tag,
            "release_id": tag,
        },
        "components": [],
    }


def release_manifest(
    tag: str,
    channel: str = "beta",
    repository: str = BETA_REPOSITORY,
) -> dict[str, object]:
    return {
        "schema": 1,
        "product": "leaf",
        "channel": channel,
        "version": tag[1:],
        "release_id": tag,
        "platforms": {
            "mlp1": {
                "artifact": {"name": f"leaf-mlp1-sd-{tag}.zip"},
                "recovery_zip": {
                    "name": f"leaf-mlp1-recovery-{tag}.zip"
                },
            }
        },
        "notes": {
            "url": f"https://github.com/{repository}/releases/tag/{tag}"
        },
    }


def write_release_zip(path: Path, tag: str, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    member = (
        f".system/leaf/releases/{tag}/provenance/components.json"
    )
    with zipfile.ZipFile(path, "w") as zf:
        if isinstance(payload, str):
            zf.writestr(member, payload)
        else:
            zf.writestr(member, json.dumps(payload))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_release_manifest(
    path: Path,
    tag: str,
    install_path: Path,
    recovery_path: Path,
    repository: str = BETA_REPOSITORY,
) -> None:
    payload = release_manifest(tag, repository=repository)
    mlp1 = payload["platforms"]["mlp1"]
    mlp1["artifact"].update(
        {"size": install_path.stat().st_size, "sha256": file_sha256(install_path)}
    )
    mlp1["recovery_zip"].update(
        {
            "size": recovery_path.stat().st_size,
            "sha256": file_sha256(recovery_path),
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def run_verifier(
    zip_path: Path,
    tag: str,
    manifest_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "python3",
        str(SCRIPT),
        str(zip_path),
        "--tag",
        tag,
        "--channel",
        "beta",
    ]
    if manifest_path is not None:
        command += [
            "--manifest",
            str(manifest_path),
            "--repository",
            BETA_REPOSITORY,
        ]
    return subprocess.run(command, capture_output=True, text=True)


class VerifierTests(unittest.TestCase):
    def assert_clean_failure(
        self, result: subprocess.CompletedProcess[str]
    ) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_zip_and_manifest(self):
        tag = "v8.7.6-beta.5"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            zip_path = base / f"leaf-mlp1-sd-{tag}.zip"
            recovery_path = base / f"leaf-mlp1-recovery-{tag}.zip"
            manifest_path = base / "leaf-update.json"
            write_release_zip(zip_path, tag, release_payload(tag))
            recovery_path.write_bytes(b"recovery fixture\n")
            write_release_manifest(
                manifest_path, tag, zip_path, recovery_path
            )

            result = run_verifier(zip_path, tag, manifest_path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release manifest OK", result.stdout)
        self.assertIn("release identity OK", result.stdout)

    def test_missing_or_invalid_zip_has_concise_error(self):
        tag = "v8.7.6-beta.5"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            missing = run_verifier(base / "missing.zip", tag)
            self.assert_clean_failure(missing)

            invalid_path = base / "invalid.zip"
            invalid_path.write_bytes(b"not a zip")
            invalid = run_verifier(invalid_path, tag)
            self.assert_clean_failure(invalid)

    def test_malformed_or_nonobject_provenance_has_concise_error(self):
        tag = "v8.7.6-beta.5"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            malformed_path = base / "malformed.zip"
            write_release_zip(malformed_path, tag, "{not json")
            malformed = run_verifier(malformed_path, tag)
            self.assert_clean_failure(malformed)

            nonobject_path = base / "nonobject.zip"
            write_release_zip(nonobject_path, tag, [])
            nonobject = run_verifier(nonobject_path, tag)
            self.assert_clean_failure(nonobject)

    def test_manifest_repository_mismatch_fails(self):
        tag = "v8.7.6-beta.5"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            zip_path = base / f"leaf-mlp1-sd-{tag}.zip"
            recovery_path = base / f"leaf-mlp1-recovery-{tag}.zip"
            manifest_path = base / "leaf-update.json"
            write_release_zip(zip_path, tag, release_payload(tag))
            recovery_path.write_bytes(b"recovery fixture\n")
            write_release_manifest(
                manifest_path,
                tag,
                zip_path,
                recovery_path,
                repository="Utility-Muffin-Research-Kitchen/Leaf",
            )

            result = run_verifier(zip_path, tag, manifest_path)

        self.assertEqual(result.returncode, 1)
        self.assertIn("notes.url", result.stderr)

    def test_missing_or_corrupt_recovery_zip_fails(self):
        tag = "v8.7.6-beta.5"
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            zip_path = base / f"leaf-mlp1-sd-{tag}.zip"
            recovery_path = base / f"leaf-mlp1-recovery-{tag}.zip"
            manifest_path = base / "leaf-update.json"
            write_release_zip(zip_path, tag, release_payload(tag))
            recovery_path.write_bytes(b"recovery fixture\n")
            write_release_manifest(
                manifest_path, tag, zip_path, recovery_path
            )

            recovery_path.unlink()
            missing = run_verifier(zip_path, tag, manifest_path)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("recovery_zip.file", missing.stderr)

            recovery_path.write_bytes(b"corrupt replacement\n")
            corrupt = run_verifier(zip_path, tag, manifest_path)
            self.assertEqual(corrupt.returncode, 1)
            self.assertIn("recovery_zip.sha256", corrupt.stderr)


class BetaMakeTargetTests(unittest.TestCase):
    def run_make(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "make",
                "-C",
                str(ROOT),
                "--no-print-directory",
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_beta_target_accepts_only_exact_beta_tags(self):
        accepted = self.run_make(
            "beta-zips", "TAG=v0.8.0-beta.1", "MAKE=true"
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        for tag in (
            "",
            "0.8.0-beta.1",
            "v0.8-beta.1",
            "v0.8.0-beta.",
            "v0.8.0-beta.0",
            "v0.8.0-beta.01",
            "v0.8.0-beta.1junk",
            "v0.8.0-foo-beta.1",
            "v0.8.0-beta.1+build",
            "v0.8.0-rc.1",
        ):
            with self.subTest(tag=tag):
                assignment = f"TAG={tag}"
                result = self.run_make(
                    "beta-zips", assignment, "MAKE=true"
                )
                self.assertNotEqual(result.returncode, 0)

    def test_tag_text_is_not_evaluated_by_make_or_recipe_shell(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            values = (
                f"v0.8.0-beta.1`id>{base / 'shell-substitution-ran'}`",
                f"v0.8.0-beta.1$(shell touch {base / 'make-function-ran'})",
            )
            for tag in values:
                with self.subTest(tag=tag):
                    result = self.run_make(
                        "beta-zips", f"TAG={tag}", "MAKE=true"
                    )
                    self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(base.iterdir()), [])

    def test_derived_identity_wins_over_outer_make_assignments(self):
        tag = "v0.8.0-beta.3"
        result = self.run_make(
            "beta-zips",
            f"TAG={tag}",
            "LEAF_RELEASE_CHANNEL=stable",
            "LEAF_RELEASE_VERSION=9.9.9",
            "LEAF_RELEASE_TAG=v9.9.9",
            "LEAF_RELEASE_REPOSITORY=example/incorrect",
            "MAKE=echo",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"RELEASE_ID={tag}", result.stdout)
        self.assertIn("LEAF_RELEASE_CHANNEL=beta", result.stdout)
        self.assertIn(f"LEAF_RELEASE_VERSION={tag[1:]}", result.stdout)
        self.assertIn(f"LEAF_RELEASE_TAG={tag}", result.stdout)
        self.assertIn(
            f"LEAF_RELEASE_REPOSITORY={BETA_REPOSITORY}",
            result.stdout,
        )

    def test_github_tag_context_is_used_and_must_match(self):
        env = os.environ.copy()
        env.pop("TAG", None)
        env["GITHUB_REF_TYPE"] = "tag"
        env["GITHUB_REF_NAME"] = "v0.8.0-beta.4"
        accepted = self.run_make("beta-zips", "MAKE=true", env=env)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        env["GITHUB_REF_NAME"] = ""
        missing = self.run_make("beta-zips", "MAKE=true", env=env)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("GITHUB_REF_NAME is empty", missing.stderr)

        env["GITHUB_REF_NAME"] = "v0.8.0-beta.4"
        rejected = self.run_make(
            "beta-zips",
            "TAG=v0.8.0-beta.5",
            "MAKE=true",
            env=env,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("does not match GITHUB_REF_NAME", rejected.stderr)

    def test_verify_target_uses_custom_release_build(self):
        tag = "v98.76.54-beta.321"
        with tempfile.TemporaryDirectory() as raw:
            release_build = Path(raw) / "custom release"
            zip_path = release_build / f"leaf-mlp1-sd-{tag}.zip"
            recovery_path = release_build / f"leaf-mlp1-recovery-{tag}.zip"
            manifest_path = release_build / "leaf-update.json"
            write_release_zip(zip_path, tag, release_payload(tag))
            recovery_path.write_bytes(b"recovery fixture\n")
            write_release_manifest(
                manifest_path, tag, zip_path, recovery_path
            )

            result = self.run_make(
                "verify-beta-zips",
                f"TAG={tag}",
                f"RELEASE_BUILD={release_build}",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release identity OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
