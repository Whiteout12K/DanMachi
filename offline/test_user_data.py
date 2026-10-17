# Regression checks for user data.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import hashlib, io, json, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import user_data


class UserDataTest(unittest.TestCase):
    def package(self, folder, member="files/ldb/account", data=b"client", state=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as t:
            entry = tarfile.TarInfo(member)
            entry.size = len(data)
            t.addfile(entry, io.BytesIO(data))
        client = stream.getvalue()
        player = json.dumps(
            state
            or {"tables": {"UserGame": [{"rank": 3}]}, "tokens": {"UserGame": "token"}}
        ).encode()
        manifest = {
            "format": "danmachi-user-v1",
            "package": user_data.PACKAGE,
            "gameSource": json.loads(
                (user_data.ROOT / "offline/apks/build.json").read_text()
            )["source_sha256"],
            "sha256": {
                n: hashlib.sha256(d).hexdigest()
                for n, d in [("player-state.json", player), ("client.tar", client)]
            },
        }
        path = Path(folder) / "export.zip"
        with zipfile.ZipFile(path, "w") as z:
            for n, d in [
                ("manifest.json", json.dumps(manifest).encode()),
                ("player-state.json", player),
                ("client.tar", client),
            ]:
                z.writestr(n, d)
        return path, player, client

    def test_round_trip_and_asset_path_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            p, state, client = self.package(folder)
            self.assertEqual(user_data.read_export(p), (state, client))
            p, _, _ = self.package(folder, "files/contents/1/files/game.png")
            with self.assertRaises(ValueError):
                user_data.read_export(p)
            p, _, _ = self.package(folder, "shared_prefs/../../outside")
            with self.assertRaises(ValueError):
                user_data.read_export(p)

    def test_modified_payload_rejected_before_pausing_current_player(self):
        with tempfile.TemporaryDirectory() as folder:
            p, _, _ = self.package(folder)
            with zipfile.ZipFile(p) as z:
                values = {n: z.read(n) for n in z.namelist()}
            values["player-state.json"] = b'{"tables":{},"tokens":{}}'
            with zipfile.ZipFile(p, "w") as z:
                for n, d in values.items():
                    z.writestr(n, d)
            with patch.object(user_data, "pause") as pause:
                with self.assertRaises(ValueError):
                    user_data.import_user(p)
                pause.assert_not_called()

    def test_archive_links_rejected(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as t:
            entry = tarfile.TarInfo("files/ldb/link")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/outside"
            t.addfile(entry)
        with self.assertRaises(ValueError):
            user_data.validate_client(stream.getvalue())


class ExportIdentificationTest(unittest.TestCase):
    def test_short_safe_name_and_collision(self):
        summary = user_data.player_summary(
            {
                "tables": {
                    "UserInfo": [{"name": "A/../B\n", "playerStatus": {"level": 7}}]
                },
                "tokens": {},
            }
        )
        self.assertEqual(summary, {"username": "A/../B", "rank": 7})
        with tempfile.TemporaryDirectory() as folder:
            name = user_data.export_filename(summary, folder)
            self.assertEqual(name.parent, Path(folder))
            self.assertNotIn("/", name.name)
            name.touch()
            self.assertNotEqual(user_data.export_filename(summary, folder), name)

    def test_named_export_contains_checked_summary_and_is_importable(self):
        state = json.dumps(
            {
                "tables": {
                    "UserInfo": [{"name": "LocalTest", "playerStatus": {"level": 3}}]
                },
                "tokens": {},
            }
        ).encode()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w"):
            pass
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "state/offline").mkdir(parents=True)
            (root / "state/temp").mkdir()
            (root / "offline/apks").mkdir(parents=True)
            (root / "offline/apks/build.json").write_text(
                (user_data.ROOT / "offline/apks/build.json").read_text()
            )
            (root / "state/offline/player-state.json").write_bytes(state)
            with (
                patch.object(user_data, "ROOT", root),
                patch.object(user_data, "WORK", root / "state/offline"),
                patch.object(user_data, "pause"),
                patch.object(
                    user_data, "client_snapshot", return_value=stream.getvalue()
                ),
                patch.object(user_data, "resume"),
            ):
                result = user_data.export_user()
                self.assertTrue(result.name.startswith("LocalTest-"))
                self.assertTrue(result.name.endswith(".zip"))
                self.assertEqual(user_data.read_export(result)[0], state)
                with zipfile.ZipFile(result) as z:
                    payload = {n: z.read(n) for n in z.namelist()}
                self.assertIn(b"LocalTest", payload["summary.txt"])
                payload["summary.txt"] = b"Forged name"
                with zipfile.ZipFile(result, "w") as z:
                    for n, d in payload.items():
                        z.writestr(n, d)
                with self.assertRaises(ValueError):
                    user_data.read_export(result)


if __name__ == "__main__":
    unittest.main()


class NativeTransactionTest(unittest.TestCase):
    def test_roundtrip_delete_and_failed_import_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "state/offline"
            work.mkdir(parents=True)
            (root / "state/temp").mkdir()
            client = root / "client"
            (client / "files/ldb").mkdir(parents=True)
            (root / "offline/apks").mkdir(parents=True)
            (root / "offline/apks/build.json").write_text(
                (user_data.ROOT / "offline/apks/build.json").read_text()
            )
            state = b'{"tables":{"UserInfo":[{"name":"Test","playerStatus":{"level":6}}]},"tokens":{},"generation":2}'
            (work / "player-state.json").write_bytes(state)
            (client / "files/ldb/account").write_bytes(b"original")
            (client / "files/contents").mkdir()
            (client / "files/contents/asset").write_bytes(b"preserve")
            with (
                patch.object(user_data, "ROOT", root),
                patch.object(user_data, "WORK", work),
                patch.object(user_data, "CLIENT", client),
                patch.object(user_data, "pause"),
                patch.object(user_data, "resume"),
            ):
                export = user_data.export_user()
                user_data.delete_user()
                self.assertFalse((client / "files/ldb").exists())
                self.assertEqual(
                    json.loads((work / "player-state.json").read_bytes())["tables"], {}
                )
                self.assertEqual(
                    (client / "files/contents/asset").read_bytes(), b"preserve"
                )
                user_data.import_user(export)
                self.assertEqual((work / "player-state.json").read_bytes(), state)
                self.assertEqual(
                    (client / "files/ldb/account").read_bytes(), b"original"
                )
                install = user_data.install_archive
                calls = []

                def fail_once(path):
                    calls.append(path)
                    if len(calls) == 1:
                        raise OSError("injected restore failure")
                    install(path)

                with patch.object(user_data, "install_archive", side_effect=fail_once):
                    with self.assertRaises(OSError):
                        user_data.import_user(export)
                self.assertEqual((work / "player-state.json").read_bytes(), state)
                self.assertEqual(
                    (client / "files/ldb/account").read_bytes(), b"original"
                )
