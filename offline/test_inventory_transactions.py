"""Resource persistence across grants, spending, deletion, retry and restart."""

# Regression checks for inventory transactions.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import copy
import tempfile
import unittest
from pathlib import Path
from save_store import SaveStore, TABLE_IDENTITIES


class InventoryTransactions(unittest.TestCase):
    def test_all_inventory_types_keep_other_items_and_spent_lifetime_totals(self):
        inventories = {
            t: k
            for t, k in TABLE_IDENTITIES.items()
            if len(k) == 2
            and (t.endswith("Item") or t.endswith("Ticket") or t == "UserCurrency")
        }
        self.assertTrue(
            {
                "UserStaminaTicket",
                "UserSkipTicket",
                "UserStatusBoardItem",
                "UserHeroSublimateItem",
                "UserEventItem",
            }
            <= inventories.keys()
        )
        for table, keys in inventories.items():
            with self.subTest(table=table), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "save.json"
                save = SaveStore(path)

                def push(puts=(), deletes=()):
                    save.apply(
                        {
                            "deltas": [
                                {
                                    "putItems": {table: list(puts)},
                                    "deleteItems": {table: list(deletes)},
                                }
                            ],
                            "checksums": {"after": {table: "native-token"}},
                        }
                    )

                item = keys[1]
                one = {
                    "userId": 1,
                    item: 10,
                    "amount": 5,
                    "cumulativeAmount": 12,
                    "reservedAmount": 0,
                    "signature": 1,
                }
                two = {**one, item: 20}
                other = {**one, "userId": 2}
                push([one, two, other])
                spent = {**one, "amount": 2}
                push([spent])
                push([spent])
                self.assertEqual(
                    SaveStore(path).state["tables"][table], [spent, two, other]
                )
                earned = {**spent, "amount": 6, "cumulativeAmount": 16}
                push([earned])
                self.assertEqual(
                    SaveStore(path).state["tables"][table], [earned, two, other]
                )
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    push([earned, earned])
                self.assertEqual(path.read_bytes(), before)
                push(deletes=[{"userId": 1, item: 10}])
                self.assertEqual(SaveStore(path).state["tables"][table], [two, other])

    def test_stamina_and_ticket_spend_commit_together_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            save = SaveStore(path)
            info = {
                "userId": 1,
                "playerStatus": {
                    "baseSP": 100,
                    "consumedNormalSP": 0,
                    "baseSPUpdatedAt": 123,
                },
            }
            ticket = {
                "userId": 1,
                "skipTicketId": 288000001,
                "amount": 5,
                "cumulativeAmount": 10,
            }

            def update(info, ticket):
                save.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {
                                    "UserInfo": [info],
                                    "UserSkipTicket": [ticket],
                                },
                                "deleteItems": {},
                            }
                        ],
                        "checksums": {
                            "after": {"UserInfo": "status", "UserSkipTicket": "ticket"}
                        },
                    }
                )

            update(info, ticket)
            spent = copy.deepcopy(info)
            spent["playerStatus"].update(baseSP=90, consumedNormalSP=10)
            update(spent, {**ticket, "amount": 4})
            update(spent, {**ticket, "amount": 4})
            self.assertEqual(SaveStore(path).state["tables"]["UserInfo"], [spent])
            self.assertEqual(
                SaveStore(path).state["tables"]["UserSkipTicket"][0]["amount"], 4
            )

    def test_all_missions_bonus_is_issued_once_after_last_mission(self):
        from save_store import REWARD_DEFINITIONS

        stage_id = next(
            int(k)
            for k, d in REWARD_DEFINITIONS.items()
            if d.get("allTasks") and len(d.get("taskIds", [])) >= 3
        )
        definition = REWARD_DEFINITIONS[str(stage_id)]
        tasks = definition["taskIds"]
        with tempfile.TemporaryDirectory() as directory:
            save = SaveStore(Path(directory) / "save.json")
            state = copy.deepcopy(save.state)
            rewards = save._claim_stage_rewards(state, stage_id, True, tasks[:-1])
            self.assertFalse(state["stageRewardClaims"][str(stage_id)].get("allTasks"))
            last = save._claim_stage_rewards(state, stage_id, False, tasks[-1:])
            self.assertEqual(last[-1], definition["allTasks"])
            save._write(state)
            reopened = SaveStore(save.path)
            self.assertEqual(
                reopened._claim_stage_rewards(
                    reopened.state, stage_id, True, tasks + tasks
                ),
                [],
            )

    def test_normal_and_skip_rewards_aggregate_drops_and_preserve_skip_cost_instruction(
        self,
    ):
        from save_store import REWARD_DEFINITIONS

        stage_id = 1010000101102
        falna = REWARD_DEFINITIONS[str(stage_id)]["first"]
        for skips in (0, 1, 5):
            with self.subTest(skips=skips), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "save.json"
                save = SaveStore(path)
                save._write(
                    {
                        "tables": {
                            "UserAdventureStage": [
                                {
                                    "userId": 1,
                                    "adventureStageId": stage_id,
                                    "token": "session",
                                    "tasks": [],
                                }
                            ],
                            "UserSkipTicket": [
                                {"userId": 1, "skipTicketId": 288000001, "amount": 5}
                            ],
                        },
                        "tokens": {},
                    }
                )
                request = {
                    "adventureStageId": stage_id,
                    "token": "session",
                    "skipCount": skips,
                    "adventureGainedItems": [
                        {"itemId": falna["itemId"], "amount": 7},
                        {"itemId": falna["itemId"], "amount": 3},
                    ],
                }
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "Insufficient skip tickets"):
                    save.adventure_complete({**request, "skipCount": 6})
                self.assertEqual(path.read_bytes(), before)
                reply = save.adventure_complete(request)
                params = reply["operation"]["parameters"]
                self.assertEqual(params["skipCount"], skips)
                self.assertEqual(
                    params["gainedItems"],
                    [{"itemId": falna["itemId"], "amount": 10 + falna["amount"]}],
                )
                self.assertEqual(SaveStore(path).adventure_complete(request), reply)
                legacy = copy.deepcopy(save.state)
                pending = next(iter(legacy["adventureCompletions"].values()))
                pending["parameters"].pop("skipCount")
                pending["parameters"]["gainedItems"] = [
                    {"itemId": falna["itemId"], "amount": 10},
                    falna,
                ]
                save._write(legacy)
                self.assertEqual(save.adventure_complete(request), reply)
                save.apply(
                    {
                        "deltas": [],
                        "checksums": {"after": {}},
                        "operations": [
                            {"id": reply["operation"]["id"], "verifier": "native-ack"}
                        ],
                    }
                )
                self.assertNotIn(
                    "operation", SaveStore(path).adventure_complete(request)
                )
                before = path.read_bytes()
                for invalid in (-1, True, 1.5, "1", 1001):
                    with self.assertRaises(ValueError):
                        save.adventure_complete({**request, "skipCount": invalid})
                self.assertEqual(path.read_bytes(), before)

    def test_interrupted_completion_recovers_once_and_new_skips_can_reuse_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            save = SaveStore(path)
            sid = 1010000101102
            stage = {
                "userId": 1,
                "adventureStageId": sid,
                "token": "reused",
                "tasks": [],
            }
            save._write(
                {
                    "tables": {
                        "UserAdventureStage": [stage],
                        "UserSkipTicket": [
                            {"userId": 1, "skipTicketId": 288000001, "amount": 5}
                        ],
                    },
                    "tokens": {},
                }
            )
            request = {
                "adventureStageId": sid,
                "token": "reused",
                "skipCount": 1,
                "adventureGainedItems": [{"itemId": 294000016, "amount": 3}],
            }
            first = save.adventure_complete(request, "first-request")["operation"]
            self.assertEqual(SaveStore(path).pending_adventures(), [first])
            self.assertEqual(
                SaveStore(path).adventure_complete(request, "first-request")[
                    "operation"
                ],
                first,
            )
            save.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [{"id": first["id"], "verifier": "ack"}],
                }
            )
            self.assertEqual(SaveStore(path).pending_adventures(), [])
            second = save.adventure_complete(request, "second-request")["operation"]
            self.assertNotEqual(second["id"], first["id"])
            self.assertEqual(
                second["parameters"]["gainedItems"], request["adventureGainedItems"]
            )
            self.assertEqual(SaveStore(path).pending_adventures(), [second])
            save.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [{**stage, "token": "new-battle"}]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            self.assertEqual(SaveStore(path).pending_adventures(), [])

    def test_normal_battle_reused_token_uses_new_entry_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            save = SaveStore(Path(directory) / "save.json")
            sid = 1010000101102
            stage = {
                "userId": 1,
                "adventureStageId": sid,
                "token": "reused",
                "lastTryDateTime": 100,
                "tasks": [],
            }
            save._write({"tables": {"UserAdventureStage": [stage]}, "tokens": {}})
            request = {
                "adventureStageId": sid,
                "token": "reused",
                "skipCount": 0,
                "adventureGainedItems": [{"itemId": 294000016, "amount": 3}],
            }
            first = save.adventure_complete(request, "first-request")["operation"]
            self.assertEqual(
                save.adventure_complete(request, "retry-with-new-id")["operation"],
                first,
            )
            save.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [{"id": first["id"], "verifier": "ack"}],
                }
            )
            self.assertNotIn(
                "operation", save.adventure_complete(request, "stale-result")
            )
            save.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [
                                    {**stage, "lastTryDateTime": 200}
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            second = save.adventure_complete(request, "second-request")["operation"]
            self.assertNotEqual(second["id"], first["id"])
            self.assertEqual(
                second["parameters"]["gainedItems"], request["adventureGainedItems"]
            )
