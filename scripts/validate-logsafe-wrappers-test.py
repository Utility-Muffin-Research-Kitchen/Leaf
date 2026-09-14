#!/usr/bin/env python3
"""Smoke-test Leaf's log-safety gate for emulator wrappers.

The accept cases are the shapes that actually ship in the seven wrappers; a
gate that fails the current payload is worse than no gate, because the next
person turns it off. The reject cases are the Leaf 0.11 failure shape and the
drift that would quietly reintroduce it.
"""

from __future__ import annotations

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

expect_accept("stderr redirect to a file is not an inherited write", {
    "emulators/ports/launch.sh": wrapper(
        "printf 'x' >>\"$RUN_LOG\" 2>&1\n"
    ),
})

if FAILURES:
    for failure in FAILURES:
        print(failure, flush=True)
    raise SystemExit(f"{len(FAILURES)} test(s) failed")
print("log-safety gate smoke test: ok")
