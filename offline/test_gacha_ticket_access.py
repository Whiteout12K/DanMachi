# Regression checks for gacha ticket access.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy, json, struct, subprocess, tempfile, unittest, zlib
from pathlib import Path
import gacha, gacha_rotation as rotation, rebuild_master as master
from build_gacha import value
from gacha_ticket_access import master_asset, PATH, NATIVE_VALIDITY_SECONDS
from save_store import SaveStore, pack


class AllTicketAccessTests(unittest.TestCase):
    def test_every_original_ticket_has_a_permanent_matching_choice(self):
        data = master.table("gachaTicket")
        expected = {value(data, r, 0) for r in master.rows(data)}
        enabled = set(rotation.permanent_ticket_ids())
        banners = [b for b in gacha.definitions()["banners"] if b["id"] in enabled]
        actual = {v["ticketId"] for b in banners for v in b["buttons"]}
        self.assertEqual(expected, actual)
        for month in [
            rotation.month_of(gacha.SESSION_TIME),
            rotation.month_of(gacha.SESSION_TIME) + 1,
        ]:
            windows = rotation.month_windows(month)
            self.assertTrue(all(windows[i] == (0, 4102444800) for i in enabled))
        self.assertTrue(
            all(
                v["currencyType"] == 2 and v["limit"] == 0
                for b in banners
                for v in b["buttons"]
            )
        )

    def test_all_ticket_forms_charge_only_their_own_ticket_and_retry_once(self):
        banners = {b["id"]: b for b in gacha.definitions()["banners"]}
        choices = {}
        for identity in rotation.permanent_ticket_ids():
            for button in banners[identity]["buttons"]:
                choices.setdefault(button["ticketId"], (identity, button))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            tickets = [
                {
                    "userId": 1,
                    "gachaTicketId": ticket,
                    "dateList": [{"aquiredAt": 1} for _ in range(v["cost"])],
                }
                for ticket, (lid, v) in choices.items()
            ]
            path.write_text(
                json.dumps(
                    {
                        "tables": {
                            "UserInfo": [{"userId": 1}],
                            "UserPC": [],
                            "UserCurrency": [
                                {"currencyId": 205000001, "cumulativeAmount": 1000}
                            ],
                            "UserGachaTicket": tickets,
                        },
                        "tokens": {},
                    }
                )
            )
            save = SaveStore(path)
            for ticket, (lid, v) in choices.items():
                request = {
                    "lotteryId": lid,
                    "buttonIndex": v["buttonType"],
                    "progressCount": 0,
                    "pickCount": v["count"],
                    "consumeAmount": v["cost"],
                }
                before = copy.deepcopy(save.state["tables"]["UserGachaTicket"])
                reply = gacha.draw(save, request, str(ticket))
                self.assertEqual(len(reply["lotteryPCs"]), v["count"])
                pool = set(
                    gacha.definitions()["groups"].get(str(v["group"]), [])
                ) | set(gacha.definitions()["groups"].get(str(v["fixedGroup"]), []))
                self.assertTrue(all(p["pcId"] in pool for p in reply["lotteryPCs"]))
                for old, new in zip(before, save.state["tables"]["UserGachaTicket"]):
                    if new["gachaTicketId"] == ticket:
                        self.assertEqual(new["dateList"], [])
                    else:
                        self.assertEqual(old, new)
                self.assertEqual(gacha.draw(save, request, str(ticket)), reply)
                self.assertEqual(save.state.get("localIrisSpent", 0), 0)
                save.state.setdefault("acknowledgedOperations", {})[
                    str(reply["operation"]["id"])
                ] = True
                save._write(save.state)

    def test_ticket_validity_master_only_changes_expiration(self):
        original = master.table("gachaTicket")
        updated = zlib.decompress(
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-K",
                    master.AES_KEY.hex(),
                    "-iv",
                    master.IV.hex(),
                ],
                input=master_asset().data,
                capture_output=True,
                check=True,
            ).stdout
        )
        restored = bytearray(updated)
        for row in master.rows(original):
            field = master.fields(original, row)[4]
            self.assertEqual(value(updated, row, 4), NATIVE_VALIDITY_SECONDS)
            if field:
                restored[field : field + 8] = original[field : field + 8]
        self.assertEqual(bytes(restored), original)

    def test_every_permanent_banner_has_native_background_and_valid_pool(self):
        from zip_reader import catalog, asset

        paths = catalog()
        for banner in gacha.definitions()["banners"]:
            if banner["id"] not in rotation.permanent_ticket_ids():
                continue
            path = f"1/files/lottery/background/{banner['id']}.png"
            self.assertIn(path, paths)
            image = asset(path).read_bytes()
            self.assertTrue(
                image.startswith(b"\x89PNG\r\n\x1a\n")
                or (image[:4] == b"RIFF" and image[8:12] == b"WEBP")
            )
            for v in banner["buttons"]:
                if v["count"] > v["fixedCount"]:
                    self.assertTrue(gacha.definitions()["groups"][str(v["group"])])
                if v["fixedCount"]:
                    self.assertTrue(gacha.definitions()["groups"][str(v["fixedGroup"])])

    def test_start_dash_can_use_additional_tickets_after_an_earlier_draw(self):
        banner = next(b for b in gacha.definitions()["banners"] if b["id"] == 171002223)
        v = banner["buttons"][0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            path.write_text(
                json.dumps(
                    {
                        "tables": {
                            "UserInfo": [{"userId": 1}],
                            "UserGachaTicket": [
                                {
                                    "userId": 1,
                                    "gachaTicketId": v["ticketId"],
                                    "dateList": [{"aquiredAt": 1}, {"aquiredAt": 2}],
                                }
                            ],
                        },
                        "tokens": {},
                    }
                )
            )
            save = SaveStore(path)
            for count in range(2):
                request = {
                    "lotteryId": banner["id"],
                    "buttonIndex": v["buttonType"],
                    "progressCount": count,
                    "pickCount": v["count"],
                    "consumeAmount": v["cost"],
                }
                reply = gacha.draw(save, request, "start-dash-" + str(count))
                save.state.setdefault("acknowledgedOperations", {})[
                    str(reply["operation"]["id"])
                ] = True
                save._write(save.state)
                save = SaveStore(path)
            self.assertEqual(save.state["tables"]["UserGachaTicket"][0]["dateList"], [])

    def test_native_ticket_button_limits_are_removed_without_other_record_changes(self):
        original = master.table("lottery")
        patched = zlib.decompress(
            subprocess.run(
                [
                    "/usr/bin/openssl",
                    "enc",
                    "-d",
                    "-aes-256-cbc",
                    "-K",
                    master.AES_KEY.hex(),
                    "-iv",
                    master.IV.hex(),
                ],
                input=gacha.master_asset().data,
                capture_output=True,
                check=True,
            ).stdout
        )
        enabled = set(rotation.permanent_ticket_ids())
        for row in master.rows(original):
            if value(original, row, 0) not in enabled:
                continue
            self.assertEqual(value(patched, row, 4), 0)
            self.assertEqual(
                value(patched, row, 5),
                4102444800 if master.fields(original, row)[5] else 0,
            )
            for currency, limit in [(21, 24), (31, 34)]:
                if value(original, row, currency) == 2:
                    self.assertEqual(value(patched, row, limit), 0)
                    for column in [
                        currency - 1,
                        currency,
                        currency + 1,
                        currency + 2,
                        currency + 4,
                        currency + 5,
                    ]:
                        self.assertEqual(
                            value(patched, row, column), value(original, row, column)
                        )
