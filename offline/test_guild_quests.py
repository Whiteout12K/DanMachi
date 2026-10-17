# Regression checks for guild quests.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import collections
import datetime
import subprocess
import unittest
import zlib
import guild_quests as g
import rebuild_master as m
from build_gacha import value


class GuildTests(unittest.TestCase):
    def test_only_monthly_and_limited_dates_change(self):
        data = m.table("achievement")
        patched = g.patch_achievements(data)
        allowed = set()
        counts = collections.Counter()
        for row in m.rows(data):
            kind = value(data, row, 2)
            if kind not in (3, 8):
                continue
            counts[kind] += 1
            fields = m.fields(data, row)
            for col in (13, 14):
                if kind == 8:
                    self.assertEqual(value(patched, row, col), 0)
                else:
                    self.assertGreater(value(patched, row, col), 0)
                if fields[col]:
                    allowed.update(range(fields[col], fields[col] + 12))
            self.assertEqual(value(patched, row, 20), value(data, row, 20))
            if kind == 8:
                self.assertEqual(value(patched, row, 20), 3)
        self.assertEqual(counts, {3: 25858, 8: 135})
        self.assertEqual(len(data), len(patched))
        self.assertTrue(
            all(i in allowed for i, (a, b) in enumerate(zip(data, patched)) if a != b)
        )

    def test_schedule_has_all_categories_across_year_and_month_rollover(self):
        data = m.table("monthlyAchievement")
        current = g.month_number(datetime.date(2026, 12, 31))
        patched = g.patch_months(data, current)
        schedule = collections.defaultdict(set)
        allowed = set()
        for row in m.rows(data):
            schedule[value(patched, row, 3)].add(
                (value(patched, row, 1), value(patched, row, 2))
            )
            start = m.fields(data, row)[3]
            allowed.update(range(start, start + 8))
        for month in (202611, 202612, 202701, 202702):
            self.assertEqual(schedule[month], {(1, 1), (2, 2), (3, 3)})
        self.assertEqual(len(schedule), 53)
        self.assertTrue(
            all(i in allowed for i, (a, b) in enumerate(zip(data, patched)) if a != b)
        )

    def test_generated_assets_round_trip_and_catalog_sizes(self):
        from zip_reader import catalog, asset

        for path in g.PATHS:
            body = asset(path).data
            self.assertEqual(catalog()[path]["size"], len(body))
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
                input=body,
                capture_output=True,
                check=True,
            ).stdout
            original = m.table(
                "achievement" if path == g.ACHIEVEMENT else "monthlyAchievement"
            )
            expected = (
                g.patch_achievements(original, g.SESSION_MONTH)
                if path == g.ACHIEVEMENT
                else g.patch_months(original, g.SESSION_MONTH)
            )
            self.assertEqual(zlib.decompress(decrypted), expected)

    def test_monthly_reward_claim_can_repeat_next_month_but_not_twice_same_completion(
        self,
    ):
        import tempfile
        from pathlib import Path
        from save_store import SaveStore

        with tempfile.TemporaryDirectory() as directory:
            save = SaveStore(Path(directory) / "save.json")
            row = {
                "userId": 1,
                "achievementId": 6080000001,
                "completedAt": 100,
                "state": 3,
                "progressParam": 1,
                "signature": 9,
                "lastResetAt": 0,
                "readState": 1,
            }

            def put(r):
                save.apply(
                    {
                        "deltas": [
                            {"putItems": {"UserAchievement": [r]}, "deleteItems": {}}
                        ],
                        "checksums": {"after": {}},
                    }
                )

            put(row)
            request = {
                "achievementIds": [{"achievementId": 6080000001, "completedAt": 100}]
            }
            first = save.achievement_complete(request)
            self.assertEqual(save.achievement_complete(request), first)
            save.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [
                        {"id": first["operation"]["id"], "verifier": "verified"}
                    ],
                }
            )
            self.assertEqual(save.achievement_complete(request), {"code": 0})
            put(dict(row, state=2, completedAt=0, progressParam=0, lastResetAt=200))
            with self.assertRaises(ValueError):
                save.achievement_complete(
                    {
                        "achievementIds": [
                            {"achievementId": 6080000001, "completedAt": 200}
                        ]
                    }
                )
            put(dict(row, completedAt=300, lastResetAt=200))
            second = save.achievement_complete(
                {"achievementIds": [{"achievementId": 6080000001, "completedAt": 300}]}
            )
            self.assertNotEqual(first["operation"]["id"], second["operation"]["id"])
            self.assertEqual(
                first["operation"]["parameters"]["receivedItems"],
                second["operation"]["parameters"]["receivedItems"],
            )

    def test_limited_batches_are_bounded_and_rotate_at_year_boundary(self):
        data = m.table("achievement")
        active = []
        for date in (datetime.date(2026, 12, 15), datetime.date(2027, 1, 15)):
            month = g.month_number(date)
            patched = g.patch_achievements(data, month)
            start, end = g.month_window(month)
            now = (start + end) // 2
            selected = {
                value(data, t, 0)
                for t in m.rows(data)
                if value(data, t, 2) == 3
                and value(patched, t, 13) <= now <= value(patched, t, 14)
            }
            self.assertGreater(len(selected), 0)
            self.assertLessEqual(len(selected), g.LIMITED_BATCH_SIZE)
            active.append(selected)
        self.assertFalse(active[0] & active[1])
