# Regression checks for local migration.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import http.client
import http.server
import json
import threading
import unittest
from server import CheckedHandler, ContentPaths, save, backend


class SilentMigrationHandler(CheckedHandler):
    def record(self, body):
        pass


class LocalMigrationTest(unittest.TestCase):
    def test_quest_support_refresh_is_read_only_and_registered(self):
        before = copy.deepcopy(save.state)
        path = "/api/game_client/friend/support/list"
        self.assertEqual(backend.api_action(path), "friend/support/list")
        for _ in range(2):
            kind, body = backend.api_response("friend/support/list", b"")
            self.assertEqual(kind, "application/json")
            self.assertEqual(
                json.loads(body), {"code": 0, "supporters": [], "is_fullset": True}
            )
        self.assertEqual(save.state, before)

    def test_both_original_asset_urls_return_the_same_asset(self):
        asset = object()
        index = ContentPaths({"1/files/image.png": asset})
        self.assertIs(index.get("/api/1/files/image.png"), asset)
        self.assertIs(index.get("/content/1/files/image.png"), asset)
        self.assertIsNone(index.get("/other/1/files/image.png"))
        self.assertIsNone(index.get("/api/1/files/missing.png"))

    def test_android_rebuild_migrates_without_resetting_player(self):
        before = copy.deepcopy(save.state)
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), SilentMigrationHandler
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        try:
            connection.request("POST", "/billing/v1.0/migration/user/token", body=b"")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            token = json.loads(response.read())["migration_token"]
            self.assertIsInstance(token, str)
            self.assertTrue(token)
            connection.request(
                "POST",
                "/billing/v1.0/migration",
                body=json.dumps({"migration_token": token}),
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["result"], "OK")
            self.assertEqual(save.state, before)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join()
