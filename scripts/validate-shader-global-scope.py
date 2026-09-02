#!/usr/bin/env python3
"""Validate the assembled Fugazi against Jawaka's global shader scope.

Jawaka's in-game picker can save a shader preset at RetroArch's global scope.
That save can replace a preset another app owns, so it is only safe when the
assembled Leaf build also ships a Fugazi that recognizes a foreign global
preset, keeps one recoverable predecessor, and can resolve the resulting
current-preset-plus-backup conflict. Fugazi 0.2.0 is the first release with
that resolver.

Jawaka decides the scope at compile time with JW_FUGAZI_RESOLVER_ASSEMBLED and
cannot see which Fugazi Leaf assembles beside it. This gate closes that gap by
reading both assembled artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Fugazi 0.2.0 carries the ownership-safe conflict resolver (Fugazi PRs #1 and
# #2). Raise this only when a newer Fugazi becomes required for the scope to
# stay recoverable, never to paper over an older assembled app.
RESOLVER_FLOOR = (0, 2, 0)

# Jawaka draws this row hint only while the scope is gated off, so the compiled
# menu carries the literal exactly when the constant is false.
DISABLED_MARKER = b"Requires Fugazi resolver"

GATE_PATTERN = re.compile(
    r"^#define\s+JW_FUGAZI_RESOLVER_ASSEMBLED\s+(true|false)\s*$",
    re.MULTILINE,
)


def gate_from_source(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"cannot read Jawaka source {path}: {exc}") from exc
    matches = GATE_PATTERN.findall(text)
    if not matches:
        raise ValueError(f"{path}: no JW_FUGAZI_RESOLVER_ASSEMBLED definition")
    if len(set(matches)) > 1:
        raise ValueError(f"{path}: conflicting JW_FUGAZI_RESOLVER_ASSEMBLED definitions")
    return matches[0] == "true"


def gate_from_binary(path: Path) -> bool:
    try:
        blob = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read assembled menu binary {path}: {exc}") from exc
    if not blob:
        raise ValueError(f"{path}: assembled menu binary is empty")
    return DISABLED_MARKER not in blob


def parse_version(raw: object, source: Path) -> tuple[int, ...]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{source}: pak_version must be a non-empty string")
    parts = raw.strip().split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"{source}: pak_version {raw!r} is not a three-part numeric version")
    return tuple(int(part) for part in parts)


def read_fugazi_version(path: Path) -> tuple[tuple[int, ...], str]:
    manifest = path / "pak.json" if path.is_dir() else path
    if not manifest.is_file():
        raise ValueError(f"missing assembled Fugazi pak manifest: {manifest}")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {manifest}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{manifest} must contain a JSON object")
    raw = document.get("pak_version")
    return parse_version(raw, manifest), str(raw).strip()


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--menu-binary",
        type=Path,
        required=True,
        help="assembled jawaka-menu binary",
    )
    parser.add_argument(
        "--fugazi-pak",
        type=Path,
        required=True,
        help="assembled Fugazi.pak directory or its pak.json",
    )
    parser.add_argument(
        "--jawaka-source",
        type=Path,
        help="cmd/jawaka-menu/main.c the payload was built from, when available",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        binary_gate = gate_from_binary(args.menu_binary)
        source_gate = (
            gate_from_source(args.jawaka_source) if args.jawaka_source else None
        )
        # A payload built from different source than the checkout on hand is a
        # stale assembly. Report it rather than trusting either half.
        if source_gate is not None and source_gate != binary_gate:
            raise ValueError(
                "assembled jawaka-menu does not match the Jawaka source gate: "
                f"source says {'enabled' if source_gate else 'disabled'}, "
                f"binary says {'enabled' if binary_gate else 'disabled'}"
            )
        enabled = binary_gate if source_gate is None else source_gate

        version, raw = read_fugazi_version(args.fugazi_pak)
        if enabled and version < RESOLVER_FLOOR:
            raise ValueError(
                f"assembled Fugazi {raw} is below the "
                f"{format_version(RESOLVER_FLOOR)} floor required by the enabled "
                "All RetroArch shader scope"
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if enabled:
        print(
            f"global shader scope: enabled; assembled Fugazi {raw} meets the "
            f"{format_version(RESOLVER_FLOOR)} resolver floor"
        )
    else:
        print(
            f"global shader scope: disabled in this build; assembled Fugazi {raw} "
            "is not gated"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
