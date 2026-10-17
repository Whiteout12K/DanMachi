# Regression checks for tutorial banner.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import unittest
import tempfile
from pathlib import Path
from save_store import SaveStore
import tutorial_banner as banner
import gacha


class BannerTests(unittest.TestCase):
    def test_reservation_and_restart_are_not_completion(self):
        state = {}
        self.assertTrue(banner.available(state))
        state["tutorialDraw"] = {"pcId": 1011018002}
        self.assertTrue(banner.available(state))
        state["acknowledgedOperations"] = {"100000001": "verified"}
        self.assertFalse(banner.available(state))

    def test_row_remains_until_native_ack_and_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            save = SaveStore(Path(d) / "save.json")
            save.state["tables"]["UserInfo"] = [{"userId": 1}]
            for _ in range(2):
                gacha.prepare(save)
                self.assertEqual(
                    sum(
                        r["lotteryId"] == banner.BANNER_ID
                        for r in save.state["tables"]["UserLottery"]
                    ),
                    1,
                )
            save.state["tutorialDraw"] = {"pcId": 1011018002}
            gacha.prepare(save)
            self.assertTrue(
                any(
                    r["lotteryId"] == banner.BANNER_ID
                    for r in save.state["tables"]["UserLottery"]
                )
            )
            save.state["acknowledgedOperations"] = {"100000001": "verified"}
            gacha.prepare(save)
            self.assertFalse(
                any(
                    r["lotteryId"] == banner.BANNER_ID
                    for r in save.state["tables"]["UserLottery"]
                )
            )
