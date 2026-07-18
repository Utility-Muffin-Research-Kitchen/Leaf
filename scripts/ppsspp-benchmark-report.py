#!/usr/bin/env python3
"""Validate and aggregate repeated PPSSPP benchmark summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any


class ReportError(RuntimeError):
    pass


CONTRACT_FIELDS = {
    "device_serial": ("device_serial",),
    "rom_path": ("rom_path",),
    "core": ("core",),
    "core_id": ("core_id",),
    "preset": ("preset",),
    "warmup_seconds": ("warmup_seconds",),
    "measurement_seconds": ("measurement_seconds",),
    "sample_interval_seconds": ("sample_interval_seconds",),
    "scene_sha256": ("scene_state", "sha256"),
    "scene_game_id": ("scene_state", "game_id"),
    "scene_game_version": ("scene_state", "game_version"),
    "input_trace_sha256": ("input_trace", "sha256"),
    "input_trace_game_id": ("input_trace", "game_id"),
}

METRICS = {
    "emulation_speed_median_percent": (
        "ppsspp",
        "emulation_speed_percent",
        "median",
    ),
    "emulation_speed_p05_percent": (
        "ppsspp",
        "emulation_speed_percent",
        "p05",
    ),
    "emulation_speed_min_percent": (
        "ppsspp",
        "emulation_speed_percent",
        "min",
    ),
    "vblank_median_per_second": (
        "ppsspp",
        "vblanks_per_second",
        "median",
    ),
    "vblank_p05_per_second": (
        "ppsspp",
        "vblanks_per_second",
        "p05",
    ),
    "rendered_fps_median": ("ppsspp", "rendered_fps", "median"),
    "process_cpu_median_percent": ("device", "process_cpu_percent", "median"),
    "gpu_load_median_percent": ("device", "gpu_load_percent", "median"),
    "soc_peak_c": ("device", "temperatures", "temp_soc_thermal", "max_c"),
    "gpu_peak_c": ("device", "temperatures", "temp_gpu_thermal", "max_c"),
}


def nested(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ReportError(f"Missing summary field: {'.'.join(path)}")
        value = value[key]
    return value


def finite_number(document: dict[str, Any], path: tuple[str, ...]) -> float:
    value = nested(document, path)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ReportError(
            f"Expected finite number at {'.'.join(path)}, observed {value!r}"
        )
    return float(value)


def rounded(value: float, places: int = 6) -> float:
    return round(value, places)


def distribution(values: list[float]) -> dict[str, float]:
    mean = statistics.mean(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "median": rounded(statistics.median(values)),
        "mean": rounded(mean),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
        "range": rounded(max(values) - min(values)),
        "sample_stddev": rounded(deviation),
        "coefficient_of_variation_percent": rounded(
            deviation / mean * 100.0 if mean else 0.0
        ),
    }


def validate_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw = path.read_bytes()
        summary = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"Could not read {path}: {error}") from error
    if not isinstance(summary, dict):
        raise ReportError(f"Summary must be a JSON object: {path}")
    if summary.get("schema_version") != 1:
        raise ReportError(f"Unsupported summary schema in {path}")
    if summary.get("status") != "completed" or summary.get("error") is not None:
        raise ReportError(f"Benchmark did not complete successfully: {path}")

    scene = summary.get("scene_state")
    if not isinstance(scene, dict) or scene.get("action") != "load":
        raise ReportError(f"Benchmark did not load a deterministic scene: {path}")
    if not scene.get("completed"):
        raise ReportError(f"Scene load did not complete: {path}")

    trace = summary.get("input_trace")
    if not isinstance(trace, dict):
        raise ReportError(f"Benchmark has no input trace: {path}")
    expanded = trace.get("expanded_event_count")
    dispatched = trace.get("dispatched_event_count")
    late = trace.get("skipped_late_event_count")
    if (
        not isinstance(expanded, int)
        or expanded <= 0
        or dispatched != expanded
        or late != 0
    ):
        raise ReportError(
            f"Incomplete input trace in {path}: "
            f"expanded={expanded} dispatched={dispatched} late={late}"
        )

    backend = summary.get("backend_evidence", {})
    for key in (
        "argument_observed",
        "backend_runtime_observed",
        "stats_backend_observed",
    ):
        if backend.get(key) is not True:
            raise ReportError(f"Backend evidence {key} did not pass: {path}")

    lifecycle = summary.get("lifecycle", {})
    for key in ("display_lifecycle_observed", "frontend_restored"):
        if lifecycle.get(key) is not True:
            raise ReportError(f"Lifecycle evidence {key} did not pass: {path}")

    sample_count = summary.get("sample_count")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise ReportError(f"Invalid sample count in {path}: {sample_count!r}")

    contract = {
        name: nested(summary, field_path)
        for name, field_path in CONTRACT_FIELDS.items()
    }
    metrics = {
        name: finite_number(summary, field_path)
        for name, field_path in METRICS.items()
    }
    transport = summary.get("transport_recovery", {})
    adb_recoveries = transport.get("adb_recoveries", [])
    debugger_reconnects = transport.get("debugger_reconnects", 0)
    if not isinstance(adb_recoveries, list) or not isinstance(
        debugger_reconnects, int
    ):
        raise ReportError(f"Invalid transport recovery evidence in {path}")

    run = {
        "name": path.parent.name,
        "summary_path": str(path.resolve()),
        "summary_sha256": hashlib.sha256(raw).hexdigest(),
        "started_unix": summary.get("started_unix"),
        "finished_unix": summary.get("finished_unix"),
        "sample_count": sample_count,
        "trace_events": {
            "expanded": expanded,
            "dispatched": dispatched,
            "late": late,
        },
        "transport_recovery": {
            "adb_recovery_count": len(adb_recoveries),
            "debugger_reconnects": debugger_reconnects,
        },
        "metrics": {
            name: rounded(value) for name, value in metrics.items()
        },
    }
    return contract, run


def markdown_report(report: dict[str, Any]) -> str:
    contract = report["contract"]
    lines = [
        "# PPSSPP benchmark repeat report",
        "",
        f"- Core/preset: `{contract['core']}` / `{contract['preset']}`",
        f"- Game: `{contract['scene_game_id']}` version "
        f"`{contract['scene_game_version']}`",
        f"- Scene SHA-256: `{contract['scene_sha256']}`",
        f"- Trace SHA-256: `{contract['input_trace_sha256']}`",
        f"- Warm-up/measurement: {contract['warmup_seconds']:.0f}s / "
        f"{contract['measurement_seconds']:.0f}s",
        f"- Runs/samples: {report['run_count']} / {report['total_sample_count']}",
        "",
        "| Run | Median speed | p05 speed | Median vblank/s | Median FPS | "
        "Median CPU | Median GPU | Peak SoC |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in report["runs"]:
        metric = run["metrics"]
        lines.append(
            f"| {run['name']} "
            f"| {metric['emulation_speed_median_percent']:.3f}% "
            f"| {metric['emulation_speed_p05_percent']:.3f}% "
            f"| {metric['vblank_median_per_second']:.3f} "
            f"| {metric['rendered_fps_median']:.3f} "
            f"| {metric['process_cpu_median_percent']:.3f}% "
            f"| {metric['gpu_load_median_percent']:.3f}% "
            f"| {metric['soc_peak_c']:.3f} °C |"
        )

    lines.extend(
        [
            "",
            "## Run-level aggregate",
            "",
            "| Run-median metric | Median | Mean | Min | Max | Range | "
            "Sample stddev | CV |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name in (
        "emulation_speed_median_percent",
        "vblank_median_per_second",
        "rendered_fps_median",
        "process_cpu_median_percent",
        "gpu_load_median_percent",
    ):
        item = report["aggregate"][name]
        lines.append(
            f"| `{name}` "
            f"| {item['median']:.3f} "
            f"| {item['mean']:.3f} "
            f"| {item['min']:.3f} "
            f"| {item['max']:.3f} "
            f"| {item['range']:.3f} "
            f"| {item['sample_stddev']:.3f} "
            f"| {item['coefficient_of_variation_percent']:.3f}% |"
        )
    lines.extend(
        [
            "",
            f"Transport recovery: {report['transport_recovery']['adb_recovery_count']} "
            "ADB recoveries, "
            f"{report['transport_recovery']['debugger_reconnects']} debugger "
            "reconnects.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate repeated PPSSPP benchmark summaries and report run-level "
            "variance."
        )
    )
    parser.add_argument("summaries", nargs="+", help="Benchmark summary.json files")
    parser.add_argument(
        "--output",
        required=True,
        help="New aggregate JSON path; a Markdown report is written beside it",
    )
    parser.add_argument(
        "--minimum-runs",
        type=int,
        default=3,
        help="Minimum compatible completed runs required (default: 3)",
    )
    args = parser.parse_args()
    if args.minimum_runs < 1:
        parser.error("minimum runs must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    output = Path(args.output).resolve()
    markdown = output.with_suffix(".md")
    if output.suffix.lower() != ".json":
        print("ppsspp-benchmark-report: output must end in .json", file=sys.stderr)
        return 1
    if output.exists() or markdown.exists():
        print(
            f"ppsspp-benchmark-report: output already exists: {output} or {markdown}",
            file=sys.stderr,
        )
        return 1
    if len(args.summaries) < args.minimum_runs:
        print(
            "ppsspp-benchmark-report: "
            f"need at least {args.minimum_runs} summaries",
            file=sys.stderr,
        )
        return 1

    try:
        loaded = [
            validate_summary(Path(summary).resolve())
            for summary in args.summaries
        ]
        contract = loaded[0][0]
        for index, (candidate, _) in enumerate(loaded[1:], start=2):
            if candidate != contract:
                raise ReportError(
                    f"Summary {index} benchmark contract does not match run 1"
                )
        runs = [run for _, run in loaded]
        summary_hashes = [run["summary_sha256"] for run in runs]
        if len(set(summary_hashes)) != len(summary_hashes):
            raise ReportError("Duplicate benchmark summaries are not repeats")
        aggregate = {
            name: distribution(
                [float(run["metrics"][name]) for run in runs]
            )
            for name in METRICS
        }
        canonical_contract = json.dumps(
            contract, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        report = {
            "schema_version": 1,
            "generated_unix": time.time(),
            "contract": contract,
            "contract_sha256": hashlib.sha256(canonical_contract).hexdigest(),
            "run_count": len(runs),
            "total_sample_count": sum(run["sample_count"] for run in runs),
            "trace_events": {
                "expanded": sum(
                    run["trace_events"]["expanded"] for run in runs
                ),
                "dispatched": sum(
                    run["trace_events"]["dispatched"] for run in runs
                ),
                "late": sum(run["trace_events"]["late"] for run in runs),
            },
            "transport_recovery": {
                "adb_recovery_count": sum(
                    run["transport_recovery"]["adb_recovery_count"]
                    for run in runs
                ),
                "debugger_reconnects": sum(
                    run["transport_recovery"]["debugger_reconnects"]
                    for run in runs
                ),
            },
            "runs": runs,
            "aggregate": aggregate,
        }
    except ReportError as error:
        print(f"ppsspp-benchmark-report: {error}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown.write_text(markdown_report(report), encoding="utf-8")
    print(f"JSON report: {output}")
    print(f"Markdown report: {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
