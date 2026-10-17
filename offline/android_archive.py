"""Install a checked TAR into the original Android application directory."""

# Reading guide: Historical checked TAR installer using the retired device transport.
# Editing notes: Not part of current Mac play. Do not run this old ADB installer;
# current assets are exposed through the virtual ZIP reader.
# Checks: offline/test_android_archive.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import posixpath, subprocess, tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ADB = [
    str(ROOT / "runtime/sdk/platform-tools/adb"),
    "-P",
    "5038",
    "-s",
    "emulator-5560",
]


def install_archive(archive, package="com.eu.danmore"):
    """Validate a TAR before the historical device install; not the current Mac path."""
    if package != "com.eu.danmore":
        raise ValueError("Unexpected game package")
    with tarfile.open(archive) as source:
        for item in source:
            parts = PurePosixPath(item.name).parts
            if not parts or PurePosixPath(item.name).is_absolute() or ".." in parts:
                raise ValueError("Unsafe archive path")
            if parts[0] not in (
                "files",
                "databases",
                "shared_prefs",
                "cache",
                "code_cache",
                "no_backup",
                "ldb",
                "app_textures",
                "app_webview",
            ):
                raise ValueError("Unexpected archive directory")
            if item.issym() or item.islnk():
                target = (
                    posixpath.normpath(
                        posixpath.join(posixpath.dirname(item.name), item.linkname)
                    )
                    if item.issym()
                    else item.linkname
                )
                if (
                    PurePosixPath(target).is_absolute()
                    or ".." in PurePosixPath(target).parts
                ):
                    raise ValueError("Unsafe archive link")
            elif not (item.isfile() or item.isdir()):
                raise ValueError("Unsupported archive member")
    # Stream into extraction so installing assets does not allocate another
    # complete TAR inside the Android disk and permanently enlarge its file.
    with Path(archive).open("rb") as stream:
        subprocess.run(
            ADB + ["exec-in", "run-as", package, "tar", "-xf", "-"],
            stdin=stream,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
