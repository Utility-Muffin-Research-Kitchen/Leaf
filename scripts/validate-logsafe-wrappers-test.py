#!/usr/bin/env python3
"""Smoke-test Leaf's log-safety gate for emulator wrappers.

The accept cases are the shapes that actually ship in the seven wrappers; a
gate that fails the current payload is worse than no gate, because the next
person turns it off. The reject cases are the Leaf 0.11 failure shape and the
drift that would quietly reintroduce it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parents[1]
TOOL = LEAF_ROOT / "scripts" / "validate-logsafe-wrappers.py"

FAILURES: list[str] = []


def run(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(TOOL), str(target)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def expect_reject(name: str, code: str, files: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative, body in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        result = run(root)
        if result.returncode == 0:
            FAILURES.append(f"{name}: expected rejection, got success")
        elif code not in result.stderr:
            FAILURES.append(
                f"{name}: expected {code}, got:\n{result.stderr.strip()}"
            )


def expect_accept(name: str, files: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative, body in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        result = run(root)
        if result.returncode != 0:
            FAILURES.append(f"{name}: expected success, got:\n{result.stderr.strip()}")


# The canonical preamble, read from the validator itself so the two can never
# drift apart silently.
sys_preamble = ""
in_preamble = False
for line in (LEAF_ROOT / "scripts" / "validate-logsafe-wrappers.py").read_text().splitlines(keepends=True):
    if in_preamble:
        if line.strip() == "'''":
            break
        sys_preamble += line
    elif line.startswith("LOGSAFE1_PREAMBLE = r'''"):
        in_preamble = True
        sys_preamble += line.split("r'''", 1)[1]

PREAMBLE = sys_preamble
assert "leaf_log_probe" in PREAMBLE, "could not extract the canonical preamble"


def wrapper(body: str, preamble: str = PREAMBLE) -> str:
    return "#!/bin/sh\nset -eu\n" + preamble + "\n" + body


expect_accept("the real ports wrapper shape", {
    "emulators/ports/launch.sh": wrapper(
        'log "[ports] preparing optional PortMaster runtime"\n'
        '"$prepare_script" || log "[ports] prep failed"\n'
        'port_log="${LOGS_PATH:-/tmp}/ports/test.log"\n'
        'if mkdir -p "${port_log%/*}" 2>/dev/null &&\n'
        '   : >"$port_log" 2>/dev/null &&\n'
        '   leaf_log_probe >>"$port_log"; then\n'
        '    log "[ports] port output: $port_log"\n'
        'else\n'
        '    port_log=/dev/null\n'
        'fi\n'
        'setsid "$port_shell" "$port_script" >>"$port_log" 2>&1 &\n'
    ),
})

expect_reject("bare echo under errexit", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'echo "[ports] preparing optional PortMaster runtime"\n'
    ),
})

expect_reject("bare echo to stderr under errexit", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'echo "ports launcher: missing port script path" >&2\n'
    ),
})

expect_reject("bare printf under errexit", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        "printf 'probe=sr0\\n'\n"
    ),
})

expect_reject("unguarded printf in the preamble region only", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'log "fine"\n'
        'echo "not fine"\n'
    ),
})

expect_accept("echo suffixed with || true", {
    "emulators/ports/launch.sh": wrapper(
        'echo "prep failed" >&2 || true\n'
    ),
})

expect_accept("printf targeting a file", {
    "emulators/ports/launch.sh": wrapper(
        '{\n'
        '    printf \'%s\\n\' \'config_save_on_exit = "false"\'\n'
        '    printf \'%s\\n\' \'video_driver = "gl"\'\n'
        '} >"$tmp_config"\n'
        '{\n'
        '    printf \'system_directory = "%s/BIOS"\\n\' "$pm_data"\n'
        '} >>"$tmp_config"\n'
    ),
})

expect_accept("brace group closed by || true", {
    "emulators/ppsspp/launch.sh": wrapper(
        'if leaf_log_probe >>"$LOG_ROOT/ppsspp.log"; then\n'
        '    exec >>"$LOG_ROOT/ppsspp.log" 2>&1\n'
        'else\n'
        '    exec >/dev/null 2>&1\n'
        'fi\n'
        '{\n'
        '    printf \'%s\\n\' "=== UMRK PPSSPP launch ==="\n'
        '    printf \'state=%s\\n\' "$STATE_ROOT"\n'
        '} || true\n'
    ),
})

expect_accept("printf inside a command substitution", {
    "emulators/ports/launch.sh": wrapper(
        'prepare_script="$(find_optional_portmaster_runtime_prepare | head -n 1)"\n'
        'MLP1_VIRTUAL_GAMEPAD="$(resolve_mlp1_virtual_gamepad || true)"\n'
    ),
})

expect_accept("multi-line command substitution", {
    "emulators/ports/launch.sh": wrapper(
        'value="$(\n'
        '    printf \'%s\\n\' candidate\n'
        ')"\n'
    ),
})

expect_reject("errexit without the preamble", "LOGSAFE002", {
    "emulators/ports/launch.sh": "#!/bin/sh\nset -eu\n\necho hi\n",
})

expect_accept("preamble present byte-for-byte", {
    "emulators/ports/launch.sh": wrapper("log ok\n"),
})

expect_reject("preamble drifted by one character", "LOGSAFE002", {
    "emulators/ports/launch.sh":
        "#!/bin/sh\nset -eu\n" + PREAMBLE.replace("XFSZ", "XFSY") + "\nlog ok\n",
})

expect_accept("xtrace-only wrapper is not gated", {
    "emulators/shared/launch.sh":
        "#!/bin/sh\nset -x\n\nrm -f \"$LOGS_PATH/$EMU_TAG.txt\"\n",
})

expect_accept("set -eu inside an embedded heredoc does not require a preamble", {
    "emulators/ports/launch.sh": wrapper(
        'write_wrapper() {\n'
        '    cat >"$path" <<\'SH\'\n'
        '#!/bin/sh\n'
        'set -eu\n'
        'exec "$real_ra" --config "$config" "$@"\n'
        'SH\n'
        '}\n'
    ),
})

expect_accept("non-emulator shell scripts are out of scope", {
    "launcher/env.sh": "#!/bin/sh\nset -eu\necho seeding\n",
    "scripts/somewhere/launch.sh": "#!/bin/sh\nset -eu\necho not an emulator wrapper\n",
})

expect_reject("package root without an emulators path component", "LOGSAFE002", {
    "launch.sh": "#!/bin/sh\nset -eu\necho unsafe\n",
})

expect_reject("alternate launcher at a package root", "LOGSAFE001", {
    "launch.sh": wrapper("log ok\n"),
    "launch-gles.sh": wrapper("echo unsafe\n"),
})

expect_accept("safe launchers at a package root", {
    "launch.sh": wrapper("log ok\n"),
    "launch-gles.sh": wrapper("log ok\n"),
})

expect_accept("stderr redirect to a file is not an inherited write", {
    "emulators/ports/launch.sh": wrapper(
        "printf 'x' >>\"$RUN_LOG\" 2>&1\n"
    ),
})

# Shapes the first gate missed: a write anywhere but the start of a line, and
# a write whose arguments merely contain a command substitution.
expect_reject("printf as the last command of an && list", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        '[ -x "$prepare" ] && printf \'%s\\n\' "$prepare"\n'
    ),
})

expect_reject("echo inside a one-line then branch", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'if [ -n "$x" ]; then echo "x is set"; fi\n'
    ),
})

expect_reject("echo whose argument holds a command substitution", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'echo "found $(basename "$port_script")"\n'
    ),
})

expect_reject("echo after a case pattern", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'case "$x" in\n'
        '    *) echo "unsupported: $x" ;;\n'
        'esac\n'
    ),
})

expect_reject("stderr-only redirect still writes the inherited stdout", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        "printf 'x\\n' 2>/dev/null\n"
    ),
})

expect_reject("unguarded subshell group", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        '( echo "in a subshell" )\n'
    ),
})

expect_reject("echo after a multi-line command substitution closes", "LOGSAFE001", {
    "emulators/ports/launch.sh": wrapper(
        'value="$(\n'
        '    printf \'%s\\n\' candidate\n'
        ')"\n'
        'echo "value=$value"\n'
    ),
})

expect_accept("printf into a pipeline", {
    "emulators/ports/launch.sh": wrapper(
        'printf \'%s\\n\' "$x" | grep -q y\n'
    ),
})

expect_accept("echo in an if condition", {
    "emulators/ports/launch.sh": wrapper(
        'if ! echo probe; then log "no stdout"; fi\n'
    ),
})

expect_accept("subshell group redirected to a file", {
    "emulators/ports/launch.sh": wrapper(
        '( printf a; printf b ) >"$f"\n'
    ),
})

expect_accept("one-line brace group redirected to a file", {
    "emulators/ports/launch.sh": wrapper(
        '{ echo a; echo b; } >>"$f"\n'
    ),
})

expect_accept("both streams redirected with &>", {
    "emulators/ports/launch.sh": wrapper(
        'echo x &>"$f"\n'
    ),
})

expect_accept("printf inside a one-line command substitution guarded with ||", {
    "emulators/ports/launch.sh": wrapper(
        '[ -f "$font" ] && FONT="$(printf \'%s\' "$font")" || true\n'
    ),
})

expect_reject("quotes nested in a parameter expansion do not hide later writes", "LOGSAFE001", {
    "emulators/fun-drastic/launch.sh": wrapper(
        'save_name() {\n'
        '    case "$1" in\n'
        '        *") ("*) printf \'%s\' "${1%%") ("*}" 2>/dev/null || true ;;\n'
        '        *) printf \'%s\' "$1" 2>/dev/null || true ;;\n'
        '    esac\n'
        '}\n'
        'echo "after the case"\n'
    ),
})

# Execute the release's final platform-validation block against a completed
# fixture. This catches a missing gate after the emulator/app packaging steps,
# even when the earlier launcher-only assembly gate passes.
release_script = (LEAF_ROOT / "scripts/make-sd-release-zip.sh").read_text()
final_checks = release_script.split('    validate_portmaster_integration "$RELEASE_ROOT"\n', 1)[1]
final_checks = final_checks.split('    audit_mlp1_build_tuning "$RELEASE_ROOT"', 1)[0]
for name, body, expected in (
    ("safe", wrapper("log ok\n"), None),
    ("missing preamble", "#!/bin/sh\nset -eu\n", "LOGSAFE002"),
    ("unsafe write", wrapper("echo unsafe\n"), "LOGSAFE001"),
):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "platforms/mlp1/emulators/ppsspp"
        package.mkdir(parents=True)
        (package / "launch.sh").write_text(body)
        result = subprocess.run(
            ["bash", "-eu", "-c", final_checks], capture_output=True, text=True,
            env=dict(os.environ, LEAF_ROOT=str(LEAF_ROOT), RELEASE_ROOT=str(root)))
        if expected is None and result.returncode != 0:
            FAILURES.append(f"final release gate ({name}): {result.stderr}")
        elif expected and (result.returncode == 0 or expected not in result.stderr):
            FAILURES.append(f"final release gate ({name}): expected {expected} rejection")

if FAILURES:
    for failure in FAILURES:
        print(failure, flush=True)
    raise SystemExit(f"{len(FAILURES)} test(s) failed")
print("log-safety gate smoke test: ok")
