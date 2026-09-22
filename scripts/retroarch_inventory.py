#!/usr/bin/env python3
"""Read-only RetroArch parity inventory for UMRK Phase 0."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


ARCHIVE_EXTENSIONS = {"zip", "7z", "rar", "gz"}
CONTAINER_EXTENSIONS = {
    "m3u",
    "m3u8",
    "chd",
    "cue",
    "iso",
    "pbp",
    "cso",
    "gdi",
    "cdi",
    "img",
    "mdf",
    "toc",
    "cbn",
    "ccd",
}


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def leaf_repo_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def load_json(path: Path, warnings: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(f"missing JSON file: {path}")
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid JSON: {path}: {exc}")
    return None


def load_toml(path: Path, warnings: list[str]) -> dict[str, Any]:
    try:
        with path.open("rb") as fp:
            return tomllib.load(fp)
    except FileNotFoundError:
        warnings.append(f"missing TOML file: {path}")
    except tomllib.TOMLDecodeError as exc:
        warnings.append(f"invalid TOML: {path}: {exc}")
    return {}


def core_id_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    name = Path(filename).name
    for suffix in ("_libretro.so", "_libretro.info"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def split_extlist(extlist: str | None) -> list[str]:
    if not extlist:
        return []
    return sorted({part.strip().lower() for part in extlist.split("|") if part.strip()})


def list_names(path: Path, pattern: str) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(item.name for item in path.glob(pattern) if item.is_file())


def inventory_umrk(root: Path, warnings: list[str]) -> dict[str, Any]:
    cores_json_path = root / "miniloong-launcher-switcher/device/mlp1/defaults/cores.json"
    systems_json_path = root / "miniloong-launcher-switcher/device/mlp1/defaults/systems.json"
    cores_json = load_json(cores_json_path, warnings) or {}

    core_dir = root / "Cores-spruce/output/mlp1/cores"
    info_dir = root / "Cores-spruce/output/mlp1/info"
    retroarch_bin = root / "retroarch-builds/output/mlp1/bin/retroarch"

    mappings = []
    stock_aliases: dict[str, Any] = {}
    if isinstance(cores_json.get("cores"), list):
        systems_json = load_json(systems_json_path, warnings) or {}
        cores_by_id = {
            core.get("id"): core
            for core in cores_json.get("cores", [])
            if isinstance(core, dict) and core.get("id")
        }
        for system in sorted(
            (row for row in systems_json.get("systems", []) if isinstance(row, dict)),
            key=lambda row: row.get("id", ""),
        ):
            core = cores_by_id.get(system.get("default_core"))
            core_file = core.get("file_name") if isinstance(core, dict) else None
            mappings.append(
                {
                    "system_id": system.get("id"),
                    "core_file": core_file,
                    "core_id": core.get("id") if isinstance(core, dict) else system.get("default_core"),
                    "info_file": core.get("info_name") if isinstance(core, dict) else None,
                    "core_type": core.get("type") if isinstance(core, dict) else None,
                    "core_status": core.get("status") if isinstance(core, dict) else None,
                    "metadata_shape": "expanded",
                }
            )
    else:
        systems = cores_json.get("systems", {})
        stock_aliases = cores_json.get("stock_parity_core_names", {})
        for system_id, data in sorted(systems.items()):
            core_file = data.get("core") if isinstance(data, dict) else None
            mappings.append(
                {
                    "system_id": system_id,
                    "core_file": core_file,
                    "core_id": core_id_from_filename(core_file),
                    "info_file": (
                        f"{core_id_from_filename(core_file)}_libretro.info"
                        if core_id_from_filename(core_file)
                        else None
                    ),
                    "core_type": "retroarch",
                    "core_status": "packaged",
                    "metadata_shape": "compat",
                }
            )

    return {
        "cores_json": rel(cores_json_path, root),
        "systems_json": rel(systems_json_path, root),
        "cores_json_shape": "expanded" if isinstance(cores_json.get("cores"), list) else "compat",
        "mapping_count": len(mappings),
        "current_mappings": mappings,
        "stock_parity_core_names": dict(sorted(stock_aliases.items())),
        "core_dir": rel(core_dir, root),
        "core_dir_exists": core_dir.is_dir(),
        "core_files": list_names(core_dir, "*_libretro.so"),
        "info_dir": rel(info_dir, root),
        "info_dir_exists": info_dir.is_dir(),
        "info_files": list_names(info_dir, "*_libretro.info"),
        "retroarch_binary": rel(retroarch_bin, root),
        "retroarch_binary_exists": retroarch_bin.is_file(),
    }


def inventory_allium(root: Path, warnings: list[str]) -> dict[str, Any]:
    config_dir = root / "static/.allium/config"
    consoles_toml = load_toml(config_dir / "consoles.toml", warnings)
    cores_toml = load_toml(config_dir / "cores.toml", warnings)

    consoles = []
    for item in consoles_toml.get("consoles", []):
        consoles.append(
            {
                "name": item.get("name"),
                "patterns": sorted(item.get("patterns", [])),
                "extensions": sorted(ext.lower() for ext in item.get("extensions", [])),
                "file_names": sorted(item.get("file_name", [])),
                "cores": item.get("cores", []),
            }
        )
    consoles.sort(key=lambda item: (item.get("name") or "").lower())

    cores = []
    for core_id, item in sorted(cores_toml.get("cores", {}).items()):
        core_type = "retroarch" if "retroarch" in item else "path"
        cores.append(
            {
                "id": core_id,
                "name": item.get("name", core_id),
                "type": core_type,
                "retroarch": item.get("retroarch"),
                "path": item.get("path"),
                "swap": bool(item.get("swap", False)),
            }
        )

    return {
        "root_exists": root.is_dir(),
        "console_count": len(consoles),
        "core_count": len(cores),
        "consoles": consoles,
        "cores": cores,
    }


def selected_emulators(menu_options: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(menu_options, dict):
        return []
    result = []
    for key, value in sorted(menu_options.items()):
        if not key.startswith("Emulator") or not isinstance(value, dict):
            continue
        result.append(
            {
                "key": key,
                "selected": value.get("selected"),
                "options": value.get("options", []),
                "devices": value.get("devices", []),
            }
        )
    return result


def parse_core_mappings(path: Path, warnings: list[str]) -> dict[str, str]:
    if not path.is_file():
        warnings.append(f"missing spruce core mapping file: {path}")
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r'"([^"]+_libretro\.so)"\)\s+echo\s+"([^"]+)"', text)
    return dict(sorted(matches))


def inventory_spruce(root: Path, warnings: list[str]) -> dict[str, Any]:
    emu_root = root / "Emu"
    systems = []
    invalid_configs = []

    for config_path in sorted(emu_root.glob("*/config.json")):
        data = load_json(config_path, warnings)
        if not isinstance(data, dict):
            invalid_configs.append(str(config_path))
            continue

        system_id = config_path.parent.name
        extensions = split_extlist(data.get("extlist"))
        archive_extensions = [ext for ext in extensions if ext in ARCHIVE_EXTENSIONS]
        container_extensions = [ext for ext in extensions if ext in CONTAINER_EXTENSIONS]
        ignore_list = sorted(name.lower() for name in data.get("ignoreList", []))
        launchlist = data.get("launchlist", [])
        m3u_generators = []
        for item in launchlist if isinstance(launchlist, list) else []:
            launch = item.get("launch") if isinstance(item, dict) else None
            if launch and "m3u_generator" in launch:
                m3u_generators.append(launch)

        emulators = selected_emulators(data.get("menuOptions"))
        selected_names = sorted(
            {
                emulator.get("selected")
                for emulator in emulators
                if emulator.get("selected")
            }
        )
        standalone_needed = any("standalone" in name for name in selected_names)

        systems.append(
            {
                "id": system_id,
                "label": data.get("label", system_id),
                "launch": data.get("launch"),
                "extlist": data.get("extlist", ""),
                "extensions": extensions,
                "archive_extensions": archive_extensions,
                "container_extensions": container_extensions,
                "ignore_file_names": ignore_list,
                "m3u_generators": sorted(m3u_generators),
                "default_emulator": data.get("default_emulator"),
                "selected_emulators": selected_names,
                "emulator_options": emulators,
                "alternative_folder_names": data.get("alternativeFolderNames", []),
                "standalone_needed": standalone_needed,
            }
        )

    core_mappings = parse_core_mappings(
        root / "spruce/scripts/emu/lib/core_mappings.sh", warnings
    )

    archive_summary = {}
    for ext in sorted(ARCHIVE_EXTENSIONS | CONTAINER_EXTENSIONS):
        archive_summary[ext] = sum(
            1 for system in systems if ext in system["extensions"]
        )

    return {
        "root_exists": root.is_dir(),
        "system_count": len(systems),
        "invalid_configs": invalid_configs,
        "systems": systems,
        "core_mappings": core_mappings,
        "core_mapping_count": len(core_mappings),
        "archive_summary": archive_summary,
    }


def find_allium_console(allium: dict[str, Any], system_id: str) -> dict[str, Any] | None:
    wanted = system_id.lower()
    for console in allium.get("consoles", []):
        patterns = [pattern.lower() for pattern in console.get("patterns", [])]
        if wanted in patterns:
            return console
    return None


def find_spruce_system(spruce: dict[str, Any], system_id: str) -> dict[str, Any] | None:
    wanted = system_id.lower()
    for system in spruce.get("systems", []):
        names = [system.get("id", "").lower()]
        names.extend(str(name).lower() for name in system.get("alternative_folder_names", []))
        if wanted in names:
            return system
    return None


def build_parity_matrix(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    umrk = inventory["umrk"]
    allium = inventory["allium"]
    spruce = inventory["spruce"]
    core_files = set(umrk.get("core_files", []))
    info_files = set(umrk.get("info_files", []))

    matrix = []
    for mapping in umrk.get("current_mappings", []):
        system_id = mapping["system_id"]
        core_file = mapping["core_file"]
        core_id = mapping["core_id"]
        core_type = mapping.get("core_type")
        core_status = mapping.get("core_status")
        expected_info = mapping.get("info_file") or (f"{core_id}_libretro.info" if core_id else None)
        allium_console = find_allium_console(allium, system_id)
        spruce_system = find_spruce_system(spruce, system_id)

        core_available = core_file in core_files
        info_available = expected_info in info_files if expected_info else False
        known_unsupported = (
            mapping.get("metadata_shape") == "expanded" and
            (core_type != "retroarch" or core_status != "packaged")
        )
        if core_available and info_available:
            status = "ready"
        elif core_available and not info_available:
            status = "missing_info"
        elif known_unsupported:
            status = "known_unsupported"
        elif umrk.get("core_dir_exists"):
            status = "mapped_missing_core"
        else:
            status = "needs_policy"

        extensions = []
        archive_extensions = []
        ignore_file_names = []
        m3u_generators = []
        spruce_default = None
        if spruce_system:
            extensions = spruce_system.get("extensions", [])
            archive_extensions = spruce_system.get("archive_extensions", [])
            ignore_file_names = spruce_system.get("ignore_file_names", [])
            m3u_generators = spruce_system.get("m3u_generators", [])
            spruce_default = spruce_system.get("default_emulator")
        elif allium_console:
            extensions = allium_console.get("extensions", [])

        matrix.append(
            {
                "system_id": system_id,
                "current_core_file": core_file,
                "current_core_id": core_id,
                "current_core_type": core_type,
                "current_core_status": core_status,
                "packaged_core": core_available,
                "expected_info": expected_info,
                "packaged_info": info_available,
                "allium_default_core": (
                    allium_console.get("cores", [None])[0] if allium_console else None
                ),
                "allium_alternate_cores": (
                    allium_console.get("cores", [])[1:] if allium_console else []
                ),
                "spruce_default_emulator": spruce_default,
                "extensions": extensions,
                "archive_extensions": archive_extensions,
                "ignore_file_names": ignore_file_names,
                "m3u_generators": m3u_generators,
                "standalone_needed": bool(
                    spruce_system and spruce_system.get("standalone_needed")
                ),
                "status": status,
            }
        )

    return matrix


def build_inventory(umrk_root: Path, allium_root: Path, spruce_root: Path) -> dict[str, Any]:
    warnings: list[str] = []
    inventory = {
        "format_version": 1,
        "generated_by": "scripts/retroarch_inventory.py",
        "repos": {
            "umrk": str(umrk_root),
            "allium": str(allium_root),
            "spruce": str(spruce_root),
        },
        "warnings": warnings,
        "umrk": inventory_umrk(umrk_root, warnings),
        "allium": inventory_allium(allium_root, warnings),
        "spruce": inventory_spruce(spruce_root, warnings),
    }
    inventory["parity_matrix"] = build_parity_matrix(inventory)
    return inventory


def md_escape(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(value) for value in row) + " |")
    return "\n".join(lines)


def render_markdown(inventory: dict[str, Any]) -> str:
    umrk = inventory["umrk"]
    allium = inventory["allium"]
    spruce = inventory["spruce"]
    matrix = inventory["parity_matrix"]

    status_counts: dict[str, int] = {}
    for row in matrix:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    archive_rows = [
        [ext, count]
        for ext, count in sorted(spruce.get("archive_summary", {}).items())
        if count
    ]

    mapping_rows = [
        [
            row["system_id"],
            row["current_core_file"],
            "yes" if row["packaged_core"] else "no",
            row["expected_info"],
            "yes" if row["packaged_info"] else "no",
            row["status"],
        ]
        for row in matrix
    ]

    parity_rows = [
        [
            row["system_id"],
            row["allium_default_core"],
            row["spruce_default_emulator"],
            row["extensions"],
            row["archive_extensions"],
            row["ignore_file_names"],
            "yes" if row["m3u_generators"] else "",
            row["status"],
        ]
        for row in matrix
    ]

    warning_lines = "\n".join(f"- {warning}" for warning in inventory["warnings"])
    if not warning_lines:
        warning_lines = "- none"

    return "\n".join(
        [
            "# RetroArch Phase 0 inventory",
            "",
            "Generated by `scripts/retroarch_inventory.py`.",
            "",
            "## Summary",
            "",
            table(
                ["Area", "Count"],
                [
                    ["UMRK current system mappings", umrk["mapping_count"]],
                    ["UMRK packaged cores", len(umrk["core_files"])],
                    ["UMRK packaged info files", len(umrk["info_files"])],
                    ["UMRK RetroArch binary present", "yes" if umrk["retroarch_binary_exists"] else "no"],
                    ["Allium consoles", allium["console_count"]],
                    ["Allium cores", allium["core_count"]],
                    ["spruce systems", spruce["system_count"]],
                    ["spruce core mappings", spruce["core_mapping_count"]],
                ],
            ),
            "",
            "## Matrix Status",
            "",
            table(["Status", "Count"], sorted(status_counts.items())),
            "",
            "## Warnings",
            "",
            warning_lines,
            "",
            "## spruce Archive And Container Coverage",
            "",
            table(["Extension", "System count"], archive_rows),
            "",
            "## Current UMRK Mapping Health",
            "",
            table(
                ["System", "Current core", "Core packaged", "Expected info", "Info packaged", "Status"],
                mapping_rows,
            ),
            "",
            "## Reference Matching Snapshot",
            "",
            table(
                [
                    "System",
                    "Allium default",
                    "spruce default",
                    "Extensions",
                    "Archives",
                    "Ignored names",
                    "M3U",
                    "Status",
                ],
                parity_rows,
            ),
            "",
        ]
    )


def write_reports(inventory: dict[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "phase-0-inventory.json"
    md_path = reports_dir / "phase-0-inventory.md"
    json_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(inventory), encoding="utf-8")
    return md_path, json_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    root = repo_root_from_script()
    leaf_repo = leaf_repo_from_script()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--umrk-root", type=Path, default=root)
    parser.add_argument(
        "--allium-root", type=Path, default=root / "Allium"
    )
    parser.add_argument(
        "--spruce-root", type=Path, default=root / "spruceOS"
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=leaf_repo / "build/retroarch/reports",
    )
    parser.add_argument("--no-write", action="store_true", help="print JSON to stdout")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    inventory = build_inventory(
        args.umrk_root.resolve(),
        args.allium_root.resolve(),
        args.spruce_root.resolve(),
    )
    if args.no_write:
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return 0

    md_path, json_path = write_reports(inventory, args.reports_dir)
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    if inventory["warnings"]:
        print(f"warnings: {len(inventory['warnings'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
