"""Virtual ZIP entries whose identical payload is stored in another part."""

# Reading guide: Shared ZIP catalog: resolve logical members whose identical bytes live
# in another retained archive part.
# Editing notes: Keep logical names stable and validate shared source metadata before
# exposing entries.
# Checks: offline/test_archive_deduplication.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import gzip, json, zipfile
from pathlib import Path
from types import SimpleNamespace


def catalog(directory):
    """Load shared-member metadata used to resolve deduplicated archive entries."""
    path = Path(directory) / "aliases.json.gz"
    if not path.is_file():
        return {"format": 1, "sources": {}}
    with gzip.open(path, "rt") as stream:
        value = json.load(stream)
    if value.get("format") != 1:
        raise ValueError("Unknown archive alias format")
    return value


def entries(directory):
    """Yield original names in original order, with their physical sources."""
    directory = Path(directory)
    sources = catalog(str(directory))["sources"]
    for path in sorted(directory.glob("*.zip")):
        description = sources.get(path.name, {})
        aliases = description.get("aliases", {})
        with zipfile.ZipFile(path) as archive:
            physical = iter(archive.infolist())
            count = description.get("count", len(archive.infolist()))
            for ordinal in range(count):
                alias = aliases.get(str(ordinal))
                if alias:
                    destination = (directory / alias["archive"]).resolve()
                    if destination.parent != directory.resolve():
                        raise ValueError("Archive alias leaves its folder")
                    info = SimpleNamespace(
                        filename=alias["name"],
                        file_size=alias["size"],
                        CRC=alias["crc"],
                        is_dir=lambda: False,
                    )
                    yield info, destination, alias["member"]
                else:
                    try:
                        info = next(physical)
                    except StopIteration:
                        raise ValueError("Archive catalog is incomplete: " + path.name)
                    yield info, path, info.filename
            if next(physical, None) is not None:
                raise ValueError("Archive catalog has extra files: " + path.name)
