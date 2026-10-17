"""Catch future extracted media without rejecting required manifests."""

# Regression checks for asset layout.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file expects the removed loose_asset_problems bundle-check
# helper.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import check_bundle


class LayoutTests(unittest.TestCase):
    def test_extracted_copy_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            phase = root / "contents/1"
            phase.mkdir(parents=True)
            (phase / "project.manifest").write_text("{}")
            (phase / "portrait.png").write_bytes(b"copy")
            with patch.object(check_bundle, "ROOT", root):
                self.assertEqual(
                    check_bundle.loose_asset_problems(),
                    ["Loose game asset outside archives: contents/1/portrait.png"],
                )

    def test_only_manifests_and_metadata_are_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            phase = root / "contents/1"
            phase.mkdir(parents=True)
            for name in ("project.manifest", "version.manifest", ".DS_Store"):
                (phase / name).write_bytes(b"metadata")
            with patch.object(check_bundle, "ROOT", root):
                self.assertEqual(check_bundle.loose_asset_problems(), [])


if __name__ == "__main__":
    unittest.main()
