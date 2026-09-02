#!/usr/bin/env python3
"""Smoke-test Leaf's MLP1 input-roster policy gate.

Each rejection case is a shape that actually shipped at some point, so the
accept cases matter just as much: a gate that fails the current wrappers is
worse than no gate, because the next person turns it off.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


LEAF_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = LEAF_ROOT.parent
TOOL = LEAF_ROOT / "scripts" / "validate-input-roster-policy.py"

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


# ROSTER001 -- the PPSSPP wrapper shipped exactly this, which discarded every
# paired controller and left only the built-in pad.
expect_reject(
    "unguarded SDL_JOYSTICK_DEVICE overwrite",
    "ROSTER001",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            'if [ -n "${JAWAKA_INPUT_VIRTUAL_EVENT:-}" ]; then\n'
            '    export SDL_JOYSTICK_DEVICE="$JAWAKA_INPUT_VIRTUAL_EVENT"\n'
            "fi\n"
        )
    },
)

expect_accept(
    "guarded fallback preserves an inherited roster",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            'if [ -z "${SDL_JOYSTICK_DEVICE:-}" ] && '
            '[ -n "${JAWAKA_INPUT_VIRTUAL_EVENT:-}" ]; then\n'
            '    export SDL_JOYSTICK_DEVICE="$JAWAKA_INPUT_VIRTUAL_EVENT"\n'
            "fi\n"
        )
    },
)

expect_accept(
    "self-referencing default preserves an inherited roster",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            'export SDL_JOYSTICK_DEVICE="${SDL_JOYSTICK_DEVICE:-$fallback}"\n'
        )
    },
)

# ROSTER002 -- DraStic's MLP1 backend opened this node directly.
expect_reject(
    "hardcoded physical event node in a wrapper",
    "ROSTER002",
    {"launch.sh": "#!/bin/sh\nINPUT_DEV=/dev/input/event4\n"},
)

expect_accept(
    "enumerating event nodes with a format string",
    {"launch.sh": '#!/bin/sh\nprintf "/dev/input/event%d\\n" "$i"\n'},
)

# ROSTER003 -- "-1 for unused players" was in the plan until RetroArch was
# observed faulting on it two seconds into every launch.
expect_reject(
    "negative joypad index as an unused-player marker",
    "ROSTER003",
    {"retroarch.cfg": 'input_max_users = "4"\ninput_player4_joypad_index = "-1"\n'},
)

expect_reject(
    "more players enabled than a roster can hold",
    "ROSTER003",
    {"retroarch.cfg": 'input_max_users = "8"\n'},
)

expect_reject(
    "controller bound past the last roster slot",
    "ROSTER003",
    {"emu.cfg": "maple_sdl_joystick_0=5\n"},
)

expect_accept(
    "a four-player roster config",
    {
        "retroarch.cfg": (
            'input_max_users = "4"\n'
            'input_player1_joypad_index = "0"\n'
            'input_player4_joypad_index = "3"\n'
            # Players beyond the roster keep RetroArch's stock identity indices;
            # they are not enabled ports and must not trip the gate.
            'input_player5_joypad_index = "4"\n'
            'input_player16_joypad_index = "15"\n'
        ),
        "emu.cfg": "maple_sdl_joystick_0=0\nmaple_sdl_joystick_3=3\n",
    },
)

# ROSTER004 -- both Loong pads report the same name.
expect_reject(
    "resolving a Loong pad by display name alone",
    "ROSTER004",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            "awk '/^N: Name=\"Loong Gamepad\"/ { found = 1 }' "
            "/proc/bus/input/devices\n"
        )
    },
)

expect_accept(
    "name plus virtual sysfs path disambiguates the uinput clone",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            "awk '\n"
            '/^N: Name="Loong Gamepad"/ { name = 1 }\n'
            "/^S: Sysfs=\\/devices\\/virtual\\/input\\// { virtual = 1 }\n"
            "' /proc/bus/input/devices\n"
        )
    },
)

expect_reject(
    "documented fallback to direct physical input",
    "ROSTER004",
    {
        "launch.sh": (
            "#!/bin/sh\n"
            'echo "virtual unavailable; falling back to direct SDL input"\n'
        )
    },
)


def check_binary_case() -> None:
    """A hardcoded node hides in an emulator's shipped library, not just its
    wrapper, so the scan has to reach into non-UTF-8 files too."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        blob = root / "lib" / "libexample.so"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"/dev/input/event4\x00\xff\xfe")
        result = run(root)
        if result.returncode == 0:
            FAILURES.append("binary scan: expected rejection, got success")
        elif "ROSTER002" not in result.stderr:
            FAILURES.append(
                f"binary scan: expected ROSTER002, got:\n{result.stderr.strip()}"
            )


