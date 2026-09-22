#!/usr/bin/env python3
"""Reject private-workspace paths in executable Leaf release inputs."""

from pathlib import Path


root = Path(__file__).resolve().parent.parent
files = [root / "Makefile", *sorted((root / "stage").glob("*.mk"))]
files += [
    path
    for path in sorted((root / "scripts").iterdir())
    if path.suffix in {".sh", ".py"}
    and path.name not in {"bootstrap.sh", "check-public-release-path.py"}
    and "-test" not in path.stem
    and "-smoke" not in path.stem
    and "fixture" not in path.stem
]

violations = []
for path in files:
    for number, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.lstrip()
        if "umrk-workspace" not in line or stripped.startswith("#"):
            continue
        if path.name == "common.mk" and stripped.startswith("OPTIONAL_PRIVATE_REPOS :="):
            continue
        violations.append(f"{path.relative_to(root)}:{number}: {stripped}")

if violations:
    raise SystemExit("Private workspace dependency in release path:\n" + "\n".join(violations))
print("Public release path check passed")
