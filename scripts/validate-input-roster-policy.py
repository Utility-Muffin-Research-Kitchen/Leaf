#!/usr/bin/env python3
"""Reject MLP1 payloads that break the paired-controller input contract.

plans/paired-wireless-controllers-mlp1.md makes Jawaka the single authority on
which controllers an emulator may see: it freezes a roster for each launch,
publishes it in SDL_JOYSTICK_DEVICE in player order, and backs that with a
private /dev/input containing exactly those devices.

Four things quietly defeat that contract, and none of them fails loudly at
runtime -- the emulator simply plays with the wrong device, with none at all,
or hands a player slot to the uncalibrated physical pad:

  ROSTER001  a wrapper overwriting an inherited SDL_JOYSTICK_DEVICE
  ROSTER002  emulator code hardcoding a physical /dev/input/eventN path
  ROSTER003  a configuration enabling more player ports than a roster holds
  ROSTER004  a launch path resolving the Loong pads by display name alone

Each of these has already shipped at least once, which is why they are gated
here rather than left to review.

Point this at an assembled MLP1 payload or a built emulator package -- not at a
multi-platform source tree. ROSTER002 cannot tell which arm of an #if a literal
belongs to, so a shared backend carrying every handheld's event node reports one
violation per platform. A compiled MLP1 artifact only contains the branch that
survived the preprocessor, which is the thing actually shipping.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Shipped wrappers are shell; emulator payloads also carry binaries whose
# embedded strings are the only place a hardcoded device path shows up.
SHELL_SUFFIXES = {".sh", ".bash"}
CONFIG_SUFFIXES = {".ini", ".cfg", ".conf"}
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}

# event%d and event* are how code enumerates; a trailing digit is a decision
# about one specific node, which is exactly what the roster exists to make.
HARDCODED_EVENT_RE = re.compile(r"/dev/input/event\d+")

ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?SDL_JOYSTICK_DEVICE=")
# Preserving the inherited value looks like `[ -z "${SDL_JOYSTICK_DEVICE:-}" ]`.
GUARD_RE = re.compile(r"-z\s+\"?\$\{?SDL_JOYSTICK_DEVICE")
GUARD_WINDOW = 12

MAX_USERS_RE = re.compile(r"input_max_users\s*=\s*\"?(\d+)\"?")
JOYPAD_INDEX_RE = re.compile(r"input_player(\d+)_joypad_index\s*=\s*\"?(-?\d+)\"?")
MAPLE_PORT_RE = re.compile(r"maple_sdl_joystick_(\d+)\s*=\s*(-?\d+)")

LOONG_NAME = "Loong Gamepad"
DEVICE_LIST_PATH = "/proc/bus/input/devices"
# The only honest way to tell the two identically named pads apart in
# /proc/bus/input/devices is the uinput clone's virtual sysfs path.
VIRTUAL_SYSFS = "/devices/virtual/input"
DIRECT_FALLBACK_RE = re.compile(
    r"fall(?:ing|s|back)?[ -]?back to direct|direct SDL input", re.IGNORECASE
)

ROSTER_MAX_CONTROLLERS = 4


class Finding:
    def __init__(self, code: str, path: Path, line: int, message: str) -> None:
        self.code = code
        self.path = path
        self.line = line
        self.message = message

    def render(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        where = f"{shown}:{self.line}" if self.line else str(shown)
        return f"{self.code} {where}: {self.message}"


def read_file(path: Path) -> tuple[str, bool]:
    """Return (text, is_text). Binaries decode as latin-1 so embedded strings
    stay searchable without pulling in a strings(1) dependency."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8"), True
    except UnicodeDecodeError:
        return data.decode("latin-1"), False


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def check_roster_overwrite(path: Path, lines: list[str]) -> list[Finding]:
    """ROSTER001: a wrapper may seed SDL_JOYSTICK_DEVICE for direct invocation,
    but never replace a value Jawaka already set -- that discards every paired
    controller and leaves the built-in pad alone in the roster."""
    findings = []
    for number, line in enumerate(lines, start=1):
        if not ASSIGN_RE.match(line):
            continue
        # Reusing the variable on the right-hand side preserves it, e.g.
        # SDL_JOYSTICK_DEVICE="${SDL_JOYSTICK_DEVICE:-$fallback}".
        _, _, rhs = line.partition("=")
        if "SDL_JOYSTICK_DEVICE" in rhs:
            continue
        window = lines[max(0, number - 1 - GUARD_WINDOW):number - 1]
        if any(GUARD_RE.search(previous) for previous in window):
            continue
        findings.append(
            Finding(
                "ROSTER001",
                path,
                number,
                "assigns SDL_JOYSTICK_DEVICE without first checking it is unset; "
                "an inherited roster must win over any wrapper default",
            )
        )
    return findings


