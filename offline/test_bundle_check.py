"""Portability checks reject unsupported hosts and nonlocal symlinks."""

# Regression checks for bundle check.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import check_bundle


class BundleTests(unittest.TestCase):
    def test_non_macos_host_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "macOS only"):
            check_bundle.check_host(
                system="Linux",
                architecture="arm64",
                version="26.6",
                sandbox_exec="/usr/bin/sandbox-exec",
            )

    def test_non_arm_host_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Apple silicon"):
            check_bundle.check_host(
                system="Darwin",
                architecture="x86_64",
                version="26.6",
                sandbox_exec="/usr/bin/sandbox-exec",
            )

    def test_older_macos_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "26.4 or later"):
            check_bundle.check_host(
                system="Darwin",
                architecture="arm64",
                version="26.3.9",
                sandbox_exec="/usr/bin/sandbox-exec",
            )

    def test_missing_macos_service_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "sandbox-exec"
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                check_bundle.check_host(
                    system="Darwin",
                    architecture="arm64",
                    version="26.6",
                    sandbox_exec=missing,
                )

    def test_internal_symlink_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "target").write_text("inside")
            (root / "link").symlink_to("target")
            check_bundle.check_local_symlinks(root)

    def test_external_symlink_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(folder)
            (root / "link").symlink_to(Path(outside))
            with self.assertRaisesRegex(ValueError, "Outside-folder symlink"):
                check_bundle.check_local_symlinks(root)

    def test_broken_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "link").symlink_to("missing")
            with self.assertRaisesRegex(ValueError, "Broken or invalid symlink"):
                check_bundle.check_local_symlinks(root)


if __name__ == "__main__":
    unittest.main()
