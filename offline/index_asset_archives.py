"""Verify archived sources before removing any extracted phase asset."""

# Reading guide: Archive index maintenance: verify retained sources and build the
# logical asset lookup.
# Editing notes: This can remove extracted copies after verification. Review
# CURRENT_SETUP.md before running; normal play uses the existing index.
# Checks: offline/test_asset_layout.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import gzip, hashlib, json, zipfile
from pathlib import Path
from asset_store import ROOT, INDEX, archive_handle
from archive_catalog import entries


def main():
    """
    Verify archived sources and update the asset index for explicit storage
    maintenance.
    """
    wanted = {}
    names = {}
    by_hash = {}
    for phase in "12345678":
        for name, item in json.loads(
            (ROOT / "contents" / phase / "project.manifest").read_text()
        )["assets"].items():
            p = ROOT / "contents" / phase / name
            if not p.is_file():
                continue
            key = phase + "/" + name
            wanted[key] = item
            names.setdefault(name, []).append(key)
            by_hash.setdefault((item["size"], item["md5"]), []).append(key)
    # Most verified assets now live only in ZIPs. Reindexing the few remaining
    # extracted files must not discard the existing archive-only mappings.
    found = {}
    if INDEX.is_file():
        with gzip.open(INDEX, "rt") as stream:
            found = json.load(stream)
        for record in found.values():
            path = (ROOT / record["archive"]).resolve()
            if not path.is_relative_to(ROOT):
                raise ValueError("External archived asset")
            info = archive_handle(str(path)).getinfo(record["member"])
            if (info.file_size, info.CRC) != (record["size"], record["crc"]):
                raise ValueError("Existing archived asset changed")

    def all_sources():
        yield from entries(ROOT / "assets/archives")
        for source in sorted((ROOT / "offline/apks").glob("*.apk")):
            with zipfile.ZipFile(source) as archive:
                for entry in archive.infolist():
                    yield entry, source, entry.filename

    for entry, source, member in all_sources():
        archive = archive_handle(str(source))
        if entry.is_dir():
            continue
        parts = entry.filename.split("/")
        candidates = []
        if len(parts) > 2 and parts[0] == "contents":
            if parts[1] in "12345678" and len(parts[1]) == 1:
                candidates = [parts[1] + "/" + "/".join(parts[2:])]
            elif parts[1] in ("voice_root", "area_atlas_root", "single_image_root"):
                candidates = names.get("/".join(parts[2:]), [])
        if source.suffix == ".apk":
            n = entry.filename
            for prefix in ("assets/common/", "assets/"):
                if n.startswith(prefix):
                    candidates += names.get(n[len(prefix) :], [])
        candidates = [
            k
            for k in candidates
            if k in wanted and k not in found and wanted[k]["size"] == entry.file_size
        ]
        if not candidates:
            continue
        data = archive.read(member)
        digest = hashlib.md5(data).hexdigest()
        for key in candidates:
            if wanted[key]["md5"] != digest:
                continue
            local = ROOT / "contents" / key
            if hashlib.md5(local.read_bytes()).hexdigest() != digest:
                continue
            try:
                label = str(source.relative_to(ROOT))
            except ValueError:
                label = str(source)
            found[key] = {
                "archive": label,
                "member": member,
                "size": entry.file_size,
                "md5": digest,
                "crc": entry.CRC,
            }
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    temp = INDEX.with_suffix(".tmp")
    with gzip.open(temp, "wt") as stream:
        json.dump(found, stream, separators=(",", ":"))
    temp.replace(INDEX)
    report = {
        "verified_archive_sources": len(found),
        "local_entries": len(wanted),
        "unmapped_retained": sorted(set(wanted) - set(found)),
    }
    (ROOT / "state/logs/archive-source-audit.json").write_text(
        json.dumps(report, indent=2)
    )
    print(report, flush=True)


if __name__ == "__main__":
    main()
