# Regression checks for guild events.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import unittest
import rebuild_master as m
from build_gacha import value
import guild_events as e
import guild_quests as g


class EventTests(unittest.TestCase):
    def test_current_quests_have_matching_available_episodes_and_stages(self):
        b = m.table("achievement")
        windows = g.limited_windows(b, g.SESSION_MONTH)
        start, end = g.month_window(g.SESSION_MONTH)
        current = [r for r, w in windows.items() if w == (start, end)]
        self.assertGreater(len(current), 0)
        self.assertLessEqual(len(current), 80)
        wanted = {e.quest_episode(b, r)[0] for r in current}
        schedule = e.schedule()
        for eid in wanted:
            self.assertEqual(schedule[eid], (start, end))
        original = m.table("adventureEpisode")
        patched = e.patch(original, "adventureEpisode")
        seen = set()
        for row in m.rows(original):
            eid = value(original, row, 0)
            if eid in wanted:
                seen.add(eid)
                for col, date in ((6, start), (7, end)):
                    if m.fields(original, row)[col]:
                        self.assertEqual(value(patched, row, col), date)
                    else:
                        self.assertEqual(value(patched, row, col), 0)
        self.assertEqual(seen, wanted)
        stages = m.table("adventureStage")
        patched = e.patch(stages, "adventureStage")
        count = 0
        for row in m.rows(stages):
            if value(stages, row, 1) in wanted:
                count += 1
                # Missing original dates are unrestricted; existing dates match.
                for col, date in ((12, start), (13, end)):
                    if m.fields(stages, row)[col]:
                        self.assertEqual(value(patched, row, col), date)
        self.assertGreater(count, 0)

    def test_objectives_and_event_fields_outside_dates_are_preserved(self):
        for name, cols in [
            ("adventure", (6, 7)),
            ("adventureEpisode", (6, 7, 24)),
            ("adventureStage", (12, 13)),
            ("shop", (4, 5)),
            ("shopProduct", (12, 13)),
            ("eventBox", (6, 7)),
        ]:
            original = m.table(name)
            patched = e.patch(original, name)
            allowed = set()
            for row in m.rows(original):
                for col in cols:
                    f = m.fields(original, row)[col]
                    if f:
                        allowed.update(range(f, f + 12))
            self.assertEqual(len(original), len(patched))
            self.assertTrue(
                all(
                    i in allowed
                    for i, (a, b) in enumerate(zip(original, patched))
                    if a != b
                )
            )

    def test_all_overridden_assets_are_generated_and_indexed(self):
        from zip_reader import asset, catalog

        for path in e.PATHS:
            self.assertEqual(len(asset(path).data), catalog()[path]["size"])

    def test_ais_reward_box_is_available_with_its_episode(self):
        episodes = m.table("adventureEpisode")
        boxes = m.table("eventBox")
        patched = e.patch(boxes, "eventBox")
        patched_episodes = e.patch(episodes, "adventureEpisode")
        row = next(r for r in m.rows(episodes) if value(episodes, r, 0) == 7090010501)
        window = e.schedule()[7090010501]
        self.assertEqual(value(patched_episodes, row, 24), window[1])
        box = next(
            r for r in m.rows(boxes) if m.text(boxes, r, 2) == m.text(episodes, row, 23)
        )
        self.assertEqual(value(patched, box, 6), window[0])
        self.assertEqual(value(patched, box, 7), window[1])
        items = m.table("eventItem")
        self.assertIn(
            m.text(boxes, box, 3), {m.text(items, r, 1) for r in m.rows(items)}
        )
