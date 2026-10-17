"""Changed source data must invalidate a previously verified launch."""

# Regression checks for startup cache.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file depends on the retired startup_cache module.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from startup_cache import signature, read, write, asset_roster


class StartupCacheTests(unittest.TestCase):
    def test_costume_changes_require_assets_but_training_does_not(self):
        player = {
            "tables": {
                "UserPC": [{"pcId": 1, "level": 1}],
                "UserCharacterCostume": [{"costumeId": 2}],
            }
        }
        old = asset_roster(player)
        player["tables"]["UserPC"][0]["level"] = 20
        self.assertEqual(old, asset_roster(player))
        player["tables"]["UserCommunicationCharacter"] = [{"costumeId": 3}]
        self.assertNotEqual(old, asset_roster(player))

    def test_source_and_roster_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "asset"
            source.write_bytes(b"first")
            old = signature(root, [source], [1])
            self.assertEqual(old, signature(root, [source], [1]))
            self.assertNotEqual(old, signature(root, [source], [2]))
            source.write_bytes(b"other")
            self.assertNotEqual(old, signature(root, [source], [1]))

    def test_broken_receipt_reverifies(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "receipt.json"
            self.assertEqual(read(p), {})
            p.write_text("incomplete")
            self.assertEqual(read(p), {})
            write(p, {"source": "verified"})
            self.assertEqual(read(p), {"source": "verified"})
            self.assertFalse(p.with_suffix(".updating").exists())


if __name__ == "__main__":
    unittest.main()
