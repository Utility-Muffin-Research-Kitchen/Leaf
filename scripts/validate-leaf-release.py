#!/usr/bin/env python3
"""Validate Leaf release identity, provenance, and assembled capabilities."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


VERSION_RE = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
BETA_TAG_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+-beta\.[1-9][0-9]*")
COMPONENT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
REQUIRED_PATH_LISTS = {
    "SDCARD_PATHS": ("/mnt/sdcard", "/media/sdcard1"),
    "ROMS_PATHS": ("/mnt/sdcard/Roms", "/media/sdcard1/Roms"),
    "IMAGES_PATHS": ("/mnt/sdcard/Images", "/media/sdcard1/Images"),
    "MUSIC_PATHS": ("/mnt/sdcard/Music", "/media/sdcard1/Music"),
    "APPS_PATHS": ("/mnt/sdcard/Apps", "/media/sdcard1/Apps"),
    "BIOS_PATHS": ("/mnt/sdcard/BIOS", "/media/sdcard1/BIOS"),
    "SAVES_PATHS": ("/mnt/sdcard/Saves", "/media/sdcard1/Saves"),
    "STATES_PATHS": ("/mnt/sdcard/States", "/media/sdcard1/States"),
    "CHEATS_PATHS": ("/mnt/sdcard/Cheats", "/media/sdcard1/Cheats"),
}


class PolicyError(Exception):
    pass


def validate_version(value: str, label: str = "version") -> str:
    if not VERSION_RE.fullmatch(value or ""):
        raise PolicyError(
            f"{label} must be a semantic version such as 0.7.0 "
            "or 0.7.0-save-isolation-ota1"
        )
    core = value.split("-", 1)[0].split("+", 1)[0]
    if any(int(part) > 9999 for part in core.split(".")):
        raise PolicyError(f"{label} component exceeds 9999")
    return value


def normalized_tag(tag: str) -> str:
    if not tag:
        raise PolicyError("stable releases require an explicit LEAF_RELEASE_TAG")
    if not tag.startswith("v") or tag.startswith("vv"):
        raise PolicyError("stable release tag must have exactly one leading lowercase v")
    return validate_version(tag[1:], "release tag")


def validate_beta_tag(tag: str) -> str:
    if not BETA_TAG_RE.fullmatch(tag or ""):
        raise PolicyError("beta tag must match vX.Y.Z-beta.N exactly")
    return validate_version(tag[1:], "beta tag")


def validate_identity(channel: str, version: str, tag: str, release_id: str) -> None:
    if not channel:
        raise PolicyError("release channel must not be empty")
    if not release_id:
        raise PolicyError("release id must not be empty")
    if tag and release_id != tag:
        raise PolicyError(
            "tagged releases require RELEASE_ID to match LEAF_RELEASE_TAG: "
            f"{release_id!r} != {tag!r}"
        )
    if channel == "stable":
        validate_version(version, "LEAF_RELEASE_VERSION")
        tag_version = normalized_tag(tag)
        if version != tag_version:
            raise PolicyError(
                "LEAF_RELEASE_VERSION does not match LEAF_RELEASE_TAG after "
                f"normalizing its leading v: {version!r} != {tag_version!r}"
            )
    elif version and version != release_id:
        validate_version(version, "LEAF_RELEASE_VERSION")


def run_git(
    repo: Path, *args: str, allow_empty: bool = False, allow_failure: bool = False
) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if allow_failure:
            return ""
        detail = exc.stderr.strip()
        raise PolicyError(f"cannot inspect Git repository {repo}: {detail or exc}") from exc
    except OSError as exc:
        detail = ""
        raise PolicyError(f"cannot inspect Git repository {repo}: {detail or exc}") from exc
    value = result.stdout.strip()
    if not value and not allow_empty:
        raise PolicyError(f"Git returned no value for {repo}: {' '.join(args)}")
    return value


def parse_component(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not COMPONENT_NAME_RE.fullmatch(name):
        raise PolicyError(f"component must be NAME=PATH with a safe name: {value!r}")
    path = Path(raw_path).resolve()
    if not path.is_dir():
        raise PolicyError(f"component repository is missing: {name}={path}")
    return name, path


def sanitize_remote(value: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    return value


def inspect_component(name: str, repo: Path, require_clean: bool) -> dict[str, object]:
    inside = run_git(repo, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        raise PolicyError(f"component is not a Git worktree: {name}={repo}")
    commit = run_git(repo, "rev-parse", "HEAD")
    status = run_git(
        repo, "status", "--porcelain=v1", "--untracked-files=normal", allow_empty=True
    )
    dirty = bool(status)
    if require_clean and dirty:
        preview = ", ".join(line[3:] for line in status.splitlines()[:5])
        raise PolicyError(f"tagged release component is dirty: {name} ({preview})")
    remote = run_git(
        repo,
        "config",
        "--get",
        "remote.origin.url",
        allow_empty=True,
        allow_failure=True,
    )
    return {
        "name": name,
        "commit": commit,
        "dirty": dirty,
        "remote": sanitize_remote(remote),
    }


def build_provenance(args: argparse.Namespace) -> dict[str, object]:
    validate_identity(args.channel, args.version, args.tag, args.release_id)
    require_clean = args.require_clean or bool(args.tag)
    seen: set[str] = set()
    components: list[dict[str, object]] = []
    for raw in args.component:
        name, repo = parse_component(raw)
        if name in seen:
            raise PolicyError(f"duplicate component name: {name}")
        seen.add(name)
        components.append(inspect_component(name, repo, require_clean))
    for required in ("leaf", "launcher", "launcher-switcher"):
        if required not in seen:
            raise PolicyError(f"missing required provenance component: {required}")
    return {
        "schema": 1,
        "product": "leaf",
        "release": {
            "channel": args.channel,
            "version": args.version,
            "tag": args.tag or None,
            "release_id": args.release_id,
        },
        "components": components,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    partial.replace(path)


def read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {label} {path}: {exc}") from exc


def require_file(path: Path, label: str, executable: bool = False) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise PolicyError(f"missing or empty {label}: {path}")
    if executable and not os.access(path, os.X_OK):
        raise PolicyError(f"{label} is not executable: {path}")


def read_retroarch_config(path: Path, label: str) -> dict[str, str]:
    require_file(path, label)
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PolicyError(f"cannot read {label} {path}: {exc}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw_value = stripped.partition("=")
        if not separator:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def validate_mlp1_retroarch_input_profile(platform: Path) -> None:
    autoconfig = read_retroarch_config(
        platform / "autoconfig" / "Loong Gamepad.cfg",
        "MLP1 RetroArch gamepad autoconfig",
    )
    defaults = read_retroarch_config(
        platform / "defaults" / "retroarch.cfg",
        "MLP1 RetroArch defaults",
    )
    expected = (
        (autoconfig, "input_l3_btn", "7"),
        (autoconfig, "input_l3_btn_label", "L3"),
        (defaults, "input_player1_l3_btn", "7"),
    )
    for config, key, value in expected:
        if config.get(key) != value:
            raise PolicyError(
                f"MLP1 RetroArch L3 mapping mismatch: {key} must be {value!r}"
            )


def read_staged_environment(env_path: Path) -> dict[str, str]:
    result = subprocess.run(
        [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "PLATFORM=mlp1",
            "/bin/sh",
            "-c",
            '. "$1"; env',
            "sh",
            str(env_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise PolicyError(
            f"staged runtime environment cannot be sourced: {result.stderr.strip()}"
        )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def validate_candidate(args: argparse.Namespace) -> None:
    root = args.release_root.resolve()
    platform = root / "platforms" / "mlp1"
    launcher = platform / "launcher"
    daemon = launcher / "bin" / "loong_pangu"
    inhibit = launcher / "bin" / "jawaka-inhibitctl"
    env_path = launcher / "env.sh"

    require_file(daemon, "launcher daemon", executable=True)
    require_file(inhibit, "launcher inhibit helper", executable=True)
    require_file(env_path, "runtime environment")
    validate_mlp1_retroarch_input_profile(platform)
    if b"relocate-games-v1" not in daemon.read_bytes():
        raise PolicyError("launcher daemon does not advertise relocate-games-v1")

    environment = read_staged_environment(env_path)
    if environment.get("UMRK_SECONDARY_SDCARD_PATH") != "/media/sdcard1":
        raise PolicyError("runtime environment does not configure the Secondary card")
    for name, expected in REQUIRED_PATH_LISTS.items():
        actual = tuple(environment.get(name, "").split(":"))
        if actual != expected:
            raise PolicyError(
                f"runtime environment {name} mismatch: "
                f"{actual!r} != {expected!r}"
            )

    provenance_path = root / "provenance" / "components.json"
    provenance = read_json(provenance_path, "component provenance")
    if not isinstance(provenance, dict) or provenance.get("schema") != 1:
        raise PolicyError("component provenance has an unsupported schema")
    release = provenance.get("release")
    if not isinstance(release, dict):
        raise PolicyError("component provenance is missing release identity")
    channel = release.get("channel")
    version = release.get("version")
    tag = release.get("tag")
    release_id = release.get("release_id")
    if (
        not isinstance(channel, str)
        or not isinstance(version, str)
        or (tag is not None and not isinstance(tag, str))
        or not isinstance(release_id, str)
    ):
        raise PolicyError("component provenance contains an invalid release identity")
    validate_identity(channel, version, tag or "", release_id)
    if version != args.version or release_id != args.release_id:
        raise PolicyError("component provenance release identity does not match candidate")
    components = provenance.get("components")
    if not isinstance(components, list):
        raise PolicyError("component provenance is missing components")
    names: set[str] = set()
    tagged = bool(tag)
    for item in components:
        if not isinstance(item, dict):
            raise PolicyError("component provenance contains a non-object entry")
        name = item.get("name")
        commit = item.get("commit")
        if not isinstance(name, str) or not COMPONENT_NAME_RE.fullmatch(name):
            raise PolicyError("component provenance contains an invalid name")
        if name in names:
            raise PolicyError(f"component provenance contains duplicate name: {name}")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise PolicyError(f"component provenance contains invalid commit: {name}")
        if tagged and item.get("dirty") is not False:
            raise PolicyError(f"tagged release component provenance is dirty: {name}")
        names.add(name)
    for required in args.required_component:
        if required not in names:
            raise PolicyError(
                f"component provenance is missing required component: {required}"
            )

    installer = args.install_stage.resolve() / "umrk-launcher-install.sh"
    require_file(installer, "managed installer")
    installer_text = installer.read_text(encoding="utf-8")
    for expected in (
        f'RELEASE_ID="{args.release_id}"',
        f'RELEASE_VERSION="{args.version}"',
        '"version": "$RELEASE_VERSION"',
        '"release_id": "$RELEASE_ID"',
    ):
        if expected not in installer_text:
            raise PolicyError(
                f"managed installer does not preserve release identity: {expected}"
            )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    identity = subparsers.add_parser("identity")
    identity.add_argument("--channel", required=True)
    identity.add_argument("--version", default="")
    identity.add_argument("--tag", default="")
    identity.add_argument("--release-id", required=True)

    beta_tag = subparsers.add_parser("beta-tag")
    beta_tag.add_argument("--tag", required=True)

    provenance = subparsers.add_parser("provenance")
    provenance.add_argument("--channel", required=True)
    provenance.add_argument("--version", default="")
    provenance.add_argument("--tag", default="")
    provenance.add_argument("--release-id", required=True)
    provenance.add_argument("--component", action="append", default=[])
    provenance.add_argument("--require-clean", action="store_true")
    provenance.add_argument("--output", type=Path, required=True)

    candidate = subparsers.add_parser("candidate")
    candidate.add_argument("--release-root", type=Path, required=True)
    candidate.add_argument("--install-stage", type=Path, required=True)
    candidate.add_argument("--version", required=True)
    candidate.add_argument("--release-id", required=True)
    candidate.add_argument("--required-component", action="append", default=[])
    return parser


def main() -> None:
    args = make_parser().parse_args()
    try:
        if args.command == "identity":
            validate_identity(args.channel, args.version, args.tag, args.release_id)
            print(
                f"release identity: channel={args.channel} "
                f"version={args.version or '(unset)'} "
                f"tag={args.tag or '(unset)'} release_id={args.release_id}"
            )
        elif args.command == "beta-tag":
            version = validate_beta_tag(args.tag)
            print(f"beta release identity: tag={args.tag} version={version}")
        elif args.command == "provenance":
            value = build_provenance(args)
            write_json(args.output, value)
            print(f"Wrote {args.output}")
        elif args.command == "candidate":
            validate_candidate(args)
            print("Leaf release candidate gate: identity, provenance, and capabilities verified")
    except PolicyError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
