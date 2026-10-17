"""Check English UI overlays while preserving original game rules and voices.

Fixtures use decoded original definitions and in-memory copies only. No player
save, archive input, ownership, cost or reward is edited by these checks.
"""

import json
import unittest
from pathlib import Path

import english_presentation as english
import rebuild_master as master
from build_gacha import value


class EnglishPresentationTests(unittest.TestCase):
    def test_only_selected_display_pointers_change_in_original_table_bytes(self):
        for name, changes in english.text_policy().items():
            original = master.table(name)
            patched = english.patch_text(name, original)
            allowed = set()
            for row in master.rows(original):
                identity = str(value(original, row, 0))
                self.assertEqual(value(patched, row, 0), int(identity))
                for col, label in changes.get(identity, {}).items():
                    field = master.fields(original, row)[int(col)]
                    allowed.update(range(field, field + 4))
                    self.assertEqual(master.text(patched, row, int(col)), label)
                    self.assertIsNone(english.JAPANESE.search(label))
            changed = {i for i, (a, b) in enumerate(zip(original, patched)) if a != b}
            self.assertLessEqual(changed, allowed, name)

    def test_display_tables_and_playable_unit_skills_have_english_labels(self):
        import gacha

        patched = {
            name: english.patch_text(name, master.table(name))
            for name in english.text_policy()
        }
        for name, col in [
            ("lottery", 2),
            ("gachaTicket", 2),
            ("eventItem", 2),
            ("shop", 2),
            ("adventureEpisode", 4),
            ("itemType", 2),
        ]:
            for row in master.rows(patched[name]):
                self.assertIsNone(
                    english.JAPANESE.search(master.text(patched[name], row, col)),
                    (name, value(patched[name], row, 0)),
                )
        used = {pc for pool in gacha.definitions()["groups"].values() for pc in pool}
        skills = set()
        for row in master.rows(patched["pc"]):
            if value(patched["pc"], row, 0) not in used:
                continue
            for col in (1, 2):
                self.assertIsNone(
                    english.JAPANESE.search(master.text(patched["pc"], row, col))
                )
            skills.update(
                value(patched["pc"], row, col) for col in (22, 24, 25, 26, 27, 28)
            )
        for row in master.rows(patched["pcSkill"]):
            if value(patched["pcSkill"], row, 0) in skills:
                for col in (1, 2):
                    self.assertIsNone(
                        english.JAPANESE.search(
                            master.text(patched["pcSkill"], row, col)
                        ),
                        value(patched["pcSkill"], row, 0),
                    )

    def test_gacha_names_change_without_changing_pools_costs_or_ticket_choices(self):
        import gzip
        import gacha

        original = json.loads(
            gzip.decompress(
                Path(gacha.__file__).with_name("gacha-catalog.json.gz").read_bytes()
            )
        )
        # Existing offline ticket compatibility already removes old draw limits.
        for banner in original["banners"]:
            for button in banner["buttons"]:
                if button["currencyType"] == 2:
                    button["limit"] = 0
        for before, after in zip(original["banners"], gacha.definitions()["banners"]):
            self.assertEqual(
                {k: v for k, v in before.items() if k != "name"},
                {k: v for k, v in after.items() if k != "name"},
            )
            self.assertIsNone(english.JAPANESE.search(after["name"]))
        for unit in gacha.unit_metadata().values():
            self.assertIsNone(english.JAPANESE.search(unit["title"] + unit["name"]))

    def test_native_index_sizes_match_localized_bytes_and_voice_sources_stay_original(
        self,
    ):
        from zip_reader import catalog, asset
        from asset_store import records

        index = catalog()
        for name in english.text_policy():
            path = english.MASTER_PREFIX + name + ".enc"
            self.assertEqual(index[path]["size"], len(asset(path).data))
        for path, record in records().items():
            if "/sound/voice" in path and path in index:
                self.assertEqual(index[path], record)

    def test_prior_artwork_sources_are_restored_without_generated_cards(self):
        from zip_reader import asset
        from asset_store import ArchivedAsset, records

        for path in (
            "3/files/lottery/background/171000067.png",
            "3/files/lottery/name/1012018005.png",
            "4/files/ui/global/global_menu_event/11_1_normal.png",
        ):
            self.assertEqual(
                asset(path).read_bytes(), ArchivedAsset(records()[path]).read_bytes()
            )
        self.assertFalse((english.ROOT / "english-cards.zip").exists())
        self.assertFalse((english.ROOT / "english-images.json").exists())
