# Regression checks for shooting.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import tempfile
import unittest
from pathlib import Path
import shooting
from save_store import SaveStore


class ShootingTests(unittest.TestCase):
    def test_completion_validates_original_playable_characters_without_extra_grants(
        self,
    ):
        for pc in shooting.playable_ids():
            reply = shooting.handle(
                "shooting/stage/complete", {"pcId": pc, "score": 12345}
            )
            self.assertEqual(reply["code"], 0)
            self.assertEqual(reply["operations"], [])
        for request in (
            {"pcId": 1, "score": 50},
            {"pcId": 67300000001, "score": -1},
            {"pcId": 67300000001, "score": True},
        ):
            self.assertNotEqual(
                shooting.handle("shooting/stage/complete", request)["code"], 0
            )
        self.assertEqual(
            shooting.handle("shooting/ranking/get", {}), {"code": 0, "ranking": []}
        )

    def test_native_score_coin_unlock_updates_persist_without_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            save = SaveStore(Path(directory) / "save.json")
            old = {"userId": 1, "shootingGameInfoId": 67000000001, "highScore": 900}
            current = {
                "userId": 1,
                "shootingGameInfoId": 67000000002,
                "highScore": 100,
                "totalScore": 100,
                "aisCoinAmount": 2,
                "playableChara": [],
            }
            save._write({"tables": {"UserShootingGame": [old, current]}, "tokens": {}})
            updated = copy.deepcopy(current)
            updated.update(
                highScore=500,
                totalScore=600,
                aisCoinAmount=12,
                playableChara=[
                    {
                        "shootingGamePcId": 67300000001,
                        "storyProgress": 2,
                        "storyRead": True,
                    }
                ],
            )
            request = {
                "deltas": [
                    {"putItems": {"UserShootingGame": [updated]}, "deleteItems": {}}
                ],
                "checksums": {"after": {"UserShootingGame": "native-checksum"}},
            }
            save.apply(request)
            save.apply(request)
            self.assertEqual(
                SaveStore(save.path).state["tables"]["UserShootingGame"], [old, updated]
            )
