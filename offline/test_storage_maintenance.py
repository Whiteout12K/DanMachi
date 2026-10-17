"""Check maintenance boundaries: logs/caches only, never assets or player data."""

# Regression checks for storage maintenance.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file depends on the removed launcher/storage.py utility.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "storage", Path(__file__).resolve().parents[1] / "launcher/storage.py"
)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class StorageTests(unittest.TestCase):
    def test_only_named_diagnostics_and_cache_are_touched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "state/logs").mkdir(parents=True)
            log = root / "state/logs/emulator.log"
            log.write_bytes(b"old\n" * 400000 + b"recent\n")
            player = root / "state/logs/player-state.json"
            player.write_bytes(b"important player data")
            calls = []

            def device(*args, **kw):
                calls.append(args)
                return "20000\tcache\n8\tcode_cache\n" if "du" in args else ""

            with patch.object(storage, "ROOT", root):
                result = storage.maintain(device)
            self.assertTrue(result["cacheCleared"])
            self.assertLess(log.stat().st_size, storage.LOG_LIMIT)
            self.assertTrue(log.read_bytes().endswith(b"recent\n"))
            self.assertEqual(player.read_bytes(), b"important player data")
            self.assertEqual(
                calls[-1], ("shell", "run-as", "com.eu.danmore", "rm", "-rf", "cache")
            )
            self.assertEqual(result["cacheFoldersCleared"], ["cache"])

    def test_only_oversized_compilation_cache_is_cleared(self):
        calls = []

        def device(*args, **kw):
            calls.append(args)
            return "100\tcache\n5000\tcode_cache\n"

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(storage, "ROOT", Path(folder)),
        ):
            self.assertEqual(
                storage.maintain(device)["cacheFoldersCleared"], ["code_cache"]
            )
        self.assertEqual(
            calls[-1], ("shell", "run-as", "com.eu.danmore", "rm", "-rf", "code_cache")
        )

    def test_small_cache_stays_intact(self):
        calls = []

        def device(*args, **kw):
            calls.append(args)
            return "2048\tcache\n8\tcode_cache\n"

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(storage, "ROOT", Path(folder)),
        ):
            self.assertFalse(storage.maintain(device)["cacheCleared"])
        self.assertEqual(len(calls), 1)

    def test_temporary_cleanup_preserves_unknown_files_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            temp = root / "state/temp"
            temp.mkdir(parents=True)
            (temp / "adb.501.log").write_bytes(b"log")
            (temp / "tmp12345678").mkdir()
            (temp / "tmp12345678/data").write_bytes(b"temporary")
            (temp / "player-state.json").write_bytes(b"save")
            outside = root / "important"
            outside.write_bytes(b"asset")
            (temp / "tmpabcdefgh").symlink_to(outside)
            with patch.object(storage, "ROOT", root):
                removed = storage.clean_temporary()
            self.assertEqual(set(removed), {"adb.501.log", "tmp12345678"})
            self.assertEqual(outside.read_bytes(), b"asset")
            self.assertEqual((temp / "player-state.json").read_bytes(), b"save")
            self.assertTrue((temp / "tmpabcdefgh").is_symlink())

    def test_symlinked_temporary_folder_is_not_cleaned(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "state").mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "adb.501.log").write_bytes(b"keep")
            (root / "state/temp").symlink_to(outside)
            with patch.object(storage, "ROOT", root):
                self.assertEqual(storage.clean_temporary(), [])
            self.assertTrue((outside / "adb.501.log").exists())


if __name__ == "__main__":
    unittest.main()
