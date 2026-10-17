# Regression checks for asset cache.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import tempfile, zipfile, unittest
from pathlib import Path
from unittest.mock import patch
import asset_cache
from asset_store import ArchivedAsset, MemoryAsset


class AssetCacheTest(unittest.TestCase):
    def test_repeat_read_and_eviction_preserve_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("one", b"1234")
                z.writestr("two", b"5678")
            with zipfile.ZipFile(path) as z:

                def asset(n):
                    i = z.getinfo(n)
                    return ArchivedAsset(
                        {
                            "archive": str(path),
                            "member": n,
                            "size": i.file_size,
                            "crc": i.CRC,
                        }
                    )

                a, b = asset("one"), asset("two")
                with (
                    patch.object(asset_cache, "LIMIT", 4),
                    patch.object(a, "read_bytes", wraps=a.read_bytes) as reads,
                ):
                    asset_cache._cache.clear()
                    asset_cache._bytes = 0
                    self.assertEqual(asset_cache.small_asset(a), b"1234")
                    self.assertEqual(asset_cache.small_asset(a), b"1234")
                    self.assertEqual(reads.call_count, 1)
                    self.assertEqual(asset_cache.small_asset(b), b"5678")
                    self.assertLessEqual(asset_cache._bytes, 4)
                    self.assertEqual(asset_cache.small_asset(a), b"1234")
                    self.assertEqual(reads.call_count, 2)

    def test_generated_asset_not_cached(self):
        self.assertIsNone(asset_cache.small_asset(MemoryAsset(b"test")))
