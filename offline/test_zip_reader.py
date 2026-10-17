# Regression checks for zip reader.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import io, struct, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import zip_reader as reader
import asset_store as store
from asset_store import ArchivedAsset, archive_handle


class ExternalReaderTests(unittest.TestCase):
    def setUp(self):
        # Earlier suites may have populated the real catalog in this process.
        # Clear it before installing a temporary archive fixture.
        reader.catalog.cache_clear()
        reader.index_bytes.cache_clear()

    def tearDown(self):
        reader.catalog.cache_clear()
        reader.index_bytes.cache_clear()
        archive_handle.cache_clear()

    def test_paths_reject_traversal_and_unrelated_files(self):
        for path in (
            "../secret",
            "/1/files/x",
            "1/../secret",
            "1//files/x",
            "state/player-state.json",
            "1/files/./x",
        ):
            self.assertFalse(reader.valid(path), path)
            self.assertIsNone(reader.asset(path))
        self.assertTrue(reader.valid("1/files/splash.png"))
        self.assertTrue(reader.valid("voice_root/files/sound/a.ogg"))

    # These archive-only fixtures omit all guild/event master tables.
    @patch("guild_quests.PATHS", ())
    @patch("guild_events.PATHS", ())
    def test_alias_priority_index_size_and_unmodified_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "assets.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("one", b"original")
                z.writestr("two", b"later")
                z.writestr("only", b"external-only")
            with zipfile.ZipFile(archive) as z:

                def record(name):
                    info = z.getinfo(name)
                    return {
                        "archive": str(archive),
                        "member": name,
                        "size": info.file_size,
                        "crc": info.CRC,
                    }

                records = {
                    "1/files/same.png": record("one"),
                    "2/files/same.png": record("two"),
                    "4/files/later.png": record("only"),
                }
            with (
                patch.object(reader, "records", return_value=records),
                patch.object(reader, "entries", return_value=[]),
            ):
                self.assertEqual(
                    reader.asset("1/files/same.png").read_bytes(), b"original"
                )
                self.assertEqual(
                    reader.asset("1/files/later.png").read_bytes(), b"external-only"
                )
                raw = reader.index_bytes()
                count = struct.unpack_from("<I", raw)[0]
                self.assertEqual(
                    count, 5
                )  # four archive paths plus virtual tutorial weights
                pos = 4
                names = []
                for _ in range(count):
                    length, size = struct.unpack_from("<HQ", raw, pos)
                    pos += 10
                    name = raw[pos : pos + length].decode()
                    pos += length
                    names.append(name)
                    self.assertEqual(size, reader.asset(name).stat().st_size)
                self.assertEqual(pos, len(raw))
                self.assertEqual(names, sorted(names))
                self.assertEqual(list(root.iterdir()), [archive])

    def test_changed_archive_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "assets.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("one", b"image")
            bad = ArchivedAsset(
                {"archive": str(archive), "member": "one", "size": 5, "crc": 0}
            )
            with self.assertRaises(ValueError):
                bad.read_bytes()

    @patch("guild_quests.PATHS", ())
    @patch("guild_events.PATHS", ())
    def test_missing_dialogue_cutout_is_read_from_zip_with_phase_alias(self):
        import plistlib
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "portraits.zip"
            prefix = "2/files/character/novel_portrait/lef_normal/"
            body = prefix + "lef_normal.body.png"
            cutout = prefix + "lef_normal.cutout.plist"
            header = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 720, 720)
            metadata = plistlib.dumps(
                {
                    "argo_character_face_cutout_info": {
                        "lef_normal": {
                            "cutout_coordinate": "{310,155}",
                            "cutout_width": "{105}",
                            "cutout_height": "{125}",
                        }
                    }
                }
            )
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(body, header)
                z.writestr(cutout, metadata)
            with zipfile.ZipFile(archive) as z:

                def record(name):
                    info = z.getinfo(name)
                    return {
                        "archive": str(archive),
                        "member": name,
                        "size": info.file_size,
                        "crc": info.CRC,
                    }

                info = z.getinfo(cutout)
                entry = SimpleNamespace(
                    filename="contents/" + cutout,
                    file_size=info.file_size,
                    CRC=info.CRC,
                    is_dir=lambda: False,
                )
                with (
                    patch.object(store, "ROOT", root),
                    patch.object(reader, "ROOT", root),
                    patch.object(reader, "records", return_value={body: record(body)}),
                    patch.object(
                        reader, "entries", return_value=[(entry, archive, cutout)]
                    ),
                ):
                    original = reader.asset("1" + cutout[1:])
                    self.assertEqual(original.read_bytes(), metadata)
                    self.assertEqual(reader.asset(cutout).read_bytes(), metadata)
                    self.assertEqual(reader.asset("1" + body[1:]).read_bytes(), header)
                    self.assertFalse(
                        reader.valid_dialogue_cutout(cutout, record(cutout), {})
                    )
                    self.assertFalse(
                        reader.valid_dialogue_cutout(
                            cutout.replace("lef_normal.cutout", "wrong.cutout"),
                            record(cutout),
                            {body: record(body)},
                        )
                    )
                    invalid = metadata.replace(b"{310,155}", b"{999,155}")
            archive_handle.cache_clear()
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(body, header)
                z.writestr(cutout, invalid)
            with zipfile.ZipFile(archive) as z:
                with patch.object(reader, "ROOT", root):
                    self.assertFalse(
                        reader.valid_dialogue_cutout(
                            cutout, record(cutout), {body: record(body)}
                        )
                    )


if __name__ == "__main__":
    unittest.main()
