"""Prevent emulator startup from recreating a disk with missing metadata."""

# Regression checks for disk guard.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file expects the retired emulator AVD profile controls.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import game


class DiskGuardTests(unittest.TestCase):
    def test_missing_or_wrong_version_never_starts_android(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(game, "AVD", Path(folder)),
            patch.object(game, "prepare") as prepare,
            patch.object(game, "adb") as adb,
        ):
            for value in (None, "1", ""):
                marker = Path(folder) / "qemu-version.txt"
                if value is None:
                    marker.unlink(missing_ok=True)
                else:
                    marker.write_text(value)
                with self.assertRaisesRegex(
                    RuntimeError, "saved disk will not be recreated"
                ):
                    game.boot()
            prepare.assert_not_called()
            adb.assert_not_called()

    def test_matching_marker_allows_profile_preparation(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(game, "AVD", Path(folder)),
            patch.object(
                game, "prepare", side_effect=RuntimeError("guard passed")
            ) as prepare,
        ):
            (Path(folder) / "qemu-version.txt").write_text("2")
            with self.assertRaisesRegex(RuntimeError, "guard passed"):
                game.boot()
            prepare.assert_called_once()
