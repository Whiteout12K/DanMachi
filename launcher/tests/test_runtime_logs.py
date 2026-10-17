# Regression checks for runtime logs.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from game import stream_log


class LogTests(unittest.TestCase):
    def test_split_error_survives_large_backtrace_and_logs_stay_bounded(self):
        data = (
            b"normal\n"
            + b"x" * 4080
            + b"\n__assert2: tutorial failed\n"
            + b"backtrace\n" * 10000
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "runtime.log"
            stream_log(SimpleNamespace(stdout=io.BytesIO(data)), path)
            errors = path.with_name("runtime-errors.log").read_bytes()
            self.assertIn(b"__assert2: tutorial failed", errors)
            self.assertNotIn(b"normal", errors)
            self.assertLessEqual(len(errors), 16384)
            self.assertLessEqual(path.stat().st_size, 16384)
