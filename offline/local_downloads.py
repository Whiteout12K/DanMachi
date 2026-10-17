"""Expose completion metadata for episode voices already in retained ZIPs.

The original client compares <episode>/<episode>.md5 to its episode ZIP
checksum. Media stays in the existing archives; these tiny markers exist
only in memory, and only for episode IDs with readable retained voices.
"""

# Reading guide: Native download metadata: voice_markers() exposes tiny completion
# records for voices already present in archives.
# Editing notes: Markers live in memory and require retained voice content; they do not
# download or fabricate missing audio.
# Checks: offline/test_local_downloads.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import json, re
from pathlib import PurePosixPath
from asset_store import ArchivedAsset, MemoryAsset

MANIFEST = "1/manifests/voice_episode.manifest"
VOICE = "voice_root/files/sound/voice_episode/"


def voice_markers(sources):
    """
    Create completion marker bytes only for episodes with retained readable voices.
    """
    record = sources.get(MANIFEST)
    if not record:
        return {}
    episodes = json.loads(ArchivedAsset(record).read_bytes()).get("episodes", {})
    retained = {}
    for path, source in sources.items():
        if not path.startswith(VOICE):
            continue
        parts = PurePosixPath(path[len(VOICE) :]).parts
        if len(parts) < 2 or not parts[0].isdigit() or not path.endswith(".ogg"):
            continue
        retained.setdefault(parts[0], []).append(source)
    result = {}
    for key, files in retained.items():
        episode = episodes.get(key, {})
        digest = episode.get("md5", "")
        if episode.get("episodeId") != int(key) or not re.fullmatch(
            "[0-9a-f]{32}", digest
        ):
            continue
        # Never advertise an episode whose retained sources cannot be read.
        if not all(ArchivedAsset(source).is_file() for source in files):
            continue
        result[VOICE + key + "/" + key + ".md5"] = digest.encode("ascii")
    return result


def manifest_asset(request_path):
    """Resolve original download-manifest URLs through the virtual archive FS."""
    from urllib.parse import unquote, urlsplit

    path = unquote(urlsplit(request_path).path)
    prefixes = ("/api/manifests/us/pkm/", "/content/manifests/us/pkm/")
    prefix = next((p for p in prefixes if path.startswith(p)), None)
    if not prefix:
        return None
    tail = path[len(prefix) :].split("/")
    if len(tail) != 2 or not all(tail) or any(p in (".", "..") for p in tail):
        return None
    name = tail[0]
    if name not in {
        "voice_episode.manifest",
        "area_atlas.manifest",
        "single_image.manifest",
        *(f"phase.manifest.{i}" for i in range(1, 9)),
    }:
        return None
    from zip_reader import asset

    return asset("1/manifests/" + name)
