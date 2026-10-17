"""Check complete Album selection, shared links and verified extraction bytes."""

# Regression checks for album assets.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import hashlib, io, tarfile, unittest, posixpath
from unittest.mock import patch
import sync_album as album
from types import SimpleNamespace


class AlbumAssetsTests(unittest.TestCase):
    def row(
        self, name="thumbnail_square.png", phase="3", unit="gac_1011001002", data=b"art"
    ):
        item = {"md5": hashlib.md5(data).hexdigest(), "size": len(data)}
        return {
            "phase": phase,
            "name": album.ART_PREFIX + unit + "/" + name,
            "md5": item["md5"],
            "size": item["size"],
            "item": item,
        }

    def test_album_includes_both_thumbnail_formats_splash_and_legacy_atlas(self):
        rows = [
            self.row(n)
            for n in (
                "thumbnail_square.png",
                "thumbnail_square2.png",
                "status_l.png",
                "all_rectangle.png",
                "texture.png",
                "texture.plist",
                "white.png",
                "lottery_upcut.png",
            )
        ]
        picked = album.album_rows({"3": {r["name"]: r["item"] for r in rows}})
        self.assertEqual(
            {r["name"].rsplit("/", 1)[-1] for r in picked},
            {
                "thumbnail_square.png",
                "thumbnail_square2.png",
                "status_l.png",
                "all_rectangle.png",
                "texture.png",
                "texture.plist",
                "white.png",
            },
        )

    def test_verified_source_is_reused_with_a_relative_visible_link(self):
        row = self.row()
        target = "files/contents/3/" + row["name"]
        operations = album.plan([row], {target: row["md5"]})
        self.assertEqual(
            operations, [("link", "files/contents/1/" + row["name"], target)]
        )
        out = io.BytesIO()
        album.write_tar(out, operations, "receipt")
        with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as archive:
            link = archive.getmembers()[0]
            self.assertTrue(link.issym())
            self.assertFalse(link.linkname.startswith("/"))
            self.assertEqual(
                posixpath.normpath(
                    posixpath.join(posixpath.dirname(link.name), link.linkname)
                ),
                target,
            )

    def test_identical_art_has_one_physical_payload_and_original_paths(self):
        rows = [self.row(unit="gac_1011001002"), self.row(unit="gac_1011001003")]
        operations = album.plan(rows, {})
        self.assertEqual(sum(k == "data" for k, _, _ in operations), 1)
        out = io.BytesIO()
        with patch.object(
            album, "resolve", return_value=SimpleNamespace(read_bytes=lambda: b"art")
        ):
            album.write_tar(out, operations, "receipt")
        with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as archive:
            for row in rows:
                self.assertIn("files/contents/1/" + row["name"], archive.getnames())
            data = next(x for x in archive if x.isfile() and x.name != album.MARKER)
            self.assertEqual(archive.extractfile(data).read(), b"art")

    def test_wrong_payload_cannot_write_success_receipt(self):
        row = self.row()
        out = io.BytesIO()
        with (
            patch.object(
                album,
                "resolve",
                return_value=SimpleNamespace(read_bytes=lambda: b"bad"),
            ),
            self.assertRaisesRegex(ValueError, "checksum mismatch"),
        ):
            album.write_tar(out, album.plan([row], {}), "receipt")
        self.assertNotIn(album.MARKER.encode(), out.getvalue())

    def test_existing_visible_copy_does_not_form_a_link_cycle(self):
        row = self.row()
        alias = "files/contents/1/" + row["name"]
        operations = album.plan([row], {alias: row["md5"]})
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0][0], "data")

    def test_hash_reader_drops_errors_and_unsafe_paths(self):
        h = "a" * 32
        self.assertEqual(
            album.parse_hashes(
                "find: Argument list too long\n"
                + h
                + "  files/contents/1/art\n"
                + h
                + "  files/contents/../save"
            ),
            {"files/contents/1/art": h},
        )


if __name__ == "__main__":
    unittest.main()
