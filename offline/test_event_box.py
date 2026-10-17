# Regression checks for event box.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import json
import tempfile
import unittest
from pathlib import Path
from save_store import SaveStore
import event_box


class EventBoxTests(unittest.TestCase):
    def test_show_preserves_progress_and_does_not_duplicate_native_box(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "player.json"
            path.write_text(
                json.dumps({"tables": {"UserInfo": [{"userId": "test"}]}, "tokens": {}})
            )
            save = SaveStore(path)
            reply = event_box.show(save, {"eventBoxId": 193000076})
            self.assertEqual(reply["code"], 0)
            self.assertEqual(reply["data"], {})
            self.assertNotIn("UserEventBox", reply)
            self.assertGreater(len(reply["UserEventBoxContent"]), 0)
            save.state["tables"]["UserEventBoxContent"][0]["pickedAmount"] = 1
            again = event_box.show(save, {"eventBoxId": 193000076})
            self.assertEqual(again["UserEventBoxContent"][0]["pickedAmount"], 1)
            self.assertEqual(len(save.state["tables"]["UserEventBox"]), 1)
            self.assertEqual(
                len(reply["UserEventBoxContent"]), len(again["UserEventBoxContent"])
            )
            before = json.dumps(save.state, sort_keys=True)
            self.assertEqual(event_box.show(save, {"eventBoxId": -1}), {"code": 1003})
            self.assertEqual(before, json.dumps(save.state, sort_keys=True))


class EventBoxDrawTests(unittest.TestCase):
    def store(self, directory, bid=193000013):
        path = Path(directory) / "player.json"
        item = event_box.draw_definitions()[0][bid]["item"]
        path.write_text(
            json.dumps(
                {
                    "tables": {
                        "UserInfo": [{"userId": 1}],
                        "UserEventItem": [
                            {
                                "userId": 1,
                                "eventItemId": item,
                                "amount": 1000,
                                "cumulativeAmount": 1000,
                                "reservedAmount": 0,
                                "signature": 1,
                                "bookEntryState": 1,
                            }
                        ],
                    },
                    "tokens": {},
                }
            )
        )
        save = SaveStore(path)
        event_box.show(save, {"eventBoxId": bid})
        return save

    def test_anniversary_draw_payment_counts_rewards_retry_and_restart(self):
        for bid in (193000013, 193000027, 193000028):
            with self.subTest(bid=bid), tempfile.TemporaryDirectory() as d:
                save = self.store(d, bid)
                request = {"eventBoxId": bid, "drawCount": 10}
                response = event_box.draw(save, request, "draw-1")
                expected = 1000 - 10 * event_box.draw_definitions()[0][bid]["cost"]
                self.assertEqual(
                    save.state["tables"]["UserEventItem"][0]["amount"], expected
                )
                self.assertEqual(
                    save.state["tables"]["UserEventItem"][0]["cumulativeAmount"], 1000
                )
                self.assertEqual(len(response["chosenItems"]), 10)
                self.assertEqual(
                    response["operation"]["parameters"]["chosenItems"],
                    response["chosenItems"],
                )
                self.assertEqual(
                    response["operation"]["parameters"]["currentStepContents"],
                    response["currentStepContents"],
                )
                self.assertEqual(
                    sum(
                        r["pickedAmount"]
                        for r in save.state["tables"]["UserEventBoxContent"]
                    ),
                    10,
                )
                self.assertEqual(
                    save.state["tables"]["UserEventBoxStep"][0]["drawCount"], 10
                )
                self.assertEqual(
                    save.state["tables"]["UserEventBox"][0]["totalDrawCount"], 10
                )
                self.assertAlmostEqual(
                    sum(r["rate"] for r in response["currentStepContents"]), 1
                )
                reopened = SaveStore(save.path)
                self.assertEqual(event_box.draw(reopened, request, "draw-1"), response)
                self.assertEqual(event_box.pending(reopened), response["operation"])
                with self.assertRaises(ValueError):
                    event_box.draw(reopened, request, "draw-2")
                self.assertEqual(
                    reopened.state["tables"]["UserEventItem"][0]["amount"], expected
                )
                self.assertNotIn("UserAchievement", response["data"])

    def test_invalid_and_unaffordable_draws_are_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            before = save.path.read_bytes()
            for request in (
                {"eventBoxId": 193000013, "drawCount": 0},
                {"eventBoxId": 193000013, "drawCount": 1001},
                {"eventBoxId": True, "drawCount": 1},
                {"eventBoxId": 193000013, "drawCount": 101},
            ):
                with self.assertRaises(ValueError):
                    event_box.draw(save, request, "invalid")
                self.assertEqual(save.path.read_bytes(), before)

    def test_stale_client_cannot_refund_payment_or_undo_count_and_ack_finishes_recovery(
        self,
    ):
        import copy, hashlib
        from save_store import pack

        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            old = copy.deepcopy(save.state["tables"])
            response = event_box.draw(
                save, {"eventBoxId": 193000013, "drawCount": 1}, "draw"
            )
            names = list(response["data"])
            expected = copy.deepcopy(response["data"])
            stale = {n: old[n] for n in names}
            save.apply(
                {
                    "deltas": [{"putItems": stale, "deleteItems": {}}],
                    "checksums": {
                        "after": {
                            n: hashlib.md5(pack(stale[n])).hexdigest() for n in names
                        }
                    },
                    "operations": [
                        {
                            "id": response["operation"]["id"],
                            "verifier": "native-verified",
                        }
                    ],
                }
            )
            for name in names:
                self.assertEqual(save.state["tables"][name], expected[name])
                self.assertEqual(
                    save.state["tokens"][name],
                    hashlib.md5(pack(expected[name])).hexdigest(),
                )
            self.assertIsNone(event_box.pending(save))
            self.assertEqual(event_box.recovery(save), ({}, {}))
            next_reply = event_box.draw(
                save, {"eventBoxId": 193000013, "drawCount": 1}, "draw-2"
            )
            self.assertNotEqual(
                next_reply["operation"]["id"], response["operation"]["id"]
            )

    def test_limited_prize_is_never_selected_after_its_quantity(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            with patch("secrets.randbelow", return_value=0):
                reply = event_box.draw(
                    save, {"eventBoxId": 193000013, "drawCount": 100}, "draw"
                )
            definitions = event_box.draw_definitions()[1]
            for row in save.state["tables"]["UserEventBoxContent"]:
                definition = definitions[row["eventBoxContentId"]]
                if definition["limited"]:
                    self.assertLessEqual(row["pickedAmount"], definition["quantity"])

    def test_original_reset_prizes_gate_next_round_without_charging_or_granting(self):
        import copy

        with tempfile.TemporaryDirectory() as d:
            bid = 193000027
            save = self.store(d, bid)
            ordered = sorted(
                event_box.definitions()[1][event_box.definitions()[0][bid]]
            )
            first, second = ordered[0][1], ordered[1][1]
            requirements = event_box.reset_prizes()[first]
            self.assertTrue(requirements)
            before = save.path.read_bytes()
            self.assertEqual(
                event_box.show(save, {"eventBoxId": bid, "eventBoxStepId": second}),
                {"code": 1003},
            )
            self.assertEqual(before, save.path.read_bytes())
            for row in save.state["tables"]["UserEventBoxContent"]:
                if row["eventBoxContentId"] in requirements:
                    row["pickedAmount"] = requirements[row["eventBoxContentId"]]
            save._write(save.state)
            balance = copy.deepcopy(save.state["tables"]["UserEventItem"])
            reply = event_box.show(save, {"eventBoxId": bid, "eventBoxStepId": second})
            self.assertEqual(reply["code"], 0)
            self.assertEqual(
                save.state["tables"]["UserEventBox"][0]["currentStepId"], second
            )
            self.assertEqual(save.state["tables"]["UserEventItem"], balance)
            self.assertNotIn("operation", reply)
            self.assertEqual(
                {r["contentId"] for r in reply["currentStepContents"]},
                {
                    r["eventBoxContentId"]
                    for r in save.state["tables"]["UserEventBoxContent"]
                    if r["eventBoxStepId"] == second
                },
            )
