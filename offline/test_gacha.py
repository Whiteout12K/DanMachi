# Regression checks for gacha.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy, json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from save_store import SaveStore
import gacha


class GachaTests(unittest.TestCase):
    def store(self, folder, iris=1000):
        p = Path(folder) / "save.json"
        p.write_text(
            json.dumps(
                {
                    "tables": {
                        "UserInfo": [{"userId": 1}],
                        "UserCurrency": [
                            {"currencyId": 205000001, "cumulativeAmount": iris}
                        ],
                        "UserPC": [],
                    },
                    "tokens": {},
                }
            )
        )
        s = SaveStore(p)
        gacha.prepare(s)
        return s

    def request(self, s):
        g = s.state["offlineGacha"]
        b = next(
            b
            for b in gacha.active_banners(g["epochDay"])
            if any(
                v["currencyType"] == 1 and v["buttonType"] == 2 and v["cost"] > 0
                for v in b["buttons"]
            )
        )
        v = next(
            v
            for v in b["buttons"]
            if v["currencyType"] == 1 and v["buttonType"] == 2 and v["cost"] > 0
        )
        return {
            "lotteryId": b["id"],
            "buttonIndex": 2,
            "progressCount": 0,
            "pickCount": v["count"],
            "consumeAmount": v["cost"],
        }, v

    def test_retry_is_durable_and_charges_once(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            r, v = self.request(s)
            response = gacha.draw(s, r, "request-1")
            reopened = SaveStore(s.path)
            self.assertEqual(gacha.draw(reopened, r, "request-1"), response)
            self.assertEqual(reopened.state["localIrisSpent"], v["cost"])
            self.assertEqual(gacha.pending(reopened), response["operation"])
            with self.assertRaises(ValueError):
                gacha.draw(reopened, r, "request-2")

    def test_invalid_and_unaffordable_draws_leave_save_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d, 0)
            r, v = self.request(s)
            before = s.path.read_bytes()
            with self.assertRaises(ValueError):
                gacha.draw(s, r, "x")
            self.assertEqual(s.path.read_bytes(), before)
            s = self.store(d)
            r, v = self.request(s)
            before = s.path.read_bytes()
            r["consumeAmount"] = 0
            with self.assertRaises(ValueError):
                gacha.draw(s, r, "x")
            self.assertEqual(s.path.read_bytes(), before)

    def test_daily_rotation_retains_standard_ticket_access(self):
        import gacha_rotation as r

        for day in range(30):
            active = gacha.active_banners(20000, (20000 + day) * 86400)
            self.assertGreaterEqual(len(active), 16)
            self.assertTrue(set(r.TICKET_BANNERS) <= {b["id"] for b in active})
            ticket = next(b for b in active if b["id"] == 171002222)
            self.assertEqual(ticket["buttons"][0]["ticketId"], 296000003)

    def test_owned_result_issues_original_bond(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            r, v = self.request(s)
            pc = gacha.definitions()["groups"][str(v["group"])][0]
            s.state["tables"]["UserPC"] = [{"pcId": pc}]
            s._write(s.state)
            with patch("gacha.secrets.choice", return_value=pc):
                response = gacha.draw(s, r, "x")
            self.assertFalse(response["lotteryPCs"][0]["isFirst"])
            self.assertEqual(response["UserPC"], [])
            self.assertEqual(
                response["UserLimitBreakItem"][0]["limitBreakItemId"],
                gacha.definitions()["bonds"][str(pc)],
            )

    def test_reply_separates_native_grants_from_result_data(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            request, v = self.request(s)
            reply = gacha.draw(s, request, "x")
            self.assertEqual(reply["lotteryPCs"], reply["data"]["lotteryPCs"])
            self.assertEqual(
                reply["lotteryPCs"], reply["operation"]["parameters"]["lotteryPCs"]
            )
            self.assertEqual(
                reply["data"]["UserLottery"], s.state["tables"]["UserLottery"]
            )
            self.assertEqual(
                reply["UserLottery"], reply["operation"]["parameters"]["UserLottery"]
            )
            self.assertNotIn("UserPC", reply["data"])
            self.assertNotIn("UserLimitBreakItem", reply["data"])
            self.assertEqual(
                reply["UserPC"], reply["operation"]["parameters"]["UserPC"]
            )

    def test_ticket_charge_is_durable_before_native_grant(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            g = s.state["offlineGacha"]
            banner = next(
                b
                for b in gacha.active_banners(g["epochDay"])
                if any(v["currencyType"] == 2 for v in b["buttons"])
            )
            v = next(v for v in banner["buttons"] if v["currencyType"] == 2)
            s.state["tables"]["UserGachaTicket"] = [
                {
                    "userId": 1,
                    "gachaTicketId": v["ticketId"],
                    "dateList": [
                        {"aquiredAt": int(time.time())} for _ in range(v["cost"])
                    ],
                    "bookEntryState": 1,
                    "signature": 1,
                    "cumulativeAmount": v["cost"],
                }
            ]
            s._write(s.state)
            r = {
                "lotteryId": banner["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": v["cost"],
            }
            reply = gacha.draw(s, r, "ticket")
            self.assertEqual(
                SaveStore(s.path).state["tables"]["UserGachaTicket"][0]["dateList"], []
            )
            self.assertEqual(gacha.draw(s, r, "ticket"), reply)

    def test_owned_historical_ticket_remains_usable_offline(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            banner = next(
                b
                for b in gacha.active_banners(s.state["offlineGacha"]["epochDay"])
                if any(v["currencyType"] == 2 for v in b["buttons"])
            )
            v = next(v for v in banner["buttons"] if v["currencyType"] == 2)
            s.state["tables"]["UserGachaTicket"] = [
                {
                    "userId": 1,
                    "gachaTicketId": v["ticketId"],
                    "dateList": [{"aquiredAt": 1}],
                }
            ]
            s._write(s.state)
            r = {
                "lotteryId": banner["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": v["cost"],
            }
            reply = gacha.draw(s, r, "historical-ticket")
            self.assertEqual(len(reply["lotteryPCs"]), v["count"])
            self.assertEqual(s.state["tables"]["UserGachaTicket"][0]["dateList"], [])

    def test_retired_scratch_controls_are_disabled_without_asset_copies(self):
        import rebuild_master as m, subprocess, zlib

        asset = gacha.scratch_asset()
        b = zlib.decompress(
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-K",
                    m.AES_KEY.hex(),
                    "-iv",
                    m.IV.hex(),
                ],
                input=asset.data,
                capture_output=True,
                check=True,
            ).stdout
        )
        self.assertEqual(len(m.rows(b)), len(m.rows(m.table("lotteryScratch"))))
        self.assertTrue(all(m.scalar(b, t, 2) == 0 for t in m.rows(b)))

    def test_master_contains_only_current_rotation(self):
        import rebuild_master as m, subprocess, zlib

        asset = gacha.master_asset()
        decoded = subprocess.run(
            [
                "/usr/bin/openssl",
                "enc",
                "-d",
                "-aes-256-cbc",
                "-K",
                m.AES_KEY.hex(),
                "-iv",
                m.IV.hex(),
            ],
            input=asset.data,
            capture_output=True,
            check=True,
        ).stdout
        b = zlib.decompress(decoded)
        now = time.time()
        active = {
            m.scalar(b, t, 0)
            for t in m.rows(b)
            if m.scalar(b, t, 4, 8) <= now
            and (m.scalar(b, t, 5, 8) == 0 or now < m.scalar(b, t, 5, 8))
        }
        save = json.loads(
            (
                Path(__file__).resolve().parents[1] / "state/offline/player-state.json"
            ).read_text()
        )
        epoch = save.get("offlineGacha", {}).get("epochDay", int(now // 86400))
        self.assertEqual(
            active,
            {
                b["id"]
                for b in gacha.active_banners(
                    epoch, progress=save.get("offlineGacha", {}).get("progress", {})
                )
            },
        )

    def test_free_limit_and_token_survive_stale_client_push(self):
        import hashlib

        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            banner = next(
                b
                for b in gacha.definitions()["banners"]
                if any(v["cost"] == 0 and v.get("limit") for v in b["buttons"])
            )
            s.gachaBanners = [banner]
            s.gachaWindows = {}
            gacha.prepare(s)
            v = next(v for v in banner["buttons"] if v["cost"] == 0 and v.get("limit"))
            stale = copy.deepcopy(s.state["tables"]["UserLottery"])
            r = {
                "lotteryId": banner["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": 0,
            }
            reply = gacha.draw(s, r, "free")
            self.assertEqual(
                reply["dataTokens"]["UserLottery"],
                hashlib.md5(gacha.pack(s.state["tables"]["UserLottery"])).hexdigest(),
            )
            s.state["tables"]["UserLottery"] = stale
            s.state["acknowledgedOperations"] = {str(reply["operation"]["id"]): True}
            s._write(s.state)
            gacha.prepare(s)
            row = next(
                r
                for r in s.state["tables"]["UserLottery"]
                if r["lotteryId"] == banner["id"]
            )
            self.assertEqual(
                next(b for b in row["buttons"] if b["buttonType"] == v["buttonType"])[
                    "count"
                ],
                1,
            )
            r["progressCount"] = 1
            before = s.path.read_bytes()
            self.assertEqual(gacha.draw(s, r, "again"), reply)
            self.assertEqual(s.path.read_bytes(), before)
            self.assertEqual(gacha.draw(s, r, "free"), reply)

    def test_daily_reset_preserves_one_time_limits(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            banner = next(
                b
                for b in gacha.definitions()["banners"]
                if any(v.get("dailyReset") for v in b["buttons"])
            )
            daily = next(
                v["buttonType"] for v in banner["buttons"] if v.get("dailyReset")
            )
            row = gacha.lottery_row(1, banner["id"])
            for v in row["buttons"]:
                v.update(count=1, lastPickedAt=int(time.time()))
            s.state["offlineGacha"]["progress"][str(banner["id"])] = row
            s._write(s.state)
            with patch("gacha.time.time", return_value=time.time() + 86400):
                gacha.prepare(s)
            for v in s.state["offlineGacha"]["progress"][str(banner["id"])]["buttons"]:
                resets = any(
                    x.get("dailyReset")
                    for x in banner["buttons"]
                    if x["buttonType"] == v["buttonType"]
                ) and not any(
                    x["cost"] == 0
                    for x in banner["buttons"]
                    if x["buttonType"] == v["buttonType"]
                )
                from gacha_rotation import cycle_start

                free = any(
                    x["cost"] == 0
                    for x in banner["buttons"]
                    if x["buttonType"] == v["buttonType"]
                )
                returned = free and int(time.time()) < cycle_start(
                    banner, time.time() + 86400
                )
                self.assertEqual(v["count"], 0 if resets or returned else 1)

    def test_used_free_banner_hidden_until_a_later_rotation_returns_it(self):
        import gacha_rotation

        with tempfile.TemporaryDirectory() as d:
            s = self.store(d)
            g = s.state["offlineGacha"]
            banner = next(
                b
                for b in gacha.definitions()["banners"]
                if b["id"] not in gacha_rotation.links()
                and any(v["cost"] == 0 for v in b["buttons"])
            )
            s.gachaBanners = [banner]
            s.gachaWindows = {}
            gacha.prepare(s)
            v = next(v for v in banner["buttons"] if v["cost"] == 0)
            r = {
                "lotteryId": banner["id"],
                "buttonIndex": v["buttonType"],
                "progressCount": 0,
                "pickCount": v["count"],
                "consumeAmount": 0,
            }
            reply = gacha.draw(s, r, "free")
            reopened = SaveStore(s.path)
            gacha.prepare(reopened)
            self.assertNotIn(
                banner["id"],
                {
                    b["id"]
                    for b in gacha.active_banners(
                        g["epochDay"],
                        progress=reopened.state["offlineGacha"]["progress"],
                    )
                },
            )
            self.assertEqual(gacha.draw(reopened, r, "free"), reply)
            today = int(gacha.SESSION_TIME // 86400)
            future = next(
                day
                for day in range(today + 1, today + 1000)
                if banner["id"]
                in {
                    b["id"]
                    for b in gacha.active_banners(
                        g["epochDay"],
                        day * 86400,
                        progress=reopened.state["offlineGacha"]["progress"],
                    )
                }
            )
            with (
                patch("gacha.SESSION_TIME", future * 86400),
                patch("gacha.time.time", return_value=future * 86400),
            ):
                returned = SaveStore(s.path)
                gacha.prepare(returned)
                row = next(
                    x
                    for x in returned.state["tables"]["UserLottery"]
                    if x["lotteryId"] == banner["id"]
                )
                self.assertEqual(
                    next(
                        x for x in row["buttons"] if x["buttonType"] == v["buttonType"]
                    )["count"],
                    0,
                )

    def test_details_use_original_names_and_actual_pool_rates(self):
        from collections import Counter

        banner = gacha.definitions()["banners"][0]
        page = gacha.details_html(banner["id"])
        units = gacha.unit_metadata()
        self.assertEqual(units[1011001002]["rarity"], 2)
        self.assertEqual(units[1011001005]["rarity"], 4)
        self.assertTrue(all(u["rarity"] in (1, 2, 3, 4) for u in units.values()))
        for v in banner["buttons"]:
            for group in (v["group"], v["fixedGroup"]):
                pool = gacha.definitions()["groups"].get(str(group), [])
                if not pool:
                    continue
                for pc in pool:
                    self.assertIn("ID " + str(pc), page)
                for rarity, count in Counter(
                    units[pc]["rarity"] for pc in pool
                ).items():
                    self.assertIn(f"{100*count/len(pool):.4f}%", page)
        self.assertIn("not historical live-service odds", page)
        self.assertIn("No matching", gacha.details_html(-1))

    def test_encryption_round_trip_for_all_scalar_widths(self):
        import rebuild_master as m

        for value in (
            b"\x01",
            b"\x03",
            (4102444800).to_bytes(8, "little"),
            bytes(range(32)),
        ):
            self.assertEqual(m.decode(gacha.encode(value, m.INNER_KEY)), value)


if __name__ == "__main__":
    unittest.main()
