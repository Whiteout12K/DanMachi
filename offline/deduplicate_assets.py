"""Share byte-identical ZIP payloads while retaining every logical asset name."""

# Reading guide: Optional storage maintenance: plan and repack byte-identical ZIP
# members while preserving logical names.
# Editing notes: The command can rewrite archive outputs. Review the plan and integrity
# checks before using it; it is not a startup dependency.
# Checks: offline/test_archive_deduplication.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import collections, copy, fcntl, gzip, hashlib, json, os, struct, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "assets/archives"


def digest_member(archive, entry):
    """Hash the uncompressed member bytes to identify exact duplicate payloads."""
    digest = hashlib.sha256()
    with archive.open(entry) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan(folder):
    """Find identical archived payloads and report their reusable storage locations."""
    paths = sorted(Path(folder).glob("*.zip"))
    groups = collections.Counter()
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            groups.update(
                (i.file_size, i.CRC) for i in archive.infolist() if not i.is_dir()
            )
    seen = {}
    sources = {}
    redirects = {}
    verified = 0
    logical = 0
    saved = 0
    for path in paths:
        aliases = {}
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            for ordinal, info in enumerate(infos):
                if info.is_dir():
                    continue
                logical += 1
                key = (info.file_size, info.CRC)
                if groups[key] < 2:
                    continue
                digest = digest_member(archive, info)
                verified += 1
                previous = seen.setdefault(key, {})
                if digest in previous:
                    first = previous[digest]
                    alias = {
                        "name": info.filename,
                        "archive": first[0],
                        "member": first[1],
                        "size": info.file_size,
                        "crc": info.CRC,
                        "sha256": digest,
                    }
                    aliases[str(ordinal)] = alias
                    redirects[(path.name, info.filename)] = alias
                    saved += info.compress_size
                else:
                    previous[digest] = (path.name, info.filename)
        sources[path.name] = {"count": len(infos), "aliases": aliases}
        print(
            "Verified duplicates in " + path.name + ": " + str(len(aliases)), flush=True
        )
    return (
        {"format": 1, "sources": sources},
        redirects,
        {
            "logicalFilesPreserved": logical,
            "duplicatePayloads": len(redirects),
            "candidatePayloadsSHA256Checked": verified,
            "duplicateCompressedBytes": saved,
        },
    )


def compressed_bytes(archive, info):
    """Read the stored compressed payload for lossless repacking."""
    archive.fp.seek(info.header_offset)
    header = archive.fp.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise ValueError("Invalid local ZIP header")
    name_size, extra_size = struct.unpack_from("<HH", header, 26)
    archive.fp.seek(name_size + extra_size, 1)
    remaining = info.compress_size
    while remaining:
        block = archive.fp.read(min(1024 * 1024, remaining))
        if not block:
            raise ValueError("Truncated ZIP payload")
        remaining -= len(block)
        yield block


