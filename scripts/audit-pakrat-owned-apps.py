#!/usr/bin/env python3
"""Reject Pak Rat-owned optional apps from a Leaf release payload."""

from __future__ import annotations

import json
import pathlib
import sys


def read_managed_apps(path: pathlib.Path) -> list[str]:
    if not path.is_file():
        raise SystemExit(f"error: missing managed app list: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: audit-pakrat-owned-apps.py RELEASE_ROOT PACKAGE.pak [...]"
        )

    release_root = pathlib.Path(sys.argv[1])
    owned = {name.casefold(): name for name in sys.argv[2:]}
    platform = release_root / "platforms" / "mlp1"
    managed_file = release_root / "managed-apps.txt"
    manifest_path = platform / "manifest.json"

    managed_apps = read_managed_apps(managed_file)
    if not manifest_path.is_file():
        raise SystemExit(f"error: missing platform manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_apps = manifest.get("managed_apps", [])
    if not isinstance(manifest_apps, list):
        raise SystemExit("error: platform manifest managed_apps must be a list")

    violations: list[str] = []
    for source, entries in (
        ("managed-apps.txt", managed_apps),
        ("platform manifest", manifest_apps),
    ):
        for entry in entries:
            package = pathlib.PurePosixPath(str(entry)).name.casefold()
            if package in owned:
                violations.append(
                    f"{source} claims Pak Rat-owned {owned[package]}: {entry}"
                )

    apps_root = release_root / "Apps"
    if apps_root.is_dir():
        for path in apps_root.rglob("*"):
            package = path.name.casefold()
            if package in owned:
                violations.append(
                    f"release stages Pak Rat-owned {owned[package]}: {path}"
                )

    if violations:
        raise SystemExit("error: " + "\nerror: ".join(violations))

    names = ", ".join(owned.values())
    print(f"Pak Rat ownership gate: optional apps absent from release ({names})")


if __name__ == "__main__":
    main()
