# Regression checks for gacha rotation.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import datetime
import unittest
import gacha
import gacha_rotation as r
import tutorial_banner
import guild_events
import guild_quests


class RotationTests(unittest.TestCase):
    def test_ten_banners_with_permanent_tickets_and_daily_pairs(self):
        now = gacha.SESSION_TIME
        epoch = int(now // 86400)
        first = r.active(epoch, now)
        self.assertEqual(first, r.active(epoch + 10, now))
        self.assertGreaterEqual(len(first), 16)
        self.assertEqual(len({b["id"] for b in first}), len(first))
        self.assertEqual(tuple(b["id"] for b in first[:6]), r.TICKET_BANNERS)
        self.assertTrue(all(not r.family(b["name"]) for b in first[12:14]))
        self.assertTrue(all(r.family(b["name"]) for b in first[14:16]))
        tomorrow = r.active(epoch, now + 86400)
        self.assertTrue(
            {b["id"] for b in first[12:16]}.isdisjoint(b["id"] for b in tomorrow[12:16])
        )
        self.assertEqual(first[:12], tomorrow[:12])
        self.assertTrue(r.current_events(now) <= {b["id"] for b in first})
        visible = [
            b for b in first if any(v["currencyType"] == 1 for v in b["buttons"])
        ]
        self.assertGreaterEqual(len(visible), 10)

    def test_standard_four_star_ticket_draw_consumes_once_and_guarantees_rarity(self):
        import tempfile, time
        from test_gacha import GachaTests

        with tempfile.TemporaryDirectory() as folder:
            save = GachaTests().store(folder)
            banner = next(
                b for b in gacha.session_banners(save) if b["id"] == 171002222
            )
            v = banner["buttons"][0]
            save.state["tables"]["UserGachaTicket"] = [
                {
                    "userId": 1,
                    "gachaTicketId": 296000003,
                    "dateList": [{"aquiredAt": int(time.time())}],
                    "cumulativeAmount": 1,
                }
            ]
            save._write(save.state)
            request = {
                "lotteryId": banner["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": v["cost"],
            }
            reply = gacha.draw(save, request, "four-star")
            self.assertEqual(save.state["tables"]["UserGachaTicket"][0]["dateList"], [])
            self.assertEqual(gacha.draw(save, request, "four-star"), reply)
            units = gacha.unit_metadata()
            self.assertTrue(
                all(units[p["pcId"]]["rarity"] == 4 for p in reply["lotteryPCs"])
            )

    def test_used_free_offer_stays_hidden_same_cycle_and_can_return_later(self):
        banners = gacha.definitions()["banners"]
        for mapped in (False, True):
            b = next(
                b
                for b in banners
                if (b["id"] in r.links()) == mapped
                and any(v["cost"] == 0 for v in b["buttons"])
            )
            v = next(v for v in b["buttons"] if v["cost"] == 0)
            now = gacha.SESSION_TIME
            progress = {
                str(b["id"]): {
                    "buttons": [
                        {
                            "buttonType": v["buttonType"],
                            "count": max(1, v.get("limit", 0)),
                            "lastPickedAt": int(now),
                        }
                    ]
                }
            }
            self.assertTrue(r.consumed(b, progress, now + 10))
            future = (
                now + 86400
                if not mapped
                else guild_quests.month_window(r.month_of(now) + 1)[0] + 1
            )
            self.assertFalse(r.consumed(b, progress, future))

    def test_tutorial_available_for_new_account_and_not_in_random_rotation(self):
        self.assertTrue(tutorial_banner.available({"tables": {}}))
        self.assertNotIn(
            tutorial_banner.BANNER_ID,
            {b["id"] for b in r.active(20000, gacha.SESSION_TIME)},
        )
        self.assertFalse(
            tutorial_banner.available(
                {
                    "tutorialDraw": {"pcId": 1011006008},
                    "acknowledgedOperations": {"100000001": "verified"},
                }
            )
        )


class PreloadedCalendarTests(unittest.TestCase):
    def test_every_day_in_month_has_matching_native_dates_and_two_rotating_pairs(self):
        from guild_quests import month_window

        month = r.month_of(gacha.SESSION_TIME)
        windows = r.month_windows(month)
        start, end = month_window(month)
        for day in range(start // 86400, end // 86400 + 1):
            timestamp = day * 86400 + 100
            active = {b["id"] for b in r.active(0, timestamp)}
            self.assertEqual(
                active, {lid for lid, (a, b) in windows.items() if a <= timestamp <= b}
            )
            self.assertGreaterEqual(len(active), 16)

    def test_running_session_accepts_tomorrows_offer_and_rejects_expired_offer(self):
        import tempfile
        from unittest.mock import patch
        from test_gacha import GachaTests

        now = gacha.SESSION_TIME
        # Keep the simulation inside the preloaded calendar month.
        start, end = guild_quests.month_window(r.month_of(now))
        now = min(now, end - 2 * 86400)
        with (
            patch("gacha.SESSION_TIME", now),
            patch("gacha.time.time", return_value=now),
            tempfile.TemporaryDirectory() as d,
        ):
            save = GachaTests().store(d, iris=10000)
            today = r.active(0, now)[12:14]
            tomorrow = r.active(0, now + 86400)[12:14]
            self.assertTrue(
                all(
                    b["id"] in {x["id"] for x in gacha.session_banners(save)}
                    for b in tomorrow
                )
            )
            expired = next(b for b in today if any(v["cost"] > 0 for v in b["buttons"]))
            v = next(v for v in expired["buttons"] if v["cost"] > 0)
            request = {
                "lotteryId": expired["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": v["cost"],
            }
            with patch("gacha.time.time", return_value=now + 86400):
                with self.assertRaisesRegex(ValueError, "scheduled dates"):
                    gacha.draw(save, request, "expired")
                banner = next(
                    b for b in tomorrow if any(v["cost"] > 0 for v in b["buttons"])
                )
                v = next(v for v in banner["buttons"] if v["cost"] > 0)
                request.update(
                    lotteryId=banner["id"],
                    buttonIndex=v["buttonType"],
                    pickCount=v["count"],
                    consumeAmount=v["cost"],
                )
                self.assertEqual(gacha.draw(save, request, "tomorrow")["code"], 0)
