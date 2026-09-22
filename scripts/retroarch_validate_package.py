#!/usr/bin/env python3
"""Read-only validator for RetroArch package and Phase 2 metadata assumptions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import retroarch_generate_metadata
import retroarch_inventory


ALLOWED_CORE_STATUSES = {"packaged", "planned", "missing", "unsupported", "defer"}
ALLOWED_CORE_TYPES = {"retroarch", "path"}
ALLOWED_ARCHIVE_MODES = {"pass_through", "extract_to_temp", "extract_to_cache", "ignore"}
ALLOWED_M3U_GENERATION = {"none", "manual", "rescan_hook"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_packaged_config_folders(
    core_doc: dict,
    label: str,
    errors: list[str],
) -> None:
    """Validate the runtime save/state namespace for packaged libretro cores."""
    seen: dict[str, tuple[str, str]] = {}
    rows = core_doc.get("cores", []) if isinstance(core_doc, dict) else []
    if not isinstance(rows, list):
        return
    for core in rows:
        if (
            not isinstance(core, dict)
            or core.get("type") != "retroarch"
            or core.get("status") != "packaged"
        ):
            continue
        core_id = core.get("id") or "<unknown>"
        config_folder = core.get("config_folder")
        folder_error = retroarch_generate_metadata.config_folder_error(config_folder)
        if folder_error:
            errors.append(
                f"{label}: {core_id}: invalid config_folder {config_folder!r}: {folder_error}"
            )
            continue
        folded = config_folder.casefold()
        prior = seen.get(folded)
        if prior is not None:
            errors.append(
                f"{label}: packaged config_folder collision: "
                f"{prior[0]}={prior[1]!r} and {core_id}={config_folder!r}"
            )
        else:
            seen[folded] = (core_id, config_folder)


def load_or_build_inventory(args: argparse.Namespace) -> dict:
    if args.inventory:
        return json.loads(args.inventory.read_text(encoding="utf-8"))
    return retroarch_inventory.build_inventory(
        args.umrk_root.resolve(),
        args.allium_root.resolve(),
        args.spruce_root.resolve(),
    )


def validate(inventory: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = list(inventory.get("warnings", []))
    umrk = inventory["umrk"]
    matrix = inventory["parity_matrix"]

    if umrk["mapping_count"] == 0:
        errors.append("current cores.json has no system mappings")

    if not umrk["retroarch_binary_exists"]:
        errors.append(f"RetroArch binary missing: {umrk['retroarch_binary']}")

    if not umrk["core_dir_exists"]:
        errors.append(f"core output directory missing: {umrk['core_dir']}")
    elif not umrk["core_files"]:
        errors.append(f"core output directory has no *_libretro.so files: {umrk['core_dir']}")

    if not umrk["info_dir_exists"]:
        errors.append(f"info output directory missing: {umrk['info_dir']}")

    missing_cores = [
        row for row in matrix if row["status"] == "mapped_missing_core"
    ]
    known_unsupported = [
        row for row in matrix if row["status"] == "known_unsupported"
    ]
    missing_info = [
        row for row in matrix if row["status"] == "missing_info"
    ]

    for row in missing_cores:
        errors.append(
            f"{row['system_id']}: mapped core not packaged: {row['current_core_file']}"
        )

    for row in known_unsupported:
        warnings.append(
            f"{row['system_id']}: default core is "
            f"{row.get('current_core_status')}/{row.get('current_core_type')}; "
            f"known but not launchable in Phase 3: {row['current_core_id']}"
        )

    for row in missing_info:
        errors.append(
            f"{row['system_id']}: packaged core lacks info file: {row['expected_info']}"
        )

    for row in matrix:
        for name in row.get("ignore_file_names", []):
            if name != name.lower():
                errors.append(f"{row['system_id']}: ignore filename is not lowercase: {name}")
            if "/" in name or "\\" in name:
                errors.append(f"{row['system_id']}: ignore filename must be exact basename: {name}")

    return errors, warnings


def load_json_document(path: Path, label: str, errors: list[str]) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{label} missing: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"{label} invalid JSON: {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{label} root must be an object: {path}")
        return {}
    return data


def load_phase2_metadata(args: argparse.Namespace, errors: list[str]) -> dict | None:
    metadata_dir = args.metadata_dir
    cores_path = args.cores_metadata
    systems_path = args.systems_metadata
    phase2_inventory_path = args.phase2_inventory

    if metadata_dir:
        cores_path = cores_path or metadata_dir / "cores.json"
        systems_path = systems_path or metadata_dir / "systems.json"
        phase2_inventory_path = phase2_inventory_path or metadata_dir / "phase-2-inventory.json"

    if not cores_path and not systems_path and not phase2_inventory_path:
        return None

    if not cores_path or not systems_path:
        errors.append("Phase 2 metadata validation requires both cores and systems metadata")
        return None

    return {
        "cores_path": cores_path,
        "systems_path": systems_path,
        "phase2_inventory_path": phase2_inventory_path,
        "cores": load_json_document(cores_path, "Phase 2 cores metadata", errors),
        "systems": load_json_document(systems_path, "Phase 2 systems metadata", errors),
        "phase2_inventory": (
            load_json_document(phase2_inventory_path, "Phase 2 inventory", errors)
            if phase2_inventory_path
            else {}
        ),
    }


def validate_canonical_folder_policy(systems_doc: dict, label: str, errors: list[str]) -> None:
    """Enforce the canonical user-folder invariants on a systems.json document:
    one public folder per user library, no ambiguous folder routing, and no
    alias/variant ids leaking out as public systems. Shared with the generator
    so the producer and the release path agree."""
    if not isinstance(systems_doc, dict) or not systems_doc.get("systems"):
        return
    policy = retroarch_generate_metadata.load_system_folder_policy()
    for message in retroarch_generate_metadata.validate_canonical_folders(systems_doc, policy):
        errors.append(f"{label}: {message}")


def metadata_core_maps(metadata: dict | None) -> tuple[dict[str, dict], dict[str, dict]]:
    if not metadata:
        return {}, {}
    by_id = {
        core.get("id"): core
        for core in metadata.get("cores", {}).get("cores", [])
        if isinstance(core, dict) and core.get("id")
    }
    by_file = {
        core.get("file_name"): core
        for core in by_id.values()
        if core.get("type") == "retroarch" and core.get("file_name")
    }
    return by_id, by_file


def packaged_metadata_names(metadata: dict | None) -> tuple[set[str], set[str]]:
    if not metadata:
        return set(), set()
    core_files: set[str] = set()
    info_files: set[str] = set()
    for core in metadata.get("cores", {}).get("cores", []):
        if not isinstance(core, dict) or core.get("status") != "packaged":
            continue
        if core.get("type") != "retroarch":
            continue
        if core.get("file_name"):
            core_files.add(core["file_name"])
        if core.get("info_name"):
            info_files.add(core["info_name"])
    return core_files, info_files


def validate_phase2_metadata(metadata: dict, inventory: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    core_doc = metadata.get("cores", {})
    system_doc = metadata.get("systems", {})
    phase2_inventory = metadata.get("phase2_inventory", {})
    source_cores = set(inventory["umrk"].get("core_files", []))
    source_info = set(inventory["umrk"].get("info_files", []))

    if core_doc.get("version") != 2:
        errors.append(f"Phase 2 cores metadata version must be 2, got {core_doc.get('version')}")
    if system_doc.get("version") != 2:
        errors.append(f"Phase 2 systems metadata version must be 2, got {system_doc.get('version')}")
    if core_doc.get("platform") != "mlp1":
        errors.append("Phase 2 cores metadata platform is not mlp1")
    if system_doc.get("platform") != "mlp1":
        errors.append("Phase 2 systems metadata platform is not mlp1")

    core_rows = core_doc.get("cores", [])
    system_rows = system_doc.get("systems", [])
    if not isinstance(core_rows, list) or not core_rows:
        errors.append("Phase 2 cores metadata has no cores list")
        core_rows = []
    if not isinstance(system_rows, list) or not system_rows:
        errors.append("Phase 2 systems metadata has no systems list")
        system_rows = []

    validate_packaged_config_folders(core_doc, "Phase 2 cores metadata", errors)

    core_ids: dict[str, dict] = {}
    metadata_packaged_core_ids: set[str] = set()
    metadata_packaged_core_files: set[str] = set()
    metadata_packaged_info_files: set[str] = set()

    for core in core_rows:
        if not isinstance(core, dict):
            errors.append("Phase 2 core row must be an object")
            continue
        core_id = core.get("id")
        if not core_id:
            errors.append("Phase 2 core row missing id")
            continue
        if core_id in core_ids:
            errors.append(f"Phase 2 duplicate core id: {core_id}")
        core_ids[core_id] = core

        core_type = core.get("type")
        status = core.get("status")
        if status == "packaged":
            metadata_packaged_core_ids.add(core_id)
        if core_type not in ALLOWED_CORE_TYPES:
            errors.append(f"{core_id}: invalid core type: {core_type}")
        if status not in ALLOWED_CORE_STATUSES:
            errors.append(f"{core_id}: invalid core status: {status}")
        if "mlp1" not in core.get("platforms", []):
            errors.append(f"{core_id}: platforms does not include mlp1")

        if core_type == "retroarch":
            file_name = core.get("file_name")
            info_name = core.get("info_name")
            if not core.get("libretro_name"):
                errors.append(f"{core_id}: retroarch core missing libretro_name")
            if not file_name or not str(file_name).endswith("_libretro.so"):
                errors.append(f"{core_id}: invalid file_name: {file_name}")
            if not info_name or not str(info_name).endswith("_libretro.info"):
                errors.append(f"{core_id}: invalid info_name: {info_name}")
            if not core.get("config_folder"):
                errors.append(f"{core_id}: retroarch core missing config_folder")

            if status == "packaged":
                if file_name not in source_cores:
                    errors.append(f"{core_id}: metadata says packaged but source core is missing: {file_name}")
                else:
                    metadata_packaged_core_files.add(file_name)
                if info_name not in source_info:
                    errors.append(f"{core_id}: metadata says packaged but source info is missing: {info_name}")
                else:
                    metadata_packaged_info_files.add(info_name)
            elif file_name in source_cores:
                errors.append(f"{core_id}: source core exists but metadata status is {status}: {file_name}")
        elif core_type == "path" and not core.get("path"):
            if status == "packaged":
                errors.append(f"{core_id}: packaged path core missing path")
            else:
                warnings.append(f"{core_id}: deferred path core has no launch path")

    for file_name in sorted(source_cores - metadata_packaged_core_files):
        errors.append(f"source core is not represented as packaged metadata: {file_name}")
    for info_name in sorted(source_info - metadata_packaged_info_files):
        errors.append(f"source info is not represented as packaged metadata: {info_name}")

    missing_refs: dict[str, set[str]] = {}
    system_ids: set[str] = set()
    for system in system_rows:
        if not isinstance(system, dict):
            errors.append("Phase 2 system row must be an object")
            continue
        system_id = system.get("id")
        if not system_id:
            errors.append("Phase 2 system row missing id")
            continue
        if system_id in system_ids:
            errors.append(f"Phase 2 duplicate system id: {system_id}")
        system_ids.add(system_id)

        default_core = system.get("default_core")
        if default_core not in core_ids:
            errors.append(f"{system_id}: default core not in Phase 2 cores metadata: {default_core}")
        else:
            default = core_ids[default_core]
            if default.get("status") != "packaged" or default.get("type") != "retroarch":
                warnings.append(
                    f"{system_id}: default core is {default.get('status')}/{default.get('type')}; "
                    f"known but not launchable in Phase 3: {default_core}"
                )

        for core_id in system.get("alternate_cores", []):
            if core_id not in core_ids:
                errors.append(f"{system_id}: alternate core not in Phase 2 cores metadata: {core_id}")
                continue
            if core_ids[core_id].get("status") != "packaged":
                missing_refs.setdefault(core_id, set()).add(system_id)

        legacy_flat_core = system.get("legacy_flat_core")
        expected_legacy_flat_core = retroarch_generate_metadata.LEGACY_FLAT_CORE_BY_SYSTEM.get(
            system_id
        )
        if legacy_flat_core != expected_legacy_flat_core:
            errors.append(
                f"{system_id}: legacy_flat_core must be {expected_legacy_flat_core!r}, "
                f"got {legacy_flat_core!r}"
            )
        if legacy_flat_core is not None:
            owner = core_ids.get(legacy_flat_core)
            if owner is None:
                errors.append(
                    f"{system_id}: legacy_flat_core not in Phase 2 cores metadata: "
                    f"{legacy_flat_core}"
                )
            elif owner.get("type") != "retroarch" or owner.get("status") != "packaged":
                errors.append(
                    f"{system_id}: legacy_flat_core must name a packaged RetroArch core: "
                    f"{legacy_flat_core}"
                )

        archive_mode = system.get("archive_mode")
        if archive_mode not in ALLOWED_ARCHIVE_MODES:
            errors.append(f"{system_id}: invalid archive_mode: {archive_mode}")
        m3u_generation = system.get("m3u_generation")
        if m3u_generation not in ALLOWED_M3U_GENERATION:
            errors.append(f"{system_id}: invalid m3u_generation: {m3u_generation}")

        for field in (
            "extensions",
            "archive_extensions",
            "archive_inner_extensions",
            "playlist_extensions",
        ):
            values = system.get(field, [])
            if not isinstance(values, list):
                errors.append(f"{system_id}: {field} must be a list")
                continue
            for value in values:
                if value != value.lower() or str(value).startswith("."):
                    errors.append(f"{system_id}: invalid extension in {field}: {value}")

        for name in system.get("ignore_file_names", []):
            if name != name.lower():
                errors.append(f"{system_id}: ignore filename is not lowercase: {name}")
            if "/" in name or "\\" in name:
                errors.append(f"{system_id}: ignore filename must be exact basename: {name}")

    for core_id, systems in sorted(missing_refs.items()):
        status = core_ids[core_id].get("status")
        warnings.append(
            f"metadata alternate core is {status}: {core_id} "
            f"(referenced by {', '.join(sorted(systems))})"
        )

    errors.extend(
        retroarch_generate_metadata.validate_system_core_overrides(
            system_doc, set(core_ids)
        )
    )
    validate_canonical_folder_policy(system_doc, "Phase 2 systems metadata", errors)

    if phase2_inventory:
        expected_packaged_core_ids = [
            core["id"]
            for core in core_rows
            if isinstance(core, dict)
            and core.get("id")
            and core.get("status") == "packaged"
        ]
        expected_missing_core_ids = [
            core["id"]
            for core in core_rows
            if isinstance(core, dict)
            and core.get("id")
            and core.get("status") == "missing"
        ]
        if phase2_inventory.get("generated_core_count") != len(core_rows):
            errors.append("Phase 2 inventory generated_core_count does not match cores.json")
        if phase2_inventory.get("generated_system_count") != len(system_rows):
            errors.append("Phase 2 inventory generated_system_count does not match systems.json")
        if phase2_inventory.get("packaged_core_count") != len(metadata_packaged_core_ids):
            errors.append("Phase 2 inventory packaged_core_count does not match packaged core metadata")
        if phase2_inventory.get("packaged_core_ids") != expected_packaged_core_ids:
            errors.append("Phase 2 inventory packaged_core_ids does not match cores.json")
        if phase2_inventory.get("missing_core_ids") != expected_missing_core_ids:
            errors.append("Phase 2 inventory missing_core_ids does not match cores.json")

    return errors, warnings


def find_report_artifact(build_report_path: Path, file_name: str, subdir: str) -> Path | None:
    for candidate in (
        build_report_path.parent / file_name,
        build_report_path.parent / subdir / file_name,
    ):
        if candidate.is_file():
            return candidate
    return None


def built_report_rows_by_file(report: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    rows = report.get("cores", []) if isinstance(report, dict) else []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if (
            isinstance(row, dict)
            and row.get("status") == "built"
            and isinstance(row.get("core_file"), str)
            and row.get("core_file")
        ):
            result[row["core_file"]] = row
    return result


BUILDER_SCRIPT_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_builder_identity(
    report: dict,
    builder_script: Path | None,
    require_fresh: bool,
) -> tuple[list[str], list[str]]:
    """Check the report was produced by the current builder.

    Every other build-report check asks whether the report is internally
    consistent and covers the packaged cores. A stale artifact passes all of
    them: its row is accurate, its hash matches the bytes on disk, and the core
    is present. What makes it stale is that it predates the build script now in
    the tree -- a different lane, pin, or set of flags would produce it today.

    Comparing the recorded script hash against the current file catches that
    without the validator needing to understand cores, lanes, or pins.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Nothing to compare against and nothing was asked for: stay quiet rather
    # than warning on every caller that does not opt into this check. The CLI
    # already refuses --require-fresh-build-report without --builder-script.
    if builder_script is None:
        if require_fresh:
            errors.append(
                "builder identity cannot be checked: --require-fresh-build-report "
                "needs --builder-script"
            )
        return errors, warnings

    recorded = report.get("builder_script_sha256")
    if not isinstance(recorded, str) or not recorded:
        message = (
            "build report has no builder_script_sha256; it predates builder "
            "identity recording and cannot be checked for staleness -- rebuild "
            "the cores with a current build-mlp1.sh"
        )
        (errors if require_fresh else warnings).append(message)
        return errors, warnings

    if not BUILDER_SCRIPT_SHA_RE.match(recorded):
        errors.append(
            f"build report builder_script_sha256 is not a sha256 digest: {recorded!r}"
        )
        return errors, warnings

    if not builder_script.is_file():
        errors.append(f"builder script missing: {builder_script}")
        return errors, warnings

    current = sha256_file(builder_script)
    if current != recorded:
        recorded_commit = report.get("builder_commit") or "unknown"
        message = (
            f"build report is stale: it was produced by a different "
            f"{builder_script.name} (report {recorded[:16]}..., current "
            f"{current[:16]}...; report builder_commit {recorded_commit}). "
            "The artifacts in the core output directory predate the current "
            "builder, so its lanes, pins, and flags are not reflected in them. "
            "Rebuild the cores."
        )
        (errors if require_fresh else warnings).append(message)

    return errors, warnings


