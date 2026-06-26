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


def tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


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
    output_root = Path(args.output).resolve()
    feed_root = output_root / FEED_PREFIX
    artifacts_root = feed_root / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    sdlreader = find_sdlreader(args.sdlreader_dir)
    meta = load_json(sdlreader / "pakrat.json")
    root_nextui = load_json(sdlreader / "pak.json")

    compat = meta.get("compat", {})
    if compat.get("nextui_pak_json") != "pak.json":
        die("SDLReader pakrat.json must declare compat.nextui_pak_json = pak.json")
    if root_nextui.get("release_filename") != "SDLReader.pakz":
        die("SDLReader root pak.json no longer looks like the NextUI manifest")

    packages = meta.get("leaf", {}).get("packages", [])
    if not packages:
        die("pakrat.json has no leaf.packages entries")

    base_url = ensure_base_url(args.base_url)
    apps_packages = []
    app_version = ""

    for pkg in packages:
        platform = pkg.get("platform")
        if platform != "mlp1":
            print(f"pakrat-local-feed: skipping non-MLP1 package {platform!r}")
            continue

        build_command = pkg.get("build_command") or []
        if build_command and not args.skip_build:
            run_command([str(part) for part in build_command], sdlreader)

        package_dir = sdlreader / pkg.get("package_dir", "")
        artifact_name = pkg.get("artifact_name")
        if not artifact_name:
            die("leaf package missing artifact_name")
        artifact_path = artifacts_root / artifact_name
        zip_pak_dir(package_dir, artifact_path)

        runtime_manifest = package_dir / pkg.get("runtime_manifest_path", "pak.json")
        runtime = load_json(runtime_manifest)
        version = pkg.get("version") or runtime.get("pak_version")
        if version != runtime.get("pak_version"):
            die(
                f"{runtime_manifest} pak_version {runtime.get('pak_version')!r} "
                f"does not match Pak Rat version {version!r}"
            )

        app_version = version
        apps_packages.append(
            {
                "platform": platform,
                "runtime": "leaf",
                "version": version,
                "install_name": pkg.get("install_name", package_dir.name),
                "runtime_manifest_path": pkg.get("runtime_manifest_path", "pak.json"),
                "artifact": {
                    "url": base_url + f"artifacts/{artifact_name}",
                    "name": artifact_name,
                    "archive": "zip",
                    "size": artifact_path.stat().st_size,
                    "installed_size": tree_size(package_dir),
                    "sha256": file_sha256(artifact_path),
                },
            }
        )

    if not apps_packages:
        die("no local Pak Rat packages were generated")

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    storefront = {
        "schema": 1,
        "product": "pak-rat",
        "catalog_revision": "local-" + generated_at.replace(":", "").replace("-", ""),
        "generated_at": generated_at,
        "apps": [
            {
                "id": meta["id"],
                "name": meta["name"],
                "summary": meta["summary"],
                "description": meta.get("description", ""),
                "author": meta.get("author", ""),
                "repo_url": meta.get("repo_url", ""),
                "categories": meta.get("categories", []),
                "version": app_version,
                "packages": apps_packages,
            }
        ],
    }

    storefront_path = feed_root / "storefront.json"
    storefront_path.write_text(json.dumps(storefront, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {storefront_path}")
    for pkg in apps_packages:
        artifact = pkg["artifact"]
        print(f"  {artifact['name']} size={artifact['size']} sha256={artifact['sha256']}")
    return storefront_path


def adb_configure(args: argparse.Namespace, url: str) -> None:
    adb = ["adb"]
    serial = args.adb_serial or os.environ.get("ADB_SERIAL")
    if serial:
        adb += ["-s", serial]
    remote_state = args.remote_state_dir
    remote_file = remote_state.rstrip("/") + "/store/dev-catalog-url"
    shell = (
        f"mkdir -p {sh_quote(remote_state.rstrip('/') + '/store')} && "
        f"printf %s {sh_quote(url)} > {sh_quote(remote_file)} && "
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
    parser.add_argument("--sdlreader-dir", help="path to SDLReader-brick")
    parser.add_argument("--host", default="127.0.0.1", help="serve host")
    parser.add_argument("--port", type=int, default=8765, help="serve port")
    parser.add_argument("--base-url", help="catalog artifact base URL")
    parser.add_argument("--serve", action="store_true", help="serve after generating")
    parser.add_argument("--skip-build", action="store_true", help="use existing package dir")
    parser.add_argument("--adb-configure", action="store_true", help="write dev-catalog-url to an attached device")
    parser.add_argument("--adb-serial", help="ADB serial; defaults to ADB_SERIAL or adb default")
    parser.add_argument("--remote-state-dir", default="/mnt/sdcard/.umrk/mlp1", help="device UMRK_INTERNAL_DATA_PATH")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.base_url:
        host = default_lan_ip() if args.adb_configure else ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host)
        args.base_url = f"http://{host}:{args.port}/pakrat/v1/"

    build_storefront(args)
    if args.adb_configure:
        adb_configure(args, ensure_base_url(args.base_url))
    print(f"Catalog base URL: {ensure_base_url(args.base_url)}")
    if args.serve:
        serve(args)


if __name__ == "__main__":
    main()

