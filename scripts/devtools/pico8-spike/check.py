#!/usr/bin/env python3
"""Synthetic checks for the private spike; no purchased files or device needed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


with tempfile.TemporaryDirectory(prefix="pico8-spike-") as tmp:
    base = Path(tmp)
    trace = base / "trace.json"
    capture = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ['TRACE']).write_text(json.dumps({
    'args': sys.argv[1:], 'libs': os.environ.get('LD_LIBRARY_PATH')}))
sys.exit(int(os.environ.get('CAPTURE_EXIT', '0')))
"""
    cards = [base / "card one", base / "card two"]
    for card in cards:
        executable(card / "BIOS/PICO8/pico8_64", capture)
        (card / "BIOS/PICO8/pico8.dat").write_text("synthetic")
        (card / "Roms/PICO8").mkdir(parents=True)
    runtime = base / "runtime"
    spike = runtime / "pico8-spike"
    spike.mkdir(parents=True)
    executable(base / "bin/mountpoint", '#!/bin/sh\nexit "${MOUNT_EXIT:-0}"\n')
    env = dict(os.environ, PLATFORM="mlp1", TRACE=str(trace),
               UMRK_RUNTIME_PATH=str(runtime),
               PATH=str(base / "bin") + os.pathsep + os.environ["PATH"])

    def sources(primary, secondary):
        for key, suffix in (("SDCARD", ""), ("BIOS", "BIOS"),
                            ("ROMS", "Roms"), ("USERDATA", ".userdata/mlp1")):
            roots = [str(card / suffix) for card in (primary, secondary)]
            env[key + "_PATH"] = roots[0]
            env[key + "_PATHS"] = ":".join(roots)
        env["RECORDINGS_PATH"] = str(primary / "Recordings")

    def launch(expected=0, **overrides):
        trace.unlink(missing_ok=True)
        result = subprocess.run(["sh", str(HERE / "launch.sh")],
                                env=dict(env, **overrides), capture_output=True)
        assert result.returncode == expected, result.stderr.decode()
        return json.loads(trace.read_text()) if trace.exists() else None

    for primary, secondary in (cards, cards[::-1]):
        sources(primary, secondary)
        (spike / "cart-path").unlink(missing_ok=True)
        args = launch()["args"]
        assert args[args.index("-home") + 1] == str(primary / ".userdata/mlp1/pico8") + "/"
        assert args[args.index("-root_path") + 1] == str(primary / "Roms/PICO8") + "/"
        assert args[args.index("-desktop") + 1] == str(primary / "Recordings/PICO8") + "/"
        assert args[-1] == "-splore"
        for source in (primary, secondary):
            cart = source / "Roms/PICO8/cart with spaces.p8.png"
            cart.write_text("synthetic")
            (spike / "cart-path").write_text(str(cart) + "\n")
            args = launch()["args"]
            assert args[-2:] == ["-run", str(cart)]
            assert args[args.index("-root_path") + 1] == str(source / "Roms/PICO8") + "/"
            assert args[args.index("-home") + 1] == str(primary / ".userdata/mlp1/pico8") + "/"
            assert args[args.index("-desktop") + 1] == str(primary / "Recordings/PICO8") + "/"
        assert launch(expected=1, MOUNT_EXIT="1") is None
        assert launch(expected=1, BIOS_PATH=str(secondary / "BIOS")) is None
        assert launch(expected=1, USERDATA_PATH=str(secondary / ".userdata/mlp1")) is None
        assert launch(expected=1, PLATFORM="mac") is None
        # A native exit is preserved, never interpreted as a fallback request.
        assert launch(expected=23, CAPTURE_EXIT="23") is not None
    (spike / "cart-path").write_text("/unconfigured/cart.p8\n")
    assert launch(expected=1) is None
    (spike / "cart-path").unlink()
    (primary / "BIOS/PICO8/pico8.dat").unlink()
    assert launch(expected=1) is None

    executable(spike / "curl", capture)
    for post in (None, str(base / "post body.txt")):
        args = ["https://example.invalid/cart", "-q", "-O", str(base / "cart file.png")]
        if post:
            args.append("--post-file=" + post)
        subprocess.run(["sh", str(HERE / "wget"), *args], env=env, check=True)
        result = json.loads(trace.read_text())
        assert result["libs"] == str(spike / "lib")
        assert "--cacert" in result["args"]
        assert "--insecure" not in result["args"]
        assert result["args"][-2:] == ["--", "https://example.invalid/cart"]
        if post:
            assert result["args"][result["args"].index("--data-binary") + 1] == "@" + post
    for args in (["--no-check-certificate"], ["-O"], [],
                 ["https://a.invalid", "https://b.invalid", "-O", "out"]):
        trace.unlink(missing_ok=True)
        result = subprocess.run(["sh", str(HERE / "wget"), *args], env=env, capture_output=True)
        assert result.returncode != 0 and not trace.exists()
print("PASS: swapped source roots, secondary carts, primary state, failure/exit paths, HTTPS adapter")
