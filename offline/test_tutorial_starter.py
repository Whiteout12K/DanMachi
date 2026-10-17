# Regression checks for tutorial starter.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import threading
import unittest
from types import SimpleNamespace
from tutorial_starter import pending, BELL, OPERATION_ID


class StarterTests(unittest.TestCase):
    def setUp(self):
        self.save = SimpleNamespace(
            lock=threading.RLock(),
            state={
                "tables": {
                    "UserInfo": [{"userId": 1}],
                    "UserPC": [],
                    "UserTutorial": [{"tutorialId": 780010001, "isEnd": False}],
                    "UserParty": [{"id": 1, "slots": [{"pcId": BELL, "type": 1}]}],
                }
            },
        )

    def test_native_grant_is_stable_and_does_not_mutate_save(self):
        before = copy.deepcopy(self.save.state)
        operation = pending(self.save)
        self.assertEqual(operation["type"], 1001)
        self.assertEqual(operation["parameters"]["UserPC"], [{"pcId": BELL}])
        self.assertEqual(operation, pending(self.save))
        self.assertEqual(before, self.save.state)

    def test_owned_character_or_completed_tutorial_never_granted(self):
        self.save.state["tables"]["UserPC"] = [{"pcId": BELL}]
        self.assertIsNone(pending(self.save))
        self.save.state["tables"]["UserPC"] = []
        self.save.state["tables"]["UserTutorial"][0]["isEnd"] = True
        self.assertIsNone(pending(self.save))

    def test_requires_expected_party_and_stops_after_ack(self):
        self.save.state["tables"]["UserParty"][0]["slots"][0]["pcId"] = 0
        self.assertIsNone(pending(self.save))
        self.save.state["tables"]["UserParty"][0]["slots"][0]["pcId"] = BELL
        self.save.state["acknowledgedOperations"] = {
            str(OPERATION_ID): "native-verifier"
        }
        self.assertIsNone(pending(self.save))


if __name__ == "__main__":
    unittest.main()
