# Regression checks for play days.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import datetime, json, tempfile, unittest
from pathlib import Path
from save_store import SaveStore
from play_days import record


def stamp(day):
    return datetime.datetime.fromisoformat(day + "T12:00:00").timestamp()


class PlayDaysTest(unittest.TestCase):
    def test_days_restart_gap_and_backward_clock(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "player.json"
            p.write_text(
                json.dumps(
                    {
                        "tables": {
                            "UserStatus": [
                                {"userId": 1, "totalLoginDays": 7, "continuousLogin": 3}
                            ],
                            "UserInfo": [{"userId": 1}],
                        },
                        "tokens": {},
                    }
                )
            )
            s = SaveStore(p)
            before_info = json.loads(json.dumps(s.state["tables"]["UserInfo"]))
            updates = record(s, stamp("2026-10-12"), True)
            self.assertNotIn("UserInfo", updates)
            self.assertEqual(s.state["tables"]["UserInfo"], before_info)
            record(s, stamp("2026-10-12"), True)
            self.assertEqual(s.state["tables"]["UserStatus"][0]["totalLoginDays"], 8)
            s = SaveStore(p)
            record(s, stamp("2026-10-13"))
            self.assertEqual(s.state["tables"]["UserStatus"][0]["continuousLogin"], 2)
            record(s, stamp("2026-10-16"))
            self.assertEqual(s.state["tables"]["UserStatus"][0]["continuousLogin"], 1)
            record(s, stamp("2026-10-13"))
            self.assertEqual(s.state["tables"]["UserStatus"][0]["totalLoginDays"], 10)
            s.state["tables"]["UserStatus"][0]["totalLoginDays"] = 0
            record(s, stamp("2026-10-16"))
            self.assertEqual(s.state["tables"]["UserStatus"][0]["totalLoginDays"], 10)

    def test_uninitialized_player_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            s = SaveStore(Path(d) / "save")
            self.assertEqual(record(s, stamp("2026-10-12")), {})
            self.assertNotIn("playDays", s.state)

    def test_monthly_days_include_today_once_and_reset_next_month(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "player.json"
            p.write_text(
                json.dumps(
                    {
                        "tables": {
                            "UserStatus": [{"userId": 1}],
                            "UserAchievement": [
                                {
                                    "userId": 1,
                                    "achievementId": 6080000001,
                                    "state": 2,
                                    "progressParam": 0,
                                    "completedAt": 0,
                                    "lastResetAt": 0,
                                },
                                {
                                    "userId": 1,
                                    "achievementId": 6080000002,
                                    "state": 2,
                                    "progressParam": 0,
                                    "completedAt": 0,
                                    "lastResetAt": 0,
                                },
                            ],
                        },
                        "tokens": {},
                    }
                )
            )
            s = SaveStore(p)
            record(s, stamp("2026-10-14"), True)
            goals = s.state["tables"]["UserAchievement"]
            self.assertEqual(goals[0]["progressParam"], 1)
            self.assertEqual(goals[0]["state"], 3)
            record(s, stamp("2026-10-14"), True)
            self.assertEqual(
                s.state["tables"]["UserAchievement"][1]["progressParam"], 1
            )
            record(s, stamp("2026-10-16"), True)
            self.assertEqual(
                s.state["tables"]["UserAchievement"][1]["progressParam"], 2
            )
            record(s, stamp("2026-10-17"), True)
            self.assertEqual(s.state["tables"]["UserAchievement"][1]["state"], 3)
            record(s, stamp("2026-11-02"), True)
            self.assertEqual(
                s.state["tables"]["UserAchievement"][1]["progressParam"], 1
            )
            self.assertEqual(s.state["tables"]["UserAchievement"][1]["state"], 2)
