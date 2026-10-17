"""Exercise shared payloads, virtual paths and collision-safe deduplication."""

# Regression checks for archive deduplication.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import gzip, hashlib, json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import archive_assets, archive_catalog, deduplicate_assets


class DedupTests(unittest.TestCase):
    def test_virtual_paths_recover_identical_media_from_another_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "assets/archives"
            source.mkdir(parents=True)
            payload = b"voice data" * 100
            name = "files/sound/voice_episode/one.ogg"
            with zipfile.ZipFile(
                source / "a.zip", "w", compression=zipfile.ZIP_DEFLATED
            ) as z:
                z.writestr("contents/1/" + name, payload)
            with zipfile.ZipFile(
                source / "b.zip", "w", compression=zipfile.ZIP_DEFLATED
            ) as z:
                z.writestr("contents/voice_root/" + name, payload)
                z.writestr("contents/single_image_root/files/unique.png", b"picture")
            catalog, redirects, report = deduplicate_assets.plan(source)
            self.assertEqual(report["duplicatePayloads"], 1)
            for key, value in catalog["sources"].items():
                if value["aliases"]:
                    deduplicate_assets.repack(source / key, value["aliases"]).replace(
                        source / key
                    )
            with gzip.open(source / "aliases.json.gz", "wt") as f:
                json.dump(catalog, f)
            logical = list(archive_catalog.entries(source))
            self.assertEqual(len(logical), 3)
            self.assertEqual(logical[1][0].filename, "contents/voice_root/" + name)
            with zipfile.ZipFile(logical[1][1]) as z:
                self.assertEqual(z.read(logical[1][2]), payload)
            archive_assets.index.cache_clear()
            try:
                with (
                    patch.object(archive_assets, "ROOT", root),
                    patch.object(archive_assets, "SOURCE", source),
                ):
                    asset = archive_assets.recover(
                        "/api/contents/"
                        + name
                        + "/"
                        + hashlib.md5(payload).hexdigest()
                        + ".ogg"
                    )
                    self.assertEqual(asset.read_bytes(), payload)
            finally:
                archive_assets.index.cache_clear()

    def test_catalog_cannot_reference_an_external_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(root / "a.zip", "w"):
                pass
            value = {
                "format": 1,
                "sources": {
                    "a.zip": {
                        "count": 1,
                        "aliases": {
                            "0": {
                                "name": "x",
                                "archive": "../outside.zip",
                                "member": "x",
                                "size": 1,
                                "crc": 1,
                            }
                        },
                    }
                },
            }
            with gzip.open(root / "aliases.json.gz", "wt") as f:
                json.dump(value, f)
            with self.assertRaises(ValueError):
                list(archive_catalog.entries(root))


if __name__ == "__main__":
    unittest.main()
