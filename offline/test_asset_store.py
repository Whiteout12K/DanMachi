# Regression checks for asset store.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import hashlib, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import asset_store as store


class StoreTest(unittest.TestCase):
    def test_verified_archive_read_range_and_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "contents/1").mkdir(parents=True)
            data = b"original media"
            archive = root / "assets.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("files/test.png", data)
            with zipfile.ZipFile(archive) as z:
                crc = z.getinfo("files/test.png").CRC
            item = {"size": len(data), "md5": hashlib.md5(data).hexdigest()}
            record = {
                **item,
                "crc": crc,
                "archive": "assets.zip",
                "member": "files/test.png",
            }
            with (
                patch.object(store, "ROOT", root),
                patch.object(
                    store, "records", return_value={"1/files/test.png": record}
                ),
            ):
                asset = store.resolve("1", "files/test.png", item)
                self.assertEqual(asset.read_bytes(), data)
                with asset.open() as stream:
                    stream.seek(4)
                    self.assertEqual(stream.read(3), data[4:7])
                with self.assertRaises(ValueError):
                    store.resolve("1", "../outside", item)
                with self.assertRaises(ValueError):
                    store.resolve("1", "/outside", item)
                record["crc"] += 1
                with self.assertRaises(ValueError):
                    asset.read_bytes()
            for handle in [store.archive_handle(str(archive))]:
                handle.close()
            store.archive_handle.cache_clear()


if __name__ == "__main__":
    unittest.main()
