# Regression checks for tutorial weights.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import unittest
import subprocess
import zlib
import rebuild_master as m
import tutorial_weights as w
from zip_reader import catalog, asset


class WeightsTests(unittest.TestCase):
    def test_exact_beginner_group_positive_weight(self):
        b = w.table_bytes()
        rows = m.rows(b)
        self.assertEqual(len(rows), 1)
        self.assertEqual(m.scalar(b, rows[0], 0), w.GROUP)
        self.assertEqual(m.scalar(b, rows[0], 1), 1)

    def test_encrypted_virtual_asset_round_trip(self):
        with asset(w.PATH).open() as stream:
            body = stream.read()
        self.assertEqual(catalog()[w.PATH]["size"], len(body))
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
            input=body,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(zlib.decompress(decoded), w.table_bytes())
