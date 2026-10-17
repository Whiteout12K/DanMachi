"""Compatibility metadata and one-time installation of smaller Ogg assets."""

# Reading guide: Audio profile compatibility: reconcile original hashes with the
# optional smaller installed Ogg representation.
# Editing notes: Keep profile updates tied to verified source metadata, not arbitrary
# file replacements.
# Checks: offline/test_audio_profile.py.
# Transport note: external_assets mode skips the historical device-install branch.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import gzip, hashlib, io, json, struct, tarfile, tempfile
from pathlib import Path

EXTRA_ID = 0xDA4D
ROOT = Path(__file__).resolve().parents[1]


def original_md5(info):
    """Look up the original audio hash before applying compatibility metadata."""
    data = info.extra
    at = 0
    while at + 4 <= len(data):
        kind, size = struct.unpack_from("<HH", data, at)
        at += 4
        value = data[at : at + size]
        at += size
        if kind == EXTRA_ID and len(value) == 16:
            return value.hex()
    return None


def sync_installed_audio():
    """
    Apply the retained smaller-audio profile to the local installation when needed.
    """
    if (
        json.loads((ROOT / "offline/apks/build.json").read_text())
        .get("external_assets", {})
        .get("version")
        == 1
    ):
        return
    profile = ROOT / "assets/audio-quality.json"
    if not profile.is_file():
        return
    from sync_master import adb
    from android_archive import install_archive
    from archive_catalog import entries
    from asset_store import archive_handle

    version = json.loads(profile.read_text())["version"]
    marker = "files/local-audio-version"
    current = adb("shell", "run-as", "com.eu.danmore", "cat", marker, check=False)
    if current.returncode == 0 and current.stdout.decode().strip() == version:
        return
    # The game must release its currently playing files before replacements.
    adb("shell", "am", "start", "-n", "com.android.settings/.Settings", check=False)
    adb("shell", "am", "force-stop", "com.eu.danmore")
    output = adb(
        "shell",
        "run-as",
        "com.eu.danmore",
        "find",
        "files/contents",
        "-type",
        "f",
        "-name",
        "*.ogg",
        check=False,
    ).stdout.decode()
    existing = set(output.splitlines())
    count = 0
    written = set()
    with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as directory:
        path = Path(directory) / "audio.tar"
        with tarfile.open(path, "w", format=tarfile.GNU_FORMAT) as tar:
            for logical, archive, member in entries(ROOT / "assets/archives"):
                destination = "files/" + logical.filename
                if (
                    destination not in existing
                    or destination in written
                    or not logical.filename.endswith(".ogg")
                ):
                    continue
                handle = archive_handle(str(archive))
                info = handle.getinfo(member)
                if original_md5(info) is None:
                    continue
                data = handle.read(info)
                entry = tarfile.TarInfo(destination)
                entry.size = len(data)
                entry.mode = 0o600
                tar.addfile(entry, io.BytesIO(data))
                written.add(destination)
                count += 1
            payload = (version + "\n").encode()
            entry = tarfile.TarInfo(marker)
            entry.size = len(payload)
            entry.mode = 0o600
            tar.addfile(entry, io.BytesIO(payload))
        install_archive(path)
    adb("shell", "sync")
    print(
        "Updated " + str(count) + " installed audio files; player save retained.",
        flush=True,
    )
