# Regression checks for local downloads.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import json, tempfile, unittest, zipfile
from pathlib import Path
from local_downloads import voice_markers, manifest_asset, VOICE, MANIFEST


class LocalDownloadsTest(unittest.TestCase):
    def test_completion_requires_original_manifest_and_retained_episode(self):
        with tempfile.TemporaryDirectory() as d:
            archive = Path(d) / "assets.zip"
            manifest = {
                "episodes": {
                    "701": {"episodeId": 701, "md5": "a" * 32},
                    "702": {"episodeId": 702, "md5": "b" * 32},
                    "703": {"episodeId": 703, "md5": "bad"},
                }
            }
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(MANIFEST, json.dumps(manifest))
                z.writestr(VOICE + "701/greeting.ogg", b"voice")
                z.writestr(VOICE + "703/greeting.ogg", b"voice")
            with zipfile.ZipFile(archive) as z:
                sources = {
                    i.filename: {
                        "archive": str(archive),
                        "member": i.filename,
                        "size": i.file_size,
                        "crc": i.CRC,
                    }
                    for i in z.infolist()
                }
            self.assertEqual(voice_markers(sources), {VOICE + "701/701.md5": b"a" * 32})
            sources[VOICE + "701/greeting.ogg"]["archive"] = str(
                Path(d) / "missing.zip"
            )
            self.assertEqual(voice_markers(sources), {})
            self.assertEqual(voice_markers({}), {})

    def test_retained_manifests_and_markers_are_readable_without_extraction(self):
        from zip_reader import catalog, asset, index_bytes

        c = catalog()
        markers = [
            p for p, r in c.items() if "local_completion" in r and p.endswith(".md5")
        ]
        self.assertGreater(len(markers), 0)
        for path in markers:
            payload = (
                asset(path).read_bytes()
                if hasattr(asset(path), "read_bytes")
                else asset(path).data
            )
            self.assertEqual(len(payload), 32)
            self.assertIn(path.encode(), index_bytes())
        for name in [
            "voice_episode.manifest",
            "area_atlas.manifest",
            "single_image.manifest",
            *(f"phase.manifest.{i}" for i in range(1, 9)),
        ]:
            for prefix in ["/api/", "/content/"]:
                source = manifest_asset(
                    prefix + "manifests/us/pkm/" + name + "/original"
                )
                self.assertIsNotNone(source)
                with source.open() as stream:
                    json.load(stream)
        for path in [
            "/api/manifests/us/pkm/../x",
            "/api/manifests/us/pkm/unknown/x",
            "/else/voice_episode.manifest/x",
        ]:
            self.assertIsNone(manifest_asset(path))

    def test_original_voice_download_list_is_preserved(self):
        from zip_reader import asset, catalog
        from asset_store import ArchivedAsset

        record = catalog()[MANIFEST]
        self.assertNotIn("local_completion", record)
        with asset(MANIFEST).open() as stream:
            local = stream.read()
        self.assertEqual(local, ArchivedAsset(record).read_bytes())
        self.assertIn("7110000190", json.loads(local)["episodes"])

    def test_boost_and_event_shared_image_catalogs_are_retained(self):
        from zip_reader import catalog, asset

        c = catalog()
        for filename, key, collection in [
            ("area_atlas.manifest", "areaAtlas", "area_atlas_root"),
            ("single_image.manifest", "singleImages", "single_image_root"),
        ]:
            with asset("1/manifests/" + filename).open() as stream:
                rows = json.load(stream)[key]
            # This original client uses PKM textures. DDS/PVR/PNG atlas
            # alternatives for other platforms are not downloads it needs.
            applicable = {
                k: v
                for k, v in rows.items()
                if filename != "area_atlas.manifest"
                or k.endswith((".pkmenc", ".plist"))
            }
            self.assertTrue(applicable)
            for entry in applicable.values():
                logical = (
                    collection
                    + "/"
                    + entry["path"].removeprefix("contents/").rsplit("/", 1)[0]
                )
                alias = "1/" + entry["path"].removeprefix("contents/").rsplit("/", 1)[0]
                self.assertTrue(logical in c or alias in c, logical)
                self.assertIsNotNone(asset(logical if logical in c else alias))


if __name__ == "__main__":
    unittest.main()
