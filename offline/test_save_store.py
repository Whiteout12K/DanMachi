# Regression checks for save store.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Two original-checksum cases require the absent native-pc-checksum-fixture.json;
# that missing fixture is a known coverage gap, not a fabricated replacement.
import tempfile
import unittest
from pathlib import Path
from save_store import SaveStore, pack, unpack, wire_tables


class PersistentAccountTest(unittest.TestCase):
    def test_bootstrap_costume_repair_preserves_progress_and_existing_outfits(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "save.json")
            home = {
                "userId": 1,
                "characterId": 100000005,
                "costumeId": 1022027000,
                "characterState": 3,
                "touchCountOther": 7,
            }
            outfit = {"userId": 1, "costumeId": 1021001000, "costumeState": 3}
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserCommunicationCharacter": [home],
                                "UserCharacterCostume": [outfit],
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            self.assertTrue(store.repair_bootstrap_costume())
            self.assertFalse(store.repair_bootstrap_costume())
            restored = SaveStore(store.path)
            self.assertEqual(
                restored.state["tables"]["UserCommunicationCharacter"], [home]
            )
            self.assertEqual(
                restored.state["tables"]["UserCharacterCostume"],
                [outfit, {"userId": 1, "costumeId": 1022027000, "costumeState": 2}],
            )
            token = restored.state["tokens"]["UserCharacterCostume"]
            restored.state["tables"]["UserCharacterCostume"][-1]["costumeState"] = 3
            self.assertFalse(restored.repair_bootstrap_costume())
            self.assertEqual(restored.state["tokens"]["UserCharacterCostume"], token)

    def test_bootstrap_costume_repair_does_not_unlock_other_or_locked_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "save.json")
            for character, costume, status in (
                (100000005, 1022027005, 3),
                (100000001, 1021001000, 3),
                (100000005, 1022027000, 1),
            ):
                store.state["tables"]["UserCommunicationCharacter"] = [
                    {
                        "userId": 1,
                        "characterId": character,
                        "costumeId": costume,
                        "characterState": status,
                    }
                ]
                self.assertFalse(store.repair_bootstrap_costume())
                self.assertNotIn("UserCharacterCostume", store.state["tables"])

    def test_shop_read_state_merges_and_persists_without_losing_other_products(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)

            def push(rows):
                store.apply(
                    {
                        "deltas": [
                            {"putItems": {"UserShopProduct": rows}, "deleteItems": {}}
                        ],
                        "checksums": {"after": {"UserShopProduct": "native-token"}},
                    }
                )

            push(
                [
                    {
                        "userId": 1,
                        "shopProductId": 207000008,
                        "readState": 1,
                        "count": 0,
                    },
                    {
                        "userId": 1,
                        "shopProductId": 207000023,
                        "readState": 1,
                        "count": 2,
                    },
                ]
            )
            push(
                [{"userId": 1, "shopProductId": 207000008, "readState": 2, "count": 0}]
            )
            restored = SaveStore(path)
            self.assertEqual(
                [
                    (r["shopProductId"], r["readState"], r["count"])
                    for r in restored.state["tables"]["UserShopProduct"]
                ],
                [(207000008, 2, 0), (207000023, 1, 2)],
            )
            self.assertEqual(
                restored.state["tokens"]["UserShopProduct"], "native-token"
            )

    def test_inventory_merges_separate_falna_rewards_without_losing_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)

            def push(rows):
                store.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserStatusBoardItem": rows},
                                "deleteItems": {},
                            }
                        ],
                        "checksums": {"after": {}},
                    }
                )

            push(
                [
                    {"userId": 1, "statusBoardItemId": 294000001, "amount": 10},
                    {"userId": 1, "statusBoardItemId": 294000016, "amount": 2},
                ]
            )
            push([{"userId": 1, "statusBoardItemId": 294000001, "amount": 8}])
            self.assertEqual(
                {
                    r["statusBoardItemId"]: r["amount"]
                    for r in SaveStore(path).state["tables"]["UserStatusBoardItem"]
                },
                {294000001: 8, 294000016: 2},
            )

    def test_backfill_delivered_once_through_native_stage_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            stage = {
                "userId": 1,
                "adventureStageId": 1010000101101,
                "token": "repeat",
                "state": 4,
                "firstCompleteDateTime": 100,
                "tasks": [],
            }
            store.apply(
                {
                    "deltas": [
                        {"putItems": {"UserAdventureStage": [stage]}, "deleteItems": {}}
                    ],
                    "checksums": {"after": {}},
                }
            )
            store.prepare_reward_backfill()
            request = {"adventureStageId": stage["adventureStageId"], "token": "repeat"}
            first = store.adventure_complete(request)
            self.assertEqual(
                first["operation"]["parameters"]["gainedItems"],
                [{"itemId": 205000002, "amount": 10000}],
            )
            self.assertEqual(SaveStore(path).adventure_complete(request), first)
            self.assertIsNone(store.pending_rewards())
            self.assertEqual(
                store.state["rewardBackfills"][0]["completionId"],
                first["operation"]["id"],
            )
            stage["token"] = "next"
            store.apply(
                {
                    "deltas": [
                        {"putItems": {"UserAdventureStage": [stage]}, "deleteItems": {}}
                    ],
                    "checksums": {"after": {}},
                }
            )
            self.assertEqual(
                store.adventure_complete(dict(request, token="next"))["operation"][
                    "parameters"
                ]["gainedItems"],
                [],
            )

    def test_achievement_rewards_are_native_persistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            row = {
                "userId": 1,
                "achievementId": 6050000001,
                "completedAt": 100,
                "state": 3,
                "progressParam": 1,
                "signature": 9,
                "lastResetAt": 0,
                "readState": 1,
            }
            store.apply(
                {
                    "deltas": [
                        {"putItems": {"UserAchievement": [row]}, "deleteItems": {}}
                    ],
                    "checksums": {"after": {}},
                }
            )
            request = {
                "achievementIds": [{"achievementId": 6050000001, "completedAt": 100}]
            }
            first = store.achievement_complete(request)
            self.assertEqual(first["operation"]["type"], 6000)
            self.assertEqual(first["operation"]["token"], "")
            self.assertIs(
                type(first["operation"]["parameters"]["issueCasinoMedal"]), int
            )
            self.assertEqual(first["operation"]["parameters"]["issueAmount"], 0)
            self.assertEqual(
                first["operation"]["parameters"]["receivedItems"],
                [{"itemId": 294000001, "amount": 10}],
            )
            self.assertEqual(first["operation"]["parameters"]["UserAchievement"], [row])
            self.assertEqual(SaveStore(path).achievement_complete(request), first)
            self.assertEqual(store.state["tables"]["UserAchievement"], [row])
            with self.assertRaises(ValueError):
                store.achievement_complete(
                    {"achievementIds": [request["achievementIds"][0]] * 2}
                )
            with self.assertRaises(ValueError):
                store.achievement_complete(
                    {
                        "achievementIds": [
                            {"achievementId": 6050000001, "completedAt": 200}
                        ]
                    }
                )
            store.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [
                        {"id": first["operation"]["id"], "verifier": "native-ack"}
                    ],
                }
            )
            self.assertEqual(SaveStore(path).achievement_complete(request), {"code": 0})
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("achievementClaims", store.state)

    def test_stamina_mission_does_not_display_or_grant_iris(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "save.json")
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAchievement": [
                                    {
                                        "userId": 1,
                                        "achievementId": 6010000001,
                                        "completedAt": 100,
                                        "state": 3,
                                    }
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            params = store.achievement_complete(
                {"achievementIds": [{"achievementId": 6010000001, "completedAt": 100}]}
            )["operation"]["parameters"]
            self.assertEqual(params["issueStamina"], 50)
            self.assertEqual(params["issueAmount"], 0)
            self.assertEqual(params["receivedItems"], [])

    def test_legacy_attack_repair_preserves_training_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            # Use the native serialization fixture, changing only the old draw identity.
            fixture = __import__("json").loads(
                (
                    Path(__file__).parent
                    / "compatibility_assets/native-pc-checksum-fixture.json"
                ).read_text()
            )
            rows = fixture.get("rows", fixture.get("UserPC"))
            if rows is None:
                rows = fixture["data"]["UserPC"]
            import copy

            pc = copy.deepcopy(rows[0])
            pc["pcId"] = 1011099002
            for slot in pc["skillSlots"]:
                slot["skillId"] = 109001001 if slot["skillSlotNumber"] in (1, 8) else 0
            store.state["tables"]["UserPC"] = [pc]
            store.state["tutorialDraw"] = {"pcId": 1011099002}
            store._write(store.state)
            self.assertTrue(store.repair_legacy_tutorial_attack())
            after = store.state["tables"]["UserPC"][0]
            self.assertEqual(
                [
                    s["skillId"]
                    for s in after["skillSlots"]
                    if s["skillSlotNumber"] in (1, 8)
                ],
                [109001039, 109001039],
            )
            self.assertEqual(after["totalExp"], pc["totalExp"])
            self.assertEqual(after["jobs"], pc["jobs"])
            self.assertFalse(SaveStore(path).repair_legacy_tutorial_attack())

    def test_familia_quest_notification_persists_without_fake_rewards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            before = store.state["tables"].copy()
            self.assertEqual(store.familia_record({"recordType": 401})["code"], 0)
            store.familia_record({"recordType": 401})
            self.assertEqual(
                SaveStore(path).state["familiaNotifications"], {"401": True}
            )
            self.assertEqual(store.state["tables"], before)
            with self.assertRaises(ValueError):
                store.familia_record({"recordType": 999})
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("familiaNotifications", store.state)

    def test_town_refresh_deletes_old_conversation_and_keeps_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            old = {
                "userId": 1,
                "characterId": 101000099,
                "createdAt": 100,
                "talkCount": 0,
            }
            new = dict(old, createdAt=200)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {"UserTownCommunication": [old]},
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {"UserTownCommunication": [new]},
                            "deleteItems": {"UserTownCommunication": [old]},
                        }
                    ],
                    "checksums": {"after": {"UserTownCommunication": "new-token"}},
                }
            )
            reloaded = SaveStore(path)
            self.assertEqual(reloaded.state["tables"]["UserTownCommunication"], [new])
            self.assertEqual(
                reloaded.state["tokens"]["UserTownCommunication"], "new-token"
            )

    def test_stage_completion_uses_native_operation_once_per_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [
                                    {
                                        "userId": 1,
                                        "adventureStageId": 1010000101101,
                                        "token": "session-one",
                                        "tasks": [
                                            {
                                                "adventureStageTaskId": 682000001,
                                                "state": 0,
                                            }
                                        ],
                                    }
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            request = {
                "adventureStageId": 1010000101101,
                "token": "session-one",
                "adventureGainedItems": [{"itemId": 205000002, "amount": 408}],
                "adventureStageTaskIds": [682000001],
            }
            first = store.adventure_complete(request)
            self.assertEqual(first["operation"]["type"], 5000)
            self.assertEqual(
                first["operation"]["parameters"]["gainedItems"],
                [
                    {"itemId": 205000002, "amount": 10408},
                    {"itemId": 205000001, "amount": 1},
                ],
            )
            self.assertEqual(SaveStore(path).adventure_complete(request), first)
            store.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [
                        {"id": first["operation"]["id"], "verifier": "native-verifier"}
                    ],
                }
            )
            self.assertNotIn("operation", SaveStore(path).adventure_complete(request))
            self.assertNotIn("UserCurrency", store.state["tables"])
            with self.assertRaises(ValueError):
                store.adventure_complete(dict(request, token="unknown-session"))
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [
                                    {
                                        "userId": 1,
                                        "adventureStageId": 1010000101101,
                                        "token": "session-two",
                                        "tasks": [
                                            {
                                                "adventureStageTaskId": 682000001,
                                                "state": 0,
                                            }
                                        ],
                                    }
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            with self.assertRaises(ValueError):
                store.adventure_complete(
                    dict(request, token="session-two", adventureStageTaskIds=[999])
                )
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("adventureCompletions", store.state)

    def test_reward_backfill_is_native_persistent_and_not_reissued(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [
                                    {
                                        "userId": 1,
                                        "adventureStageId": 1010000101102,
                                        "state": 4,
                                        "tasks": [
                                            {
                                                "adventureStageTaskId": 682000004,
                                                "state": 2,
                                            }
                                        ],
                                    }
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            store.prepare_reward_backfill()
            pending = store.pending_rewards()
            self.assertEqual(pending["type"], 2000)
            self.assertEqual(
                pending["parameters"]["receivedItems"],
                [
                    {"itemId": 294000016, "amount": 2},
                    {"itemId": 205000001, "amount": 1},
                ],
            )
            self.assertNotIn("UserCurrency", store.state["tables"])
            store = SaveStore(path)
            store.prepare_reward_backfill()
            self.assertEqual(len(store.state["rewardBackfills"]), 1)
            self.assertEqual(store.pending_rewards(), pending)
            store.apply(
                {
                    "deltas": [],
                    "checksums": {"after": {}},
                    "operations": [
                        {"id": pending["id"], "verifier": "native-reward-ack"}
                    ],
                }
            )
            self.assertIsNone(SaveStore(path).pending_rewards())
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("stageRewardClaims", store.state)

    def test_story_completion_without_combat_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "save.json")
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserAdventureStage": [
                                    {
                                        "userId": 1,
                                        "adventureStageId": 1010000101103,
                                        "token": "",
                                        "tasks": [],
                                        "state": 1,
                                    }
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            request = {
                "adventureStageId": 1010000101103,
                "token": "1-story-session",
                "adventureRecord": {
                    "turnCount": 0,
                    "deathCount": 0,
                    "normalAttackCount": 0,
                },
            }
            self.assertEqual(
                store.adventure_complete(request)["operation"]["type"], 5000
            )
            with self.assertRaises(ValueError):
                store.adventure_complete(
                    dict(
                        request,
                        token="1-fake",
                        adventureGainedItems=[{"itemId": 205000002, "amount": 1}],
                    )
                )

    def test_consumed_resources_are_replaced_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {"UserInfo": [{"userId": 1000000001}]},
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            resources, tokens = store.resources()
            consumed = dict(
                resources["UserItemToken"][0], consumer=70000, value=6010000001
            )
            store.apply(
                {
                    "deltas": [
                        {"putItems": {}, "deleteItems": {"UserItemToken": [consumed]}}
                    ],
                    "checksums": {"after": {}},
                }
            )
            resources, tokens = store.resources()
            self.assertEqual(len(resources["UserItemToken"]), 100)
            self.assertEqual(len(resources["UserRandomSeed"]), 100)
            self.assertNotIn(
                consumed["signature"],
                [r["signature"] for r in resources["UserItemToken"]],
            )
            self.assertEqual(SaveStore(path).state, store.state)
            self.assertEqual(store.resources(), (resources, tokens))
            store.reset({"data": {}, "dataTokens": {}})
            self.assertEqual(store.resources(), ({}, {}))

    def test_friendship_milestones_persist_without_duplicate_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserCharacter": [
                                    {"userId": 1, "characterId": 101000099}
                                ]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            request = {
                "friendshipStates": [
                    {
                        "characterId": 101000099,
                        "friendship": 100,
                        "friendshipLv": 3,
                        "userHeroType": 0,
                    }
                ]
            }
            self.assertEqual(store.friendship_complete(request)["code"], 0)
            first = store.state.copy()
            store.friendship_complete(request)
            self.assertEqual(first, SaveStore(path).state)
            with self.assertRaises(ValueError):
                store.friendship_complete(
                    {
                        "friendshipStates": [
                            dict(request["friendshipStates"][0], characterId=999)
                        ]
                    }
                )
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("friendshipMilestones", store.state)

    def test_pc_checksum_matches_observed_original_client(self):
        import json, hashlib
        from save_store import canonical_pcs

        fixture = json.loads(
            (
                Path(__file__).parent
                / "compatibility_assets/native-pc-checksum-fixture.json"
            ).read_text()
        )
        self.assertEqual(
            hashlib.md5(pack(canonical_pcs(fixture["rows"]))).hexdigest(),
            fixture["native_checksum"],
        )

    def test_tutorial_draw_is_persistent_and_once_per_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)
            from save_store import PC_FIELD_ORDER

            pc = {k: 0 for k in PC_FIELD_ORDER}
            pc.update(
                userId=1,
                pcId=1011001001,
                skillSlots=[],
                jobs=[],
                jobSlots=[],
                isUnlockedHeroSublimate=False,
            )
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {"UserInfo": [{"userId": 1}], "UserPC": [pc]},
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {}},
                }
            )
            request = {"lotteryId": 171001765, "pcId": 1011018002}
            first = store.tutorial_draw(request)
            self.assertEqual(SaveStore(path).tutorial_draw(request), first)
            self.assertEqual(len(store.state["tables"]["UserPC"]), 1)
            self.assertEqual(first["operation"]["type"], 1001)
            self.assertEqual(first["data"]["lotteryPCs"], first["lotteryPCs"])
            self.assertEqual(
                first["operation"]["parameters"]["lotteryPCs"], first["lotteryPCs"]
            )
            self.assertNotIn("UserPC", first["data"])
            self.assertEqual(
                first["operation"]["parameters"]["UserPC"], [{"pcId": request["pcId"]}]
            )
            self.assertEqual(store.tutorial_draw(dict(request, pcId=1011001003)), first)
            store.reset({"data": {}, "dataTokens": {}})
            self.assertNotIn("tutorialDraw", store.state)
            with self.assertRaises(ValueError):
                store.tutorial_draw(request)

    def test_area_identity_retains_other_areas(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "save.json")

            def update(rows):
                store.apply(
                    {
                        "deltas": [{"putItems": {"UserArea": rows}, "deleteItems": {}}],
                        "checksums": {"after": {}},
                    }
                )

            update(
                [
                    {"userId": 1, "areaId": 10, "encountCount": 0},
                    {"userId": 1, "areaId": 20, "encountCount": 0},
                ]
            )
            update([{"userId": 1, "areaId": 10, "encountCount": 1}])
            self.assertEqual(
                [r["encountCount"] for r in store.state["tables"]["UserArea"]], [1, 0]
            )

    def test_episode_difficulty_updates_keep_other_episodes_and_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)

            def update(puts, deletes=None):
                store.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserEpisodeDifficulty": puts},
                                "deleteItems": {"UserEpisodeDifficulty": deletes or []},
                            }
                        ],
                        "checksums": {
                            "after": {"UserEpisodeDifficulty": "episode-token"}
                        },
                    }
                )

            first = {"userId": 1, "episodeId": 7160000101, "difficulty": 1}
            second = {"userId": 1, "episodeId": 7030000101, "difficulty": 1}
            update([first, second])
            changed = {**first, "difficulty": 2}
            update([changed])
            self.assertEqual(
                SaveStore(path).state["tables"]["UserEpisodeDifficulty"],
                [changed, second],
            )
            update([], [{"userId": 1, "episodeId": 7160000101}])
            self.assertEqual(
                SaveStore(path).state["tables"]["UserEpisodeDifficulty"], [second]
            )
            self.assertEqual(
                store.state["tokens"]["UserEpisodeDifficulty"], "episode-token"
            )

    def test_exp_item_rewards_merge_by_account_item_and_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)

            def update(puts, deletes=None):
                store.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserExpItem": puts},
                                "deleteItems": {"UserExpItem": deletes or []},
                            }
                        ],
                        "checksums": {"after": {"UserExpItem": "exp-token"}},
                    }
                )

            first = {
                "userId": 1,
                "expItemId": 292000001,
                "amount": 0,
                "reservedAmount": 10,
                "cumulativeAmount": 0,
                "bookEntryState": 1,
                "signature": 0,
            }
            second = {**first, "expItemId": 292000002}
            other = {**first, "userId": 2}
            update([first, second, other])
            reward = {**first, "amount": 5, "cumulativeAmount": 5}
            new = {**first, "expItemId": 292000003, "amount": 1}
            update([reward, new])
            update([reward, new])
            self.assertEqual(
                SaveStore(path).state["tables"]["UserExpItem"],
                [reward, second, other, new],
            )
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                update([reward, reward])
            self.assertEqual(path.read_bytes(), before)
            update([], [{"userId": 1, "expItemId": 292000001}])
            self.assertEqual(
                SaveStore(path).state["tables"]["UserExpItem"], [second, other, new]
            )
            self.assertEqual(store.state["tokens"]["UserExpItem"], "exp-token")

    def test_stage_updates_preserve_other_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.json"
            store = SaveStore(path)

            def update(rows):
                store.apply(
                    {
                        "deltas": [
                            {
                                "putItems": {"UserAdventureStage": rows},
                                "deleteItems": {},
                            }
                        ],
                        "checksums": {"after": {"UserAdventureStage": "token"}},
                    }
                )

            update(
                [
                    {"userId": 1, "adventureStageId": 1100000103101, "state": 0},
                    {"userId": 1, "adventureStageId": 1100000103102, "state": 0},
                ]
            )
            update([{"userId": 1, "adventureStageId": 1100000103101, "state": 1}])
            rows = SaveStore(path).state["tables"]["UserAdventureStage"]
            self.assertEqual([r["state"] for r in rows], [1, 0])
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                update([rows[0], rows[0]])
            self.assertEqual(path.read_bytes(), before)

    def test_wire_singletons_and_collections(self):
        values = {
            "UserInfo": [{"userId": 1}],
            "UserAdventureStage": [{"adventureStageId": 9}],
            "UserStatus": [],
        }
        result = unpack(pack(wire_tables(values)))
        self.assertEqual(result["UserInfo"], {"userId": 1})
        self.assertEqual(result["UserAdventureStage"], [{"adventureStageId": 9}])
        self.assertEqual(result["UserStatus"], [])
        self.assertEqual(values["UserInfo"], [{"userId": 1}])
        with self.assertRaises(ValueError):
            wire_tables({"UserInfo": [{}, {}]})

    def test_unsigned_large_ids(self):
        for value in (1100000103101, 2**63, 2**64 - 1):
            self.assertEqual(pack(value)[0], 0xCF)
            self.assertEqual(unpack(pack(value)), value)

    def test_restart_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "player-state.json"
            store = SaveStore(path)
            store.apply(
                {
                    "deltas": [
                        {
                            "putItems": {
                                "UserInfo": [{"userId": 1, "name": "Test player"}]
                            },
                            "deleteItems": {},
                        }
                    ],
                    "checksums": {"after": {"UserInfo": "old-token"}},
                }
            )
            self.assertEqual(
                SaveStore(path).state["tables"]["UserInfo"][0]["name"], "Test player"
            )
            previous = path.read_bytes()
            with self.assertRaises(ValueError):
                store.apply(
                    {
                        "deltas": [{"putItems": {}, "deleteItems": {"UserInfo": [1]}}],
                        "checksums": {"after": {}},
                    }
                )
            self.assertEqual(path.read_bytes(), previous)
            store.reset({"data": {"UserCommunicationCharacter": []}, "dataTokens": {}})
            fresh = SaveStore(path)
            self.assertNotIn("UserInfo", fresh.state["tables"])
            self.assertEqual(fresh.state["tokens"], {})
            self.assertEqual(fresh.state["generation"], 1)
            self.assertFalse(path.with_name("player-state.before-reset.json").exists())


if __name__ == "__main__":
    unittest.main()
