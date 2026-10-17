# Regression checks for android archive.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
import io, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from android_archive import install_archive


class ArchiveInstallTests(unittest.TestCase):
    def archive(self, folder, name, link=None):
        path = Path(folder) / "test.tar"
        with tarfile.open(path, "w") as t:
            e = tarfile.TarInfo(name)
            if link is not None:
                e.type = tarfile.SYMTYPE
                e.linkname = link
                t.addfile(e)
            else:
                e.size = 4
                t.addfile(e, io.BytesIO(b"data"))
        return path

    def test_invalid_paths_and_links_rejected_before_android_is_touched(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("android_archive.subprocess.run") as run,
        ):
            for name, link in [
                ("../outside", None),
                ("files/link", "../../../outside"),
                ("files/link", "/outside"),
            ]:
                with self.assertRaises(ValueError):
                    install_archive(self.archive(folder, name, link))
            run.assert_not_called()

    def test_archive_streams_directly_without_allocating_a_guest_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, "files/ldb/account")
            with patch(
                "android_archive.subprocess.run", side_effect=RuntimeError("failed")
            ) as run:
                with self.assertRaises(RuntimeError):
                    install_archive(path)
                run.assert_called_once()
                self.assertEqual(
                    run.call_args.args[0][-6:],
                    ["exec-in", "run-as", "com.eu.danmore", "tar", "-xf", "-"],
                )
                self.assertEqual(Path(run.call_args.kwargs["stdin"].name), path)
