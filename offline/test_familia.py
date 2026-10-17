# Regression checks for familia.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy, tempfile, unittest
from pathlib import Path
from save_store import SaveStore
import familia


class LocalFamiliaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.save = SaveStore(Path(self.temp.name) / "save.json")
        self.save.state = {
            "tables": {
                "UserInfo": [
                    {"userId": 1, "name": "Player", "playerStatus": {"level": 7}}
                ],
                "UserPC": [{"pcId": 1011001001}],
                "UserCurrency": [{"currencyId": 205000002, "amount": 1000}],
            },
            "tokens": {},
        }

    def call(self, action, request=None, key="test"):
        return familia.handle(self.save, "familia/" + action, request or {}, key)

    def create(self):
        return self.call(
            "create",
            {
                "name": "Local Familia",
                "godId": 20000001,
                "style": 21000001,
                "activeTime": 22000001,
            },
        )

    def test_entry_search_and_invitations_are_valid_without_remote_players(self):
        before = copy.deepcopy(self.save.state)
        self.assertEqual(self.call("mystatus")["status"]["familiaId"], 0)
        self.assertEqual(self.call("search/random")["familias"], [])
        self.assertEqual(self.call("invited/list")["requests"], [])
        self.assertEqual(self.save.state, before)

    def test_create_retry_settings_and_persistence_preserve_player(self):
        player = copy.deepcopy(self.save.state["tables"])
        first = self.create()
        self.assertEqual(first["status"]["familiaId"], 1)
        self.assertEqual(self.create(), first)
        self.assertEqual(
            self.call("get", {"familiaId": 1})["members"][0]["name"], "Player"
        )
        self.call(
            "manage/change/info",
            {"familiaId": 1, "description": "Changed", "requireApproval": True},
            "settings",
        )
        restored = SaveStore(self.save.path)
        self.assertEqual(
            restored.state["offlineFamilia"]["group"]["description"], "Changed"
        )
        self.assertEqual(restored.state["tables"], player)

    def test_messages_are_local_bounded_and_retry_protected(self):
        self.create()
        request = {"familiaId": 1, "postType": 0, "message": "Hello"}
        first = self.call("msg_board/send", request, "same")
        self.assertEqual(self.call("msg_board/send", request, "same"), first)
        self.assertEqual(len(self.call("msg_board/feed")["messages"]), 1)
        for i in range(105):
            self.call("msg_board/send", dict(request, message=str(i)), str(i))
        state = self.save.state["offlineFamilia"]
        self.assertEqual(len(state["messages"]), 100)
        self.assertLessEqual(len(state["retries"]), 32)

    def test_leave_rejoin_and_break_are_consistent(self):
        self.create()
        self.call("leave", {}, "leave")
        self.assertEqual(self.call("mystatus")["status"]["familiaId"], 0)
        self.call("join/send", {"familiaId": 1}, "join")
        self.assertEqual(self.call("mystatus")["status"]["familiaId"], 1)
        self.call("break", {}, "break")
        self.assertEqual(self.call("search/random")["familias"], [])

    def test_bad_requests_and_foreign_family_do_not_change_save(self):
        self.create()
        before = copy.deepcopy(self.save.state)
        self.assertEqual(
            self.call("manage/change/info", {"familiaId": 2, "description": "bad"})[
                "result"
            ],
            1,
        )
        with self.assertRaises(ValueError):
            self.call("msg_board/send", {"message": "x" * 2001})
        with self.assertRaises(ValueError):
            self.call("manage/change/god", {"godId": True})
        self.assertEqual(self.save.state, before)


if __name__ == "__main__":
    unittest.main()
