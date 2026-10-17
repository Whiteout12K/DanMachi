# Regression checks for anniversary events.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import hashlib, struct, subprocess, time, unittest, zlib
import anniversary_events as events
import rebuild_master as m


class AnniversaryEventsTest(unittest.TestCase):
    def test_original_map_records_are_unchanged(self):
        original = m.table("adventureMapInfo")
        self.assertEqual(events.patch_map_table(original), original)

    def test_anniversary_box_dates_match_books_and_preserve_contents(self):
        aliases = events.anniversary_box_aliases()
        self.assertIn("event_box.193000013", aliases)
        self.assertIn("event_box.193000027", aliases)
        original = m.table("eventBox")
        patched = events.patch_box_table(original)
        allowed = set()
        found = set()
        for row in m.rows(original):
            alias = m.text(original, row, 2)
            if alias not in aliases:
                continue
            found.add(alias)
            fields = m.fields(original, row)
            for column, expected in ((6, events.START), (7, events.END)):
                if fields[column]:
                    self.assertEqual(m.scalar(patched, row, column, 8), expected)
                    allowed.update(range(fields[column], fields[column] + 12))
        self.assertEqual(found, aliases)
        self.assertTrue(
            all(
                i in allowed
                for i, (a, b) in enumerate(zip(original, patched))
                if a != b
            )
        )
        from guild_events import asset

        for name in ("eventBox",):
            encrypted = asset("1/master/divide_enc/" + name + ".enc").data
            decoded = subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-K",
                    m.AES_KEY.hex(),
                    "-iv",
                    m.IV.hex(),
                ],
                input=encrypted,
                capture_output=True,
                check=True,
            ).stdout
            table = zlib.decompress(decoded)
            self.assertEqual(events.patch_box_table(table), table)

    def test_all_six_are_open_and_other_tables_fields_are_unchanged(self):
        original = m.table("adventureEpisode")
        patched = events.patch_table(original)
        allowed = set()
        found = set()
        for row in m.rows(original):
            try:
                eid = m.scalar(original, row, 0, 8)
            except (ValueError, AssertionError):
                eid = m.scalar(original, row, 0, 4)
            if eid not in events.EPISODES:
                continue
            found.add(eid)
            ff = m.fields(original, row)
            self.assertEqual(m.scalar(patched, row, 6, 8), events.START)
            self.assertEqual(m.scalar(patched, row, 7, 8), events.END)
            # Native DomainAdventure::list excludes nonzero start dates before
            # the hardcoded 0x5db13de0 cutoff, even if the end date is future.
            self.assertTrue(events.START == 0 or events.START >= 0x5DB13DE0)
            self.assertLess(events.START, time.time())
            self.assertGreater(events.END, time.time())
            for col in (6, 7):
                allowed.update(range(ff[col], ff[col] + 12))
            if len(ff) > 24 and ff[24] and m.text(original, row, 23):
                self.assertEqual(m.scalar(patched, row, 24, 8), events.END)
                allowed.update(range(ff[24], ff[24] + 12))
        self.assertEqual(found, set(events.EPISODES))
        self.assertEqual(len(original), len(patched))
        self.assertTrue(
            all(
                i in allowed
                for i, (a, b) in enumerate(zip(original, patched))
                if a != b
            )
        )

    def test_stage_dates_match_episodes_without_changing_unlocks_or_rewards(self):
        original = m.table("adventureStage")
        patched = events.patch_stage_table(original)
        allowed = set()
        found = set()
        count = 0
        for row in m.rows(original):
            episode = m.scalar(original, row, 1, 8)
            if episode not in events.EPISODES:
                continue
            found.add(episode)
            count += 1
            ff = m.fields(original, row)
            self.assertEqual(m.scalar(patched, row, 12, 8), events.START)
            self.assertEqual(m.scalar(patched, row, 13, 8), events.END)
            for col in (12, 13):
                allowed.update(range(ff[col], ff[col] + 12))
        self.assertEqual(found, set(events.EPISODES))
        self.assertGreater(count, 15)
        self.assertEqual(len(original), len(patched))
        self.assertTrue(
            all(
                i in allowed
                for i, (a, b) in enumerate(zip(original, patched))
                if a != b
            )
        )
        encrypted = events.stage_master_asset().data
        decrypted = subprocess.run(
            [
                "/usr/bin/openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-K",
                m.AES_KEY.hex(),
                "-iv",
                m.IV.hex(),
            ],
            input=encrypted,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(zlib.decompress(decrypted), patched)
        from zip_reader import catalog, asset
        from guild_events import asset as rotating_asset

        combined = rotating_asset(events.STAGE_MASTER).data
        self.assertEqual(catalog()[events.STAGE_MASTER]["size"], len(combined))
        self.assertEqual(asset(events.STAGE_MASTER).data, combined)

    def test_anniversary_shops_and_products_have_no_dates_only(self):
        ids = events.anniversary_shop_ids()
        self.assertEqual(len(ids), 15)
        from zip_reader import catalog, asset

        for name, products, cols in [
            ("shop", False, (4, 5)),
            ("shopProduct", True, (12, 13)),
        ]:
            original = m.table(name)
            patched = events.patch_shop_table(original, products)
            allowed = set()
            found = set()
            count = 0
            for row in m.rows(original):
                shop = m.scalar(original, row, 14 if products else 0, 4)
                if shop not in ids:
                    continue
                found.add(shop)
                count += 1
                ff = m.fields(original, row)
                for col in cols:
                    if ff[col]:
                        self.assertEqual(m.scalar(patched, row, col, 8), 0)
                        allowed.update(range(ff[col], ff[col] + 12))
            self.assertEqual(found, ids)
            self.assertEqual(count, 684 if products else 15)
            self.assertEqual(len(original), len(patched))
            self.assertTrue(
                all(
                    i in allowed
                    for i, (a, b) in enumerate(zip(original, patched))
                    if a != b
                )
            )
            path = "1/master/divide_enc/" + name + ".enc"
            encrypted = asset(path).data
            self.assertEqual(catalog()[path]["size"], len(encrypted))
            decrypted = subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-K",
                    m.AES_KEY.hex(),
                    "-iv",
                    m.IV.hex(),
                ],
                input=encrypted,
                capture_output=True,
                check=True,
            ).stdout
            from guild_events import patch as event_patch

            combined = event_patch(patched, name)
            combined = events.patch_shop_table(combined, products)
            self.assertEqual(zlib.decompress(decrypted), combined)

    def test_encrypted_catalog_and_final_story_script_are_readable(self):
        encrypted = events.master_asset().data
        decrypted = subprocess.run(
            [
                "/usr/bin/openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-K",
                m.AES_KEY.hex(),
                "-iv",
                m.IV.hex(),
            ],
            input=encrypted,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            zlib.decompress(decrypted), events.patch_table(m.table("adventureEpisode"))
        )
        from zip_reader import catalog, asset
        from guild_events import asset as rotating_asset

        combined = rotating_asset(events.MASTER).data
        self.assertEqual(catalog()[events.MASTER]["size"], len(combined))
        self.assertEqual(asset(events.MASTER).data, combined)
        self.assertIsNotNone(
            asset("1/master/divide_novel_command_enc/novelCommand751040548.enc")
        )
        final = asset(events.FINAL_SCRIPT)
        self.assertIsNotNone(final)
        with final.open() as f:
            data = f.read()
        decoded = subprocess.run(
            [
                "/usr/bin/openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-K",
                m.AES_KEY.hex(),
                "-iv",
                m.IV.hex(),
            ],
            input=data,
            capture_output=True,
            check=True,
        ).stdout
        self.assertTrue(m.rows(zlib.decompress(decoded)))


if __name__ == "__main__":
    unittest.main()
