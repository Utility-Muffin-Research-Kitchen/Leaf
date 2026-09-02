#!/usr/bin/env python3
"""Mutation fixtures for the assembled shader-coverage gate."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parents[1]
TOOL = Path(
    os.environ.get(
        "SHADER_COVERAGE_TOOL",
        LEAF_ROOT / "scripts" / "validate-shader-coverage.py",
    )
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_fixture(root: Path) -> tuple[Path, Path, Path]:
    platform = root / "platform"
    exclusions = root / "exclusions.json"
    reports = root / "reports"
    write_json(
        platform / "defaults" / "systems.json",
        {
            "systems": [
                {"id": "A", "default_core": "retro"},
                {"id": "B", "default_core": "standalone"},
                {"id": "C", "default_core": "missing"},
            ]
        },
    )
    write_json(
        platform / "defaults" / "cores.json",
        {
            "cores": [
                {
                    "id": "retro",
                    "type": "retroarch",
                    "status": "packaged",
                    "supports_menu": True,
                },
                {
                    "id": "standalone",
                    "type": "path",
                    "status": "packaged",
                    "supports_menu": False,
                },
                {
                    "id": "missing",
                    "type": "retroarch",
                    "status": "missing",
                    "supports_menu": True,
                },
            ]
        },
    )
    write_json(
        platform / "shaders" / "manifest.json",
        {
            "presets": [
                {
                    "path": "leaf-recommended/one.glslp",
                    "qualification": "recommended",
                    "intended_systems": ["A"],
                },
                {
                    "path": "leaf-recommended/two.glslp",
                    "qualification": "recommended",
                    "intended_systems": ["A"],
                },
            ]
        },
    )
    write_json(exclusions, {"schema_version": 1, "exclusions": []})
    reports.mkdir()
    return platform, exclusions, reports


def run(platform: Path, exclusions: Path, reports: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "python3",
            str(TOOL),
            "--platform-dir",
            str(platform),
            "--exclusions",
            str(exclusions),
            "--report-root",
            str(reports),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def expect(name: str, mutate, success: bool, message: str = "") -> None:
    with tempfile.TemporaryDirectory(prefix="leaf-shader-coverage-") as temporary:
        platform, exclusions, reports = make_fixture(Path(temporary))
        mutate(platform, exclusions, reports)
        result = run(platform, exclusions, reports)
        if (result.returncode == 0) != success or message not in (
            result.stdout + result.stderr
        ):
            wanted = "success" if success else "failure"
            raise SystemExit(
                f"{name}: expected {wanted} containing {message!r}\n"
                f"stdout:\n{result.stdout}stderr:\n{result.stderr}"
            )


def no_change(*_args) -> None:
    pass


def remove_second(platform: Path, *_args) -> None:
    path = platform / "shaders" / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["presets"].pop()
    write_json(path, document)


def misspell_system(platform: Path, *_args) -> None:
    path = platform / "shaders" / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["presets"][0]["intended_systems"] = ["TYPO"]
    write_json(path, document)


def reclassify_core(platform: Path, *_args) -> None:
    path = platform / "defaults" / "cores.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["cores"][0].update({"type": "path", "supports_menu": False})
    write_json(path, document)


def add_exclusion(
    platform: Path, exclusions: Path, reports: Path, create_report: bool
) -> None:
    remove_second(platform)
    if create_report:
        (reports / "approved.md").write_text("Approved test exclusion.\n", encoding="utf-8")
    write_json(
        exclusions,
        {
            "schema_version": 1,
            "exclusions": [
                {
                    "system_id": "A",
                    "reason": "Test-only approved exception",
                    "report": "approved.md",
                }
            ],
        },
    )


def valid_exclusion(platform: Path, exclusions: Path, reports: Path) -> None:
    add_exclusion(platform, exclusions, reports, True)


def orphan_exclusion(platform: Path, exclusions: Path, reports: Path) -> None:
    add_exclusion(platform, exclusions, reports, False)


def stale_exclusion(_platform: Path, exclusions: Path, reports: Path) -> None:
    (reports / "approved.md").write_text("Old approval.\n", encoding="utf-8")
    write_json(
        exclusions,
        {
            "schema_version": 1,
            "exclusions": [
                {
                    "system_id": "A",
                    "reason": "No longer needed",
                    "report": "approved.md",
                }
            ],
        },
    )


expect("valid assembly", no_change, True, "1 eligible, 1 covered")
expect("second mapping removed", remove_second, False, "A (1)")
expect("unknown system typo", misspell_system, False, "unknown intended system")
expect("path defaults are excluded", reclassify_core, True, "0 eligible")
expect("report-linked exclusion", valid_exclusion, True, "1 excluded")
expect("orphan report", orphan_exclusion, False, "report does not exist")
expect("stale exclusion", stale_exclusion, False, "covered system A is stale")

print("validate-shader-coverage-test: ok")
