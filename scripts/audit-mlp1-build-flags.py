#!/usr/bin/env python3
"""Audit MLP1 release payload manifests for the RK3566/A55 build contract."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED_PLATFORM = "mlp1"
EXPECTED_SOC = "rk3566"
EXPECTED_CPU = "cortex-a55"
EXPECTED_CPU_FLAG = "-mcpu=cortex-a55"
EXPECTED_TUNE_FLAG = "-mtune=cortex-a55"
KNOWN_PROFILES = {"release", "size", "perf", "debug"}


@dataclass(frozen=True)
class ManifestSpec:
    label: str
    relpath: str
    kind: str = "binary"
    required: bool = True
    allow_missing_flags: bool = False


@dataclass(frozen=True)
class AuditRoot:
    label: str
    root: Path
    platform_dir: Path
    apps_dir: Path | None


@dataclass
class Finding:
    level: str
    path: str
    message: str


SPECS = [
    ManifestSpec("Jawaka launcher", "platforms/mlp1/launcher/build-manifest.json"),
    ManifestSpec("RetroArch", "platforms/mlp1/bin/retroarch.build-manifest.json"),
    ManifestSpec("libretro cores", "platforms/mlp1/cores/build-report.json", kind="cores", allow_missing_flags=True),
    ManifestSpec("PPSSPP", "platforms/mlp1/emulators/ppsspp/manifest.json"),
    ManifestSpec("DraStic", "platforms/mlp1/emulators/drastic/manifest.json", allow_missing_flags=True),
    ManifestSpec("Mupen64Plus", "platforms/mlp1/emulators/mupen64plus/manifest.json"),
    ManifestSpec("SSH server", "Apps/mlp1/SSHServer.pak/build-manifest.json"),
    ManifestSpec("Thing-File", "Apps/mlp1/Thing-File.pak/build-manifest.json"),
    ManifestSpec("CentralScrutinizer", "Apps/mlp1/CentralScrutinizer.pak/build-manifest.json"),
    ManifestSpec("Fugazi", "Apps/mlp1/Fugazi.pak/build-manifest.json"),
    ManifestSpec("Joe's Calibrage", "Apps/mlp1/Joe's Calibrage.pak/build-manifest.json"),
    ManifestSpec(
        "RetroArch app pak",
        "Apps/shared/RetroArch.pak/build-manifest.json",
        kind="metadata",
        required=False,
        allow_missing_flags=True,
    ),
]


def finding_level(strict: bool) -> str:
    return "error" if strict else "warning"


def add(findings: list[Finding], level: str, path: Path | str, message: str) -> None:
    findings.append(Finding(level=level, path=str(path), message=message))


def discover_audit_roots(path: Path) -> list[AuditRoot]:
    root = path.resolve()
    release_root = root / "platforms" / EXPECTED_PLATFORM
    payload_root = root / ".system" / "leaf" / "platforms" / EXPECTED_PLATFORM
    releases_root = root / ".system" / "leaf" / "releases"

    if release_root.is_dir():
        return [AuditRoot("release", root, release_root, root / "Apps")]

    if payload_root.is_dir():
        return [AuditRoot("payload", root, payload_root, root / "Apps")]

    if releases_root.is_dir():
        roots: list[AuditRoot] = []
        for child in sorted(releases_root.iterdir()):
            platform_dir = child / "platforms" / EXPECTED_PLATFORM
            if platform_dir.is_dir():
                roots.append(AuditRoot(child.name, child, platform_dir, child / "Apps"))
        return roots

    if root.name == EXPECTED_PLATFORM and (root / "launcher").is_dir():
        return [AuditRoot("platform", root, root, None)]

    return []


def manifest_path(audit_root: AuditRoot, spec: ManifestSpec) -> Path:
    platform_prefix = f"platforms/{EXPECTED_PLATFORM}/"
    if spec.relpath.startswith(platform_prefix):
        return audit_root.platform_dir / spec.relpath[len(platform_prefix) :]
    if spec.relpath.startswith("Apps/") and audit_root.apps_dir is not None:
        return audit_root.root / spec.relpath
    return audit_root.root / spec.relpath


def load_json(path: Path, findings: list[Finding], spec: ManifestSpec, strict: bool) -> dict[str, Any] | None:
    if not path.exists():
        if spec.required:
            add(findings, finding_level(strict), path, f"{spec.label} manifest is missing")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add(findings, "error", path, f"{spec.label} manifest is invalid JSON: {exc}")
        return None
    if not isinstance(data, dict):
        add(findings, "error", path, f"{spec.label} manifest root must be a JSON object")
        return None
    return data


def exception_text(data: dict[str, Any]) -> str:
    exceptions = data.get("exceptions")
    if not isinstance(exceptions, list):
        return ""
    parts = []
    for item in exceptions:
        if isinstance(item, dict):
            parts.append(" ".join(str(value) for value in item.values()))
        else:
            parts.append(str(item))
    return " ".join(parts)


def check_equal(
    findings: list[Finding],
    data: dict[str, Any],
    path: Path,
    field: str,
    expected: str,
    strict: bool,
) -> None:
    value = data.get(field)
    if value is None or value == "":
        add(findings, finding_level(strict), path, f"missing {field}={expected}")
        return
    if value != expected:
        add(findings, "error", path, f"{field} is {value!r}, expected {expected!r}")


def check_profile(findings: list[Finding], data: dict[str, Any], path: Path, strict: bool) -> None:
    profile = data.get("build_profile")
    if profile is None or profile == "":
        add(findings, finding_level(strict), path, "missing build_profile")
        return
    if profile not in KNOWN_PROFILES:
        add(findings, "warning", path, f"unknown build_profile {profile!r}")


def flag_text(data: dict[str, Any]) -> str:
    values = []
    for field in ("cflags", "cxxflags", "ldflags"):
        value = data.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values)


def check_flags(
    findings: list[Finding],
    data: dict[str, Any],
    path: Path,
    spec: ManifestSpec,
    strict: bool,
) -> None:
    flags = flag_text(data)
    if not flags:
        if not spec.allow_missing_flags and "prebuilt" not in exception_text(data).lower():
            add(findings, finding_level(strict), path, "missing cflags/cxxflags/ldflags metadata")
        return

    if EXPECTED_CPU_FLAG not in flags:
        add(findings, finding_level(strict), path, f"flags do not include {EXPECTED_CPU_FLAG}")
    if EXPECTED_TUNE_FLAG not in flags:
        add(findings, finding_level(strict), path, f"flags do not include {EXPECTED_TUNE_FLAG}")
    if "-O0" in flags and data.get("build_profile") != "debug":
        add(findings, "warning", path, "non-debug build metadata contains -O0")


def check_binary_manifest(
    findings: list[Finding],
    data: dict[str, Any],
    path: Path,
    spec: ManifestSpec,
    strict: bool,
) -> None:
    check_equal(findings, data, path, "platform", EXPECTED_PLATFORM, strict)
    check_equal(findings, data, path, "target_soc", EXPECTED_SOC, strict)
    check_equal(findings, data, path, "target_cpu", EXPECTED_CPU, strict)
    check_profile(findings, data, path, strict)
    check_flags(findings, data, path, spec, strict)


def check_core_report(findings: list[Finding], data: dict[str, Any], path: Path, spec: ManifestSpec, strict: bool) -> None:
    check_binary_manifest(findings, data, path, spec, strict)
    rows = data.get("cores")
    if not isinstance(rows, list):
        add(findings, finding_level(strict), path, "core report missing cores list")
        return

    generic = []
    upstream_a53 = []
    missing_tuning = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in {"built", "staged"}:
            continue
        tuning = row.get("tuning")
        core = str(row.get("core") or row.get("core_file") or "unknown")
        if tuning == "generic-aarch64":
            generic.append(core)
        elif tuning == "upstream-a53-platform":
            upstream_a53.append(core)
        elif tuning is None:
            missing_tuning.append(core)

    if generic:
        add(findings, "warning", path, "cores still reported as generic-aarch64: " + " ".join(generic[:12]))
    if upstream_a53:
        add(findings, "warning", path, "cores still reported as upstream-a53-platform: " + " ".join(upstream_a53[:12]))
    if missing_tuning:
        add(findings, finding_level(strict), path, "built cores missing tuning status: " + " ".join(missing_tuning[:12]))


def audit_one_root(audit_root: AuditRoot, strict: bool) -> list[Finding]:
    findings: list[Finding] = []
    if not audit_root.platform_dir.is_dir():
        add(findings, "error", audit_root.platform_dir, "missing MLP1 platform directory")
        return findings

    for spec in SPECS:
        path = manifest_path(audit_root, spec)
        data = load_json(path, findings, spec, strict)
        if data is None:
            continue
        if spec.kind == "metadata":
            continue
        if spec.kind == "cores":
            check_core_report(findings, data, path, spec, strict)
        else:
            check_binary_manifest(findings, data, path, spec, strict)

    return findings


def render_text(all_findings: dict[str, list[Finding]]) -> None:
    total_errors = sum(1 for findings in all_findings.values() for item in findings if item.level == "error")
    total_warnings = sum(1 for findings in all_findings.values() for item in findings if item.level == "warning")
    print(f"MLP1 tuning audit: {total_errors} error(s), {total_warnings} warning(s)")
    for label, findings in all_findings.items():
        print(f"[{label}]")
        if not findings:
            print("  ok")
            continue
        for item in findings:
            print(f"  {item.level}: {item.path}: {item.message}")


def render_json(all_findings: dict[str, list[Finding]]) -> None:
    payload = {
        "errors": sum(1 for findings in all_findings.values() for item in findings if item.level == "error"),
        "warnings": sum(1 for findings in all_findings.values() for item in findings if item.level == "warning"),
        "roots": {
            label: [item.__dict__ for item in findings]
            for label, findings in all_findings.items()
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Leaf release root, install stage, payload root, or platform root")
    parser.add_argument("--strict", action="store_true", help="treat missing migrated metadata as errors")
    parser.add_argument("--json", action="store_true", help="write machine-readable findings")
    args = parser.parse_args()

    roots = discover_audit_roots(args.root)
    if not roots:
        print(f"error: could not find an MLP1 Leaf release or payload under {args.root}", file=sys.stderr)
        return 2

    all_findings = {
        audit_root.label: audit_one_root(audit_root, args.strict)
        for audit_root in roots
    }

    if args.json:
        render_json(all_findings)
    else:
        render_text(all_findings)

    has_errors = any(item.level == "error" for findings in all_findings.values() for item in findings)
    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