def validate_build_report(
    build_report_path: Path,
    report: dict,
    inventory: dict,
    metadata: dict | None,
    require_full: bool = False,
    builder_script: Path | None = None,
    require_fresh: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not report:
        return errors, warnings

    identity_errors, identity_warnings = validate_builder_identity(
        report, builder_script, require_fresh
    )
    errors.extend(identity_errors)
    warnings.extend(identity_warnings)

    if report.get("version") != 2:
        errors.append(f"build report version must be 2, got {report.get('version')}")
    if report.get("platform") != "mlp1":
        errors.append(f"build report platform must be mlp1, got {report.get('platform')}")
    if report.get("status") != "passed":
        errors.append(f"build report status must be passed, got {report.get('status')}")

    rows = report.get("cores", [])
    if not isinstance(rows, list):
        errors.append(f"build report cores must be a list: {build_report_path}")
        return errors, warnings

    source_cores = set(inventory["umrk"].get("core_files", []))
    source_info = set(inventory["umrk"].get("info_files", []))
    _, metadata_by_file = metadata_core_maps(metadata)
    seen_core_files: set[str] = set()
    seen_library_names: dict[str, tuple[str, str]] = {}
    built_core_files: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            errors.append("build report core row must be an object")
            continue
        core = row.get("core", "")
        status = row.get("status", "")
        core_file = row.get("core_file", "")
        info_file = row.get("info_file", "")
        reason = row.get("reason", "")

        if status == "built":
            library_name = row.get("library_name")
            expected_sha256 = row.get("sha256")
            if not core_file or not str(core_file).endswith("_libretro.so"):
                errors.append(f"build report built core has invalid core_file: {core} -> {core_file}")
                continue
            if core_file in seen_core_files:
                errors.append(f"build report duplicate core_file: {core_file}")
            seen_core_files.add(core_file)
            built_core_files.add(core_file)
            folder_error = retroarch_generate_metadata.config_folder_error(library_name)
            if folder_error:
                errors.append(
                    f"build report {core_file} has invalid library_name {library_name!r}: "
                    f"{folder_error}"
                )
            else:
                prior_library = seen_library_names.get(library_name.casefold())
                if prior_library is not None:
                    errors.append(
                        f"build report library_name collision: "
                        f"{prior_library[0]}={prior_library[1]!r} and "
                        f"{core_file}={library_name!r}"
                    )
                else:
                    seen_library_names[library_name.casefold()] = (core_file, library_name)
            if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
                errors.append(f"build report {core_file} has invalid sha256: {expected_sha256!r}")
            if core_file not in source_cores:
                errors.append(f"build report built core not staged: {core} -> {core_file}")
            if info_file and info_file not in source_info:
                errors.append(f"build report built info not staged: {core} -> {info_file}")
            artifact_path = find_report_artifact(build_report_path, core_file, "cores")
            if artifact_path is None:
                errors.append(
                    f"build report core artifact unavailable for checksum validation: {core_file}"
                )
            elif isinstance(expected_sha256, str) and SHA256_RE.fullmatch(expected_sha256):
                actual_sha256 = sha256_file(artifact_path)
                if actual_sha256 != expected_sha256:
                    errors.append(
                        f"build report checksum mismatch: {core_file}: "
                        f"report={expected_sha256} actual={actual_sha256}"
                    )
            metadata_core = metadata_by_file.get(core_file)
            if metadata and not metadata_core:
                errors.append(f"build report built core missing from Phase 2 metadata: {core_file}")
            elif metadata_core and metadata_core.get("status") != "packaged":
                errors.append(
                    f"build report built core is not packaged in Phase 2 metadata: "
                    f"{metadata_core.get('id')} ({metadata_core.get('status')})"
                )
            elif metadata_core and metadata_core.get("id") != core:
                errors.append(
                    f"build report core id mismatch: {core_file}: "
                    f"metadata={metadata_core.get('id')!r} report={core!r}"
                )
            elif metadata_core and metadata_core.get("info_name") != info_file:
                errors.append(
                    f"build report info filename mismatch: {core_file}: "
                    f"metadata={metadata_core.get('info_name')!r} report={info_file!r}"
                )
            elif metadata_core and metadata_core.get("config_folder") != library_name:
                errors.append(
                    f"build report library_name mismatch: {core_file}: "
                    f"metadata={metadata_core.get('config_folder')!r} "
                    f"report={library_name!r}"
                )
        elif status in {"failed", "deferred"}:
            warnings.append(f"build report {status} core: {core} ({reason})")
        else:
            errors.append(f"build report invalid core status for {core}: {status}")

    requested_count = report.get("requested_count")
    if requested_count != len(rows):
        errors.append(
            f"build report requested_count does not match core rows: "
            f"{requested_count!r} != {len(rows)}"
        )
    actual_failed_count = sum(
        1 for row in rows if isinstance(row, dict) and row.get("status") == "failed"
    )
    actual_deferred_count = sum(
        1 for row in rows if isinstance(row, dict) and row.get("status") == "deferred"
    )
    actual_built_count = sum(
        1 for row in rows if isinstance(row, dict) and row.get("status") == "built"
    )
    actual_library_name_count = sum(
        1
        for row in rows
        if isinstance(row, dict)
        and row.get("status") == "built"
        and isinstance(row.get("library_name"), str)
        and bool(row.get("library_name"))
    )
    if report.get("built_count") != actual_built_count:
        errors.append(
            f"build report built_count does not match rows: "
            f"{report.get('built_count')!r} != {actual_built_count}"
        )
    if report.get("failed_count") != actual_failed_count:
        errors.append(
            f"build report failed_count does not match rows: "
            f"{report.get('failed_count')!r} != {actual_failed_count}"
        )
    if report.get("deferred_count") != actual_deferred_count:
        errors.append(
            f"build report deferred_count does not match rows: "
            f"{report.get('deferred_count')!r} != {actual_deferred_count}"
        )
    if report.get("library_name_count") != actual_library_name_count:
        errors.append(
            f"build report library_name_count does not match built rows: "
            f"{report.get('library_name_count')!r} != {actual_library_name_count}"
        )
    if actual_library_name_count != actual_built_count:
        errors.append(
            f"build report has {actual_built_count} built core(s) but only "
            f"{actual_library_name_count} library_name value(s)"
        )
    if report.get("library_name_status") != "complete":
        errors.append(
            f"build report library_name_status must be complete, got "
            f"{report.get('library_name_status')!r}"
        )
    generated_packaged_count = len(packaged_metadata_names(metadata)[0])
    if require_full and not metadata:
        errors.append("full build-report validation requires cores metadata")
    if metadata and (require_full or requested_count == generated_packaged_count):
        expected_core_files = packaged_metadata_names(metadata)[0]
        for core_file in sorted(expected_core_files - built_core_files):
            errors.append(f"full build report missing packaged core result: {core_file}")
        for core_file in sorted(built_core_files - expected_core_files):
            errors.append(f"full build report contains unexpected built core: {core_file}")
    elif metadata and requested_count != generated_packaged_count:
        warnings.append(
            f"build report covers {requested_count} requested core(s), "
            f"while Phase 2 metadata has {generated_packaged_count} packaged core(s); "
            "treating build report as a partial/targeted report"
        )

    return errors, warnings


def info_file_for_core(core_file: str) -> str:
    if core_file.endswith(".so"):
        return f"{core_file[:-3]}.info"
    return f"{Path(core_file).stem}.info"


def resolve_mlp1_package_root(package_root: Path) -> Path:
    candidates = [
        package_root,
        package_root / "UMRK" / "mlp1",
        package_root / "mlp1",
    ]
    for candidate in candidates:
        if (candidate / "manifest.json").is_file() or (
            candidate / "defaults" / "cores.json"
        ).is_file():
            return candidate
    return package_root / "UMRK" / "mlp1"


def load_package_json(path: Path, errors: list[str]) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"package JSON missing: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"package JSON invalid: {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"package JSON root must be an object: {path}")
        return {}
    return data


def compare_name_sets(
    label: str,
    expected: set[str],
    actual: set[str],
    errors: list[str],
) -> None:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    for name in missing:
        errors.append(f"{label} missing from package: {name}")
    for name in extra:
        errors.append(f"{label} unexpectedly packaged: {name}")


def validate_package_root(
    package_root: Path,
    inventory: dict,
    metadata: dict | None = None,
    build_report: dict | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    umrk = inventory["umrk"]
    mlp1_root = resolve_mlp1_package_root(package_root.resolve())

    if not mlp1_root.is_dir():
        errors.append(f"package MLP1 root missing: {mlp1_root}")
        return errors, warnings

    manifest = load_package_json(mlp1_root / "manifest.json", errors)
    if manifest and manifest.get("platform") != "mlp1":
        errors.append(f"package manifest platform is not mlp1: {mlp1_root / 'manifest.json'}")

    defaults = load_package_json(mlp1_root / "defaults" / "cores.json", errors)
    expanded_defaults = isinstance(defaults.get("cores"), list)
    package_systems_doc: dict = {}
    compat_systems = defaults.get("systems", {}) if isinstance(defaults, dict) else {}

    if expanded_defaults:
        package_systems_doc = load_package_json(mlp1_root / "defaults" / "systems.json", errors)
        if defaults.get("version") != 2:
            errors.append(f"package cores metadata version must be 2, got {defaults.get('version')}")
        if package_systems_doc.get("version") != 2:
            errors.append(
                f"package systems metadata version must be 2, got "
                f"{package_systems_doc.get('version')}"
            )
        if not isinstance(package_systems_doc.get("systems"), list) or not package_systems_doc.get("systems"):
            errors.append(f"package defaults have no systems metadata: {mlp1_root / 'defaults' / 'systems.json'}")
        validate_packaged_config_folders(defaults, "package cores metadata", errors)
        validate_canonical_folder_policy(package_systems_doc, "staged systems.json", errors)
        if metadata:
            if defaults != metadata.get("cores", {}):
                errors.append("package defaults/cores.json does not match generated Phase 3 cores metadata")
            if package_systems_doc != metadata.get("systems", {}):
                errors.append("package defaults/systems.json does not match generated Phase 3 systems metadata")
    else:
        if not compat_systems:
            errors.append(f"package defaults have no system mappings: {mlp1_root / 'defaults' / 'cores.json'}")
        if metadata and isinstance(metadata.get("cores", {}).get("cores"), list):
            errors.append(
                f"package defaults/cores.json still uses the compatibility shape after Phase 3 cutover: "
                f"{mlp1_root / 'defaults' / 'cores.json'}"
            )

    retroarch_bin = mlp1_root / "bin" / "retroarch"
    if not retroarch_bin.is_file():
        errors.append(f"package RetroArch binary missing: {retroarch_bin}")
    elif not os.access(retroarch_bin, os.X_OK):
        errors.append(f"package RetroArch binary is not executable: {retroarch_bin}")

    core_dir = mlp1_root / "cores"
    info_dir = mlp1_root / "info"
    package_cores = set(retroarch_inventory.list_names(core_dir, "*_libretro.so"))
    package_info = set(retroarch_inventory.list_names(info_dir, "*_libretro.info"))

    if not core_dir.is_dir():
        errors.append(f"package core directory missing: {core_dir}")
    if not info_dir.is_dir():
        errors.append(f"package info directory missing: {info_dir}")

    package_metadata = {"cores": defaults} if expanded_defaults else metadata
    expected_cores, expected_info = packaged_metadata_names(package_metadata)
    if not expected_cores:
        expected_cores = set(umrk.get("core_files", []))
    if not expected_info:
        expected_info = set(umrk.get("info_files", []))

    compare_name_sets("core", expected_cores, package_cores, errors)
    compare_name_sets("info file", expected_info, package_info, errors)

    metadata_by_id, metadata_by_file = metadata_core_maps(package_metadata)

    if build_report:
        report_rows = built_report_rows_by_file(build_report)
        # A report may be useful as an advisory targeted-build check on its
        # own, but once a package root is supplied it is the release contract:
        # every packaged RetroArch core must have one successful probe row.
        for core_file in sorted(expected_cores - set(report_rows)):
            errors.append(f"package contract build report missing core: {core_file}")
        for core_file in sorted(set(report_rows) - expected_cores):
            errors.append(f"package contract build report contains unexpected core: {core_file}")
        for core_file, row in sorted(report_rows.items()):
            if core_file not in package_cores:
                continue
            expected_sha256 = row.get("sha256")
            if isinstance(expected_sha256, str) and SHA256_RE.fullmatch(expected_sha256):
                actual_sha256 = sha256_file(core_dir / core_file)
                if actual_sha256 != expected_sha256:
                    errors.append(
                        f"package core checksum mismatch: {core_file}: "
                        f"report={expected_sha256} package={actual_sha256}"
                    )
            metadata_core = metadata_by_file.get(core_file)
            if metadata_core and metadata_core.get("config_folder") != row.get("library_name"):
                errors.append(
                    f"package core library_name mismatch: {core_file}: "
                    f"metadata={metadata_core.get('config_folder')!r} "
                    f"report={row.get('library_name')!r}"
                )

    for core_file in sorted(package_cores):
        expected_info = info_file_for_core(core_file)
        if expected_info not in package_info:
            errors.append(f"package core lacks matching info file: {core_file} -> {expected_info}")

    if expanded_defaults:
        for system in package_systems_doc.get("systems", []):
            if not isinstance(system, dict):
                errors.append("package system metadata row must be an object")
                continue
            system_id = system.get("id")
            legacy_flat_core = system.get("legacy_flat_core")
            expected_legacy_flat_core = (
                retroarch_generate_metadata.LEGACY_FLAT_CORE_BY_SYSTEM.get(system_id)
            )
            if legacy_flat_core != expected_legacy_flat_core:
                errors.append(
                    f"{system_id}: package legacy_flat_core must be "
                    f"{expected_legacy_flat_core!r}, got {legacy_flat_core!r}"
                )
            if legacy_flat_core is not None:
                owner = metadata_by_id.get(legacy_flat_core)
                if (
                    owner is None
                    or owner.get("type") != "retroarch"
                    or owner.get("status") != "packaged"
                ):
                    errors.append(
                        f"{system_id}: package legacy_flat_core must name a packaged "
                        f"RetroArch core: {legacy_flat_core}"
                    )
            default_core_id = system.get("default_core")
            core = metadata_by_id.get(default_core_id)
            if not core:
                errors.append(f"{system_id}: default core not in package cores metadata: {default_core_id}")
                continue
            if core.get("type") != "retroarch" or core.get("status") != "packaged":
                warnings.append(
                    f"{system_id}: default core is {core.get('status')}/{core.get('type')}; "
                    f"known but not launchable in Phase 3: {default_core_id}"
                )
                continue

            core_file = core.get("file_name")
            if core_file not in package_cores:
                alternate_ok = False
                for alternate_id in system.get("alternate_cores", []):
                    alternate = metadata_by_id.get(alternate_id)
                    if (
                        alternate
                        and alternate.get("type") == "retroarch"
                        and alternate.get("status") == "packaged"
                        and alternate.get("file_name") in package_cores
                    ):
                        alternate_ok = True
                        warnings.append(
                            f"{system_id}: default core missing from package, packaged alternate exists: "
                            f"{default_core_id} -> {alternate_id}"
                        )
                        break
                if not alternate_ok:
                    errors.append(f"{system_id}: default package core missing: {core_file}")
                continue

            expected_info = core.get("info_name") or info_file_for_core(core_file)
            if expected_info not in package_info:
                errors.append(f"{system_id}: default package core lacks info file: {expected_info}")
    else:
        for system_id, data in sorted(compat_systems.items()):
            core_file = data.get("core") if isinstance(data, dict) else None
            if not core_file:
                errors.append(f"{system_id}: package mapping has no core")
                continue
            if core_file not in package_cores:
                errors.append(f"{system_id}: mapped package core missing: {core_file}")
                continue
            metadata_core = metadata_by_file.get(core_file)
            if metadata and not metadata_core:
                errors.append(f"{system_id}: mapped package core not in metadata: {core_file}")
            elif metadata_core and metadata_core.get("status") != "packaged":
                errors.append(
                    f"{system_id}: mapped package core is not packaged in metadata: "
                    f"{metadata_core.get('id')} ({metadata_core.get('status')})"
                )
            expected_info = info_file_for_core(core_file)
            if expected_info not in package_info:
                errors.append(f"{system_id}: mapped package core lacks info file: {expected_info}")

    if "genesis_plus_gx_libretro.so" not in package_cores:
        errors.append("vertical-slice core missing from package: genesis_plus_gx_libretro.so")

    return errors, warnings


def parse_args(argv: list[str]) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument(
        "--package-root",
        action="append",
        type=Path,
        default=[],
        help="Validate a staged package root such as miniloong-launcher-switcher/build/package or build/sd.",
    )
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        help="Validate Phase 2 generated metadata from a directory containing cores.json and systems.json.",
    )
    parser.add_argument("--cores-metadata", type=Path)
    parser.add_argument("--systems-metadata", type=Path)
    parser.add_argument("--phase2-inventory", type=Path)
    parser.add_argument(
        "--canonical-systems",
        type=Path,
        help="Validate only the canonical user-folder policy on a staged systems.json "
        "(no inventory/core build required). Intended as a release-path gate.",
    )
    parser.add_argument(
        "--build-report",
        type=Path,
        help="Optionally validate a Cores-spruce build-report.json against staged outputs and metadata.",
    )
    parser.add_argument(
        "--require-full-build-report",
        action="store_true",
        help="Require --build-report to cover every packaged RetroArch core in the supplied metadata.",
    )
    parser.add_argument(
        "--builder-script",
        type=Path,
        help="Path to the Cores-spruce build-mlp1.sh that should have produced "
        "--build-report. Its sha256 is compared against the report's "
        "builder_script_sha256 to detect artifacts left over from an earlier builder.",
    )
    parser.add_argument(
        "--require-fresh-build-report",
        action="store_true",
        help="Treat a missing or mismatched builder identity as an error rather than a "
        "warning. Intended for release paths; dev staging gets the warning.",
    )
    parser.add_argument("--umrk-root", type=Path, default=root)
    parser.add_argument(
        "--allium-root", type=Path, default=root / "Allium"
    )
    parser.add_argument(
        "--spruce-root", type=Path, default=root / "spruceOS"
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.require_full_build_report and not args.build_report:
        print("error: --require-full-build-report requires --build-report", file=sys.stderr)
        return 2

    if args.require_fresh_build_report and not args.build_report:
        print("error: --require-fresh-build-report requires --build-report", file=sys.stderr)
        return 2

    if args.require_fresh_build_report and not args.builder_script:
        print(
            "error: --require-fresh-build-report requires --builder-script",
            file=sys.stderr,
        )
        return 2

    if args.canonical_systems:
        errors: list[str] = []
        systems_doc = load_json_document(args.canonical_systems, "staged systems.json", errors)
        validate_canonical_folder_policy(systems_doc, "staged systems.json", errors)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if errors:
            print(f"canonical-folder validation failed: {len(errors)} error(s)")
            return 1
        print("canonical-folder validation passed")
        return 0

    inventory = load_or_build_inventory(args)
    errors, warnings = validate(inventory)
    metadata = load_phase2_metadata(args, errors)

    if metadata:
        metadata_errors, metadata_warnings = validate_phase2_metadata(metadata, inventory)
        errors.extend(metadata_errors)
        warnings.extend(metadata_warnings)

    build_report: dict | None = None
    if args.build_report:
        build_report = load_json_document(args.build_report, "build report", errors)
        report_errors, report_warnings = validate_build_report(
            args.build_report,
            build_report,
            inventory,
            metadata,
            require_full=args.require_full_build_report,
            builder_script=args.builder_script,
            require_fresh=args.require_fresh_build_report,
        )
        errors.extend(report_errors)
        warnings.extend(report_warnings)

    for package_root in args.package_root:
        package_errors, package_warnings = validate_package_root(
            package_root,
            inventory,
            metadata,
            build_report,
        )
        errors.extend(package_errors)
        warnings.extend(package_warnings)

    warnings = list(dict.fromkeys(warnings))

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)

    if errors:
        print(f"RetroArch package validation failed: {len(errors)} error(s)")
        return 1

    print("RetroArch package validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
