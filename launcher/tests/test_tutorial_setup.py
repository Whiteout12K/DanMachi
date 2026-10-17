# Regression checks for tutorial setup.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import unittest
from tutorial_setup import SetupReload


class SetupTests(unittest.TestCase):
    def ready(self):
        return {
            "tables": {
                "UserInfo": [{"userId": 1}],
                "UserPC": [],
                "UserTutorial": [{"tutorialId": 780010001, "isEnd": False}],
                "UserParty": [{"id": 1, "slots": [{"pcId": 1011001001, "type": 1}]}],
            }
        }

    def test_first_account_reload_is_delayed_once_and_preserves_state(self):
        watcher = SetupReload({"tables": {}})
        state = self.ready()
        before = copy.deepcopy(state)
        self.assertFalse(watcher.observe(state, 1))
        self.assertFalse(watcher.observe(state, 5))
        self.assertTrue(watcher.observe(state, 6))
        self.assertFalse(watcher.observe(state, 20))
        self.assertEqual(state, before)

    def test_existing_account_never_reloads(self):
        watcher = SetupReload(self.ready())
        self.assertFalse(watcher.observe(self.ready(), 1))
        self.assertFalse(watcher.observe(self.ready(), 100))

    def test_normal_native_grant_cancels_reload(self):
        watcher = SetupReload({"tables": {}})
        state = self.ready()
        watcher.observe(state, 1)
        state["tables"]["UserPC"] = [{"pcId": 1011001001}]
        self.assertFalse(watcher.observe(state, 100))
