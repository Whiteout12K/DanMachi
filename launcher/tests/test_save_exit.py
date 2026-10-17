# Regression checks for save exit.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "offline"), str(ROOT / "launcher")]
from save_store import SaveStore
from save_exit import save_before_close


class SaveExitTests(unittest.TestCase):
    def test_checkpoint_preserves_latest_progress_and_pending_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(Path(directory) / "player-state.json")
            state = {
                "tables": {
                    "UserInfo": [{"userId": 1, "name": "Player"}],
                    "UserSkipTicket": [{"userId": 1, "skipTicketId": 2, "amount": 3}],
                },
                "tokens": {"UserSkipTicket": "native-checksum"},
                "questSessions": {"last": {"operationId": 100000051}},
                "acknowledgedOperations": {"100000051": "ack"},
            }
            store._write(state)
            before = copy.deepcopy(store.state)
            store.checkpoint()
            self.assertEqual(SaveStore(store.path).state, before)

    def test_close_requires_server_confirmation_and_preserves_client_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "files/ldb/000003.log"
            db.parent.mkdir(parents=True)
            db.write_bytes(b"latest client save")
            with patch(
                "save_exit.urllib.request.urlopen",
                return_value=io.BytesIO(b'{"saved":true}'),
            ) as request:
                save_before_close(root)
            self.assertEqual(request.call_args.args[0].method, "POST")
            self.assertEqual(db.read_bytes(), b"latest client save")
            with patch(
                "save_exit.urllib.request.urlopen",
                return_value=io.BytesIO(b'{"saved":false}'),
            ):
                with self.assertRaises(RuntimeError):
                    save_before_close(root)
