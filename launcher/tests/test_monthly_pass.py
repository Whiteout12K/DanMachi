"""Guard the exact monthly-only native eligibility change and full restoration."""

# Regression checks for monthly pass.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import hashlib
import json
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MonthlyPassPatch(unittest.TestCase):
    def test_monthly_gate_patch_preserves_the_guarded_native_build(self):
        record = json.loads((ROOT / "launcher/compatibility-patches.json").read_text())
        gates = [
            c
            for c in record["changes"]
            if int(c["offset"], 16) in (0x235EE34, 0x235EC50)
        ]
        self.assertEqual(len(gates), 2)
        for gate in gates:
            self.assertEqual(gate["after"], "20008052c0035fd6")
        with zipfile.ZipFile(ROOT / "offline/apks/config.arm64_v8a.apk") as archive:
            native = archive.read("lib/arm64-v8a/libapp.so")
        for gate in gates:
            offset = int(gate["offset"], 16)
            self.assertEqual(native[offset : offset + 8], bytes.fromhex(gate["before"]))
        path = next(
            (ROOT / "DanMachi MF.app/Contents/Client/android/data/app").glob(
                "*/com.eu.danmore-*/lib/arm64/libapp.so"
            )
        )
        patched = path.read_bytes()
        self.assertEqual(
            hashlib.sha256(patched).hexdigest(), record["patched_native_sha256"]
        )
        original = bytearray(patched)
        for change in reversed(record["changes"]):
            off = int(change["offset"], 16)
            after = bytes.fromhex(change["after"])
            before = bytes.fromhex(change["before"])
            self.assertEqual(original[off : off + len(after)], after)
            original[off : off + len(after)] = before
        self.assertEqual(
            hashlib.sha256(original).hexdigest(), record["input_native_sha256"]
        )
