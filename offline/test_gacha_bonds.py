# Regression checks for gacha bonds.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from save_store import SaveStore
import gacha

PC = 1012011001
BOND = 299000299


class BondTests(unittest.TestCase):
    def test_different_banners_accumulate_bonds_and_preserve_spent_history(self):
        banners = []
        groups = gacha.definitions()["groups"]
        for b in gacha.definitions()["banners"]:
            for v in b["buttons"]:
                if v.get("step") or v["currencyType"] != 1:
                    continue
                pools = [
                    groups.get(str(v[k]), []) for k in ("group", "fixedGroup") if v[k]
                ]
                if pools and all(PC in p for p in pools):
                    banners.append((b, v))
                    break
        self.assertGreaterEqual(len(banners), 2)
        with tempfile.TemporaryDirectory() as d:
            save = SaveStore(Path(d) / "save.json")
            save._write(
                {
                    "tables": {
                        "UserInfo": [{"userId": 1}],
                        "UserPC": [{"pcId": PC}],
                        "UserCurrency": [
                            {"currencyId": 205000001, "cumulativeAmount": 100000}
                        ],
                        "UserLimitBreakItem": [
                            {
                                "userId": 1,
                                "limitBreakItemId": BOND,
                                "amount": 2,
                                "cumulativeAmount": 5,
                                "signature": 1,
                                "bookEntryState": 1,
                            }
                        ],
                    },
                    "tokens": {},
                }
            )
            save.gachaBanners = [b for b, v in banners[:2]]
            expected_amount = 2
            expected_cumulative = 5
            for index, (b, v) in enumerate(banners[:2]):
                gacha.prepare(save)
                request = {
                    "lotteryId": b["id"],
                    "buttonIndex": v["buttonType"],
                    "pickCount": v["count"],
                    "consumeAmount": v["cost"],
                    "progressCount": 0,
                }
                with patch("gacha.secrets.choice", return_value=PC):
                    reply = gacha.draw(save, request, str(index))
                expected_amount += v["count"]
                expected_cumulative += v["count"]
                item = reply["UserLimitBreakItem"][0]
                self.assertEqual(item["amount"], expected_amount)
                self.assertEqual(item["cumulativeAmount"], expected_cumulative)
                operation = reply["operation"]["id"]
                # Native table construction historically resets cumulative to amount.
                row = {
                    "userId": 1,
                    "limitBreakItemId": BOND,
                    "amount": item["amount"],
                    "cumulativeAmount": item["amount"],
                    "signature": operation,
                    "bookEntryState": 1,
                }
                save.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserLimitBreakItem": [row]},
                                "deleteItems": {},
                            }
                        ],
                        "checksums": {"after": {"UserLimitBreakItem": "native-token"}},
                        "operations": [{"id": operation, "verifier": "verified"}],
                    }
                )
                actual = save.state["tables"]["UserLimitBreakItem"][0]
                self.assertEqual(actual["amount"], expected_amount)
                self.assertEqual(actual["cumulativeAmount"], expected_cumulative)
                balance_before = dict(actual)
                sequence_before = save.state["offlineGacha"]["sequence"]
                self.assertEqual(gacha.draw(save, request, str(index)), reply)
                self.assertEqual(
                    save.state["tables"]["UserLimitBreakItem"][0], balance_before
                )
                self.assertEqual(
                    save.state["offlineGacha"]["sequence"], sequence_before
                )
                # Later spending must remain possible after the grant commits.
                spent = dict(actual, amount=actual["amount"] - 1)
                save.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserLimitBreakItem": [spent]},
                                "deleteItems": {},
                            }
                        ],
                        "checksums": {"after": {"UserLimitBreakItem": "spent-token"}},
                    }
                )
                expected_amount -= 1
                self.assertEqual(
                    save.state["tables"]["UserLimitBreakItem"][0]["amount"],
                    expected_amount,
                )
                save = SaveStore(save.path)
                save.gachaBanners = [x for x, y in banners[:2]]
