# Regression checks for menu pages.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import re
import json
import unittest
from urllib.parse import quote
from menu_pages import page, SUPPORT_LAYOUTS


class OfflineMenuPagesTest(unittest.TestCase):
    def test_support_guards_preserve_native_bindings_and_other_controls(self):
        from zip_reader import asset, catalog, index_bytes
        from asset_store import ArchivedAsset

        for name, tags in SUPPORT_LAYOUTS.items():
            path = "1/files/ui_atlas/title/" + name
            record = catalog()[path]
            original = json.loads(
                ArchivedAsset({**record, "size": record["archive_size"]}).read_bytes()
            )
            with asset(path).open() as source:
                data = source.read()
            self.assertEqual(len(data), record["size"])
            guarded = json.loads(data)
            self.assertEqual(
                len(original["root"]["childs"]), len(guarded["root"]["childs"])
            )
            for before, after in zip(
                original["root"]["childs"], guarded["root"]["childs"]
            ):
                if before["tag"] in tags:
                    self.assertEqual(after["position"], {"x": -8192, "y": -8192})
                    self.assertEqual(after["opacity"], 0)
                    after["position"] = before["position"]
                    after["opacity"] = before["opacity"]
            self.assertEqual(guarded, original)
        self.assertIn(b"modal_support_top.json", index_bytes())

    def test_original_help_route_and_close_guidance(self):
        body = page("/content").decode()
        self.assertIn("Offline Help", body)
        self.assertIn("Export User.command", body)
        self.assertIn("close button", body)
        self.assertIsNone(page("/content/1/files/image.png"))

    def test_policy_index_and_all_documents_are_local(self):
        request = "url=" + quote(
            "https://www.wfs.games/en/eu/policies/danmemo_google.html", safe=""
        )
        index = page("/offline/page", request).decode()
        links = re.findall(r'href="([^"]+)"', index)
        self.assertEqual(len(links), 4)
        for link in links:
            body = page(link).decode()
            self.assertIn("Publisher: WFS", body)
            self.assertNotRegex(body, r"<(?:script|img|iframe|link)\b")
            self.assertNotRegex(body, r'(?:href|src)=["\']https?://')
            self.assertIn("default-src 'none'", body)
        self.assertGreater(len(page("/offline/policy/terms")), 10000)
        self.assertIsNone(page("/offline/policy/missing"))

    def test_external_urls_cannot_fetch_remote_content_or_inject_html(self):
        body = page(
            "/offline/page",
            "url=" + quote("https://example.com/<script>bad</script>", safe=""),
        ).decode()
        self.assertIn("Offline information", body)
        self.assertNotIn("example.com", body)
        self.assertNotIn("<script>", body)
        spoof = page(
            "/offline/page",
            "url=" + quote("https://www.wfs.games.example.com/terms/x", safe=""),
        ).decode()
        self.assertIn("Offline information", spoof)

    def test_retained_policy_urls_choose_the_right_local_document(self):
        for route, kind in [
            ("terms", "terms"),
            ("privacypolicy", "privacy"),
            ("gem", "currency"),
        ]:
            body = page(
                "/offline/page",
                "url="
                + quote(
                    "https://www.wfs.games/en/eu/" + route + "/danmemo_google.html",
                    safe="",
                ),
            )
            self.assertEqual(body, page("/offline/policy/" + kind))
