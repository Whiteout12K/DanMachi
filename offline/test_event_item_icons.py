# Regression checks for event item icons.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import struct, unittest
import event_item_icons as icons
from asset_store import records, ArchivedAsset


class EventItemIconsTest(unittest.TestCase):
    def test_every_original_event_item_has_both_variants(self):
        from zip_reader import catalog, asset

        sources = records()
        catalogue = catalog()
        seen = {}
        for identity, name in icons.items():
            for variant in icons.VARIANTS:
                path = f"{icons.PREFIX}{identity}_{variant}.png"
                self.assertIn(path, catalogue)
                record = catalogue[path]
                key = (record["archive"], record["member"])
                if key not in seen:
                    data = asset(path).read_bytes()  # checks original ZIP size/CRC
                    self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                    self.assertTrue(all(struct.unpack(">II", data[16:24])))
                    seen[key] = len(data)
                self.assertEqual(record["size"], seen[key])
                if path in sources:
                    self.assertEqual(record, sources[path])
        self.assertIsNone(asset(icons.PREFIX + "999999999_noframe.png"))

    def test_grand_day_uses_its_identical_rerun_art(self):
        aliases = icons.resolutions(records())
        for old, new in zip(range(290000101, 290000105), range(290000750, 290000754)):
            for v in icons.VARIANTS:
                self.assertEqual(
                    aliases[f"{icons.PREFIX}{old}_{v}.png"],
                    (f"{icons.PREFIX}{new}_{v}.png", "same-name"),
                )

    def test_substitutes_are_distinct_from_all_neighboring_currencies(self):
        sources = records()
        resolved = icons.resolutions(sources)
        for group in icons.groups():
            for identity in group:
                path = f"{icons.PREFIX}{identity}_noframe.png"
                if resolved.get(path, ("", ""))[1] != "distinct-fallback":
                    continue
                for other in set(group) - {identity}:
                    for variant in icons.VARIANTS:
                        left = f"{icons.PREFIX}{identity}_{variant}.png"
                        right = f"{icons.PREFIX}{other}_{variant}.png"
                        self.assertNotEqual(
                            sources[resolved.get(left, (left, ""))[0]]["md5"],
                            sources[resolved.get(right, (right, ""))[0]]["md5"],
                        )
        self.assertEqual(
            icons.aliases(sources), {p: sources[s] for p, (s, k) in resolved.items()}
        )

    def test_every_shop_currency_has_distinct_art(self):
        import rebuild_master as master
        from build_gacha import value

        sources = dict(records())
        sources.update(icons.aliases(sources))
        data = master.table("eventItem")
        ids = {master.text(data, r, 1): value(data, r, 0) for r in master.rows(data)}
        shop = master.table("shop")
        count = 0
        for row in master.rows(shop):
            group = {
                ids[master.text(shop, row, c)]
                for c in (6, 7, 8, 9, 11, 12)
                if master.text(shop, row, c) in ids
            }
            if len(group) < 2:
                continue
            count += 1
            for variant in icons.VARIANTS:
                hashes = [
                    sources[f"{icons.PREFIX}{n}_{variant}.png"]["md5"] for n in group
                ]
                self.assertEqual(len(hashes), len(set(hashes)), group)
        self.assertGreater(count, 100)
