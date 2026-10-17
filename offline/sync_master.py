"""Install verified archived game tables without copying the media archive."""

# Reading guide: Historical table installation utility retained for reference.
# Editing notes: This contains an old ADB workflow and is not part of the current Mac
# launch path. Current maintenance must use the folder-local Mac setup; do not run this
# legacy installer.
# Checks: launcher/CURRENT_SETUP.md.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib
import json
import posixpath
from pathlib import Path
import subprocess
import tarfile
import tempfile
from android_archive import install_archive
from asset_store import resolve, ArchivedAsset, archive_handle
from audio_profile import original_md5, sync_installed_audio

ROOT = Path(__file__).resolve().parents[1]
ADB = [
    str(ROOT / "runtime/sdk/platform-tools/adb"),
    "-P",
    "5038",
    "-s",
    "emulator-5560",
]
PACKAGE = "com.eu.danmore"


def adb(*args, check=True):
    """
    Historical device-command helper; not used by the current Mac maintenance path.
    """
    return subprocess.run(
        ADB + list(args), check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def main():
    """
    Historical master installer; consult CURRENT_SETUP.md instead of running this on
    Mac.
    """
    if (
        json.loads((ROOT / "offline/apks/build.json").read_text())
        .get("external_assets", {})
        .get("version")
        == 1
    ):
        print("External ZIP assets enabled; no Android media copies required.")
        return
    sync_installed_audio()
    from sync_voice import ensure_episode

    ensure_episode(7010000101)
    from sync_unit import (
        ensure_unit,
        ensure_costume,
        ensure_communication_portraits,
        _ensure_assets,
    )

    save_path = ROOT / "state/offline/player-state.json"
    if save_path.exists():
        saved = json.loads(save_path.read_text())
        for row in saved.get("tables", {}).get("UserPC", []):
            ensure_unit(row["pcId"])
        costumes = {
            r["costumeId"]
            for r in saved.get("tables", {}).get("UserCharacterCostume", [])
        }
        costumes.update(
            r["costumeId"]
            for r in saved.get("tables", {}).get("UserCommunicationCharacter", [])
            if r.get("costumeId")
        )
        for costume in sorted(costumes):
            ensure_costume(costume)
    ensure_communication_portraits()
    from sync_album import ensure_album

    ensure_album()
    # Native communication and shop screens also use these fixed NPC models.
    for costume in (1021003000, 1022043000):
        ensure_costume(costume)
    _ensure_assets(
        ("files/friend/bg.jpg",), "local-friend-background", require_sprite=False
    )
    files = []
    for phase in ("1", "2", "3", "4", "5"):
        metadata = json.loads(
            (ROOT / "contents" / phase / "project.manifest").read_text()
        )["assets"]
        for name, item in sorted(metadata.items()):
            # Town scenery is needed immediately after the opening tutorial.
            if phase == "3" and not name.startswith(
                (
                    "files/lwf/battleLwf/810000",
                    "files/lwf/battleLwf/8121",
                    "files/areaAtlas/",
                    "files/adventure/",
                    "files/movie/",
                    "files/ui/",
                    "files/lwf/uiLwf/tutorial/",
                    "files/lwf/uiLwf/home/",
                    "files/lwf/uiLwf/lottery/",
                    "files/lwf/uiLwf/quest/",
                    "files/ui_atlas/",
                )
            ):
                continue
            if phase in ("4", "5") and not name.startswith(
                (
                    "files/spine/realCharacterSpine/1112030000.",
                    "files/spine/enemySpine/3501",
                )
            ):
                continue
            path = resolve(phase, name, item)
            if path is None:
                continue
            if path.stat().st_size != item["size"] or (
                not isinstance(path, ArchivedAsset)
                and hashlib.md5(path.read_bytes()).hexdigest() != item["md5"]
            ):
                raise ValueError("Archived asset hash mismatch: " + phase + "/" + name)
            files.append((path, phase + "/" + name, item["md5"]))
    # Explicit version replacements are separately hashed; original manifests stay intact.
    overlays = ROOT / "offline/compatibility_assets"
    if (overlays / "manifest.json").exists():
        for entry in json.loads((overlays / "manifest.json").read_text())["assets"]:
            path = (overlays / entry["file"]).resolve()
            if overlays.resolve() not in path.parents or not entry["target"].startswith(
                "1/master/"
            ):
                raise ValueError("Unsafe compatibility asset")
            if hashlib.md5(path.read_bytes()).hexdigest() != entry["md5"]:
                raise ValueError("Compatibility asset checksum mismatch")
            files.append((path, entry["target"], entry["md5"]))
    required = {
        "1/master/divide_enc/communicationCharacter.enc",
        "1/master/divide_enc/characterCostume.enc",
        "1/master/divide_enc/shop.enc",
        "1/files/ui/world/direction.png",
        "1/files/movie/opening.usm",
    }
    if not required.issubset({name for _, name, _ in files}):
        raise ValueError("Required startup tables are missing")
    # Audio migration updates existing files separately. Keep the original
    # asset identity here to avoid rewriting all unchanged startup assets.
    identities = []
    for path, name, digest in files:
        if isinstance(path, ArchivedAsset):
            digest = (
                original_md5(
                    archive_handle(str(path.archive())).getinfo(path.record["member"])
                )
                or digest
            )
        identities.append((name, digest))
    fingerprint = hashlib.sha256(
        ("opening-overlay-v3-gnu:" + json.dumps(identities)).encode()
    ).hexdigest()
    current = adb(
        "shell", "run-as", PACKAGE, "cat", "files/local-master-version", check=False
    )
    if current.returncode == 0 and current.stdout.decode().strip() == fingerprint:
        print("Verified opening assets already installed.")
        return
    # A changed receipt does not mean the complete media cache needs copying.
    # Compare actual payloads, including converted audio, before installing.
    observed = adb(
        "shell",
        "run-as",
        PACKAGE,
        "sh",
        "-c",
        "'find -L files/contents -type f -print0 | xargs -0 -n 64 md5sum'",
        check=False,
    )
    hashes = {}
    if observed.returncode == 0:
        for line in observed.stdout.decode().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and len(parts[0]) == 32:
                hashes[parts[1].lstrip("*")] = parts[0]
    changed = []
    for path, name, digest in files:
        actual = hashlib.md5()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                actual.update(chunk)
        if hashes.get("files/contents/" + name) != actual.hexdigest():
            changed.append((path, name, digest))
    adb("shell", "am", "force-stop", PACKAGE)
    temporary_root = ROOT / "state/temp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
        archive = Path(directory) / "master.tar"
        with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
            installed = {name for _, name, _ in files}
            for path, name, _ in changed:
                if isinstance(path, ArchivedAsset):
                    entry = tarfile.TarInfo("files/contents/" + name)
                    entry.size = path.stat().st_size
                    entry.mode = 0o600
                    with path.open() as stream:
                        tar.addfile(entry, stream)
                else:
                    tar.add(path, arcname="files/contents/" + name, recursive=False)
            # The research bootstrap only registers phase 1 with FileUtils.
            # Expose verified phase-2 and town scenery assets there without duplicating their data.
            for path, name, _ in files:
                if name.split("/", 1)[0] not in ("2", "3", "4", "5"):
                    continue
                alias = "1/" + name[2:]
                if alias in installed:
                    continue
                link = tarfile.TarInfo("files/contents/" + alias)
                link.type = tarfile.SYMTYPE
                link.linkname = posixpath.relpath(
                    "files/contents/" + name, posixpath.dirname(link.name)
                )
                tar.addfile(link)
            marker = Path(directory) / "version"
            marker.write_text(fingerprint + "\n")
            tar.add(marker, arcname="files/local-master-version", recursive=False)
        install_archive(archive, PACKAGE)
    print(
        "Verified "
        + str(len(files))
        + " startup assets; installed "
        + str(len(changed))
        + " changed files; player save retained."
    )


if __name__ == "__main__":
    main()
