"""Guard the exact To Title callback and its nonreturning reload status."""

# Regression checks for title return.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import json
import struct
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TitleReturnPatch(unittest.TestCase):
    def test_confirm_callback_exits_to_launcher_without_teardown(self):
        record = json.loads((ROOT / "launcher/compatibility-patches.json").read_text())
        change = next(c for c in record["changes"] if int(c["offset"], 16) == 0x1CE3FCC)
        with zipfile.ZipFile(ROOT / "offline/apks/config.arm64_v8a.apk") as archive:
            original = archive.read("lib/arm64-v8a/libapp.so")
        self.assertEqual(original[0x1CE3FCC:0x1CE3FD4], bytes.fromhex(change["before"]))
        status, branch = struct.unpack("<II", bytes.fromhex(change["after"]))
        self.assertEqual(status, 0x52800960)  # mov w0, #75
        self.assertEqual(branch & 0xFC000000, 0x14000000)  # b, not bl
        delta = branch & 0x3FFFFFF
        if delta & 0x2000000:
            delta -= 0x4000000
        self.assertEqual(0x1CE3FD0 + delta * 4, 0xD62DF0)
        # Verified original _exit PLT entry, including its GOT load.
        self.assertEqual(
            original[0xD62DF0:0xD62E00].hex(), "f0ad01f0111240f91082009120021fd6"
        )
