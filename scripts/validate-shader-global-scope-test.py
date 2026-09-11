#!/usr/bin/env python3
"""Mutation fixtures for the assembled global shader scope gate."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parents[1]
TOOL = Path(
    os.environ.get(
        "SHADER_GLOBAL_SCOPE_TOOL",
        LEAF_ROOT / "scripts" / "validate-shader-global-scope.py",
    )
)

DISABLED_MARKER = b"Requires Fugazi resolver"


def make_fixture(root: Path) -> tuple[Path, Path, Path]:
    """An assembly with the scope enabled and a resolver-carrying Fugazi."""
    menu = root / "platforms" / "mlp1" / "launcher" / "bin" / "jawaka-menu"
    menu.parent.mkdir(parents=True, exist_ok=True)
    # Real menu binaries keep the runtime guard message whether or not the
    # scope is gated; only the row hint tracks the constant.
    menu.write_bytes(
        b"\x7fELF fixture\x00"
        b"All RetroArch requires a Leaf build with Fugazi's conflict resolver.\x00"
    )

    pak = root / "Apps" / "mlp1" / "Fugazi.pak"
    pak.mkdir(parents=True, exist_ok=True)
    (pak / "pak.json").write_text(
        json.dumps({"name": "Fugazi", "platform": "mlp1", "pak_version": "0.2.0"}),
        encoding="utf-8",
    )

    source = root / "jawaka" / "cmd" / "jawaka-menu" / "main.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "/* comment */\n#define JW_FUGAZI_RESOLVER_ASSEMBLED true\n",
        encoding="utf-8",
    )
    return menu, pak, source


def run(menu: Path, pak: Path, source: Path | None) -> subprocess.CompletedProcess:
    command = [
        "python3",
        str(TOOL),
        "--menu-binary",
        str(menu),
        "--fugazi-pak",
        str(pak),
    ]
    if source is not None:
        command += ["--jawaka-source", str(source)]
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def expect(name: str, mutate, success: bool, message: str = "", pass_source=True) -> None:
    with tempfile.TemporaryDirectory(prefix="leaf-shader-global-scope-") as temporary:
        menu, pak, source = make_fixture(Path(temporary))
        mutate(menu, pak, source)
        result = run(menu, pak, source if pass_source else None)
        if (result.returncode == 0) != success or message not in (
            result.stdout + result.stderr
        ):
            wanted = "success" if success else "failure"
            raise SystemExit(
                f"{name}: expected {wanted} containing {message!r}\n"
                f"stdout:\n{result.stdout}stderr:\n{result.stderr}"
            )


def set_version(pak: Path, value: object) -> None:
    path = pak / "pak.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["pak_version"] = value
    path.write_text(json.dumps(document), encoding="utf-8")


def gate_off(menu: Path, source: Path) -> None:
    menu.write_bytes(menu.read_bytes() + DISABLED_MARKER + b"\x00")
    source.write_text(
        "#define JW_FUGAZI_RESOLVER_ASSEMBLED false\n", encoding="utf-8"
    )


def no_change(*_args) -> None:
    pass


def older_fugazi(_menu: Path, pak: Path, _source: Path) -> None:
    set_version(pak, "0.1.0")


def newer_fugazi(_menu: Path, pak: Path, _source: Path) -> None:
    set_version(pak, "0.3.1")


def gated_off_with_older_fugazi(menu: Path, pak: Path, source: Path) -> None:
    gate_off(menu, source)
    set_version(pak, "0.1.0")


def stale_binary(menu: Path, _pak: Path, _source: Path) -> None:
    # Source enables the scope but the payload still holds a gated-off build.
    menu.write_bytes(menu.read_bytes() + DISABLED_MARKER + b"\x00")


def missing_pak(_menu: Path, pak: Path, _source: Path) -> None:
    (pak / "pak.json").unlink()


def unparsable_version(_menu: Path, pak: Path, _source: Path) -> None:
    set_version(pak, "0.2")


def missing_gate_define(_menu: Path, _pak: Path, source: Path) -> None:
    source.write_text("/* the constant was renamed */\n", encoding="utf-8")


def empty_binary(menu: Path, _pak: Path, _source: Path) -> None:
    menu.write_bytes(b"")


expect("resolver-carrying assembly", no_change, True, "meets the 0.2.0 resolver floor")
expect("older Fugazi beside enabled scope", older_fugazi, False, "below the 0.2.0 floor")
expect("newer Fugazi", newer_fugazi, True, "meets the 0.2.0 resolver floor")
expect("scope gated off", gated_off_with_older_fugazi, True, "disabled in this build")
expect("stale menu payload", stale_binary, False, "does not match the Jawaka source gate")
expect("missing pak manifest", missing_pak, False, "missing assembled Fugazi pak manifest")
expect("unparsable version", unparsable_version, False, "not a three-part numeric version")
expect("renamed gate constant", missing_gate_define, False, "no JW_FUGAZI_RESOLVER_ASSEMBLED")
expect("empty menu binary", empty_binary, False, "assembled menu binary is empty")

# Without the source on hand the binary alone decides, and an assembled menu
# that dropped the gated-off hint must still enforce the floor.
expect(
    "binary-only enabled scope",
    older_fugazi,
    False,
    "below the 0.2.0 floor",
    pass_source=False,
)
expect(
    "binary-only gated off",
    gated_off_with_older_fugazi,
    True,
    "disabled in this build",
    pass_source=False,
)

print("validate-shader-global-scope-test: ok")
