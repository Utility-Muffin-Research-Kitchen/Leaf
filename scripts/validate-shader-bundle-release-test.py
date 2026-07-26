#!/usr/bin/env python3
"""Smoke-test Leaf's MLP1 shader bundle release gate."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = LEAF_ROOT.parent
RETROARCH_BUILDS = WORKSPACE_ROOT / "retroarch-builds"
TOOL = RETROARCH_BUILDS / "scripts" / "mlp1_shader_bundle.py"
BUNDLE = RETROARCH_BUILDS / "output" / "mlp1" / "shaders"


def run(*args: str, expect_success: bool) -> None:
    result = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if (result.returncode == 0) != expect_success:
        detail = result.stderr.strip() or result.stdout.strip()
        expectation = "succeed" if expect_success else "fail"
        raise SystemExit(f"expected {' '.join(args)} to {expectation}: {detail}")


def validate(path: Path, expect_success: bool) -> None:
    run(
        "python3",
        str(TOOL),
        "validate",
        "--output",
        str(path),
        expect_success=expect_success,
    )


def fixture_copy(root: Path, name: str) -> Path:
    destination = root / name
    shutil.copytree(BUNDLE, destination)
    return destination


def main() -> int:
    run(
        "make",
        "-C",
        str(RETROARCH_BUILDS),
        "shaders-mlp1",
        expect_success=True,
    )
    if not (LEAF_ROOT / "stage" / "licenses" / "SHADERS.md").is_file():
        raise SystemExit("missing Leaf shader notice")

    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    shader_path = next(
        row["path"]
        for row in manifest["files"]
        if row["path"].endswith((".glsl", ".glslp"))
    )

    with tempfile.TemporaryDirectory(prefix="leaf-shader-release-") as temporary:
        root = Path(temporary)
        valid = fixture_copy(root, "valid")
        validate(valid, expect_success=True)

        partial = fixture_copy(root, "partial")
        (partial / shader_path).unlink()
        validate(partial, expect_success=False)

        modified = fixture_copy(root, "modified")
        with (modified / shader_path).open("a", encoding="utf-8") as handle:
            handle.write("\n// release-gate tamper fixture\n")
        validate(modified, expect_success=False)

        contaminated = fixture_copy(root, "contaminated")
        state = contaminated / ".umrk" / "should-not-ship.txt"
        state.parent.mkdir()
        state.write_text("mutable state\n", encoding="utf-8")
        validate(contaminated, expect_success=False)

    print("shader-bundle-release-policy-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
