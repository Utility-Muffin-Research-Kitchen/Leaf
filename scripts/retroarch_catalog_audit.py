#!/usr/bin/env python3
"""Catalog audit + drift guard for the ROM-upload acceptance policy.

Reads the generated systems catalog (config/retroarch/mlp1/systems.json)
and both PRINTS a per-system policy inventory and ASSERTS the invariants the
Central Scrutinizer / Jawaka ROM-upload gate depends on. Exits non-zero on any
violation so it can gate producer changes (drift prevention).

Checks:
  * archive extensions / direct extensions / playlist extensions are lowercase and
    dotless (mirrors retroarch_validate_package.py);
  * archive_mode is a known mode, and a system that lists archive_extensions grants
    a *direct archive* upload only under a pass-through mode (matches the runtime
    classifier in CentralScrutinizer/src/rom_policy.c: only "pass_through" grants);
  * representative ZIP-capable systems still accept .zip, and representative
    disc/PSP systems still reject it -- derived from the catalog, never a hardcoded
    count (the current count is reported, not asserted);
  * the set of "empty policy" systems (no extensions/archive/playlist/exact names,
    so the gate fail-opens and cannot enforce a format) is exactly the documented
    allow-list; a NEW empty policy fails the audit and forces a decision.

Run: python3 scripts/retroarch_catalog_audit.py
     python3 scripts/retroarch_catalog_audit.py --systems <path> --quiet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Known archive_mode values (kept in step with retroarch_validate_package.py).
ALLOWED_ARCHIVE_MODES = {"pass_through", "extract_to_temp", "extract_to_cache", "ignore"}
# Only these modes grant a *direct* archive upload (mirrors src/rom_policy.c).
ARCHIVE_GRANTING_MODES = {"pass_through"}

# Documented dispositions for the systems whose policy is intentionally empty.
# These are redundant core-variant / legacy folder rows that mirror a canonical
# system; the gate fail-opens for them (enforced:false) so uploads still work, and
# the canonical row carries the real policy. See docs/rom-upload-catalog-audit.md.
DOCUMENTED_EMPTY_POLICIES = {
    "MAME2003": "MAME core variant; mirrors MAME (same ROMs, older core).",
    "MAME2010": "MAME core variant; mirrors MAME (same ROMs, older core).",
    "MD32X": "Legacy 32X-on-Mega-Drive row; the canonical 32X and MD rows carry the policy.",
}

# Representative systems, derived expectations verified against the catalog.
REPRESENTATIVE_ZIP_CAPABLE = [
    "AMIGA",
    "ATOMISWAVE",
    "FC",
    "GBA",
    "MAME",
    "NAOMI",
    "N64",
    "NEOGEO",
    "PC98",
    "SFC",
]
REPRESENTATIVE_NON_ZIP = ["PSP", "PS", "DC", "PCECD"]


def load_systems(path: Path) -> list[dict]:
    doc = json.loads(path.read_text())
    systems = doc["systems"] if isinstance(doc, dict) and "systems" in doc else doc
    return systems if isinstance(systems, list) else list(systems.values())


def lower(values) -> list[str]:
    return [str(v).lower() for v in (values or [])]


def accepts_zip(system: dict) -> bool:
    """Mirror the runtime: a direct archive upload needs the extension in
    archive_extensions AND a pass-through-granting archive_mode."""
    mode = system.get("archive_mode") or ""
    return "zip" in lower(system.get("archive_extensions")) and mode in ARCHIVE_GRANTING_MODES


def is_empty_policy(system: dict) -> bool:
    return not any(
        system.get(field)
        for field in ("extensions", "archive_extensions", "playlist_extensions", "file_names")
    )


def audit(systems: list[dict], quiet: bool) -> list[str]:
    errors: list[str] = []
    zip_capable: list[str] = []
    empty: list[str] = []

    if not quiet:
        print(f"{'ID':<14}{'direct':<24}{'archive (mode)':<24}{'playlist':<10}exact/ignore")
        print("-" * 96)

    for system in sorted(systems, key=lambda s: s.get("id", "")):
        sid = system.get("id", "?")
        ext = lower(system.get("extensions"))
        aext = lower(system.get("archive_extensions"))
        mode = system.get("archive_mode") or ""
        pl = lower(system.get("playlist_extensions"))
        fn = system.get("file_names") or []
        ig = system.get("ignore_file_names") or []

        # lowercase / dotless
        for field in ("extensions", "archive_extensions", "archive_inner_extensions", "playlist_extensions"):
            for value in system.get(field, []) or []:
                if value != value.lower() or str(value).startswith("."):
                    errors.append(f"{sid}: {field} entry is not lowercase/dotless: {value!r}")

        # known archive_mode
        if mode not in ALLOWED_ARCHIVE_MODES:
            errors.append(f"{sid}: unknown archive_mode: {mode!r}")

        # direct archive permission tied to a granting mode
        if aext and mode not in ARCHIVE_GRANTING_MODES:
            errors.append(
                f"{sid}: lists archive_extensions {aext} but archive_mode {mode!r} does not grant a direct archive upload"
            )

        if accepts_zip(system):
            zip_capable.append(sid)
        if is_empty_policy(system):
            empty.append(sid)

        if not quiet:
            exact = ",".join(fn) + ("/" + ",".join(ig) if ig else "")
            print(f"{sid:<14}{','.join(ext)[:22]:<24}{(','.join(aext) + ' (' + mode + ')')[:22]:<24}{','.join(pl)[:8]:<10}{exact}")

    zip_set = set(zip_capable)
    empty_set = set(empty)

    # representative regression (derived, not a hardcoded count)
    for sid in REPRESENTATIVE_ZIP_CAPABLE:
        if sid not in zip_set:
            errors.append(f"regression: representative ZIP-capable system {sid} no longer accepts .zip")
    for sid in REPRESENTATIVE_NON_ZIP:
        if sid in zip_set:
            errors.append(f"regression: {sid} unexpectedly became ZIP-capable")

    # empty-policy allow-list (drift guard)
    for sid in sorted(empty_set - DOCUMENTED_EMPTY_POLICIES.keys()):
        errors.append(
            f"empty policy: {sid} accepts nothing and is not documented in DOCUMENTED_EMPTY_POLICIES "
            f"(add a disposition or give it a policy)"
        )
    for sid in sorted(DOCUMENTED_EMPTY_POLICIES.keys() - empty_set):
        errors.append(f"empty policy: {sid} is documented as empty but now carries a policy (update the audit doc)")

    if not quiet:
        print("-" * 96)
        print(f"total systems: {len(systems)}")
        print(f"ZIP-capable ({len(zip_set)}/{len(systems)}): {' '.join(sorted(zip_set))}")
        print(f"empty policy (fail-open, documented): {' '.join(sorted(empty_set))}")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--systems",
        type=Path,
        default=root / "config/retroarch/mlp1/systems.json",
    )
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    args = parser.parse_args()

    if not args.systems.is_file():
        print(f"error: systems catalog not found: {args.systems}", file=sys.stderr)
        return 2

    errors = audit(load_systems(args.systems), args.quiet)
    if errors:
        print("\nROM-upload catalog audit FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  error: {err}", file=sys.stderr)
        return 1
    print("\nROM-upload catalog audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
