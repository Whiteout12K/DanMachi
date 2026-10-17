"""All retained free offers work without invented balances or ticket rows."""

# Regression checks for gacha balances.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from save_store import SaveStore
import gacha


class BalanceTests(unittest.TestCase):
    def store(self, d, banner):
        save = SaveStore(Path(d) / "save.json")
        save._write(
            {
                "tables": {
                    "UserInfo": [{"userId": 1}],
                    "UserCurrency": [{"currencyId": 205000002, "cumulativeAmount": 0}],
                    "UserPC": [],
                },
                "tokens": {},
            }
        )
        save.gachaBanners = [banner]
        gacha.prepare(save)
        return save

    def request(self, b, v):
        return {
            "lotteryId": b["id"],
            "buttonIndex": v["buttonType"],
            "progressCount": 0,
            "pickCount": v["count"],
            "consumeAmount": v["cost"],
        }

    def test_every_retained_free_offer_without_iris_or_tickets(self):
        count = 0
        for b in gacha.definitions()["banners"]:
            for v in b["buttons"]:
                if v["cost"] != 0:
                    continue
                with self.subTest(
                    banner=b["id"], button=v["buttonType"], step=v.get("step")
                ):
                    with tempfile.TemporaryDirectory() as d:
                        save = self.store(d, b)
                        row = save.state["tables"]["UserLottery"][0]
                        next(
                            x
                            for x in row["buttons"]
                            if x["buttonType"] == v["buttonType"]
                        )["currentStepIndex"] = v.get("step", 1)
                        save._write(save.state)
                        with patch(
                            "gacha.secrets.choice", side_effect=lambda pool: pool[0]
                        ):
                            reply = gacha.draw(save, self.request(b, v), "free-check")
                        self.assertEqual(reply["code"], 0)
                        self.assertEqual(len(reply["lotteryPCs"]), v["count"])
                        self.assertEqual(
                            save.state["tables"]["UserCurrency"],
                            [{"currencyId": 205000002, "cumulativeAmount": 0}],
                        )
                        self.assertNotIn("UserGachaTicket", save.state["tables"])
                        self.assertEqual(save.state.get("localIrisSpent", 0), 0)
                        self.assertEqual(
                            gacha.draw(
                                SaveStore(save.path), self.request(b, v), "free-check"
                            ),
                            reply,
                        )
                        count += 1
        self.assertGreater(count, 0)
        print("Retained free offers verified:", count)

    def test_missing_iris_paid_offer_rejected_without_mutation(self):
        b = next(
            b
            for b in gacha.definitions()["banners"]
            if any(
                v["cost"] > 0 and v["currencyType"] == 1 and not v.get("step")
                for v in b["buttons"]
            )
        )
        v = next(
            v
            for v in b["buttons"]
            if v["cost"] > 0 and v["currencyType"] == 1 and not v.get("step")
        )
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d, b)
            before = copy.deepcopy(save.state)
            disk = save.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Not enough earned Iris"):
                gacha.draw(save, self.request(b, v), "paid-check")
            self.assertEqual(save.state, before)
            self.assertEqual(save.path.read_bytes(), disk)

    def test_missing_ticket_rejected_without_mutation(self):
        b = next(
            b
            for b in gacha.definitions()["banners"]
            if any(v["cost"] > 0 and v["currencyType"] == 2 for v in b["buttons"])
        )
        v = next(v for v in b["buttons"] if v["cost"] > 0 and v["currencyType"] == 2)
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d, b)
            disk = save.path.read_bytes()
            with self.assertRaisesRegex(
                ValueError, "Not enough unexpired Gacha tickets"
            ):
                gacha.draw(save, self.request(b, v), "ticket-check")
            self.assertEqual(save.path.read_bytes(), disk)
