"""Recover shared media on demand from the user's CRC-checked ZIP archives."""

# Reading guide: Archive recovery: locate manifest-matching retained ZIP members for
# requested logical assets.
# Editing notes: Recovery must verify the source rather than silently substituting
# unrelated bytes.
# Checks: offline/test_asset_layout.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools
import hashlib
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import zipfile
from asset_store import ArchivedAsset, archive_handle
from archive_catalog import entries
from audio_profile import original_md5

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/archives"
COLLECTIONS = ("voice_root", "area_atlas_root", "single_image_root")


@functools.lru_cache(maxsize=1)
def index():
    """Read indexed archived asset sources for on-demand recovery."""
    result = {}
    for entry, archive, member in entries(SOURCE):
        parts = PurePosixPath(entry.filename).parts
        if (
            entry.is_dir()
            or len(parts) < 3
            or parts[0] != "contents"
            or parts[1] not in COLLECTIONS
            or ".." in parts
        ):
            continue
        name = "/".join(parts[2:])
        result.setdefault(name, (archive, member, parts[1]))
    return result


def recover(url):
    """Find and verify the retained source for one requested asset."""
    path = unquote(urlsplit(url).path)
    prefix = next(
        (
            p
            for p in ("/api/contents/", "/content/contents/", "/content/", "/storage/")
            if path.startswith(p)
        ),
        None,
    )
    if prefix is None:
        return None
    parts = PurePosixPath(path[len(prefix) :]).parts
    collection_hint = None
    if parts and parts[0] in COLLECTIONS:
        collection_hint = parts[0]
        parts = parts[1:]
    if not parts or ".." in parts or parts[0] != "files":
        return None
    expected = None
    name = "/".join(parts)
    if name not in index() and len(parts) > 1:
        candidate = "/".join(parts[:-1])
        digest = PurePosixPath(parts[-1]).stem
        if len(digest) == 32 and all(c in "0123456789abcdef" for c in digest):
            name = candidate
            expected = digest
    source = index().get(name)
    if source is None:
        return None
    archive, entry, collection = source
    if collection_hint is not None and collection_hint != collection:
        return None
    target = (ROOT / "contents" / collection / name).resolve()
    if (ROOT / "contents" / collection).resolve() not in target.parents:
        return None
    if target.is_file():
        if not expected or hashlib.md5(target.read_bytes()).hexdigest() == expected:
            return target
        # An older extracted cache must not hide a matching compact source.
    z = archive_handle(str(archive))
    info = z.getinfo(entry)
    # Frozen game tables can retain an original audio URL. Its ZIP metadata
    # binds that original checksum to this deliberately smaller replacement.
    if (
        expected
        and expected != original_md5(info)
        and hashlib.md5(z.read(entry)).hexdigest() != expected
    ):
        return None
    return ArchivedAsset(
        {
            "archive": str(archive),
            "member": entry,
            "size": info.file_size,
            "crc": info.CRC,
            "md5": expected or "",
        }
    )