def repack(path, aliases):
    """Copy compressed bytes unchanged; validate every retained payload."""
    temporary = path.with_suffix(".deduplicating")
    expected = {}
    try:
        with (
            zipfile.ZipFile(path) as source,
            zipfile.ZipFile(temporary, "w", allowZip64=True) as target,
        ):
            target.comment = source.comment
            for ordinal, old in enumerate(source.infolist()):
                if str(ordinal) in aliases:
                    continue
                if old.flag_bits & 9 or old.file_size >= zipfile.ZIP64_LIMIT:
                    raise ValueError("Unsupported ZIP entry for raw copying")
                info = copy.copy(old)
                info.header_offset = target.start_dir
                target._writecheck(info)
                target._didModify = True
                target.fp.seek(target.start_dir)
                target.fp.write(info.FileHeader(False))
                digest = hashlib.sha256()
                for block in compressed_bytes(source, old):
                    digest.update(block)
                    target.fp.write(block)
                target.start_dir = target.fp.tell()
                target.filelist.append(info)
                target.NameToInfo[info.filename] = info
                expected[info.filename] = (
                    info.file_size,
                    info.CRC,
                    info.compress_size,
                    digest.hexdigest(),
                )
        with zipfile.ZipFile(temporary) as check:
            if len(check.infolist()) != len(expected):
                raise ValueError("Retained file count changed")
            for info in check.infolist():
                digest = hashlib.sha256()
                for block in compressed_bytes(check, info):
                    digest.update(block)
                if expected[info.filename] != (
                    info.file_size,
                    info.CRC,
                    info.compress_size,
                    digest.hexdigest(),
                ):
                    raise ValueError("Compressed payload changed: " + info.filename)
        with temporary.open("rb") as file:
            os.fsync(file.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main():
    """Run the requested deduplication planning or archive maintenance action."""
    if (FOLDER / "aliases.json.gz").exists():
        raise RuntimeError("The archive collection is already deduplicated.")
    import sys

    sys.path.insert(0, str(ROOT / "launcher"))
    import game

    if game.connected():
        raise RuntimeError("Close the game before compacting asset archives.")
    with (ROOT / "state/launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        catalog, redirects, report = plan(FOLDER)
        if not redirects:
            print("No duplicate payloads found.")
            return
        prepared = {}
        backups = {}
        index_path = ROOT / "state/offline/asset-sources.json.gz"
        original_index = index_path.read_bytes()
        catalog_path = FOLDER / "aliases.json.gz"
        before = sum(p.stat().st_size for p in FOLDER.glob("*.zip"))
        try:
            for name, description in catalog["sources"].items():
                if description["aliases"]:
                    print(
                        "Copying and verifying retained compressed bytes: " + name,
                        flush=True,
                    )
                    prepared[FOLDER / name] = repack(
                        FOLDER / name, description["aliases"]
                    )
            records = json.loads(gzip.decompress(original_index))
            for record in records.values():
                alias = (
                    redirects.get((Path(record["archive"]).name, record["member"]))
                    if Path(record["archive"]).parent == Path("assets/archives")
                    else None
                )
                if alias:
                    if (record["size"], record["crc"]) != (alias["size"], alias["crc"]):
                        raise ValueError("Indexed alias metadata mismatch")
                    record["archive"] = "assets/archives/" + alias["archive"]
                    record["member"] = alias["member"]
            # Originals remain available until both the new physical ZIPs and
            # virtual paths have been validated. They are removed on success.
            for path, temporary in prepared.items():
                backup = path.with_suffix(".dedup-original")
                path.replace(backup)
                backups[path] = backup
                temporary.replace(path)
            with gzip.open(catalog_path, "wt") as stream:
                json.dump(catalog, stream, separators=(",", ":"))
            with gzip.open(index_path, "wt") as stream:
                json.dump(records, stream, separators=(",", ":"))
            from archive_catalog import entries

            handles = {}
            count = 0
            try:
                for logical, physical, member in entries(FOLDER):
                    if physical not in handles:
                        handles[physical] = zipfile.ZipFile(physical)
                    actual = handles[physical].getinfo(member)
                    if (logical.file_size, logical.CRC) != (
                        actual.file_size,
                        actual.CRC,
                    ):
                        raise ValueError("Logical asset metadata changed")
                    if not logical.is_dir():
                        count += 1
                if count != report["logicalFilesPreserved"]:
                    raise ValueError("Logical assets missing")
                for record in records.values():
                    path = ROOT / record["archive"]
                    if path not in handles:
                        handles[path] = zipfile.ZipFile(path)
                    actual = handles[path].getinfo(record["member"])
                    if (actual.file_size, actual.CRC) != (
                        record["size"],
                        record["crc"],
                    ):
                        raise ValueError("Phase asset mapping changed")
            finally:
                for handle in handles.values():
                    handle.close()
            after = (
                sum(p.stat().st_size for p in FOLDER.glob("*.zip"))
                + catalog_path.stat().st_size
            )
            if after >= before:
                raise ValueError("No net storage saving")
            report.update(
                {
                    "beforeBytes": before,
                    "afterBytes": after,
                    "savedBytes": before - after,
                    "allOriginalLogicalNamesPreserved": True,
                    "allRetainedCompressedPayloadsSHA256Verified": True,
                    "phaseReferencesVerified": len(records),
                }
            )
        except BaseException:
            for path, backup in backups.items():
                path.unlink(missing_ok=True)
                backup.replace(path)
            index_path.write_bytes(original_index)
            catalog_path.unlink(missing_ok=True)
            raise
        finally:
            for temporary in prepared.values():
                temporary.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink()
        (ROOT / "state/logs/lossless-asset-deduplication.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
