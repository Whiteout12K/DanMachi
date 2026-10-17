"""Only identical archived client assets may share a stored payload."""

# Regression checks for profile repack.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file depends on the removed repack_profile module.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import io, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import repack_profile


class ProfileRepackTest(unittest.TestCase):
    def test_duplicate_assets_share_bytes_but_player_files_stay_independent(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as source:
            for name, data in [
                ("files/contents/1/a.png", b"asset"),
                ("files/contents/2/b.png", b"asset"),
                ("files/contents/2/c.png", b"other"),
                ("shared_prefs/player.xml", b"asset"),
            ]:
                item = tarfile.TarInfo(name)
                item.size = len(data)
                source.addfile(item, io.BytesIO(data))
        archive.seek(0)
        process = MagicMock(stdout=archive)
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state/temp").mkdir(parents=True)
            destination = root / "client.tar"
            with (
                patch.object(repack_profile, "ROOT", root),
                patch.object(repack_profile.subprocess, "run"),
                patch.object(repack_profile.subprocess, "Popen", return_value=process),
            ):
                result = repack_profile.repack(destination)
            with tarfile.open(destination) as output:
                duplicate = output.getmember("files/contents/2/b.png")
                self.assertTrue(duplicate.issym())
                self.assertEqual(duplicate.linkname, "../1/a.png")
                self.assertTrue(output.getmember("shared_prefs/player.xml").isfile())
                self.assertEqual(
                    output.extractfile("shared_prefs/player.xml").read(), b"asset"
                )
                self.assertEqual(
                    output.extractfile("files/contents/2/c.png").read(), b"other"
                )
            self.assertEqual(result["duplicateAssetBytesAvoided"], 5)
