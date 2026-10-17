# Regression checks for audio profile.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import hashlib, struct, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import archive_assets
from audio_profile import EXTRA_ID, original_md5


class AudioProfileTests(unittest.TestCase):
    def test_original_audio_url_resolves_only_to_its_bound_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "archives"
            source.mkdir()
            old = b"original audio"
            new = b"smaller audio"
            name = "files/sound/voice_episode/example/one.ogg"
            info = zipfile.ZipInfo("contents/voice_root/" + name)
            info.extra = struct.pack("<HH", EXTRA_ID, 16) + hashlib.md5(old).digest()
            with zipfile.ZipFile(source / "audio.zip", "w") as archive:
                archive.writestr(info, new)
            archive_assets.index.cache_clear()
            try:
                with (
                    patch.object(archive_assets, "ROOT", root),
                    patch.object(archive_assets, "SOURCE", source),
                ):
                    for digest in (
                        hashlib.md5(old).hexdigest(),
                        hashlib.md5(new).hexdigest(),
                    ):
                        self.assertEqual(
                            archive_assets.recover(
                                "/api/contents/" + name + "/" + digest + ".ogg"
                            ).read_bytes(),
                            new,
                        )
                    self.assertIsNone(
                        archive_assets.recover(
                            "/api/contents/"
                            + name
                            + "/00000000000000000000000000000000.ogg"
                        )
                    )
                    cached = root / "contents/voice_root" / name
                    cached.parent.mkdir(parents=True)
                    cached.write_bytes(old)
                    self.assertEqual(
                        archive_assets.recover(
                            "/api/contents/"
                            + name
                            + "/"
                            + hashlib.md5(new).hexdigest()
                            + ".ogg"
                        ).read_bytes(),
                        new,
                    )
            finally:
                archive_assets.index.cache_clear()

    def test_ordinary_assets_have_no_checksum_override(self):
        self.assertIsNone(original_md5(zipfile.ZipInfo("ordinary.png")))


if __name__ == "__main__":
    unittest.main()
