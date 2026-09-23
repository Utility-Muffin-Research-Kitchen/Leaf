#!/usr/bin/env python3
"""Require the artifacts Leaf ships for a core beyond its libretro binary.

The Cores-spruce stock-parity cache and build report already require every
core's .so plus a probed library name. This gate covers what those do not: the
matching .info file, the shipped catalog entry, a checksum-bound probed report
row, and the per-core default settings template. It runs before a device
payload is replaced and before a release ZIP is accepted, so a partial payload
cannot ship silently.

The catalog entry supplies the file, info, and config-folder names, so only the
core id is pinned here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REQUIRED_CORES = ("flycast_fast_umrk",)


class PayloadError(ValueError):
    pass


def load_json(path: Path, label: str):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PayloadError(f"cannot read {label} {path}: {error}") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise PayloadError(f"cannot parse {label} {path}: {error}") from error


def require_artifact(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise PayloadError(f"missing or empty {label}: {path}")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog_entry(catalog, core: str) -> dict:
    entries = catalog if isinstance(catalog, list) else catalog.get("cores")
    if not isinstance(entries, list):
        raise PayloadError(
            "cores catalog must be an array or an object with a cores array"
        )
    matches = [
        row for row in entries if isinstance(row, dict) and row.get("id") == core
    ]
    if len(matches) != 1:
        raise PayloadError(
            f"cores catalog has {len(matches)} {core} entries, expected one"
        )
    return matches[0]


def report_row(report, core: str) -> dict:
    rows = report.get("cores") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        raise PayloadError("core build report has no cores array")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("core") == core
    ]
    if len(matches) != 1:
        raise PayloadError(
            f"core build report has {len(matches)} {core} rows, expected one"
        )
    return matches[0]


def validate_core(
    platform_dir: Path,
    cores_dir: Path,
    info_dir: Path,
    report_path: Path,
    core: str,
) -> None:
    entry = catalog_entry(
        load_json(platform_dir / "defaults" / "cores.json", "cores catalog"), core
    )
    if entry.get("status") != "packaged":
        raise PayloadError(
            f"cores catalog {core} status is {entry.get('status')!r}, "
            "not 'packaged'"
        )
    core_file = entry.get("file_name") or f"{core}_libretro.so"
    info_file = entry.get("info_name") or f"{core}_libretro.info"
    config_folder = entry.get("config_folder")
    if not isinstance(config_folder, str) or not config_folder:
        raise PayloadError(
            f"cores catalog {core} has no config_folder for its default settings"
        )

    core_path = require_artifact(cores_dir / core_file, f"{core} core binary")
    require_artifact(info_dir / info_file, f"{core} info file")

    report = load_json(report_path, "core build report")
    if (
        report.get("status") != "passed"
        or report.get("library_name_status") != "complete"
    ):
        raise PayloadError(
            "core build report is not verified: "
            f"status={report.get('status')!r} "
            f"library_name_status={report.get('library_name_status')!r}"
        )
    row = report_row(report, core)
    if row.get("status") != "built":
        raise PayloadError(
            f"core build report {core} row is {row.get('status')!r}, not 'built'"
        )
    if row.get("core_file") != core_file:
        raise PayloadError(
            f"core build report {core} row names {row.get('core_file')!r}, "
            f"catalog expects {core_file!r}"
        )
    actual_sha256 = sha256_file(core_path)
    if row.get("sha256") != actual_sha256:
        raise PayloadError(
            f"{core} binary does not match its build report checksum: {core_path}"
        )
    if not row.get("library_name"):
        raise PayloadError(f"core build report {core} row has no probed library name")
    if row.get("library_name_source") not in ("container", "device"):
        raise PayloadError(f"core build report {core} row has no probe source")

    require_artifact(
        platform_dir
        / "defaults"
        / "retroarch"
        / "core-options"
        / config_folder
        / f"{config_folder}.opt",
        f"{core} default settings template",
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform-dir",
        type=Path,
        required=True,
        help=(
            "payload or platform root holding defaults/ and, unless overridden, "
            "cores/ and info/"
        ),
    )
    parser.add_argument("--cores-dir", type=Path)
    parser.add_argument("--info-dir", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    platform_dir = args.platform_dir
    cores_dir = args.cores_dir or platform_dir / "cores"
    info_dir = args.info_dir or platform_dir / "info"
    report_path = args.report or cores_dir / "build-report.json"
    for core in REQUIRED_CORES:
        validate_core(platform_dir, cores_dir, info_dir, report_path, core)
        print(
            f"core payload: {core} binary + info + verified report + catalog "
            "+ default settings"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PayloadError as error:
        print(f"mlp1 core payload: {error}", file=sys.stderr)
        raise SystemExit(1)
