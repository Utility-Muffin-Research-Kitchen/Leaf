#!/usr/bin/env python3
"""Reject MLP1 payloads whose emulator wrappers can be killed by their own log.

plans/bugfixes/standalone-launch-dies-on-unwritable-session-log.md: every child
of the launcher writes to the session log on the FAT card, and a log that has
gone unwritable (bad cluster chain, full card, the FAT32 4 GiB per-file
ceiling) turns every unguarded `echo` under `set -e` into a dead launch -- the
Leaf 0.11 ports failure that two users hit and that no UMRK device could
reproduce. Seven wrappers across six repos ship the same shape, which is
exactly how the ROSTER005 awk bug survived, so the pattern is gated here
rather than left to review.

  LOGSAFE001  a wrapper that sets errexit and contains a bare echo/printf to
              the inherited stdout/stderr -- neither routed through the
              preamble's log(), nor suffixed with || true, nor a write that
              targets a file or a command substitution
  LOGSAFE002  a wrapper that sets errexit and does not carry the LOG-SAFE-1
              preamble byte-for-byte

Point this at an assembled MLP1 payload (or any tree holding
emulators/*/launch.sh wrappers). Only emulators/ launchers are checked: those
are the processes whose death is invisible -- a black flash and a return to
the menu.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__"}

# The canonical LOG-SAFE-1 preamble. Byte-identical across every wrapper, so a
# wrapper whose copy has drifted (in either direction) fails LOGSAFE002. The
# probe deliberately writes a real byte with SIGXFSZ ignored inside a subshell:
# at the FAT32 ceiling the kernel raises SIGXFSZ and its default action would
# kill the probe shell before the write could fail with EFBIG.
LOGSAFE1_PREAMBLE = r'''# LOG-SAFE-1. The session log lives on a FAT card and can go unwritable (a bad
# cluster chain, a full card, or the FAT32 4 GiB per-file ceiling). stdout and
# stderr here are inherited from the launcher and point at that file. Under
# set -e a failed echo would abort this script and the game would never start,
# so probe both once and fall back to /dev/null, then never let a log write
# decide whether a game launches.
leaf_log_probe() {
    # A real byte, not a zero-length write: a 0-byte write can succeed without
    # touching the device and would not detect EIO/EFBIG. The subshell ignores
    # SIGXFSZ: at the FAT32 ceiling the kernel raises it and its default action
    # would kill this shell before the write could fail with EFBIG.
    ( trap '' XFSZ; printf '\n' ) 2>/dev/null
}
leaf_log_probe >/dev/null 2>&1 || true
if ! leaf_log_probe; then
    exec >/dev/null
fi
if ! leaf_log_probe >&2; then
    exec 2>/dev/null
fi

log() { ( trap '' XFSZ; printf '%s\n' "$*" ) 2>/dev/null || true; }
'''

HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
ERREXIT_RE = re.compile(r"^\s*set\s+(?:-[A-Za-z]*e[A-Za-z]*\s+)+|^\s*set\s+-[A-Za-z]*e[A-Za-z]*$|^\s*set\s+-o\s+errexit\b")
PRINTF_TO_STDOUT_RE = re.compile(r"^\s*(?:\w+=\S+\s+)*(?:echo|printf)\s")
LOG_CALL_RE = re.compile(r"^\s*log\s")


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


def strip_quoted(line: str) -> str:
    """Remove single- and double-quoted spans, so keyword spotting ignores
    string contents. Awk programs single-quoted whole are the case that
    matters."""
    out = []
    quote = None
    escaped = False
    for ch in line:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            out.append(" " if ch != "\t" else "\t")
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(" ")
            continue
        out.append(ch)
    return "".join(out)


def strip_single_quoted(line: str) -> str:
    """Remove only single-quoted spans. Command substitution and parentheses
    inside double quotes still execute, so they must keep counting toward
    the $( depth."""
    out = []
    quote = None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            out.append(" " if ch != "\t" else "\t")
            continue
        if ch == "'":
            quote = ch
            out.append(" ")
            continue
        out.append(ch)
    return "".join(out)


def logical_lines(text: str) -> list[tuple[int, str]]:
    """Join backslash continuations into logical lines, dropping comments and
    heredoc bodies. Returns (first_physical_line, logical_text)."""
    raw = text.splitlines()
    result: list[tuple[int, str]] = []
    heredoc_end: str | None = None
    buffer: list[str] = []
    start = 0
    for number, line in enumerate(raw, start=1):
        if heredoc_end is not None:
            if line.strip() == heredoc_end:
                heredoc_end = None
            continue
        if not buffer:
            start = number
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = HEREDOC_START_RE.search(strip_quoted(line))
            if match and "=" not in line.split("<<")[0].split(match.group(1))[0]:
                heredoc_end = match.group(1)
                continue
        buffer.append(line)
        if line.rstrip("\n").endswith("\\"):
            continue
        joined = "\n".join(buffer)
        buffer = []
        # Drop comment tails on the joined statement.
        joined = re.sub(r"(?<!\\)\s#.*$", "", joined, flags=re.S)
        result.append((start, joined))
    return result


def command_sub_depth(line: str, depth: int) -> int:
    """Track command-substitution depth across logical lines. Single-quoted
    spans cannot hold a substitution; double-quoted ones can, so their parens
    still count. Plain parens (function definitions, subshell groups) pair up
    and cancel, so only genuinely unbalanced ones move the depth."""
    stripped = strip_single_quoted(line)
    depth += stripped.count("(") - stripped.count(")")
    return max(depth, 0)


def group_redirect_spans(lines: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """Line-index spans of brace groups whose closing brace carries a file
    redirect: `{ printf ...; } >"$tmp_config"`. Statements inside such a group
    write to the group's target, not to inherited stdout."""
    spans: list[tuple[int, int]] = []
    open_index: int | None = None
    for index, (_, logical) in enumerate(lines):
        unquoted = strip_quoted(logical).strip()
        if open_index is None and (unquoted == "{" or unquoted.endswith(" {")):
            open_index = index
            continue
        if open_index is not None and unquoted.startswith("}"):
            # `} >file` redirects the whole group at a file; `} || true` means
            # a failed statement inside the group cannot abort the script.
            if re.search(r"}\s*>>?", unquoted) or re.match(r"}\s*\|\|", unquoted):
                spans.append((open_index, index))
            open_index = None
    return spans


def scan_wrapper(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = logical_lines(text)
    sets_errexit = any(ERREXIT_RE.match(logical) for _, logical in lines)
    if sets_errexit and LOGSAFE1_PREAMBLE not in text:
        findings.append(
            Finding(
                "LOGSAFE002",
                path,
                1,
                "sets errexit but does not carry the LOG-SAFE-1 preamble "
                "byte-for-byte; an unwritable session log fd aborts the launch "
                "on its first unguarded write",
            )
        )
    if not sets_errexit:
        return findings

    redirected_groups = group_redirect_spans(lines)
    depth = 0
    for index, (number, logical) in enumerate(lines):
        inside_substitution = depth > 0
        depth = command_sub_depth(logical, depth)
        if inside_substitution or depth > 0:
            continue
        if any(open_ <= index <= close for open_, close in redirected_groups):
            continue
        if LOG_CALL_RE.match(logical):
            continue
        if not PRINTF_TO_STDOUT_RE.match(logical):
            continue
        unquoted = strip_quoted(logical)
        if "||" in unquoted:
            continue
        if re.search(r">>?\s*(?!&)", unquoted) or "2>>" in unquoted:
            # Redirect to a path: a file write, not an inherited-fd write.
            # (2>&1 alongside a file redirect still ends at that file.)
            continue
        if re.search(r"(?:^|\s)\d*>\s*&\s*\d", unquoted):
            findings.append(
                Finding(
                    "LOGSAFE001",
                    path,
                    number,
                    "bare echo/printf to an inherited descriptor under errexit; "
                    "route it through log() or guard it, or the launch dies "
                    "when the session log is unwritable",
                )
            )
            continue
        if "$(" in strip_single_quoted(logical) or "`" in strip_single_quoted(logical):
            continue
        findings.append(
            Finding(
                "LOGSAFE001",
                path,
                number,
                "bare echo/printf to stdout under errexit; route it through "
                "log() or guard it, or the launch dies when the session log "
                "is unwritable",
            )
        )
    return findings


def iter_wrappers(root: Path):
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("launch*.sh")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if "emulators" not in path.parts:
            continue
        yield path


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_wrappers(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SystemExit(f"error: cannot read {path}: {exc}") from exc
        findings.extend(scan_wrapper(path, text))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="assembled payload(s) or wrapper tree(s) to check",
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
            f"\n{len(findings)} log-safety violation(s); see "
            "plans/bugfixes/standalone-launch-dies-on-unwritable-session-log.md",
            file=sys.stderr,
        )
        return 1

    print("log-safety policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
