#!/usr/bin/env python3
"""Build and serve a local Pak Rat feed for Mac/MLP1 testing.

This script intentionally writes only under Leaf/build/pakrat-local. It does not
touch leaf-docs or the production leaf.game catalog.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
LEAF_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = LEAF_ROOT / "build" / "pakrat-local"
FEED_PREFIX = Path("pakrat") / "v1"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ARTIFACT_KEYS = (
    "url",
    "name",
    "archive",
    "size",
    "installed_size",
    "sha256",
)
MAX_VERSIONS_PER_PACKAGE = 16


def die(message: str) -> None:
    print(f"pakrat-local-feed: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_sdlreader(default: str | None) -> Path:
    candidates = []
    if default:
        candidates.append(Path(default))
    candidates.extend(
        [
            LEAF_ROOT.parent / "SDLReader-brick",
            Path("/Volumes/Storage/GitHub/SDLReader-brick"),
        ]
    )
    for candidate in candidates:
        if (candidate / "pakrat.json").is_file():
            return candidate
    checked = ", ".join(str(c) for c in candidates)
    die(f"could not find SDLReader-brick with pakrat.json; checked {checked}")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"missing {path}")
    except json.JSONDecodeError as exc:
        die(f"invalid JSON in {path}: {exc}")


def run_command(argv: list[str], cwd: Path) -> None:
    print(f"+ (cd {cwd} && {' '.join(argv)})")
    subprocess.run(argv, cwd=str(cwd), check=True)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_pak_dir(package_dir: Path, out_zip: Path) -> None:
    if not package_dir.is_dir():
        die(f"missing package dir: {package_dir}")
    if package_dir.suffix != ".pak":
        die(f"package dir must be a single top-level .pak directory: {package_dir}")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip = out_zip.with_suffix(out_zip.suffix + ".partial")
    if tmp_zip.exists():
        tmp_zip.unlink()

    with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in sorted(package_dir.rglob("*")):
            rel = item.relative_to(package_dir.parent)
            if item.is_dir():
                continue
            info = zipfile.ZipInfo(str(rel).replace(os.sep, "/"))
            mode = item.stat().st_mode
            info.external_attr = (mode & 0o777) << 16
            with item.open("rb") as fp:
                zf.writestr(info, fp.read(), compress_type=zipfile.ZIP_DEFLATED)

    tmp_zip.replace(out_zip)


def inspect_zip_artifact(
    artifact_path: Path, install_name: str, runtime_manifest_path: str
) -> tuple[dict, int]:
    if not artifact_path.is_file():
        die(f"missing artifact: {artifact_path}")
    if artifact_path.suffix.casefold() != ".zip":
        die(f"artifact must be a ZIP: {artifact_path}")
    if not install_name.endswith(".pak") or "/" in install_name or "\\" in install_name:
        die(f"unsafe install_name: {install_name!r}")
    runtime_parts = Path(runtime_manifest_path).parts
    if (
        not runtime_parts
        or Path(runtime_manifest_path).is_absolute()
        or ".." in runtime_parts
        or "\\" in runtime_manifest_path
    ):
        die(f"unsafe runtime_manifest_path: {runtime_manifest_path!r}")

    expected_manifest = (
        Path(install_name, *runtime_parts).as_posix()
    )
    installed_size = 0
    runtime_bytes: bytes | None = None
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            seen_names: set[str] = set()
            for info in archive.infolist():
                name = info.filename
                path = Path(name)
                if (
                    not name
                    or name.startswith("/")
                    or "\\" in name
                    or ".." in path.parts
                    or path.parts[0] != install_name
                ):
                    die(f"{artifact_path}: unsafe or unexpected archive path {name!r}")
                if name in seen_names:
                    die(f"{artifact_path}: duplicate archive path {name!r}")
                seen_names.add(name)
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in (0, 0o040000, 0o100000):
                    die(f"{artifact_path}: non-regular archive entry {name!r}")
                if info.is_dir():
                    continue
                installed_size += info.file_size
                if name == expected_manifest:
                    runtime_bytes = archive.read(info)
    except zipfile.BadZipFile as exc:
        die(f"invalid ZIP {artifact_path}: {exc}")

    if runtime_bytes is None:
        die(f"{artifact_path}: missing {expected_manifest}")
    try:
        runtime = json.loads(runtime_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"{artifact_path}: invalid runtime manifest: {exc}")
    if not isinstance(runtime, dict):
        die(f"{artifact_path}: runtime manifest must be an object")
    return runtime, installed_size


def parse_artifact_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        app_id, separator, raw_path = value.partition("=")
        if not separator or not app_id or not raw_path:
            die(f"invalid --artifact {value!r}; expected APP_ID=/path/to/file.zip")
        if app_id in overrides:
            die(f"duplicate --artifact override for {app_id}")
        overrides[app_id] = Path(raw_path).expanduser().resolve()
    return overrides


def require_metadata_string(meta: dict, key: str, source: Path) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value.strip():
        die(f"{source}: {key} must be a non-empty string")
    return value


def require_path_segment(value: str, label: str, source: Path) -> str:
    if (
        not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).name != value
    ):
        die(f"{source}: unsafe {label}: {value!r}")
    return value


def require_version(value: object, label: str, source: Path) -> str:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        die(f"{source}: {label} must be an exact MAJOR.MINOR.PATCH string")
    components = tuple(int(part) for part in value.split("."))
    if any(part > 9999 for part in components):
        die(f"{source}: {label} component exceeds 9999")
    return value


def version_key(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def optional_min_leaf_version(meta: dict, source: Path) -> str | None:
    if "min_leaf_version" not in meta:
        return None
    return require_version(
        meta.get("min_leaf_version"), "min_leaf_version", source
    )


def artifact_facts(artifact: object, source: Path) -> dict:
    if not isinstance(artifact, dict):
        die(f"{source}: artifact must be an object")
    facts = {key: artifact.get(key) for key in ARTIFACT_KEYS}
    if not isinstance(facts["url"], str) or not facts["url"]:
        die(f"{source}: artifact.url must be a non-empty string")
    if not isinstance(facts["name"], str) or not facts["name"].endswith(".zip"):
        die(f"{source}: artifact.name must end with .zip")
    require_path_segment(facts["name"], "artifact.name", source)
    if facts["archive"] != "zip":
        die(f"{source}: artifact.archive must be zip")
    for key in ("size", "installed_size"):
        if (
            isinstance(facts[key], bool)
            or not isinstance(facts[key], int)
            or facts[key] <= 0
        ):
            die(f"{source}: artifact.{key} must be a positive integer")
    if not isinstance(facts["sha256"], str) or not SHA256_RE.fullmatch(
        facts["sha256"]
    ):
        die(f"{source}: artifact.sha256 must be 64 hexadecimal characters")
    facts["sha256"] = facts["sha256"].lower()
    return facts


def version_entry(entry: object, source: Path) -> dict:
    if not isinstance(entry, dict):
        die(f"{source}: version entry must be an object")
    result = {
        "version": require_version(entry.get("version"), "version", source),
        "artifact": artifact_facts(entry.get("artifact"), source),
    }
    minimum = optional_min_leaf_version(entry, source)
    if minimum is not None:
        result["min_leaf_version"] = minimum
    return result


def normalized_history_package(
    app: dict, package: object, source: Path, is_content: bool = False
) -> dict:
    if not isinstance(package, dict):
        die(f"{source}: package must be an object")
    platform = require_metadata_string(package, "platform", source)
    install_name = require_metadata_string(package, "install_name", source)
    require_path_segment(install_name, "install_name", source)
    if not install_name.endswith(".pak"):
        die(f"{source}: install_name must end with .pak")
    runtime = package.get("runtime", "leaf")
    if runtime != "leaf":
        die(f"{source}: package runtime must be leaf")
    runtime_manifest_path = package.get("runtime_manifest_path", "pak.json")
    if not isinstance(runtime_manifest_path, str) or not runtime_manifest_path:
        die(f"{source}: runtime_manifest_path must be a non-empty string")

    legacy = version_entry(package, source)
    if "min_leaf_version" in legacy and not is_content:
        die(f"{source}: legacy package version must be an ungated safe floor")
    versions_value = package.get("versions")
    legacy_import = versions_value is None
    if legacy_import:
        versions = [legacy]
    else:
        if not isinstance(versions_value, list) or not versions_value:
            die(f"{source}: versions must be a non-empty array")
        if len(versions_value) > MAX_VERSIONS_PER_PACKAGE:
            die(
                f"{source}: versions exceeds the "
                f"{MAX_VERSIONS_PER_PACKAGE}-entry client limit"
            )
        versions = [version_entry(value, source) for value in versions_value]
        keys = [version_key(value["version"]) for value in versions]
        if any(left <= right for left, right in zip(keys, keys[1:])):
            die(f"{source}: versions must be unique and strictly descending")

    by_version = {value["version"]: value for value in versions}
    if len(by_version) != len(versions):
        die(f"{source}: duplicate package version")
    if is_content:
        # Every content package gates on the contract that defines it, so it
        # has no ungated floor and needs none: gate-unaware clients never
        # parse this lane. The legacy fields still mirror something real --
        # the newest entry rather than the newest ungated one.
        if any("min_leaf_version" not in value for value in versions):
            die(f"{source}: every content version must declare min_leaf_version")
        floor = max(versions, key=lambda value: version_key(value["version"]))
        if (
            legacy["version"] != floor["version"]
            or legacy["artifact"] != floor["artifact"]
            or legacy.get("min_leaf_version") != floor.get("min_leaf_version")
            or app.get("version") != floor["version"]
        ):
            die(f"{source}: legacy app/package fields do not match the newest version")
    else:
        floors = [value for value in versions if "min_leaf_version" not in value]
        if not floors:
            die(f"{source}: package history has no ungated safe floor")
        floor = max(floors, key=lambda value: version_key(value["version"]))
        if (
            legacy["version"] != floor["version"]
            or legacy["artifact"] != floor["artifact"]
            or app.get("version") != floor["version"]
        ):
            die(f"{source}: legacy app/package fields do not match the safe floor")

    return {
        "platform": platform,
        "runtime": "leaf",
        "install_name": install_name,
        "runtime_manifest_path": runtime_manifest_path,
        "versions": versions,
        "legacy_import": legacy_import,
    }


def load_history_index(path: Path | None) -> dict[tuple[str, str, str], dict]:
    if path is None:
        return {}
    catalog = load_json(path)
    if catalog.get("schema") != 1 or catalog.get("product") != "pak-rat":
        die(f"{path}: history must be a Pak Rat schema-1 storefront")
    apps = catalog.get("apps")
    if not isinstance(apps, list):
        die(f"{path}: history apps must be an array")
    content = catalog.get("content", [])
    if not isinstance(content, list):
        die(f"{path}: history content must be an array")
    result: dict[tuple[str, str, str], dict] = {}
    seen_ids: set[str] = set()
    for entries, is_content in ((apps, False), (content, True)):
        for app in entries:
            if not isinstance(app, dict):
                die(f"{path}: history app must be an object")
            app_id = require_metadata_string(app, "id", path)
            # S-3, enforced against published history too: an id that has
            # appeared in both lanes cannot be resolved to one install_path.
            if app_id in seen_ids:
                die(f"{path}: duplicate history app id: {app_id}")
            seen_ids.add(app_id)
            packages = app.get("packages")
            if not isinstance(packages, list) or not packages:
                die(f"{path}: history app packages must be a non-empty array")
            for package in packages:
                normalized = normalized_history_package(
                    app, package, path, is_content
                )
                key = (
                    app_id,
                    normalized["platform"],
                    normalized["install_name"].casefold(),
                )
                if key in result:
                    die(f"{path}: duplicate history package for {app_id}")
                normalized["source_path"] = path
                normalized["is_content"] = is_content
                result[key] = normalized
    return result


def local_history_artifact_path(history_path: Path, artifact: dict) -> Path | None:
    url_path = unquote(urlsplit(artifact["url"]).path)
    marker = "/artifacts/"
    if marker not in url_path:
        return None
    relative = Path(url_path.split(marker, 1)[1])
    if relative.is_absolute() or ".." in relative.parts:
        die(f"{history_path}: unsafe historical artifact URL {artifact['url']!r}")
    return history_path.parent / "artifacts" / relative


def verify_artifact_file(path: Path, artifact: dict, source: Path) -> None:
    if path.stat().st_size != artifact["size"] or file_sha256(path) != artifact["sha256"]:
        die(f"{source}: historical artifact bytes disagree with catalog facts: {path}")


def materialize_history_versions(
    history: dict,
    app_id: str,
    artifacts_root: Path,
    base_url: str,
) -> list[dict]:
    versions = copy.deepcopy(history["versions"])
    source_path: Path = history["source_path"]
    for value in versions:
        artifact = value["artifact"]
        expected_relative = Path(app_id) / value["version"] / artifact["name"]
        source_artifact = local_history_artifact_path(source_path, artifact)
        if source_artifact is not None and source_artifact.is_file():
            verify_artifact_file(source_artifact, artifact, source_path)
            destination = artifacts_root / expected_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                verify_artifact_file(destination, artifact, source_path)
            elif source_artifact.resolve() != destination.resolve():
                shutil.copy2(source_artifact, destination)
        elif urlsplit(artifact["url"]).scheme not in ("https",):
            die(f"{source_path}: missing local historical artifact for {artifact['url']}")

        url_path = unquote(urlsplit(artifact["url"]).path)
        expected_suffix = "/artifacts/" + expected_relative.as_posix()
        if not url_path.endswith(expected_suffix):
            if history["legacy_import"]:
                artifact["url"] = base_url + f"artifacts/{expected_relative.as_posix()}"
            elif urlsplit(artifact["url"]).scheme != "https":
                die(
                    f"{source_path}: historical artifact URL is not version-qualified: "
                    f"{artifact['url']}"
                )
    return versions


def merge_package_history(
    history: dict | None,
    current: dict,
    app_id: str,
    runtime_manifest_path: str,
    artifacts_root: Path,
    base_url: str,
    source: Path,
    is_content: bool = False,
) -> tuple[list[dict], dict]:
    if history is None:
        versions: list[dict] = []
    else:
        if (
            history["runtime"] != "leaf"
            or history["runtime_manifest_path"] != runtime_manifest_path
        ):
            die(f"{source}: package identity disagrees with history")
        versions = materialize_history_versions(
            history, app_id, artifacts_root, base_url
        )

    existing = next(
        (value for value in versions if value["version"] == current["version"]),
        None,
    )
    if existing is not None:
        if existing != current:
            die(
                f"{source}: immutable history conflict for "
                f"{app_id} {current['version']}"
            )
    else:
        if versions and version_key(current["version"]) <= max(
            version_key(value["version"]) for value in versions
        ):
            die(f"{source}: new package version must be newer than history")
        versions.append(current)

    versions.sort(key=lambda value: version_key(value["version"]), reverse=True)
    if len(versions) > MAX_VERSIONS_PER_PACKAGE:
        die(
            f"{source}: versions exceeds the "
            f"{MAX_VERSIONS_PER_PACKAGE}-entry client limit"
        )
    if is_content:
        # STORE-CONTENT-1: there is no ungated safe floor in content[], but
        # every entry still has a gate. Immutability and append-only history
        # above apply unchanged.
        if any("min_leaf_version" not in value for value in versions):
            die(f"{source}: every content version must declare min_leaf_version")
        floor = max(versions, key=lambda value: version_key(value["version"]))
        return versions, floor
    floors = [value for value in versions if "min_leaf_version" not in value]
    if not floors:
        die(
            f"{source}: gated version {current['version']} requires explicit "
            "history with an ungated safe floor"
        )
    floor = max(floors, key=lambda value: version_key(value["version"]))
    return versions, floor


def resolve_app_dirs(args: argparse.Namespace) -> list[Path]:
    if args.app_dir:
        app_dirs = [Path(value).expanduser().resolve() for value in args.app_dir]
    else:
        app_dirs = [find_sdlreader(args.sdlreader_dir).resolve()]
    seen: set[Path] = set()
    result: list[Path] = []
    for app_dir in app_dirs:
        if app_dir in seen:
            die(f"duplicate --app-dir: {app_dir}")
        if not (app_dir / "pakrat.json").is_file():
            die(f"missing {app_dir / 'pakrat.json'}")
        seen.add(app_dir)
        result.append(app_dir)
    return result


def require_output_root(value: str) -> Path:
    output_root = Path(value).expanduser().resolve()
    allowed_root = DEFAULT_OUTPUT.resolve()
    try:
        output_root.relative_to(allowed_root)
    except ValueError:
        die(f"--output must be {allowed_root} or a child path")
    return output_root


def ensure_base_url(base_url: str) -> str:
    return base_url if base_url.endswith("/") else base_url + "/"


def default_lan_ip() -> str:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def build_storefront(args: argparse.Namespace) -> Path:
    output_root = require_output_root(args.output)
    feed_root = output_root / FEED_PREFIX
    storefront_path = feed_root / "storefront.json"
    explicit_history = (
        Path(args.history).expanduser().resolve() if args.history else None
    )
    history_path = explicit_history
    if history_path is None and storefront_path.is_file():
        history_path = storefront_path
    history_index = load_history_index(history_path)

    artifacts_root = feed_root / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    app_dirs = resolve_app_dirs(args)
    artifact_overrides = parse_artifact_overrides(args.artifact)
    base_url = ensure_base_url(args.base_url)
    apps: list[dict] = []
    content: list[dict] = []
    seen_ids: set[str] = set()
    seen_install_names: set[str] = set()
    used_history_keys: set[tuple[str, str, str]] = set()

    for app_dir in app_dirs:
        metadata_path = app_dir / "pakrat.json"
        meta = load_json(metadata_path)
        if meta.get("schema") != 1:
            die(f"{metadata_path}: schema must be 1")
        app_id = require_metadata_string(meta, "id", metadata_path)
        require_path_segment(app_id, "app id", metadata_path)
        # S-3: one lane per id. Both lanes resolve to the same install_path,
        # so an id in both is a duplicate-identity bug, not two audiences.
        if app_id in seen_ids:
            die(f"duplicate app id: {app_id}")
        seen_ids.add(app_id)
        kind = meta.get("kind", "app")
        if kind not in ("app", "content"):
            die(f"{metadata_path}: kind must be \"app\" or \"content\"")
        is_content = kind == "content"

        packages = meta.get("leaf", {}).get("packages", [])
        if not isinstance(packages, list) or not packages:
            die(f"{metadata_path}: leaf.packages must be a non-empty array")
        if is_content:
            # D16: cores and standalone emulator binaries are
            # platform-specific, so there is nothing a shared content pak
            # could correctly ship. Refused explicitly rather than left to
            # fail later as "no MLP1 package", which would hide the reason.
            for pkg in packages:
                if isinstance(pkg, dict) and pkg.get("platform") == "shared":
                    die(
                        f"{metadata_path}: content packages must name a "
                        "concrete platform; \"shared\" is refused"
                    )
        selected = [pkg for pkg in packages if pkg.get("platform") == "mlp1"]
        if not selected:
            die(f"{metadata_path}: no MLP1 Leaf package")
        if app_id in artifact_overrides and len(selected) != 1:
            die(f"--artifact override for {app_id} requires exactly one MLP1 package")

        app_packages: list[dict] = []
        app_floor_versions: set[str] = set()
        current_versions: set[str] = set()
        for pkg in selected:
            if not isinstance(pkg, dict):
                die(f"{metadata_path}: package must be an object")
            package_dir_raw = pkg.get("package_dir")
            artifact_name = pkg.get("artifact_name")
            install_name = pkg.get("install_name")
            runtime_manifest_path = pkg.get("runtime_manifest_path", "pak.json")
            if not isinstance(package_dir_raw, str) or not package_dir_raw:
                die(f"{metadata_path}: package_dir must be a non-empty string")
            if not isinstance(artifact_name, str) or not artifact_name.endswith(".zip"):
                die(f"{metadata_path}: artifact_name must end with .zip")
            require_path_segment(artifact_name, "artifact_name", metadata_path)
            if not isinstance(install_name, str) or not install_name.endswith(".pak"):
                die(f"{metadata_path}: install_name must end with .pak")
            require_path_segment(install_name, "install_name", metadata_path)
            if not isinstance(runtime_manifest_path, str) or not runtime_manifest_path:
                die(f"{metadata_path}: runtime_manifest_path must be a non-empty string")
            version = require_version(
                pkg.get("version"), "package version", metadata_path
            )
            minimum = optional_min_leaf_version(pkg, metadata_path)
            if is_content and minimum is None:
                die(
                    f"{metadata_path}: every content version must declare "
                    "min_leaf_version"
                )

            install_key = install_name.casefold()
            if install_key in seen_install_names:
                die(f"duplicate install name: {install_name}")
            seen_install_names.add(install_key)

            package_dir = (app_dir / package_dir_raw).resolve()
            try:
                package_dir.relative_to(app_dir)
            except ValueError:
                die(f"{metadata_path}: package_dir escapes app root")
            if package_dir.name != install_name:
                die(
                    f"{metadata_path}: package_dir name {package_dir.name!r} "
                    f"does not match install_name {install_name!r}"
                )

            build_command = pkg.get("build_command") or []
            override = artifact_overrides.get(app_id)
            if override is None and build_command and not args.skip_build:
                if not isinstance(build_command, list) or not all(
                    isinstance(part, str) and part for part in build_command
                ):
                    die(f"{metadata_path}: build_command must be a string array")
                run_command(build_command, app_dir)

            artifact_relative = Path(app_id) / version / artifact_name
            artifact_path = artifacts_root / artifact_relative
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path = artifact_path.with_name(
                ".candidate-" + artifact_path.name
            )
            candidate_path.unlink(missing_ok=True)
            if override is not None:
                if override.name != artifact_name:
                    die(
                        f"--artifact for {app_id} must be named {artifact_name}, "
                        f"got {override.name}"
                    )
                if not override.is_file():
                    die(f"missing exact artifact override: {override}")
                shutil.copy2(override, candidate_path)
            else:
                zip_pak_dir(package_dir, candidate_path)

            runtime, installed_size = inspect_zip_artifact(
                candidate_path, install_name, runtime_manifest_path
            )
            # The lane is a claim; the built .pak is the fact. A package in
            # content[] whose artifact declares no `provides` would install
            # and then contribute nothing, and a `provides` pak in apps[]
            # would be offered to gate-unaware clients that cannot use it.
            artifact_provides = isinstance(runtime.get("provides"), dict)
            if is_content and not artifact_provides:
                die(
                    f"{candidate_path}: kind is content but the runtime "
                    "manifest declares no `provides` block"
                )
            if not is_content and artifact_provides:
                die(
                    f"{candidate_path}: runtime manifest declares `provides`, "
                    "so this package belongs in the content lane "
                    "(set \"kind\": \"content\" in pakrat.json)"
                )
            if version != runtime.get("pak_version"):
                die(
                    f"{candidate_path}: runtime pak_version "
                    f"{runtime.get('pak_version')!r} does not match Pak Rat "
                    f"version {version!r}"
                )
            runtime_has_minimum = "min_leaf_version" in runtime
            runtime_minimum = runtime.get("min_leaf_version")
            if (
                (minimum is None and runtime_has_minimum)
                or (minimum is not None and runtime_minimum != minimum)
            ):
                die(
                    f"{candidate_path}: runtime min_leaf_version "
                    f"{runtime_minimum!r} does not match Pak Rat "
                    f"min_leaf_version {minimum!r}"
                )

            artifact = {
                "url": base_url + f"artifacts/{artifact_relative.as_posix()}",
                "name": artifact_name,
                "archive": "zip",
                "size": candidate_path.stat().st_size,
                "installed_size": installed_size,
                "sha256": file_sha256(candidate_path),
            }
            current = {
                "version": version,
                "artifact": artifact,
            }
            if minimum is not None:
                current["min_leaf_version"] = minimum

            history_key = (app_id, "mlp1", install_name.casefold())
            history = history_index.get(history_key)
            if history is None and any(
                key[0] == app_id for key in history_index
            ):
                die(f"{metadata_path}: package identity disagrees with history")
            if history is not None:
                used_history_keys.add(history_key)
            if history is not None and history.get("is_content", False) != is_content:
                die(
                    f"{metadata_path}: {app_id} changed lanes; published "
                    "history cannot move between apps[] and content[]"
                )
            versions, floor = merge_package_history(
                history,
                current,
                app_id,
                runtime_manifest_path,
                artifacts_root,
                base_url,
                metadata_path,
                is_content,
            )
            candidate_path.replace(artifact_path)

            current_versions.add(version)
            app_floor_versions.add(floor["version"])
            emitted = {
                "platform": "mlp1",
                "runtime": "leaf",
                "version": floor["version"],
                "install_name": install_name,
                "runtime_manifest_path": runtime_manifest_path,
                "artifact": copy.deepcopy(floor["artifact"]),
                "versions": versions,
            }
            # In apps[] the legacy fields ARE the ungated safe floor, so they
            # never carry a gate. In content[] they mirror the newest entry,
            # which has one -- and omitting it would leave the legacy fields
            # claiming an install that no gated client would accept.
            if is_content and "min_leaf_version" in floor:
                emitted["min_leaf_version"] = floor["min_leaf_version"]
            app_packages.append(emitted)

        if len(current_versions) != 1:
            die(f"{metadata_path}: all MLP1 packages must use one app version")
        if len(app_floor_versions) != 1:
            die(f"{metadata_path}: all MLP1 packages must use one safe-floor version")
        app_version = next(iter(app_floor_versions))
        categories = meta.get("categories", [])
        if not isinstance(categories, list) or not all(
            isinstance(value, str) and value for value in categories
        ):
            die(f"{metadata_path}: categories must be a string array")
        (content if is_content else apps).append(
            {
                "id": app_id,
                "name": require_metadata_string(meta, "name", metadata_path),
                "summary": require_metadata_string(meta, "summary", metadata_path),
                "description": require_metadata_string(meta, "description", metadata_path),
                "author": require_metadata_string(meta, "author", metadata_path),
                "repo_url": require_metadata_string(meta, "repo_url", metadata_path),
                "categories": categories,
                "version": app_version,
                "packages": app_packages,
            }
        )

    unknown_overrides = sorted(set(artifact_overrides) - seen_ids)
    if unknown_overrides:
        die(f"--artifact references unknown app ids: {', '.join(unknown_overrides)}")
    unused_history = sorted(set(history_index) - used_history_keys)
    if unused_history:
        app_id, platform, install_name = unused_history[0]
        die(
            "history contains a package that was not regenerated: "
            f"{app_id} {platform} {install_name}"
        )

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    storefront = {
        "schema": 1,
        "product": "pak-rat",
        "catalog_revision": "local-" + generated_at.replace(":", "").replace("-", ""),
        "generated_at": generated_at,
        "apps": apps,
    }
    # `schema` stays 1 and the key is only emitted when it has entries: a
    # gate-unaware client parses apps[], ignores an unknown `content` key, and
    # never learns a content pak exists. That is the whole reason this is a
    # new lane rather than a flag on an existing one.
    if content:
        storefront["content"] = content

    storefront_partial = storefront_path.with_suffix(".json.partial")
    storefront_partial.write_text(
        json.dumps(storefront, indent=2) + "\n", encoding="utf-8"
    )
    storefront_partial.replace(storefront_path)
    print(f"Wrote {storefront_path}")
    for app in apps + content:
        for pkg in app["packages"]:
            artifact = pkg["versions"][0]["artifact"]
            print(
                f"  {app['id']} {pkg['versions'][0]['version']} "
                f"{artifact['name']} "
                f"size={artifact['size']} sha256={artifact['sha256']}"
            )
    return storefront_path


def adb_command(args: argparse.Namespace) -> list[str]:
    adb = ["adb"]
    serial = args.adb_serial or os.environ.get("ADB_SERIAL")
    if serial:
        adb += ["-s", serial]
    return adb


def adb_reverse(args: argparse.Namespace) -> None:
    adb = adb_command(args)
    spec = f"tcp:{args.port}"
    print(f"Configuring ADB reverse: device {spec} -> host {spec}")
    subprocess.run(adb + ["reverse", spec, spec], check=True)


def adb_configure(args: argparse.Namespace, url: str) -> None:
    adb = adb_command(args)
    remote_state = args.remote_state_dir
    remote_file = remote_state.rstrip("/") + "/store/dev-catalog-url"
    shell = (
        f"mkdir -p {sh_quote(remote_state.rstrip('/') + '/store')} && "
        f"printf '%s\\n' {sh_quote(url)} > {sh_quote(remote_file)} && "
        f"cat {sh_quote(remote_file)}"
    )
    print(f"Configuring device dev catalog URL: {url}")
    subprocess.run(adb + ["shell", shell], check=True)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print("http:", fmt % args)


def serve(args: argparse.Namespace) -> None:
    output_root = Path(args.output).resolve()
    handler = lambda *a, **kw: QuietHandler(*a, directory=str(output_root), **kw)
    server = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {output_root}")
    print(f"Mac URL:    http://127.0.0.1:{args.port}/pakrat/v1/storefront.json")
    if args.adb_reverse:
        print(f"Device URL: http://127.0.0.1:{args.port}/pakrat/v1/storefront.json (ADB reverse)")
    else:
        print(f"Device URL: http://{default_lan_ip()}:{args.port}/pakrat/v1/storefront.json")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="output root")
    parser.add_argument(
        "--app-dir",
        action="append",
        default=[],
        help="app repo containing pakrat.json; repeat for multiple apps",
    )
    parser.add_argument("--sdlreader-dir", help="path to SDLReader-brick")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="APP_ID=ZIP",
        help="use an exact prebuilt artifact for one selected app",
    )
    parser.add_argument("--host", default="127.0.0.1", help="serve host")
    parser.add_argument("--port", type=int, default=8765, help="serve port")
    parser.add_argument("--base-url", help="catalog artifact base URL")
    parser.add_argument(
        "--history",
        help=(
            "schema-1 storefront whose immutable version history should be "
            "merged; defaults to the existing output storefront"
        ),
    )
    parser.add_argument("--serve", action="store_true", help="serve after generating")
    parser.add_argument("--skip-build", action="store_true", help="use existing package dir")
    parser.add_argument("--adb-configure", action="store_true", help="write dev-catalog-url to an attached device")
    parser.add_argument("--adb-reverse", action="store_true", help="set up adb reverse and use a device-loopback catalog URL")
    parser.add_argument("--adb-serial", help="ADB serial; defaults to ADB_SERIAL or adb default")
    parser.add_argument("--remote-state-dir", default="/mnt/sdcard/.umrk/mlp1", help="device UMRK_INTERNAL_DATA_PATH")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reverse_base_url = f"http://127.0.0.1:{args.port}/pakrat/v1/"
    if args.adb_reverse:
        if args.base_url and ensure_base_url(args.base_url) != reverse_base_url:
            die(f"--adb-reverse requires --base-url {reverse_base_url}")
        args.base_url = reverse_base_url
        args.adb_configure = True
    if not args.base_url:
        host = default_lan_ip() if args.adb_configure else ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host)
        args.base_url = f"http://{host}:{args.port}/pakrat/v1/"

    build_storefront(args)
    if args.adb_reverse:
        adb_reverse(args)
    if args.adb_configure:
        adb_configure(args, ensure_base_url(args.base_url))
    print(f"Catalog base URL: {ensure_base_url(args.base_url)}")
    if args.serve:
        serve(args)


if __name__ == "__main__":
    main()
