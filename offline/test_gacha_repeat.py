# Regression checks for gacha repeat.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import tempfile
import unittest
from pathlib import Path
from save_store import SaveStore
import gacha


class RepeatTests(unittest.TestCase):
    def test_consumed_free_repeat_replays_same_operation_without_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            s = SaveStore(Path(d) / "save.json")
            s._write(
                {"tables": {"UserInfo": [{"userId": 1}], "UserPC": []}, "tokens": {}}
            )
            gacha.prepare(s)
            b = next(
                b
                for b in gacha.definitions()["banners"]
                if any(v["cost"] == 0 and v.get("limit") == 1 for v in b["buttons"])
            )
            s.gachaBanners = [b]
            s.gachaWindows = {}
            gacha.prepare(s)
            v = next(v for v in b["buttons"] if v["cost"] == 0 and v.get("limit") == 1)
            request = {
                "lotteryId": b["id"],
                "buttonIndex": v["buttonType"],
                "pickCount": v["count"],
                "consumeAmount": 0,
                "progressCount": 0,
            }
            response = gacha.draw(s, request, "first")
            s.state["acknowledgedOperations"] = {
                str(response["operation"]["id"]): "verified"
            }
            s._write(s.state)
            before = s.path.read_bytes()
            self.assertEqual(gacha.draw(s, request, "repeat-stale"), response)
            self.assertEqual(
                gacha.draw(s, dict(request, progressCount=1), "repeat-current"),
                response,
            )
            self.assertEqual(s.path.read_bytes(), before)
            # Existing saves made before banner/button identity metadata.
            s.state["offlineGacha"]["lastDraw"].pop("bannerId")
            s.state["offlineGacha"]["lastDraw"].pop("buttonType")
            s._write(s.state)
            before = s.path.read_bytes()
            self.assertEqual(gacha.draw(s, request, "repeat-legacy"), response)
            self.assertEqual(s.path.read_bytes(), before)
            row = next(
                r for r in response["data"]["UserLottery"] if r["lotteryId"] == b["id"]
            )
            self.assertEqual(
                next(x for x in row["buttons"] if x["buttonType"] == v["buttonType"])[
                    "count"
                ],
                1,
            )
