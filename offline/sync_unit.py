"""Expose archive-backed artwork for a locally awarded unit before it is used."""

# Reading guide: Unit artwork availability: expose retained assets for native units,
# costumes and communication portraits.
# Editing notes: This prepares media only; it must not grant ownership or change
# character progress.
# Checks: offline/test_inventory_transactions.py.
# Transport note: external_assets mode uses the virtual ZIP reader and returns
# before the retained legacy ADB install branch. Do not invoke old device helpers.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools, hashlib, json, posixpath, subprocess, tarfile, tempfile
from pathlib import Path
from asset_store import resolve
from android_archive import install_archive

ROOT = Path(__file__).resolve().parents[1]
ADB = [
    str(ROOT / "runtime/sdk/platform-tools/adb"),
    "-P",
    "5038",
    "-s",
    "emulator-5560",
]


@functools.lru_cache(maxsize=1)
def manifests():
    """Cache original manifests used to locate unit artwork."""
    return {
        str(i): json.loads((ROOT / f"contents/{i}/project.manifest").read_text())[
            "assets"
        ]
        for i in range(1, 9)
    }


def ensure_unit(pc_id):
    """Expose retained media required to render a locally granted unit."""
    if type(pc_id) is not int or not 1011000000 <= pc_id < 1020000000:
        raise ValueError("Invalid unit")
    # The base character costume is shared across rarity variants.
    spine = pc_id - pc_id % 1000 + 30000000
    character = 101000000 + (pc_id // 1000) % 1000
    prefixes = (
        f"files/character/portrait/tal_{character}/",
        f"files/character/lottery/gac_{pc_id}/",
        f"files/spine/characterSpine/{str(spine)[:-1]}",
        f"files/lottery/name/{pc_id}.",
        f"files/lottery/text/{pc_id}.",
    )
    return _ensure_assets(prefixes, "local-unit-" + str(pc_id))


def ensure_costume(costume_id):
    """Expose retained costume media without granting costume ownership."""
    if type(costume_id) is not int or not 1020000000 <= costume_id < 1030000000:
        raise ValueError("Invalid costume")
    spine = costume_id + 90000000
    # Atlas page names append a page number directly to the model identifier.
    return _ensure_assets(
        (f"files/spine/realCharacterSpine/{spine}",), "local-costume-" + str(costume_id)
    )


def ensure_communication_portraits():
    # The roster displays silhouettes for locked characters too. Without its
    # shadow image the original client dereferences a null sprite on entry.
    """Expose retained portraits used by native communication screens."""
    names = tuple(
        n
        for assets in manifests().values()
        for n in assets
        if n.startswith("files/character/portrait/") and n.endswith("/shadow.png")
    )
    return _ensure_assets(
        names + ("files/character/portrait/tal_dummy/",),
        "local-communication-roster-v1",
        require_sprite=False,
    )


def _ensure_assets(prefixes, marker_name, require_sprite=True):
    """Verify and prepare only the selected manifest-backed asset paths."""
    files = []
    for phase, assets in manifests().items():
        for name, item in assets.items():
            if name.startswith(prefixes):
                path = resolve(phase, name, item)
                if path is not None:
                    files.append((phase, name, item, path))
    if not files or (
        require_sprite and not any(name.endswith(".skel") for _, name, _, _ in files)
    ):
        raise ValueError("No verified sprite for " + marker_name)
    if (
        json.loads((ROOT / "offline/apks/build.json").read_text())
        .get("external_assets", {})
        .get("version")
        == 1
    ):
        from zip_reader import asset

        if not all(
            asset(phase + "/" + name) is not None for phase, name, _, _ in files
        ):
            raise ValueError("External unit source missing")
        return
    version = hashlib.sha256(
        json.dumps([(p, n, i["md5"]) for p, n, i, _ in files]).encode()
    ).hexdigest()
    marker = "files/" + marker_name
    result = subprocess.run(
        ADB + ["shell", "run-as", "com.eu.danmore", "cat", marker], capture_output=True
    )
    if result.returncode == 0 and result.stdout.decode().strip() == version:
        return
    with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as directory:
        archive = Path(directory) / "unit.tar"
        with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
            for phase, name, item, path in files:
                data = path.read_bytes()
                if hashlib.md5(data).hexdigest() != item["md5"]:
                    raise ValueError("Unit asset checksum mismatch")
                import io

                entry = tarfile.TarInfo("files/contents/" + phase + "/" + name)
                entry.size = len(data)
                entry.mode = 0o600
                tar.addfile(entry, io.BytesIO(data))
                if phase != "1":
                    entry = tarfile.TarInfo("files/contents/1/" + name)
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = posixpath.relpath(
                        "files/contents/" + phase + "/" + name,
                        posixpath.dirname(entry.name),
                    )
                    tar.addfile(entry)
            data = (version + "\n").encode()
            entry = tarfile.TarInfo(marker)
            entry.size = len(data)
            entry.mode = 0o600
            tar.addfile(entry, io.BytesIO(data))
        install_archive(archive)