def check_device_list_parser() -> None:
    """ROSTER005. Both shapes shipped: the Handlers= miss was in all four
    copies of this resolver, and the missing record reset was in two of them.
    The second is the nastier one -- it returns a real event node belonging to
    the previous device, so the caller's own [ -e ] guard passes."""
    header = "#!/bin/sh\nresolve() {\n    awk '\n"
    footer = "    ' /proc/bus/input/devices\n}\n"
    name_and_sysfs = (
        '        /^N: Name="Loong Gamepad"/ { name = 1 }\n'
        "        /^S: Sysfs=\\/devices\\/virtual\\/input\\// { virtual = 1 }\n"
    )
    bare_match = (
        "        /^H: Handlers=/ {\n"
        "            for (i = 1; i <= NF; i++) {\n"
        "                if ($i ~ /^event[0-9]+$/) { event = $i }\n"
        "            }\n"
        "        }\n"
    )
    stripped_match = (
        "        /^H: Handlers=/ {\n"
        "            for (i = 1; i <= NF; i++) {\n"
        "                h = $i\n"
        "                sub(/^Handlers=/, \"\", h)\n"
        "                if (h ~ /^event[0-9]+$/) { event = h }\n"
        "            }\n"
        "        }\n"
    )
    blank_reset = '        /^$/ { name = 0; virtual = 0; event = "" }\n'
    record_reset = '        /^I:/ { name = 0; virtual = 0; event = "" }\n'
    tail = '        name && virtual && event != "" { print event; exit }\n'

    cases = [
        ("both defects", blank_reset + name_and_sysfs + bare_match + tail, 2),
        ("handlers only", record_reset + name_and_sysfs + bare_match + tail, 1),
        ("reset only", blank_reset + name_and_sysfs + stripped_match + tail, 1),
        ("clean", record_reset + name_and_sysfs + stripped_match + tail, 0),
    ]
    for label, body, expected in cases:
        with tempfile.TemporaryDirectory(prefix="leaf-roster005-") as temp:
            wrapper = Path(temp) / "launch.sh"
            wrapper.write_text(header + body + footer, encoding="utf-8")
            result = run(wrapper)
            found = result.stderr.count("ROSTER005")
            if found != expected:
                FAILURES.append(
                    f"ROSTER005 {label}: expected {expected} finding(s), got "
                    f"{found}\n{result.stderr.strip()}"
                )

    # A file that only mentions the path must not be flagged.
    with tempfile.TemporaryDirectory(prefix="leaf-roster005-ok-") as temp:
        wrapper = Path(temp) / "notes.sh"
        wrapper.write_text(
            "#!/bin/sh\n# see /proc/bus/input/devices\necho hi\n", encoding="utf-8"
        )
        if run(wrapper).returncode != 0:
            FAILURES.append("ROSTER005 flagged a file that only mentions the path")


def check_shipped_wrappers() -> None:
    """The gate must pass the wrappers currently shipped for MLP1. If this
    fails, the gate is wrong -- not the wrappers."""
    wrappers = [
        WORKSPACE_ROOT / "PPSSPP-spruce" / "package-mlp1.sh",
        WORKSPACE_ROOT / "Flycast-standalone" / "config" / "mlp1" / "launch.sh",
        WORKSPACE_ROOT / "N64-standalone" / "config" / "mlp1" / "launch.sh",
        WORKSPACE_ROOT / "Fun-Drastic-standalone" / "config" / "mlp1" / "launch.sh",
    ]
    for wrapper in wrappers:
        if not wrapper.exists():
            print(f"skip (not checked out): {wrapper}")
            continue
        result = run(wrapper)
        if result.returncode != 0:
            FAILURES.append(
                f"shipped wrapper rejected: {wrapper}\n{result.stderr.strip()}"
            )


check_binary_case()
check_device_list_parser()
check_shipped_wrappers()

if FAILURES:
    for failure in FAILURES:
        print(f"FAIL {failure}")
    raise SystemExit(1)

print("validate-input-roster-policy-test: ok")
