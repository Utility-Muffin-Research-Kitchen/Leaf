#!/usr/bin/env python3
"""Validate the MLP1 PPSSPP Vulkan runtime/package/metadata contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


VULKAN_RUNTIME_ID = "rk3566-g52-g29p1"


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"error: expected JSON object: {path}")
    return value


def validate(platform: Path) -> None:
    runtime = platform / f"runtime/graphics/vulkan/{VULKAN_RUNTIME_ID}"
    runtime_manifest = load_json(runtime / "manifest.json")
    if runtime_manifest.get("id") != VULKAN_RUNTIME_ID:
        raise SystemExit("error: unexpected Vulkan runtime id")
    if runtime_manifest.get("kind") != "platform-vulkan-runtime":
        raise SystemExit("error: unexpected Vulkan runtime kind")

    files = runtime_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("error: Vulkan runtime manifest has no file inventory")
    for row in files:
        if not isinstance(row, dict) or not row.get("path") or not row.get("sha256"):
            raise SystemExit("error: malformed Vulkan runtime file inventory")
        path = runtime / row["path"]
        if not path.is_file():
            raise SystemExit(f"error: Vulkan runtime file missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row["sha256"]:
            raise SystemExit(f"error: Vulkan runtime checksum mismatch: {path}")

    package = platform / "emulators/ppsspp"
    manifest = load_json(package / "manifest.json")
    if manifest.get("default_graphics_backend") != "vulkan-display":
        raise SystemExit("error: PPSSPP package does not default to Vulkan display")
    if manifest.get("vulkan_runtime") != runtime_manifest.get("id"):
        raise SystemExit("error: PPSSPP and Vulkan runtime manifests disagree")
    if manifest.get("fallback_entrypoint") != "launch-gles.sh":
        raise SystemExit("error: PPSSPP package does not declare the GLES fallback")
    for rel in ("launch.sh", "launch-gles.sh", "bin/PPSSPPSDL"):
        path = package / rel
        if not path.is_file() or not os.access(path, os.X_OK):
            raise SystemExit(f"error: PPSSPP executable missing: {path}")

    launch_text = (package / "launch.sh").read_text(encoding="utf-8")
    if "USERDATA_PATH" not in launch_text:
        raise SystemExit("error: PPSSPP launcher does not use USERDATA_PATH")
    launch_lines = launch_text.splitlines()
    if not any(
        line.strip() == 'ROTATION_MODE="${ROTATION_MODE:-native}"'
        for line in launch_lines
    ):
        raise SystemExit("error: native rotation is not the Vulkan default")
    native_rotation = launch_text.split("            native)", 1)[-1].split(
        "                ;;", 1
    )[0]
    if "portmaster" in native_rotation.lower():
        raise SystemExit("error: native PPSSPP rotation depends on PortMaster")
    if 'STATE_ROOT="$PLATFORM_ROOT/state/ppsspp"' in launch_lines:
        raise SystemExit("error: PPSSPP launcher still writes release-managed state")
    if 'OLD_STATE_ROOT="$PLATFORM_ROOT/state/ppsspp"' not in launch_lines:
        raise SystemExit("error: PPSSPP launcher lost the one-time legacy state migration")

    cores = load_json(platform / "defaults/cores.json").get("cores")
    systems = load_json(platform / "defaults/systems.json").get("systems")
    if not isinstance(cores, list) or not isinstance(systems, list):
        raise SystemExit("error: malformed PPSSPP metadata catalog")
    by_core = {row.get("id"): row for row in cores if isinstance(row, dict)}
    by_system = {row.get("id"): row for row in systems if isinstance(row, dict)}
    if not by_core.get("ppsspp", {}).get("requires_direct_drm"):
        raise SystemExit("error: Vulkan PPSSPP core must request direct DRM")
    if by_core.get("ppsspp_gles", {}).get("requires_direct_drm"):
        raise SystemExit("error: GLES PPSSPP core must not request direct DRM")
    if by_core.get("ppsspp_gles", {}).get("path") != "emulators/ppsspp/launch-gles.sh":
        raise SystemExit("error: GLES PPSSPP core points at the wrong launcher")
    if by_system.get("PSP", {}).get("default_core") != "ppsspp":
        raise SystemExit("error: PSP does not default to Vulkan PPSSPP")
    if "ppsspp_gles" not in by_system.get("PSP", {}).get("alternate_cores", []):
        raise SystemExit("error: PSP has no GLES fallback core")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform_dir", type=Path)
    args = parser.parse_args()
    validate(args.platform_dir)
    print("PPSSPP Vulkan gate: runtime, package, metadata, and fallback verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
