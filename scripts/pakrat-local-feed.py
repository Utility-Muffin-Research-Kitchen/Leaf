#!/usr/bin/env python3
"""Build and serve a local Pak Rat feed for Mac/MLP1 testing.

This script intentionally writes only under Leaf/build/pakrat-local. It does not
touch leaf-docs or the production leaf.game catalog.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
LEAF_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = LEAF_ROOT / "build" / "pakrat-local"
FEED_PREFIX = Path("pakrat") / "v1"


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
    if output_root.exists():
        shutil.rmtree(output_root)
    feed_root = output_root / FEED_PREFIX
    artifacts_root = feed_root / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    app_dirs = resolve_app_dirs(args)
    artifact_overrides = parse_artifact_overrides(args.artifact)
    base_url = ensure_base_url(args.base_url)
    apps: list[dict] = []
    seen_ids: set[str] = set()
    seen_install_names: set[str] = set()
    seen_artifact_names: set[str] = set()

    for app_dir in app_dirs:
        metadata_path = app_dir / "pakrat.json"
        meta = load_json(metadata_path)
        if meta.get("schema") != 1:
            die(f"{metadata_path}: schema must be 1")
        app_id = require_metadata_string(meta, "id", metadata_path)
        if app_id in seen_ids:
            die(f"duplicate app id: {app_id}")
        seen_ids.add(app_id)

        packages = meta.get("leaf", {}).get("packages", [])
        if not isinstance(packages, list) or not packages:
            die(f"{metadata_path}: leaf.packages must be a non-empty array")
        selected = [pkg for pkg in packages if pkg.get("platform") == "mlp1"]
        if not selected:
            die(f"{metadata_path}: no MLP1 Leaf package")
        if app_id in artifact_overrides and len(selected) != 1:
            die(f"--artifact override for {app_id} requires exactly one MLP1 package")

        app_packages: list[dict] = []
        app_versions: set[str] = set()
        for pkg in selected:
            package_dir_raw = pkg.get("package_dir")
            artifact_name = pkg.get("artifact_name")
            install_name = pkg.get("install_name")
            runtime_manifest_path = pkg.get("runtime_manifest_path", "pak.json")
            if not isinstance(package_dir_raw, str) or not package_dir_raw:
                die(f"{metadata_path}: package_dir must be a non-empty string")
            if not isinstance(artifact_name, str) or not artifact_name.endswith(".zip"):
                die(f"{metadata_path}: artifact_name must end with .zip")
            if not isinstance(install_name, str) or not install_name.endswith(".pak"):
                die(f"{metadata_path}: install_name must end with .pak")
            if not isinstance(runtime_manifest_path, str) or not runtime_manifest_path:
                die(f"{metadata_path}: runtime_manifest_path must be a non-empty string")

            install_key = install_name.casefold()
            if install_key in seen_install_names:
                die(f"duplicate install name: {install_name}")
            seen_install_names.add(install_key)
            artifact_key = artifact_name.casefold()
            if artifact_key in seen_artifact_names:
                die(f"duplicate artifact name: {artifact_name}")
            seen_artifact_names.add(artifact_key)

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

            artifact_path = artifacts_root / artifact_name
            if override is not None:
                if override.name != artifact_name:
                    die(
                        f"--artifact for {app_id} must be named {artifact_name}, "
                        f"got {override.name}"
                    )
                if not override.is_file():
                    die(f"missing exact artifact override: {override}")
                shutil.copy2(override, artifact_path)
            else:
                zip_pak_dir(package_dir, artifact_path)

            runtime, installed_size = inspect_zip_artifact(
                artifact_path, install_name, runtime_manifest_path
            )
            version = pkg.get("version") or runtime.get("pak_version")
            if not isinstance(version, str) or not version:
                die(f"{metadata_path}: package version must be a non-empty string")
            if version != runtime.get("pak_version"):
                die(
                    f"{artifact_path}: runtime pak_version "
                    f"{runtime.get('pak_version')!r} does not match Pak Rat "
                    f"version {version!r}"
                )
            app_versions.add(version)
            app_packages.append(
                {
                    "platform": "mlp1",
                    "runtime": "leaf",
                    "version": version,
                    "install_name": install_name,
                    "runtime_manifest_path": runtime_manifest_path,
                    "artifact": {
                        "url": base_url + f"artifacts/{artifact_name}",
                        "name": artifact_name,
                        "archive": "zip",
                        "size": artifact_path.stat().st_size,
                        "installed_size": installed_size,
                        "sha256": file_sha256(artifact_path),
                    },
                }
            )

        if len(app_versions) != 1:
            die(f"{metadata_path}: all MLP1 packages must use one app version")
        app_version = next(iter(app_versions))
        categories = meta.get("categories", [])
        if not isinstance(categories, list) or not all(
            isinstance(value, str) and value for value in categories
        ):
            die(f"{metadata_path}: categories must be a string array")
        apps.append(
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

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    storefront = {
        "schema": 1,
        "product": "pak-rat",
        "catalog_revision": "local-" + generated_at.replace(":", "").replace("-", ""),
        "generated_at": generated_at,
        "apps": apps,
    }

    storefront_path = feed_root / "storefront.json"
    storefront_path.write_text(json.dumps(storefront, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {storefront_path}")
    for app in apps:
        for pkg in app["packages"]:
            artifact = pkg["artifact"]
            print(
                f"  {app['id']} {artifact['name']} "
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
