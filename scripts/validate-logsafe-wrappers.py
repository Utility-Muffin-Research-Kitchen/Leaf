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

Point this at an assembled MLP1 payload, an emulator package directory, or a
wrapper file. In a tree, emulators/ launchers and launch*.sh files directly
inside the supplied directory are checked.
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
# past a file-size rlimit the kernel raises SIGXFSZ, whose default action would
# kill the probe shell before the write could fail with EFBIG. (The FAT32
# per-file ceiling itself fails the write with EFBIG and no signal.)
LOGSAFE1_PREAMBLE = r'''# LOG-SAFE-1. The session log lives on a FAT card and can go unwritable (a bad
# cluster chain, a full card, or the FAT32 4 GiB per-file ceiling). stdout and
# stderr here are inherited from the launcher and point at that file. Under
# set -e a failed echo would abort this script and the game would never start,
# so probe both once and fall back to /dev/null, then never let a log write
# decide whether a game launches.
leaf_log_probe() {
    # A real byte, not a zero-length write: a 0-byte write can succeed without
    # touching the device and would not detect EIO/EFBIG. The subshell ignores
    # SIGXFSZ: past a file-size rlimit the kernel raises it, and its default
    # action would kill this shell before the write could fail with EFBIG.
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
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# A redirection on a masked segment: optional fd, operator, optional dup '&'.
REDIRECT_RE = re.compile(r"(?<![\w<>&])(\d*)(&>>?|>>?)\s*(&?)")

# Operators after which a failed echo/printf cannot trip errexit: the left side
# of || and &&, a pipeline stage that writes into a pipe, a background job.
NON_FATAL_NEXT_OPS = {"||", "&&", "|", "&"}
CONDITION_KEYWORDS = {"if", "elif", "while", "until"}
BODY_KEYWORDS = {"then", "do"}
OTHER_KEYWORDS = {"else", "time"}


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


class Segment:
    """One simple command at the top level of the script: outside quotes and
    command substitutions. `masked` blanks every quoted or substituted span to
    'Q' so keyword and redirect spotting only ever sees shell syntax."""

    __slots__ = ("line", "text", "masked", "prev_op", "next_op")

    def __init__(self, line: int, text: str, masked: str, prev_op: str, next_op: str) -> None:
        self.line = line
        self.text = text
        self.masked = masked
        self.prev_op = prev_op
        self.next_op = next_op


class Scanner:
    """Split logical lines into top-level command segments. Quote and
    substitution state carries across lines, so a multi-line "$( ... )" or a
    multi-line double-quoted string is never mistaken for top-level code."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.prev_op = "\n"

    def segments(self, number: int, logical: str) -> list[Segment]:
        out: list[Segment] = []
        buf: list[str] = []
        mbuf: list[str] = []
        s = logical
        n = len(s)
        i = 0

        def emit(chunk: str, top: bool) -> None:
            buf.append(chunk)
            mbuf.append(chunk if top else "Q" * len(chunk))

        def flush(op: str) -> None:
            out.append(Segment(number, "".join(buf), "".join(mbuf), self.prev_op, op))
            buf.clear()
            mbuf.clear()
            self.prev_op = op

        while i < n:
            ch = s[i]
            top = self.stack[-1] if self.stack else None
            if top == "'":
                emit(ch, False)
                if ch == "'":
                    self.stack.pop()
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                emit(s[i:i + 2], False)
                i += 2
                continue
            if top == "${":
                # Parameter expansion: quotes inside nest ("${x%%") ("*}"),
                # and only the matching brace ends it.
                if ch == "}":
                    self.stack.pop()
                elif ch in "'\"":
                    self.stack.append(ch)
                elif s.startswith("${", i) or s.startswith("$(", i):
                    self.stack.append(s[i:i + 2])
                    emit(s[i:i + 2], False)
                    i += 2
                    continue
                emit(ch, False)
                i += 1
                continue
            if top == '"':
                if ch == '"':
                    self.stack.pop()
                    emit(ch, False)
                    i += 1
                elif s.startswith("${", i):
                    self.stack.append("${")
                    emit("${", False)
                    i += 2
                elif s.startswith("$(", i):
                    self.stack.append("$(")
                    emit("$(", False)
                    i += 2
                elif ch == "`":
                    self.stack.append("`")
                    emit(ch, False)
                    i += 1
                else:
                    emit(ch, False)
                    i += 1
                continue
            # Code: the top level, or inside $( ), ( ) within one, or backticks.
            if ch in "'\"":
                self.stack.append(ch)
                emit(ch, False)
                i += 1
                continue
            if s.startswith("${", i):
                self.stack.append("${")
                emit("${", False)
                i += 2
                continue
            if s.startswith("$(", i):
                self.stack.append("$(")
                emit("$(", False)
                i += 2
                continue
            if ch == "`":
                if top == "`":
                    self.stack.pop()
                else:
                    self.stack.append("`")
                emit(ch, False)
                i += 1
                continue
            if top is not None:
                if ch == "(":
                    self.stack.append("(")
                elif ch == ")":
                    self.stack.pop()
                emit(ch, False)
                i += 1
                continue
            two = s[i:i + 2]
            if ch == "\n":
                flush("\n")
                i += 1
            elif two in ("&&", "||", ";;"):
                flush(two)
                i += 2
            elif ch == ";":
                flush(";")
                i += 1
            elif ch == "|" and not (i > 0 and s[i - 1] == ">"):
                flush("|")
                i += 1
            elif ch == "&" and not ((i > 0 and s[i - 1] in "<>") or s[i + 1:i + 2] == ">"):
                flush("&")
                i += 1
            elif ch in "()":
                # Subshell group, function-definition parens, or a case pattern
                # terminator; scan_wrapper pairs them.
                flush(ch)
                i += 1
            else:
                emit(ch, True)
                i += 1
        if buf or self.prev_op not in ("\n",):
            flush("\n")
        return out


def stdout_goes_to_file(masked: str) -> bool:
    """True when the segment's own redirections send stdout to a file (or
    /dev/null) rather than to an inherited descriptor."""
    target = "inherited"
    for match in REDIRECT_RE.finditer(masked):
        fd, op, dup = match.groups()
        if op.startswith("&>"):
            target = "file"
        elif fd in ("", "1"):
            target = "inherited" if dup else "file"
    return target == "file"


def tail_guards(segment: Segment, masked_tail: str) -> bool:
    return segment.next_op in NON_FATAL_NEXT_OPS or stdout_goes_to_file(masked_tail)


def scan_wrapper(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    sets_errexit = any(ERREXIT_RE.match(logical) for _, logical in logical_lines(text))
    has_preamble = LOGSAFE1_PREAMBLE in text
    if sets_errexit and not has_preamble:
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

    # The preamble is gated byte-for-byte above, and its own writes are the
    # guarded probe and log(); blank it (keeping line numbers) before scanning.
    body = text.replace(LOGSAFE1_PREAMBLE, "\n" * LOGSAFE1_PREAMBLE.count("\n"), 1)
    scanner = Scanner()
    segments: list[Segment] = []
    for number, logical in logical_lines(body):
        segments.extend(scanner.segments(number, logical))

    guarded = [False] * len(segments)
    candidates: list[tuple[int, bool]] = []
    groups: list[tuple[str, int]] = []
    in_condition = False

    for index, segment in enumerate(segments):
        if segment.prev_op == "(":
            groups.append(("(", index))
        elif segment.prev_op == ")" and groups and groups[-1][0] == "(":
            _, start = groups.pop()
            # `( ... ) >file` or `( ... ) || true`: this segment is the tail.
            if tail_guards(segment, segment.masked):
                for inner in range(start, index):
                    guarded[inner] = True

        words = segment.masked.split()
        negated = False
        while words:
            word = words[0]
            if word == "{":
                groups.append(("{", index))
            elif word == "}":
                if groups and groups[-1][0] == "{":
                    _, start = groups.pop()
                    tail = segment.masked.split("}", 1)[1]
                    if tail_guards(segment, tail):
                        for inner in range(start, index):
                            guarded[inner] = True
            elif word in CONDITION_KEYWORDS:
                in_condition = True
            elif word in BODY_KEYWORDS:
                in_condition = False
            elif word == "!":
                negated = True
            elif word not in OTHER_KEYWORDS and not ASSIGNMENT_RE.match(word):
                break
            words.pop(0)
        if words and words[0] in ("echo", "printf"):
            candidates.append((index, in_condition or negated))

    for index, exempt in candidates:
        segment = segments[index]
        if exempt or guarded[index]:
            continue
        if segment.next_op in NON_FATAL_NEXT_OPS or stdout_goes_to_file(segment.masked):
            continue
        findings.append(
            Finding(
                "LOGSAFE001",
                path,
                segment.line,
                "bare echo/printf to an inherited stdout under errexit; route "
                "it through log() or guard it, or the launch dies when the "
                "session log is unwritable",
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
        if path.parent != root and "emulators" not in path.parts:
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
        help="assembled payload(s), emulator package directory(s), or wrapper file(s) to check",
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
