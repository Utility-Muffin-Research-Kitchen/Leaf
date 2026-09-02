#!/usr/bin/env python3
"""Validate shader coverage against an assembled platform catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def indexed_rows(document: dict, key: str, source: Path) -> dict[str, dict]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"{source}: {key} must be an array")
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{source}: every {key} row must have a string id")
        row_id = row["id"]
        if row_id in indexed:
            raise ValueError(f"{source}: duplicate {key} id {row_id}")
        indexed[row_id] = row
    return indexed


def eligible_systems(systems: dict[str, dict], cores: dict[str, dict]) -> set[str]:
    eligible = set()
    for system_id, system in systems.items():
        core = cores.get(system.get("default_core"))
        if (
            core
            and core.get("type") == "retroarch"
            and core.get("status") == "packaged"
            and core.get("supports_menu") is True
        ):
            eligible.add(system_id)
    return eligible


def recommendation_coverage(manifest: dict, known_systems: set[str]) -> dict[str, set[str]]:
    presets = manifest.get("presets")
    if not isinstance(presets, list):
        raise ValueError("shader manifest: presets must be an array")
    coverage: dict[str, set[str]] = {system_id: set() for system_id in known_systems}
    for preset in presets:
        if not isinstance(preset, dict):
            raise ValueError("shader manifest: every preset must be an object")
        intended = preset.get("intended_systems")
        if intended is None:
            continue
        if not isinstance(intended, list) or not all(
            isinstance(system_id, str) for system_id in intended
        ):
            raise ValueError("shader manifest: intended_systems must be an array of strings")
        unknown = sorted(set(intended) - known_systems)
        if unknown:
            raise ValueError(
                "shader manifest: unknown intended system(s): " + ", ".join(unknown)
            )
        if preset.get("qualification") != "recommended":
            continue
        path = preset.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("shader manifest: recommended preset is missing its path")
        for system_id in intended:
            coverage[system_id].add(path)
    return coverage


def load_exclusions(
    path: Path,
    report_root: Path,
    eligible: set[str],
    coverage: dict[str, set[str]],
) -> set[str]:
    document = load_object(path)
    if document.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    rows = document.get("exclusions")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: exclusions must be an array")

    excluded = set()
    report_root = report_root.resolve()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{path}: every exclusion must be an object")
        system_id = row.get("system_id")
        reason = row.get("reason")
        report = row.get("report")
        if not isinstance(system_id, str) or not system_id:
            raise ValueError(f"{path}: every exclusion needs a system_id")
        if system_id in excluded:
            raise ValueError(f"{path}: duplicate exclusion for {system_id}")
        if system_id not in eligible:
            raise ValueError(
                f"{path}: exclusion for {system_id} is stale or not an eligible RetroArch default"
            )
        if len(coverage[system_id]) >= 2:
            raise ValueError(f"{path}: exclusion for covered system {system_id} is stale")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path}: exclusion for {system_id} needs a reason")
        if not isinstance(report, str) or not report:
            raise ValueError(f"{path}: exclusion for {system_id} needs a report")
        relative = Path(report)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{path}: exclusion report must stay under the report root")
        report_path = (report_root / relative).resolve()
        if report_root not in report_path.parents or not report_path.is_file():
            raise ValueError(f"{path}: exclusion report does not exist: {report}")
        excluded.add(system_id)
    return excluded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform-dir",
        type=Path,
        required=True,
        help="assembled platform directory containing defaults/ and shaders/",
    )
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    systems_path = args.platform_dir / "defaults" / "systems.json"
    cores_path = args.platform_dir / "defaults" / "cores.json"
    manifest_path = args.platform_dir / "shaders" / "manifest.json"
    try:
        systems = indexed_rows(load_object(systems_path), "systems", systems_path)
        cores = indexed_rows(load_object(cores_path), "cores", cores_path)
        coverage = recommendation_coverage(
            load_object(manifest_path), set(systems)
        )
        eligible = eligible_systems(systems, cores)
        excluded = load_exclusions(
            args.exclusions, args.report_root, eligible, coverage
        )
        uncovered = sorted(
            system_id
            for system_id in eligible
            if len(coverage[system_id]) < 2 and system_id not in excluded
        )
        if uncovered:
            details = ", ".join(
                f"{system_id} ({len(coverage[system_id])})"
                for system_id in uncovered
            )
            raise ValueError(
                "eligible systems need at least two recommended shaders or a "
                f"report-linked exclusion: {details}"
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    covered = eligible - excluded
    print(
        f"shader coverage: {len(eligible)} eligible, {len(covered)} covered, "
        f"{len(excluded)} excluded"
    )
    print("eligible systems: " + ", ".join(sorted(eligible)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
