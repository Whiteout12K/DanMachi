"""Regression checks for selective updates and failed/duplicate save requests."""

# Regression checks for save updates.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from save_store import SaveStore
from play_days import record
import gacha


class SaveUpdateTests(unittest.TestCase):
    def store(self, directory):
        save = SaveStore(Path(directory) / "save.json")
        save._write(
            {
                "tables": {
                    "UserInfo": [{"userId": 1}],
                    "UserStatus": [{"userId": 1, "totalLoginDays": 0}],
                    "UserExpItem": [{"userId": 1, "expItemId": 10, "amount": 2}],
                    "UnrelatedHistory": [
                        {"id": i, "details": [i] * 10} for i in range(1000)
                    ],
                },
                "tokens": {},
                "accountHistory": {"events": [{"id": i} for i in range(1000)]},
            }
        )
        return save

    def delta(self, rows):
        return {
            "deltas": [{"putItems": {"UserExpItem": rows}, "deleteItems": {}}],
            "checksums": {"after": {"UserExpItem": "updated"}},
        }

    def test_invalid_request_preserves_disk_and_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            old = save.state
            before = copy.deepcopy(old)
            disk = save.path.read_bytes()
            request = self.delta([{"userId": 1, "expItemId": 10, "amount": 9}])
            request["deltas"][0]["deleteItems"] = {"UnsupportedTable": [{"id": 1}]}
            with self.assertRaises(ValueError):
                save.apply(request)
            self.assertEqual(old, before)
            self.assertEqual(save.state, before)
            self.assertEqual(save.path.read_bytes(), disk)

    def test_duplicate_request_skips_disk_write_and_preserves_progress(self):
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            request = self.delta([{"userId": 1, "expItemId": 10, "amount": 9}])
            save.apply(request)
            with patch.object(save, "_write", wraps=save._write) as writes:
                save.apply(request)
            self.assertEqual(writes.call_count, 0)
            self.assertEqual(SaveStore(save.path).state, save.state)

    def test_day_resources_and_banner_updates_do_not_change_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            save = self.store(d)
            old = save.state
            before = copy.deepcopy(old)
            record(save, now=1792000000)
            save.resources()
            gacha.prepare(save)
            self.assertEqual(old, before)
            self.assertEqual(
                save.state["tables"]["UnrelatedHistory"],
                before["tables"]["UnrelatedHistory"],
            )
            self.assertEqual(save.state["accountHistory"], before["accountHistory"])
            self.assertEqual(SaveStore(save.path).state, save.state)