def check_hardcoded_event(path: Path, text: str, is_text: bool) -> list[Finding]:
    """ROSTER002: the physical and virtual Loong pads share a name and differ
    only by node, and their numbering is incidental kernel ordering. Any
    literal event node is a guess that the roster already answers."""
    findings = []
    if is_text:
        for number, line in enumerate(text.splitlines(), start=1):
            match = HARDCODED_EVENT_RE.search(line)
            if match:
                findings.append(
                    Finding(
                        "ROSTER002",
                        path,
                        number,
                        f"hardcodes {match.group(0)}; resolve the device from "
                        "SDL_JOYSTICK_DEVICE instead",
                    )
                )
        return findings

    seen = sorted(set(HARDCODED_EVENT_RE.findall(text)))
    if seen:
        findings.append(
            Finding(
                "ROSTER002",
                path,
                0,
                "embeds hardcoded input node(s) "
                + ", ".join(seen)
                + "; resolve the device from SDL_JOYSTICK_DEVICE instead",
            )
        )
    return findings


def check_player_ports(path: Path, lines: list[str]) -> list[Finding]:
    """ROSTER003: a roster holds at most four controllers, so a config must not
    open more ports than that -- and must never use -1 as an "unused player"
    marker, which RetroArch reads into an unsigned index and faults on."""
    findings = []
    for number, line in enumerate(lines, start=1):
        match = MAX_USERS_RE.search(line)
        if match and int(match.group(1)) > ROSTER_MAX_CONTROLLERS:
            findings.append(
                Finding(
                    "ROSTER003",
                    path,
                    number,
                    f"enables {match.group(1)} players; a launch roster holds at "
                    f"most {ROSTER_MAX_CONTROLLERS}",
                )
            )

        match = JOYPAD_INDEX_RE.search(line)
        if match and int(match.group(2)) < 0:
            findings.append(
                Finding(
                    "ROSTER003",
                    path,
                    number,
                    "uses a negative joypad index as an unused-player marker; "
                    "RetroArch reads it into an unsigned index and faults on the "
                    "first poll -- omit the key instead",
                )
            )

        match = MAPLE_PORT_RE.search(line)
        if match and int(match.group(2)) >= ROSTER_MAX_CONTROLLERS:
            findings.append(
                Finding(
                    "ROSTER003",
                    path,
                    number,
                    f"binds a controller to port {match.group(2)}; a launch "
                    f"roster holds at most {ROSTER_MAX_CONTROLLERS}",
                )
            )
    return findings


def check_direct_fallback(path: Path, text: str, lines: list[str]) -> list[Finding]:
    """ROSTER004: both Loong pads report the name "Loong Gamepad", so matching
    on the name alone can hand an emulator the grabbed, uncalibrated physical
    device. Pairing it with the uinput clone's virtual sysfs path is the
    accepted way to disambiguate."""
    findings = []
    # awk and sed programs escape the separators (\/devices\/virtual\/input\/),
    # so compare against a backslash-stripped copy or every correct wrapper
    # trips this rule.
    unescaped = text.replace("\\", "")
    scans_device_list = DEVICE_LIST_PATH in unescaped and LOONG_NAME in unescaped
    if scans_device_list and VIRTUAL_SYSFS not in unescaped:
        for number, line in enumerate(lines, start=1):
            if LOONG_NAME in line:
                findings.append(
                    Finding(
                        "ROSTER004",
                        path,
                        number,
                        "identifies a Loong pad by display name alone; the "
                        "physical and virtual devices share that name, so also "
                        f"require {VIRTUAL_SYSFS} or use the roster",
                    )
                )
                break

    for number, line in enumerate(lines, start=1):
        if DIRECT_FALLBACK_RE.search(line):
            findings.append(
                Finding(
                    "ROSTER004",
                    path,
                    number,
                    "describes a fallback to direct physical input; a roster or "
                    "namespace failure must block the launch instead",
                )
            )
    return findings


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        try:
            text, is_text = read_file(path)
        except OSError as exc:
            raise SystemExit(f"error: cannot read {path}: {exc}") from exc

        findings.extend(check_hardcoded_event(path, text, is_text))
        if not is_text:
            continue

        lines = text.splitlines()
        suffix = path.suffix.lower()
        shell_like = suffix in SHELL_SUFFIXES or (
            lines and lines[0].startswith("#!") and "sh" in lines[0]
        )
        if shell_like:
            findings.extend(check_roster_overwrite(path, lines))
            findings.extend(check_direct_fallback(path, text, lines))
        if shell_like or suffix in CONFIG_SUFFIXES:
            findings.extend(check_player_ports(path, lines))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="assembled platform payload(s) or source tree(s) to check",
    )
    args = parser.parse_args()

    findings: list[Finding] = []
    for target in args.paths:
        if not target.exists():
            raise SystemExit(f"error: no such path: {target}")
        findings.extend(scan(target))

    if findings:
        root = Path.cwd()
        for finding in findings:
            print(finding.render(root), file=sys.stderr)
        print(
            f"\n{len(findings)} input-roster policy violation(s); see "
            "plans/paired-wireless-controllers-mlp1.md",
            file=sys.stderr,
        )
        return 1

    print("input-roster policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
