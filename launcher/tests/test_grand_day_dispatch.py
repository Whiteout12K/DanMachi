# Regression checks for grand day dispatch.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import hashlib, json, struct, sys, unittest, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
import grand_day_stage_list as h


class GrandDayDispatchTest(unittest.TestCase):
    def test_entry_stage_belongs_to_original_orario_page(self):
        sys.path.insert(0, str(ROOT / "offline"))
        import rebuild_master as m
        from build_gacha import value

        data = m.table("adventureMapNode")
        nodes = [row for row in m.rows(data) if value(data, row, 1) == h.FIRST_STAGE]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(value(data, nodes[0], 2), 1)
        self.assertEqual(m.text(data, nodes[0], 3), "Orario")
        stages = m.table("adventureStage")
        stage = next(
            row for row in m.rows(stages) if value(stages, row, 0) == h.FIRST_STAGE
        )
        self.assertEqual(value(stages, stage, 1), h.EPISODE)
        self.assertEqual(m.text(stages, stage, 2), "Corruption")

    def test_guarded_original_flow_and_complete_native_reversal(self):
        original = zipfile.ZipFile(ROOT / "offline/apks/config.arm64_v8a.apk").read(
            "lib/arm64-v8a/libapp.so"
        )
        self.assertEqual(
            original[h.ENTRY : h.ENTRY + 4],
            struct.pack("<I", h.branch(h.ENTRY, h.INITIALIZE, True)),
        )
        record = json.loads((ROOT / "launcher/compatibility-patches.json").read_text())
        data = next(
            (ROOT / "DanMachi MF.app/Contents/Client/android/data/app").glob(
                "*/com.eu.danmore-*/lib/arm64/libapp.so"
            )
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(data).hexdigest(), record["patched_native_sha256"]
        )
        for off, blob in h.patches().items():
            self.assertEqual(data[off : off + len(blob)], blob)
        words = struct.unpack("<12I", h.patches()[h.WRAPPER])

        def identity(start):
            return (
                ((words[start] >> 5) & 65535)
                | (((words[start + 1] >> 5) & 65535) << 16)
                | (((words[start + 2] >> 5) & 65535) << 32)
            )

        self.assertEqual(identity(0), 7160000101)
        self.assertEqual(words[3], 0xEB08003F)  # compare x1; preserve initializer args
        self.assertEqual(words[4], 0x540000E1)  # non-Grand-Day skips stage seed
        self.assertEqual(identity(5), 1160000101102)
        self.assertEqual(words[8], 0xF9025808)  # str x8,[x0,#0x4b0]
        self.assertEqual(words[9], 0x52800028)
        self.assertEqual(words[10], 0xB904BC08)
        self.assertEqual(words[11], h.branch(h.WRAPPER + 44, h.INITIALIZE))
        back = struct.unpack("<11I", h.patches()[h.WRAPPER + 64])
        self.assertEqual(back[0], 0xF9425408)  # map-state episode at +0x4a8
        self.assertEqual(back[5], 0x54000041)
        self.assertEqual(back[6], h.branch(h.WRAPPER + 88, 0x19BE884))
        self.assertEqual(back[7], struct.unpack("<I", original[0x19BE860:0x19BE864])[0])
        self.assertEqual(back[8], 0x35000048)
        self.assertEqual(back[9], h.branch(h.WRAPPER + 100, 0x19BE884))
        self.assertEqual(back[10], h.branch(h.WRAPPER + 104, 0x19BE868))
        # The original map dispatch and ordinary layer setup are restored.
        for off, size in ((0x1A73254, 12), (0x1A2994C, 8)):
            self.assertEqual(data[off : off + size], original[off : off + size])
        # Guard the evidence for the selected-stage offset in original init.
        self.assertEqual(original[0x19BAF44:0x19BAF48], bytes.fromhex("685a42f9"))
        restored = bytearray(data)
        for patch in record["changes"]:
            off = int(patch["offset"], 16)
            before = bytes.fromhex(patch["before"])
            after = bytes.fromhex(patch["after"])
            self.assertEqual(restored[off : off + len(after)], after)
            restored[off : off + len(before)] = before
        self.assertEqual(
            hashlib.sha256(restored).hexdigest(), record["input_native_sha256"]
        )
        self.assertEqual(bytes(restored), original)
