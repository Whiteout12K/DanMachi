"""Install original episode voices directly from CRC-checked retained archives."""

# Reading guide: Episode voice installation: copy only requested original voice content
# from checked retained archives.
# Editing notes: Do not infer that missing original audio has been recovered. Preserve
# original episode identities.
# Checks: offline/test_local_downloads.py.
# Transport note: external_assets mode uses the virtual ZIP reader and returns
# before the retained legacy ADB install branch. Do not invoke old device helpers.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib, io, json, posixpath, subprocess, tarfile, tempfile
from pathlib import Path
from archive_catalog import entries
from asset_store import archive_handle
from android_archive import install_archive

ROOT = Path(__file__).resolve().parents[1]
ADB = [
    str(ROOT / "runtime/sdk/platform-tools/adb"),
    "-P",
    "5038",
    "-s",
    "emulator-5560",
]


def ensure_episode(episode_id):
    """Make one episode original voice assets available from checked retained ZIPs."""
    if type(episode_id) is not int or episode_id < 1:
        raise ValueError("Invalid episode")
    prefix = "contents/voice_root/files/sound/voice_episode/" + str(episode_id) + "/"
    files = [
        (entry, archive, member)
        for entry, archive, member in entries(ROOT / "assets/archives")
        if entry.filename.startswith(prefix) and not entry.is_dir()
    ]
    if not files:
        raise ValueError("Original episode voices are missing")
    if (
        json.loads((ROOT / "offline/apks/build.json").read_text())
        .get("external_assets", {})
        .get("version")
        == 1
    ):
        return
    version = hashlib.sha256(
        json.dumps([(e.filename, e.CRC, e.file_size) for e, _, _ in files]).encode()
    ).hexdigest()
    marker = "files/local-episode-" + str(episode_id)
    r = subprocess.run(
        ADB + ["shell", "run-as", "com.eu.danmore", "cat", marker], capture_output=True
    )
    if r.returncode == 0 and r.stdout.decode().strip() == version:
        return
    with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as directory:
        archive = Path(directory) / "voice.tar"
        with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
            for logical, source, member in files:
                handle = archive_handle(str(source))
                info = handle.getinfo(member)
                if (info.CRC, info.file_size) != (logical.CRC, logical.file_size):
                    raise ValueError("Episode voice source changed")
                data = handle.read(info)
                entry = tarfile.TarInfo("files/" + logical.filename)
                entry.size = len(data)
                entry.mode = 0o600
                tar.addfile(entry, io.BytesIO(data))
                name = logical.filename.removeprefix("contents/voice_root/")
                link = tarfile.TarInfo("files/contents/1/" + name)
                link.type = tarfile.SYMTYPE
                link.linkname = posixpath.relpath(
                    entry.name, posixpath.dirname(link.name)
                )
                tar.addfile(link)
            data = (version + "\n").encode()
            entry = tarfile.TarInfo(marker)
            entry.size = len(data)
            entry.mode = 0o600
            tar.addfile(entry, io.BytesIO(data))
        install_archive(archive)
