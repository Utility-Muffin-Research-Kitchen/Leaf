#!/usr/bin/env python3
"""Check FFmpeg reuse decisions against the RetroArch build manifest."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).with_name("validate-mlp1-retroarch-build.py")


class RetroarchReuseTests(unittest.TestCase):
    def test_required_ffmpeg_stamp_controls_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            binary = root / "retroarch"
            manifest_path = root / "build-manifest.json"
            stamp = root / "input-stamp.json"
            binary.write_bytes(b"retroarch fixture")
            stamp.write_text('{"source_lock_sha256":"test"}\n', encoding="utf-8")
            manifest = {
                "configure_flags": ["--enable-ssl", "--enable-ffmpeg"],
                "patch_controls": {"MLP1_PATCH_SET": "one,two"},
                "ffmpeg_input_stamp_sha256": hashlib.sha256(stamp.read_bytes()).hexdigest(),
            }

            def check() -> subprocess.CompletedProcess[str]:
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                return subprocess.run([
                    sys.executable, str(TOOL), "--binary", str(binary),
                    "--manifest", str(manifest_path), "--expected-patch-set", "one,two",
                    "--require-ffmpeg", "--ffmpeg-stamp", str(stamp),
                ], text=True, capture_output=True, check=False)

            self.assertEqual(check().returncode, 0)
            manifest["configure_flags"] = ["--enable-ssl", "--disable-ffmpeg"]
            self.assertIn("recording support", check().stderr)
            manifest["configure_flags"] = ["--enable-ssl", "--enable-ffmpeg"]
            stamp.write_text('{"source_lock_sha256":"changed"}\n', encoding="utf-8")
            self.assertIn("stamp does not match", check().stderr)


if __name__ == "__main__":
    unittest.main()
