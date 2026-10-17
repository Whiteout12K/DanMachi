"""Bounded RAM cache for small immutable archive members; no extracted files."""

# Reading guide: Small-asset cache: keep bounded immutable payloads in RAM to avoid
# repeating ZIP reads.
# Editing notes: Large media remains streamed from archives; do not add a persistent
# extracted cache.
# Checks: offline/test_asset_cache.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

from collections import OrderedDict
from threading import Lock
from asset_store import ArchivedAsset

LIMIT = 16 * 1024 * 1024
MAX_ITEM = 256 * 1024
_cache = OrderedDict()
_bytes = 0
_lock = Lock()


def small_asset(source):
    """Cache small immutable members in RAM and leave large payloads uncached."""
    global _bytes
    if not isinstance(source, ArchivedAsset) or source.record["size"] > MAX_ITEM:
        return None
    r = source.record
    key = (str(source.archive()), r["member"], r["size"], r["crc"])
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    data = source.read_bytes()
    with _lock:
        if key in _cache:
            return _cache[key]
        while _cache and _bytes + len(data) > LIMIT:
            _, old = _cache.popitem(last=False)
            _bytes -= len(old)
        if len(data) <= LIMIT:
            _cache[key] = data
            _bytes += len(data)
    return data
