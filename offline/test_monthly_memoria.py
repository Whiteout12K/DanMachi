# Regression checks for monthly memoria.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import json, tempfile, unittest, copy
from pathlib import Path
from save_store import (
    SaveStore,
    ACHIEVEMENT_REWARDS,
    memoria_reward_ids,
    route_achievement_rewards,
)


class MonthlyMemoriaTests(unittest.TestCase):
    def test_memoria_claim_and_legacy_retry_use_memoria_channel(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "save.json"
            p.write_text(
                json.dumps(
                    {
                        "tables": {
                            "UserAchievement": [
                                {
                                    "userId": 1,
                                    "achievementId": 6080000001,
                                    "completedAt": 100,
                                    "state": 3,
                                }
                            ]
                        },
                        "tokens": {},
                    }
                )
            )
            save = SaveStore(p)
            request = {
                "achievementIds": [{"achievementId": 6080000001, "completedAt": 100}]
            }
            first = copy.deepcopy(save.achievement_complete(request))
            params = first["operation"]["parameters"]
            self.assertEqual(params["receivedItems"], [])
            self.assertEqual(
                params["receivedMemorias"], [{"memoriaId": 1201000005, "level": 1}]
            )
            self.assertEqual(SaveStore(p).achievement_complete(request), first)
            op = next(iter(save.state["achievementClaims"].values()))
            op["parameters"]["receivedItems"] = [{"itemId": 1201000005, "amount": 1}]
            op["parameters"]["receivedMemorias"] = []
            save._write(save.state)
            retry = save.achievement_complete(request)
            self.assertEqual(retry, first)
            op = next(iter(save.state["achievementClaims"].values()))
            op["parameters"]["receivedMemorias"] = [
                {"memoriaId": 1201000005, "amount": 1}
            ]
            save._write(save.state)
            self.assertEqual(save.achievement_complete(request), first)

    def test_all_retained_memoria_rewards_and_mixed_items(self):
        rewards = [
            r
            for r in ACHIEVEMENT_REWARDS.values()
            if r.get("itemId") in memoria_reward_ids()
        ]
        self.assertGreaterEqual(len(rewards), 30)
        params = {
            "receivedItems": rewards + [{"itemId": 205000001, "amount": 10}],
            "receivedMemorias": [],
        }
        route_achievement_rewards(params)
        self.assertEqual(len(params["receivedMemorias"]), len(rewards))
        self.assertEqual(params["receivedItems"], [{"itemId": 205000001, "amount": 10}])
        before = json.dumps(params)
        route_achievement_rewards(params)
        self.assertEqual(json.dumps(params), before)
