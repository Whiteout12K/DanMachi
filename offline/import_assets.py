"""Import manifest-verified assets, including shared archive collections."""

# Reading guide: Asset import utility: verify manifest identities before accepting asset
# payloads or shared collections.
# Editing notes: Importing media is separate from importing a player account; account
# tools live in user_data.py.
# Checks: offline/test_asset_store.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
from archive_catalog import entries
from asset_store import archive_handle

ROOT = Path(__file__).resolve().parents[1]


def import_assets(directory, phases=("1", "2")):
    """
    Import requested assets only after validating their original manifest metadata.
    """
    wanted = {}
    shared = {}
    for phase in phases:
        manifest = json.loads(
            (ROOT / "contents" / phase / "project.manifest").read_text()
        )
        for name, item in manifest["assets"].items():
            relative = PurePosixPath("contents") / phase / name
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe manifest path")
            wanted[str(relative)] = item
            shared.setdefault(name, []).append((str(relative), item))
    report = {
        "source": str(directory),
        "imported": 0,
        "bytes_added": 0,
        "already_present": 0,
        "mismatches": [],
    }
    for entry, archive, member in entries(directory):
        zipped = archive_handle(str(archive))
        parts = PurePosixPath(entry.filename).parts
        if (
            len(parts) > 2
            and parts[:1] == ("contents",)
            and parts[1] in ("voice_root", "area_atlas_root", "single_image_root")
            and not entry.is_dir()
        ):
            candidates = shared.get("/".join(parts[2:]), [])
            pending = [
                (n, i)
                for n, i in candidates
                if not (ROOT / n).is_file() and i["size"] == entry.file_size
            ]
            if pending:
                data = zipped.read(member)
                digest = hashlib.md5(data).hexdigest()
                for name, item in pending:
                    if digest != item["md5"]:
                        continue
                    destination = ROOT / name
                    if (
                        ROOT / "contents"
                    ).resolve() not in destination.resolve().parents:
                        raise ValueError("Unsafe shared asset path")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(destination.name + ".importing")
                    temporary.write_bytes(data)
                    temporary.replace(destination)
                    report["imported"] += 1
                    report["bytes_added"] += len(data)
            continue
        item = wanted.get(entry.filename)
        if item is None or entry.is_dir():
            continue
        destination = ROOT / entry.filename
        if (ROOT / "contents").resolve() not in destination.resolve().parents:
            raise ValueError("Asset destination leaves the contents folder")
        if (
            destination.is_file()
            and destination.stat().st_size == item["size"]
            and hashlib.md5(destination.read_bytes()).hexdigest() == item["md5"]
        ):
            report["already_present"] += 1
            continue
        if entry.file_size != item["size"]:
            report["mismatches"].append(entry.filename)
            continue
        data = zipped.read(member)
        if hashlib.md5(data).hexdigest() != item["md5"]:
            report["mismatches"].append(entry.filename)
            continue
        # A supplied valid original asset may replace an invalid local copy.
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".importing")
        temporary.write_bytes(data)
        temporary.replace(destination)
        report["imported"] += 1
        report["bytes_added"] += len(data)
    (ROOT / "state/logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "state/logs/asset-import.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--phases", nargs="+", default=["1", "2"])
    args = parser.parse_args()
    import_assets(args.directory, args.phases)
