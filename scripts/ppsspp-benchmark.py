#!/usr/bin/env python3
"""Run a controlled PPSSPP Vulkan/GLES benchmark on an attached MLP1.

The harness launches PPSSPP through Jawaka so direct-DRM lifecycle and
performance-profile behavior are part of the measurement.  It temporarily
installs a known PPSSPP preset with the local debugger enabled, then restores
the exact pre-run configuration.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


LEAF_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = LEAF_ROOT.parent
PPSSPP_ROOT = WORKSPACE_ROOT / "PPSSPP-spruce"
DEFAULT_PRESET_ROOT = PPSSPP_ROOT / "output/mlp1/ppsspp/defaults"
DEFAULT_OUTPUT_ROOT = LEAF_ROOT / "build/benchmarks/ppsspp"
REMOTE_SOCKET = "/tmp/jawaka-runtime/jawakad.sock"
CORE_IDS = {"vulkan": "ppsspp", "gles": "ppsspp_gles"}


class BenchmarkError(RuntimeError):
    pass


def quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def run(
    command: list[str],
    *,
    check: bool = True,
    text: bool = True,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=text,
        env=env,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode(errors="replace").strip()
        stdout = result.stdout.strip() if text else result.stdout.decode(errors="replace").strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        raise BenchmarkError(f"{shlex.join(command)}: {detail}")
    return result


class Adb:
    def __init__(self, serial: str | None) -> None:
        if serial:
            self.serial = serial
        else:
            result = run(["adb", "devices"])
            self.serial = ""
            for line in result.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) >= 2 and fields[1] == "device":
                    self.serial = fields[0]
                    break
            if not self.serial:
                raise BenchmarkError("No online adb device found")
        self.prefix = ["adb", "-s", self.serial]
        run(self.prefix + ["get-state"])

    def command(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        text: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        return run(
            self.prefix + arguments,
            check=check,
            text=text,
            timeout=timeout,
        )

    def shell(
        self,
        script: str,
        *,
        check: bool = True,
        timeout: float | None = None,
    ) -> str:
        result = self.command(["shell", script], check=check, timeout=timeout)
        return result.stdout.replace("\r\n", "\n").rstrip("\r\n")

    def exec_out(self, arguments: list[str], *, check: bool = True) -> bytes:
        return self.command(["exec-out"] + arguments, check=check, text=False).stdout

    def push(self, local_path: Path, remote_path: str) -> None:
        self.command(["push", str(local_path), remote_path])

    def process_ids(self, name: str) -> list[int]:
        output = self.shell(f"pidof {quote(name)} 2>/dev/null || true")
        return [int(value) for value in output.split() if value.isdigit()]

    def process_snapshot(self) -> dict[str, list[int]]:
        return {
            name: self.process_ids(name)
            for name in (
                "loong_pangu",
                "jawaka-launcher",
                "jawaka-osd",
                "weston",
                "PPSSPPSDL",
            )
        }


class Logger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def replace_ini_values(text: str, section: str, values: dict[str, str]) -> str:
    """Replace or add keys in one INI section without rewriting other sections."""
    lines = text.splitlines()
    section_pattern = re.compile(r"^\s*\[\s*" + re.escape(section) + r"\s*\]\s*$", re.I)
    any_section_pattern = re.compile(r"^\s*\[[^]]+\]\s*$")
    start = next((i for i, line in enumerate(lines) if section_pattern.match(line)), None)

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {value}" for key, value in values.items())
        return "\n".join(lines) + "\n"

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if any_section_pattern.match(lines[index]):
            end = index
            break

    remaining = {key.lower(): (key, value) for key, value in values.items()}
    output = lines[: start + 1]
    key_pattern = re.compile(r"^\s*([^#;][^=]*?)\s*=")
    for line in lines[start + 1 : end]:
        match = key_pattern.match(line)
        lowered = match.group(1).strip().lower() if match else ""
        if lowered in remaining:
            key, value = remaining.pop(lowered)
            output.append(f"{key} = {value}")
        else:
            output.append(line)
    output.extend(f"{key} = {value}" for key, value in remaining.values())
    output.extend(lines[end:])
    return "\n".join(output) + "\n"


def ini_value(text: str, section: str, key: str) -> str | None:
    current = ""
    for line in text.splitlines():
        section_match = re.match(r"^\s*\[\s*([^]]+?)\s*\]\s*$", line)
        if section_match:
            current = section_match.group(1)
            continue
        if current.lower() != section.lower():
            continue
        key_match = re.match(r"^\s*([^#;][^=]*?)\s*=\s*(.*?)\s*$", line)
        if key_match and key_match.group(1).strip().lower() == key.lower():
            return key_match.group(2)
    return None


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def rounded(value: float | None, places: int = 3) -> float | None:
    return round(value, places) if value is not None else None


def numeric(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


class WebSocketClient:
    """Small RFC 6455 client sufficient for PPSSPP's JSON debugger."""

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.socket = socket.create_connection((host, port), timeout=timeout)
        self.socket.settimeout(timeout)
        self.buffer = bytearray()
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET /debugger HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: debugger.ppsspp.org\r\n"
            "\r\n"
        )
        self.socket.sendall(request.encode("ascii"))
        response = self._read_until(b"\r\n\r\n").decode("iso-8859-1")
        if not response.startswith("HTTP/1.1 101") and not response.startswith("HTTP/1.0 101"):
            raise BenchmarkError(f"PPSSPP debugger WebSocket rejected upgrade: {response.splitlines()[0]}")
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        headers = {}
        for line in response.split("\r\n")[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.lower()] = value.strip()
        if headers.get("sec-websocket-accept") != accept:
            raise BenchmarkError("PPSSPP debugger returned an invalid WebSocket accept key")

    def _receive(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise BenchmarkError("PPSSPP debugger WebSocket closed unexpectedly")
            self.buffer.extend(chunk)
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self.buffer:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise BenchmarkError("PPSSPP debugger closed during WebSocket handshake")
            self.buffer.extend(chunk)
        end = self.buffer.index(marker) + len(marker)
        data = bytes(self.buffer[:end])
        del self.buffer[:end]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.socket.sendall(header + masked)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._receive(2)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._receive(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._receive(8))[0]
        mask = self._receive(4) if second & 0x80 else b""
        payload = self._receive(length)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return final, opcode, payload

    def receive_text(self) -> str:
        fragments = bytearray()
        text_started = False
        while True:
            final, opcode, payload = self._read_frame()
            if opcode == 0x8:
                raise BenchmarkError("PPSSPP debugger WebSocket closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                fragments = bytearray(payload)
                text_started = True
            elif opcode == 0x0 and text_started:
                fragments.extend(payload)
            else:
                continue
            if final:
                return fragments.decode("utf-8")

    def request(
        self,
        event: str,
        ticket: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_object = {"event": event, "ticket": ticket}
        if parameters:
            request_object.update(parameters)
        self._send_frame(
            0x1,
            json.dumps(request_object, separators=(",", ":")).encode("utf-8"),
        )
        while True:
            response = json.loads(self.receive_text())
            if response.get("ticket") == ticket:
                if response.get("event") == "error":
                    raise BenchmarkError(
                        f"PPSSPP debugger error: {response.get('message', response)}"
                    )
                if response.get("event") == event:
                    return response

    def request_gpu_stats(self, ticket: str) -> dict[str, Any]:
        return self.request("gpu.stats.get", ticket)

    def close(self) -> None:
        try:
            self._send_frame(0x8, struct.pack("!H", 1000))
        except OSError:
            pass
        self.socket.close()


class BenchmarkSession:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.adb = Adb(args.serial or os.environ.get("ADB_SERIAL"))
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        output = Path(args.output) if args.output else (
            DEFAULT_OUTPUT_ROOT / f"{timestamp}-{args.core}-{args.preset}"
        )
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.log = Logger(self.output / "session.log")
        self.sdcard = ""
        self.remote_config = ""
        self.remote_backup = ""
        self.remote_state = ""
        self.config_prepared = False
        self.forward_active = False
        self.websocket: WebSocketClient | None = None
        self.pid: int | None = None
        self.samples: list[dict[str, Any]] = []
        self.frontend_before: dict[str, list[int]] = {}
        self.frontend_during: dict[str, list[int]] = {}
        self.frontend_after: dict[str, list[int]] = {}
        self.log_offsets: dict[str, int] = {}
        self.error: str | None = None
        self.effective_config = ""
        self.backend_evidence: dict[str, Any] = {}
        self.started_at = time.time()

    def resolve_sdcard(self) -> str:
        environment = os.environ.copy()
        environment.update(
            {
                "PLATFORM_ID": "mlp1",
                "REMOTE_SDCARD_PATH": self.args.remote_sd,
                "ADB_SERIAL": self.adb.serial,
            }
        )
        result = run(
            [str(LEAF_ROOT / "scripts/adb-resolve-umrk-sd.sh")],
            env=environment,
        )
        return result.stdout.strip()

    def ensure_preflight(self) -> None:
        self.sdcard = self.resolve_sdcard()
        self.log(f"Using adb device {self.adb.serial}; active SD is {self.sdcard}")
        if "'" in self.sdcard or "\n" in self.sdcard:
            raise BenchmarkError(f"Unsupported resolved SD path: {self.sdcard!r}")
        if not self.adb.shell(f"[ -f {quote(self.args.rom)} ] && echo yes") == "yes":
            raise BenchmarkError(f"ROM not found on device: {self.args.rom}")
        controller = (
            f"{self.sdcard}/.system/leaf/platforms/mlp1/launcher/bin/"
            "jawaka-platformctl"
        )
        checks = (
            f"[ -x {quote(controller)} ] && "
            f"[ -S {quote(REMOTE_SOCKET)} ] && echo yes"
        )
        if self.adb.shell(checks) != "yes":
            raise BenchmarkError("Jawaka controller or daemon socket is unavailable")
        running = self.adb.process_ids("PPSSPPSDL")
        if running and not self.args.replace_running:
            raise BenchmarkError(
                f"PPSSPP is already running (pid {running}); pass --replace-running to terminate it"
            )
        if running:
            self.log(f"Terminating pre-existing PPSSPP process(es): {running}")
            self.adb.shell("killall PPSSPPSDL 2>/dev/null || true")
            self.wait_process_gone(10.0)
            if self.adb.process_ids("PPSSPPSDL"):
                self.adb.shell("killall -KILL PPSSPPSDL 2>/dev/null || true")
                self.wait_process_gone(5.0)
        self.frontend_before = self.adb.process_snapshot()
        if not self.frontend_before["jawaka-launcher"]:
            raise BenchmarkError("Jawaka launcher is not active before benchmark")

    def recover_stale_config(self) -> None:
        command = f"""
set -eu
state={quote(self.remote_state)}
config={quote(self.remote_config)}
backup={quote(self.remote_backup)}
if [ -f "$state" ]; then
    previous="$(cat "$state" 2>/dev/null || true)"
    case "$previous" in
        existed=1)
            [ -f "$backup" ] || {{
                echo "stale PPSSPP benchmark backup is missing" >&2
                exit 1
            }}
            cp -p "$backup" "$config"
            ;;
        existed=0)
            rm -f "$config"
            ;;
        *)
            echo "invalid stale PPSSPP benchmark state" >&2
            exit 1
            ;;
    esac
    rm -f "$state" "$backup"
    sync
    echo recovered
fi
"""
        result = self.adb.shell(command)
        if result:
            self.log("Recovered PPSSPP configuration left by an interrupted benchmark")

    def prepare_config(self) -> None:
        config_dir = (
            f"{self.sdcard}/.userdata/mlp1/ppsspp/config/ppsspp/PSP/SYSTEM"
        )
        self.remote_config = f"{config_dir}/ppsspp.ini"
        self.remote_backup = f"{self.remote_config}.umrk-benchmark-backup"
        self.remote_state = f"{self.remote_config}.umrk-benchmark-state"
        self.adb.shell(f"mkdir -p {quote(config_dir)}")
        self.recover_stale_config()

        preset_path = Path(self.args.preset_root) / f"ppsspp-{self.args.preset}.ini"
        if not preset_path.is_file():
            raise BenchmarkError(f"PPSSPP preset not found: {preset_path}")
        preset = preset_path.read_text(encoding="utf-8")
        self.effective_config = replace_ini_values(
            preset,
            "General",
            {
                "RemoteISOPort": str(self.args.debug_port),
                "RemoteDebuggerOnStartup": "True",
                "RemoteDebuggerLocal": "True",
            },
        )
        (self.output / "effective.ini").write_text(
            self.effective_config,
            encoding="utf-8",
        )
        config_sha = hashlib.sha256(self.effective_config.encode("utf-8")).hexdigest()
        (self.output / "benchmark-overrides.json").write_text(
            json.dumps(
                {
                    "preset": self.args.preset,
                    "preset_path": str(preset_path),
                    "effective_config_sha256": config_sha,
                    "backend_command_line": self.args.core,
                    "debugger": {
                        "port": self.args.debug_port,
                        "on_startup": True,
                        "local": True,
                    },
                    "graphics": {
                        key: ini_value(self.effective_config, "Graphics", key)
                        for key in (
                            "GraphicsBackend",
                            "InternalResolution",
                            "FrameSkip",
                            "AutoFrameSkip",
                            "InflightFrames",
                            "RenderDuplicateFrames",
                        )
                    },
                    "cpu": {
                        key: ini_value(self.effective_config, "CPU", key)
                        for key in (
                            "CPUCore",
                            "FastMemoryAccess",
                            "CPUSpeed",
                        )
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        self.adb.shell(
            f"""
set -eu
config={quote(self.remote_config)}
backup={quote(self.remote_backup)}
state={quote(self.remote_state)}
if [ -e "$config" ]; then
    cp -p "$config" "$backup"
    printf 'existed=1\\n' >"$state"
else
    rm -f "$backup"
    printf 'existed=0\\n' >"$state"
fi
"""
        )
        self.config_prepared = True
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(self.effective_config)
            temporary = Path(handle.name)
        try:
            remote_temporary = f"{self.remote_config}.tmp"
            self.adb.push(temporary, remote_temporary)
            self.adb.shell(
                f"mv {quote(remote_temporary)} {quote(self.remote_config)} && sync"
            )
        finally:
            temporary.unlink(missing_ok=True)
        self.log(
            f"Installed controlled {self.args.preset} preset; original config is recoverable"
        )

    def restore_config(self) -> None:
        if not self.config_prepared:
            return
        self.adb.shell(
            f"""
set -eu
config={quote(self.remote_config)}
backup={quote(self.remote_backup)}
state={quote(self.remote_state)}
previous="$(cat "$state" 2>/dev/null || true)"
case "$previous" in
    existed=1)
        [ -f "$backup" ] || {{
            echo "PPSSPP benchmark backup is missing" >&2
            exit 1
        }}
        cp -p "$backup" "$config"
        ;;
    existed=0)
        rm -f "$config"
        ;;
    *)
        echo "PPSSPP benchmark state is missing or invalid" >&2
        exit 1
        ;;
esac
rm -f "$state" "$backup"
sync
"""
        )
        self.config_prepared = False
        self.log("Restored the pre-benchmark PPSSPP configuration")

    def remote_file_size(self, path: str) -> int:
        output = self.adb.shell(
            f"if [ -f {quote(path)} ]; then wc -c <{quote(path)}; else echo 0; fi"
        )
        return int(output.strip() or "0")

    def mark_log_offsets(self) -> None:
        paths = {
            "ppsspp.log": f"{self.sdcard}/.userdata/mlp1/logs/ppsspp.log",
            "umrk-launcher.log": (
                f"{self.sdcard}/.userdata/mlp1/logs/umrk-launcher.log"
            ),
        }
        self.log_offsets = {
            remote: self.remote_file_size(remote) for remote in paths.values()
        }

    def capture_log_slices(self) -> None:
        if not self.log_offsets:
            return
        paths = {
            "ppsspp.log": f"{self.sdcard}/.userdata/mlp1/logs/ppsspp.log",
            "umrk-launcher.log": (
                f"{self.sdcard}/.userdata/mlp1/logs/umrk-launcher.log"
            ),
        }
        for local_name, remote in paths.items():
            offset = self.log_offsets.get(remote, 0)
            content = self.adb.shell(
                f"if [ -f {quote(remote)} ]; then "
                f"tail -c +{offset + 1} {quote(remote)} 2>/dev/null || true; fi",
                check=False,
            )
            (self.output / local_name).write_text(content + ("\n" if content else ""), encoding="utf-8")

    def capture_device_identity(self) -> None:
        script = r"""
echo "serial=$(cat /sys/class/android_usb/android0/iSerial 2>/dev/null || true)"
echo "uname=$(uname -a)"
echo "buildroot=$(cat /etc/os-release 2>/dev/null | tr '\n' ' ')"
echo "meminfo:"
sed -n '1,24p' /proc/meminfo
echo "swap:"
cat /proc/swaps
echo "display:"
for connector in /sys/class/drm/card*-*; do
    [ -f "$connector/status" ] || continue
    printf '%s status=%s modes=' "$(basename "$connector")" "$(cat "$connector/status")"
    tr '\n' ',' <"$connector/modes" 2>/dev/null || true
    echo
done
echo "cpu:"
for policy in /sys/devices/system/cpu/cpufreq/policy*; do
    [ -d "$policy" ] || continue
    printf '%s governor=%s min=%s max=%s available=%s\n' \
        "$(basename "$policy")" \
        "$(cat "$policy/scaling_governor" 2>/dev/null)" \
        "$(cat "$policy/cpuinfo_min_freq" 2>/dev/null)" \
        "$(cat "$policy/cpuinfo_max_freq" 2>/dev/null)" \
        "$(cat "$policy/scaling_available_frequencies" 2>/dev/null)"
done
echo "devfreq:"
for node in /sys/class/devfreq/*; do
    [ -d "$node" ] || continue
    printf '%s governor=%s min=%s max=%s available=%s\n' \
        "$(basename "$node")" \
        "$(cat "$node/governor" 2>/dev/null)" \
        "$(cat "$node/min_freq" 2>/dev/null)" \
        "$(cat "$node/max_freq" 2>/dev/null)" \
        "$(cat "$node/available_frequencies" 2>/dev/null)"
done
echo "thermal:"
for zone in /sys/class/thermal/thermal_zone*; do
    [ -d "$zone" ] || continue
    printf '%s type=%s temp=%s\n' \
        "$(basename "$zone")" \
        "$(cat "$zone/type" 2>/dev/null)" \
        "$(cat "$zone/temp" 2>/dev/null)"
done
"""
        (self.output / "device.txt").write_text(
            self.adb.shell(script) + "\n",
            encoding="utf-8",
        )

    def launch(self) -> None:
        controller = (
            f"{self.sdcard}/.system/leaf/platforms/mlp1/launcher/bin/"
            "jawaka-platformctl"
        )
        request = json.dumps(
            {
                "type": "launch-game",
                "system": "PSP",
                "rom_path": self.args.rom,
                "core_id": CORE_IDS[self.args.core],
            },
            separators=(",", ":"),
        )
        response = self.adb.shell(
            f"{quote(controller)} --socket {quote(REMOTE_SOCKET)} "
            f"request {quote(request)}"
        )
        try:
            response_object = json.loads(response)
        except json.JSONDecodeError as error:
            raise BenchmarkError(f"Jawaka returned invalid launch response: {response}") from error
        if response_object.get("type") != "ok":
            raise BenchmarkError(
                f"Jawaka rejected {self.args.core} launch: "
                f"{response_object.get('message', response)}"
            )
        self.log(f"Jawaka accepted {self.args.core} launch: {response}")
        launcher_pids = self.adb.process_ids("jawaka-launcher")
        if launcher_pids:
            self.adb.shell(
                "kill -KILL " + " ".join(str(pid) for pid in launcher_pids)
            )
            self.log(
                "Closed the launcher process so jawakad can enter the requested game"
            )

        deadline = time.monotonic() + self.args.startup_timeout
        while time.monotonic() < deadline:
            pids = self.adb.process_ids("PPSSPPSDL")
            if pids:
                self.pid = pids[0]
                self.log(f"PPSSPP started as pid {self.pid}")
                return
            time.sleep(0.5)
        raise BenchmarkError("Timed out waiting for PPSSPP to start")

    def wait_process_gone(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.adb.process_ids("PPSSPPSDL"):
                return True
            time.sleep(0.25)
        return not self.adb.process_ids("PPSSPPSDL")

    def process_alive(self) -> bool:
        return bool(self.pid and self.pid in self.adb.process_ids("PPSSPPSDL"))

    def capture_backend_evidence(self) -> None:
        if not self.pid:
            return
        command_line = self.adb.shell(
            f"tr '\\000' ' ' </proc/{self.pid}/cmdline 2>/dev/null || true"
        )
        mappings = self.adb.shell(
            f"grep -E 'lib(vulkan|mali|GLES|EGL|SDL)' "
            f"/proc/{self.pid}/maps 2>/dev/null | "
            "awk '{print $NF}' | sort -u || true"
        ).splitlines()
        self.backend_evidence = {
            "command_line": command_line,
            "graphics_mappings": mappings,
        }
        (self.output / "backend.json").write_text(
            json.dumps(self.backend_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def connect_debugger(self) -> None:
        self.adb.command(
            ["forward", "--remove", f"tcp:{self.args.debug_port}"],
            check=False,
        )
        self.adb.command(
            [
                "forward",
                f"tcp:{self.args.debug_port}",
                f"tcp:{self.args.debug_port}",
            ]
        )
        self.forward_active = True
        deadline = time.monotonic() + self.args.debugger_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if not self.process_alive():
                raise BenchmarkError("PPSSPP exited before debugger connected")
            candidate: WebSocketClient | None = None
            try:
                candidate = WebSocketClient(
                    "127.0.0.1",
                    self.args.debug_port,
                    timeout=min(5.0, self.args.debugger_timeout),
                )
                candidate.request(
                    "version",
                    "harness-version",
                    {"name": "UMRK PPSSPP benchmark", "version": "1"},
                )
                game_status = candidate.request("game.status", "harness-game-status")
                if not game_status.get("game"):
                    candidate.close()
                    time.sleep(0.5)
                    continue
                self.websocket = candidate
                self.log("Connected to PPSSPP GPU statistics debugger")
                return
            except (OSError, BenchmarkError) as error:
                last_error = error
                if candidate:
                    candidate.close()
                time.sleep(0.5)
        raise BenchmarkError(f"Timed out connecting to PPSSPP debugger: {last_error}")

    def telemetry(self) -> dict[str, Any]:
        if not self.pid:
            raise BenchmarkError("Cannot sample telemetry without a PPSSPP pid")
        script = f"""
pid={self.pid}
[ -d "/proc/$pid" ] || exit 44
cpu_cur=0
for node in /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq; do
    [ -f "$node" ] || continue
    value="$(cat "$node" 2>/dev/null || echo 0)"
    [ "$value" -gt "$cpu_cur" ] 2>/dev/null && cpu_cur="$value"
done
echo "cpu_cur_khz=$cpu_cur"
echo "gpu_cur_hz=$(cat /sys/class/devfreq/fde60000.gpu/cur_freq 2>/dev/null || echo 0)"
echo "gpu_load=$(cat /sys/class/devfreq/fde60000.gpu/load 2>/dev/null || echo unknown)"
echo "gpu_governor=$(cat /sys/class/devfreq/fde60000.gpu/governor 2>/dev/null || echo unknown)"
echo "dmc_cur_hz=$(cat /sys/class/devfreq/dmc/cur_freq 2>/dev/null || echo 0)"
echo "dmc_load=$(cat /sys/class/devfreq/dmc/load 2>/dev/null || echo unknown)"
echo "dmc_governor=$(cat /sys/class/devfreq/dmc/governor 2>/dev/null || echo unknown)"
echo "proc_ticks=$(awk '{{print $14 + $15}}' /proc/$pid/stat)"
sed -n \
    -e 's/^VmRSS:[[:space:]]*/proc_rss_kb=/p' \
    -e 's/^VmSize:[[:space:]]*/proc_vmsize_kb=/p' \
    -e 's/^VmSwap:[[:space:]]*/proc_swap_kb=/p' \
    /proc/$pid/status | sed 's/[[:space:]]*kB$//'
sed -n \
    -e 's/^MemAvailable:[[:space:]]*/mem_available_kb=/p' \
    -e 's/^SwapFree:[[:space:]]*/swap_free_kb=/p' \
    /proc/meminfo | sed 's/[[:space:]]*kB$//'
for zone in /sys/class/thermal/thermal_zone*; do
    [ -d "$zone" ] || continue
    name="$(tr -d '\n' <"$zone/type" 2>/dev/null | tr -c 'A-Za-z0-9_' '_')"
    echo "temp_${{name}}_millic=$(cat "$zone/temp" 2>/dev/null || echo 0)"
done
"""
        output = self.adb.shell(script)
        result: dict[str, Any] = {}
        for line in output.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key] = numeric(value)
        load_match = re.match(r"(\d+)@(\d+)", str(result.get("gpu_load", "")))
        if load_match:
            result["gpu_load_percent"] = int(load_match.group(1))
            result["gpu_load_reported_hz"] = int(load_match.group(2))
        dmc_match = re.match(r"(\d+)@(\d+)", str(result.get("dmc_load", "")))
        if dmc_match:
            result["dmc_load_percent"] = int(dmc_match.group(1))
            result["dmc_load_reported_hz"] = int(dmc_match.group(2))
        return result

    def warm_up(self) -> None:
        self.log(f"Warming up for {self.args.warmup:.1f} seconds")
        deadline = time.monotonic() + self.args.warmup
        while time.monotonic() < deadline:
            if not self.process_alive():
                raise BenchmarkError("PPSSPP exited during warm-up")
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    def sample(self) -> None:
        if not self.websocket:
            raise BenchmarkError("PPSSPP debugger is not connected")
        sample_file = self.output / "samples.jsonl"
        measurement_started = time.monotonic()
        deadline = measurement_started + self.args.duration
        next_sample = measurement_started
        previous_ticks: int | None = None
        previous_time: float | None = None
        index = 0
        with sample_file.open("w", encoding="utf-8") as handle:
            while time.monotonic() < deadline:
                if not self.process_alive():
                    raise BenchmarkError("PPSSPP exited during measurement")
                now = time.monotonic()
                if now < next_sample:
                    time.sleep(next_sample - now)
                if index > 0 and time.monotonic() >= deadline:
                    break
                requested_at = time.monotonic()
                stats = self.websocket.request_gpu_stats(f"sample-{index}")
                telemetry = self.telemetry()
                current_ticks = int(telemetry.get("proc_ticks", 0))
                if previous_ticks is not None and previous_time is not None:
                    elapsed = requested_at - previous_time
                    if elapsed > 0:
                        telemetry["proc_cpu_percent"] = (
                            (current_ticks - previous_ticks)
                            / self.args.clock_ticks
                            / elapsed
                            * 100.0
                        )
                previous_ticks = current_ticks
                previous_time = requested_at
                record = {
                    "index": index,
                    "elapsed_seconds": requested_at - measurement_started,
                    "host_time": time.time(),
                    "gpu_stats": stats,
                    "telemetry": telemetry,
                }
                self.samples.append(record)
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                handle.flush()
                fps = stats.get("fps", {}).get("actual")
                vps = stats.get("vblanksPerSecond", {}).get("actual")
                self.log(
                    f"sample {index + 1}: rendered={fps} fps, emulation={vps} vblank/s, "
                    f"GPU={telemetry.get('gpu_load', '?')}"
                )
                index += 1
                next_sample += self.args.interval
                if next_sample < time.monotonic() - self.args.interval:
                    next_sample = time.monotonic()
        if not self.samples:
            raise BenchmarkError("Measurement window produced no samples")

    def terminate_ppsspp(self) -> None:
        pids = self.adb.process_ids("PPSSPPSDL")
        if not pids:
            return
        signal = "-KILL" if self.args.exit_signal == "KILL" else "-TERM"
        self.log(f"Terminating PPSSPP with SIG{self.args.exit_signal}: {pids}")
        self.adb.shell(f"kill {signal} " + " ".join(str(pid) for pid in pids), check=False)
        if not self.wait_process_gone(10.0):
            remaining = self.adb.process_ids("PPSSPPSDL")
            self.log(f"PPSSPP did not exit promptly; forcing SIGKILL: {remaining}")
            self.adb.shell(
                "kill -KILL " + " ".join(str(pid) for pid in remaining),
                check=False,
            )
            self.wait_process_gone(5.0)

    def wait_frontend(self, timeout: float = 30.0) -> bool:
        required = [
            name
            for name in ("jawaka-launcher", "jawaka-osd", "weston")
            if self.frontend_before.get(name)
        ]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.adb.process_snapshot()
            socket_ready = (
                self.adb.shell(f"[ -S {quote(REMOTE_SOCKET)} ] && echo yes") == "yes"
            )
            if socket_ready and all(snapshot[name] for name in required):
                self.frontend_after = snapshot
                return True
            time.sleep(0.5)
        self.frontend_after = self.adb.process_snapshot()
        return False

    def close_debugger(self) -> None:
        if self.websocket:
            self.websocket.close()
            self.websocket = None
        if self.forward_active:
            self.adb.command(
                ["forward", "--remove", f"tcp:{self.args.debug_port}"],
                check=False,
            )
            self.forward_active = False

    def make_summary(self, frontend_restored: bool) -> dict[str, Any]:
        fps_values = [
            float(item["gpu_stats"]["fps"]["actual"])
            for item in self.samples
            if item.get("gpu_stats", {}).get("fps", {}).get("actual") is not None
        ]
        vps_values = [
            float(item["gpu_stats"]["vblanksPerSecond"]["actual"])
            for item in self.samples
            if item.get("gpu_stats", {})
            .get("vblanksPerSecond", {})
            .get("actual")
            is not None
        ]
        target_values = [
            float(item["gpu_stats"]["vblanksPerSecond"]["target"])
            for item in self.samples
            if item.get("gpu_stats", {})
            .get("vblanksPerSecond", {})
            .get("target")
        ]
        target_vps = statistics.median(target_values) if target_values else 60.0 / 1.001
        speed_values = [value / target_vps * 100.0 for value in vps_values]
        final_frames = []
        if self.samples:
            final_frames = self.samples[-1]["gpu_stats"].get("timing", {}).get("frames", [])
        frame_ms = [
            float(value) * 1000.0
            for value in final_frames
            if isinstance(value, (int, float)) and 0.0 < float(value) < 2.0
        ]
        telemetry = [item.get("telemetry", {}) for item in self.samples]

        def values_for(key: str) -> list[float]:
            return [
                float(item[key])
                for item in telemetry
                if isinstance(item.get(key), (int, float))
            ]

        temperatures: dict[str, dict[str, float | None]] = {}
        temperature_keys = sorted(
            {
                key
                for item in telemetry
                for key in item
                if key.startswith("temp_") and key.endswith("_millic")
            }
        )
        for key in temperature_keys:
            values = [value / 1000.0 for value in values_for(key)]
            temperatures[key.removesuffix("_millic")] = {
                "median_c": rounded(statistics.median(values) if values else None),
                "max_c": rounded(max(values) if values else None),
            }

        expected_backend_argument = f"--graphics={self.args.core}"
        command_line = str(self.backend_evidence.get("command_line", ""))
        mappings = self.backend_evidence.get("graphics_mappings", [])
        gpu_info = [
            str(item.get("gpu_stats", {}).get("info", "")) for item in self.samples
        ]
        staged_vulkan_driver_observed = any(
            "/runtime/graphics/vulkan/rk3566-g52-g29p1/lib/libmali.so.1"
            in mapping
            for mapping in mappings
        )
        system_gles_runtime_observed = (
            any("/usr/lib/libSDL2-" in mapping for mapping in mappings)
            and any("/usr/lib/libmali.so" in mapping for mapping in mappings)
        )
        stats_backend_observed = (
            any("Pipelines loaded:" in info for info in gpu_info)
            if self.args.core == "vulkan"
            else any("Programs loaded:" in info for info in gpu_info)
        )
        backend_runtime_observed = (
            staged_vulkan_driver_observed
            if self.args.core == "vulkan"
            else system_gles_runtime_observed
        )
        direct_drm_expected = self.args.core == "vulkan"
        weston_before = bool(self.frontend_before.get("weston"))
        weston_during = bool(self.frontend_during.get("weston"))
        direct_drm_observed = (
            weston_before and not weston_during
            if direct_drm_expected
            else weston_before and weston_during
        )

        return {
            "schema_version": 1,
            "status": "failed" if self.error else "completed",
            "error": self.error,
            "device_serial": self.adb.serial,
            "sdcard_path": self.sdcard,
            "rom_path": self.args.rom,
            "core": self.args.core,
            "core_id": CORE_IDS[self.args.core],
            "preset": self.args.preset,
            "warmup_seconds": self.args.warmup,
            "measurement_seconds": self.args.duration,
            "sample_interval_seconds": self.args.interval,
            "sample_count": len(self.samples),
            "exit_signal": f"SIG{self.args.exit_signal}",
            "started_unix": self.started_at,
            "finished_unix": time.time(),
            "ppsspp": {
                "rendered_fps": {
                    "median": rounded(statistics.median(fps_values) if fps_values else None),
                    "min": rounded(min(fps_values) if fps_values else None),
                    "p05": rounded(percentile(fps_values, 5)),
                },
                "vblanks_per_second": {
                    "target": rounded(target_vps),
                    "median": rounded(statistics.median(vps_values) if vps_values else None),
                    "min": rounded(min(vps_values) if vps_values else None),
                    "p05": rounded(percentile(vps_values, 5)),
                },
                "emulation_speed_percent": {
                    "median": rounded(statistics.median(speed_values) if speed_values else None),
                    "min": rounded(min(speed_values) if speed_values else None),
                    "p05": rounded(percentile(speed_values, 5)),
                },
                "final_sample_frame_history_ms": {
                    "count": len(frame_ms),
                    "median": rounded(statistics.median(frame_ms) if frame_ms else None),
                    "p95": rounded(percentile(frame_ms, 95)),
                    "p99": rounded(percentile(frame_ms, 99)),
                    "max": rounded(max(frame_ms) if frame_ms else None),
                },
            },
            "device": {
                "cpu_frequency_khz": {
                    "median": rounded(
                        statistics.median(values_for("cpu_cur_khz"))
                        if values_for("cpu_cur_khz")
                        else None
                    ),
                    "min": rounded(
                        min(values_for("cpu_cur_khz"))
                        if values_for("cpu_cur_khz")
                        else None
                    ),
                },
                "gpu_frequency_hz": {
                    "median": rounded(
                        statistics.median(values_for("gpu_cur_hz"))
                        if values_for("gpu_cur_hz")
                        else None
                    ),
                    "min": rounded(
                        min(values_for("gpu_cur_hz"))
                        if values_for("gpu_cur_hz")
                        else None
                    ),
                },
                "gpu_load_percent": {
                    "median": rounded(
                        statistics.median(values_for("gpu_load_percent"))
                        if values_for("gpu_load_percent")
                        else None
                    ),
                    "max": rounded(
                        max(values_for("gpu_load_percent"))
                        if values_for("gpu_load_percent")
                        else None
                    ),
                },
                "dmc_frequency_hz": {
                    "median": rounded(
                        statistics.median(values_for("dmc_cur_hz"))
                        if values_for("dmc_cur_hz")
                        else None
                    ),
                },
                "process_cpu_percent": {
                    "median": rounded(
                        statistics.median(values_for("proc_cpu_percent"))
                        if values_for("proc_cpu_percent")
                        else None
                    ),
                    "max": rounded(
                        max(values_for("proc_cpu_percent"))
                        if values_for("proc_cpu_percent")
                        else None
                    ),
                },
                "process_rss_kb": {
                    "median": rounded(
                        statistics.median(values_for("proc_rss_kb"))
                        if values_for("proc_rss_kb")
                        else None
                    ),
                    "max": rounded(
                        max(values_for("proc_rss_kb"))
                        if values_for("proc_rss_kb")
                        else None
                    ),
                },
                "temperatures": temperatures,
            },
            "backend_evidence": {
                **self.backend_evidence,
                "expected_argument": expected_backend_argument,
                "argument_observed": expected_backend_argument in command_line,
                "vulkan_loader_observed": any(
                    "libvulkan" in mapping for mapping in mappings
                ),
                "mali_driver_observed": any("libmali" in mapping for mapping in mappings),
                "staged_vulkan_driver_observed": staged_vulkan_driver_observed,
                "system_gles_runtime_observed": system_gles_runtime_observed,
                "stats_backend_observed": stats_backend_observed,
                "backend_runtime_observed": backend_runtime_observed,
            },
            "lifecycle": {
                "direct_drm_expected": direct_drm_expected,
                "display_lifecycle_observed": direct_drm_observed,
                "frontend_restored": frontend_restored,
                "before": self.frontend_before,
                "during": self.frontend_during,
                "after": self.frontend_after,
            },
        }

    def run(self) -> int:
        frontend_restored = False
        try:
            self.ensure_preflight()
            self.capture_device_identity()
            self.prepare_config()
            self.mark_log_offsets()
            self.launch()
            self.frontend_during = self.adb.process_snapshot()
            self.capture_backend_evidence()
            self.connect_debugger()
            self.warm_up()
            self.sample()
        except (BenchmarkError, OSError, ValueError, json.JSONDecodeError) as error:
            self.error = str(error)
            self.log(f"ERROR: {self.error}")
        except KeyboardInterrupt:
            self.error = "interrupted"
            self.log("Interrupted; restoring PPSSPP and frontend state")
        finally:
            self.close_debugger()
            self.terminate_ppsspp()
            if self.frontend_before:
                frontend_restored = self.wait_frontend()
                self.log(
                    "Frontend restoration passed"
                    if frontend_restored
                    else "Frontend restoration timed out"
                )
            try:
                self.capture_log_slices()
            except (BenchmarkError, OSError) as error:
                self.log(f"Could not capture log slices: {error}")
            try:
                self.restore_config()
            except (BenchmarkError, OSError) as error:
                self.error = self.error or f"config restoration failed: {error}"
                self.log(f"ERROR: config restoration failed: {error}")

        summary = self.make_summary(frontend_restored)
        if not self.error and not frontend_restored:
            self.error = "frontend restoration timed out"
        if not self.error and not summary["backend_evidence"]["argument_observed"]:
            self.error = "requested graphics backend was not observed on the command line"
        if not self.error and not summary["backend_evidence"]["backend_runtime_observed"]:
            self.error = "requested graphics runtime was not observed in the process"
        if not self.error and not summary["backend_evidence"]["stats_backend_observed"]:
            self.error = "PPSSPP GPU stats did not confirm the requested backend"
        if not self.error and not summary["lifecycle"]["display_lifecycle_observed"]:
            self.error = "expected display-server lifecycle was not observed"
        if self.error and summary["error"] != self.error:
            self.log(f"ERROR: {self.error}")
            summary = self.make_summary(frontend_restored)
        (self.output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.log(f"Evidence written to {self.output}")
        if self.error:
            return 1
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark PPSSPP through Jawaka on an attached MLP1 and preserve "
            "GPU, thermal, memory, and lifecycle evidence."
        )
    )
    parser.add_argument("--rom", required=True, help="Absolute ROM path on the device")
    parser.add_argument(
        "--core",
        choices=tuple(CORE_IDS),
        default="vulkan",
        help="PPSSPP graphics backend to request (default: vulkan)",
    )
    parser.add_argument(
        "--preset",
        choices=("balanced", "performance"),
        default="balanced",
        help="Controlled PPSSPP preset (default: balanced)",
    )
    parser.add_argument(
        "--preset-root",
        default=str(DEFAULT_PRESET_ROOT),
        help="Directory containing ppsspp-balanced.ini and ppsspp-performance.ini",
    )
    parser.add_argument("--warmup", type=float, default=15.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--debugger-timeout", type=float, default=30.0)
    parser.add_argument("--debug-port", type=int, default=28000)
    parser.add_argument(
        "--exit-signal",
        choices=("TERM", "KILL"),
        default="TERM",
        help="Signal used after measurement; KILL exercises crash recovery",
    )
    parser.add_argument(
        "--replace-running",
        action="store_true",
        help="Terminate an already-running PPSSPP before starting",
    )
    parser.add_argument(
        "--remote-sd",
        default=os.environ.get("REMOTE_SDCARD_PATH", "auto"),
        help="Device SD mount or auto (default: auto)",
    )
    parser.add_argument("--serial", help="ADB device serial (defaults to ADB_SERIAL)")
    parser.add_argument("--output", help="New evidence directory")
    parser.add_argument(
        "--clock-ticks",
        type=float,
        default=100.0,
        help="Device USER_HZ for process CPU calculation (default: 100)",
    )
    args = parser.parse_args()
    if args.warmup < 0 or args.duration <= 0 or args.interval <= 0:
        parser.error("warmup must be >= 0; duration and interval must be > 0")
    if not 1 <= args.debug_port <= 65535:
        parser.error("debug port must be in 1..65535")
    return args


def main() -> int:
    try:
        return BenchmarkSession(parse_args()).run()
    except (BenchmarkError, FileExistsError) as error:
        print(f"ppsspp-benchmark: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
