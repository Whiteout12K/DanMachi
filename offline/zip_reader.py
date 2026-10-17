"""Read-only virtual Android assets backed by existing host archives."""

# Reading guide: Virtual filesystem: catalog() assembles logical paths, index_bytes()
# serializes them, asset() serves the correct overlay or ZIP member.
# Editing notes: Overlay sizes must match served bytes. Phase aliases must preserve
# explicitly retained files; never turn missing unknown IDs into broad catch-all assets.
# Checks: offline/test_zip_reader.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools, struct, plistlib, re
from collections import deque
from threading import Lock

_stats_lock = Lock()
_stats = {
    "files": 0,
    "bytes": 0,
    "recent": deque(maxlen=8),
    "anniversaryReads": {},
    "recentVoices": deque(maxlen=8),
}


def record_read(path, size):
    """Update bounded diagnostic counters after serving a virtual asset."""
    with _stats_lock:
        _stats["files"] += 1
        _stats["bytes"] += size
        _stats["recent"].append(path)
        if "/sound/voice_episode/" in path:
            _stats["recentVoices"].append(path)
        if path in (
            "1/master/divide_enc/adventure.enc",
            "1/master/divide_enc/adventureEpisode.enc",
            "1/master/divide_enc/adventureMapInfo.enc",
        ):
            _stats["anniversaryReads"][path] = (
                _stats["anniversaryReads"].get(path, 0) + 1
            )


def statistics():
    """
    Return a snapshot of virtual asset diagnostics without exposing mutable queues.
    """
    with _stats_lock:
        return {
            **_stats,
            "recent": list(_stats["recent"]),
            "recentVoices": list(_stats["recentVoices"]),
        }


from pathlib import PurePosixPath
from asset_store import ROOT
from archive_catalog import entries
from asset_store import records, ArchivedAsset


# Logical path and portrait metadata validation
def valid(path):
    """Accept only normalized relative paths under supported virtual asset roots."""
    p = PurePosixPath(path)
    return (
        not p.is_absolute()
        and ".." not in p.parts
        and str(p) == path
        and p.parts
        and p.parts[0]
        in (
            *map(str, range(1, 9)),
            "voice_root",
            "area_atlas_root",
            "single_image_root",
        )
    )


def valid_dialogue_cutout(path, record, sources):
    """Check retained portrait crop metadata against the matching PNG bounds."""
    name = PurePosixPath(path).parent.name
    if PurePosixPath(path).name != name + ".cutout.plist":
        return False
    body = sources.get(str(PurePosixPath(path).with_name(name + ".body.png")))
    if not body:
        return False
    try:
        data = plistlib.loads(ArchivedAsset(record).read_bytes())
        face = data["argo_character_face_cutout_info"][name]
        point = re.fullmatch(r"\{(\d+),(\d+)\}", face["cutout_coordinate"])
        width = re.fullmatch(r"\{(\d+)\}", face["cutout_width"])
        height = re.fullmatch(r"\{(\d+)\}", face["cutout_height"])
        if not all((point, width, height)):
            return False
        x, y = map(int, point.groups())
        w = int(width[1])
        h = int(height[1])
        with ArchivedAsset(body).open() as stream:
            header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        bw, bh = struct.unpack(">II", header[16:24])
        return w > 0 and h > 0 and x + w <= bw and y + h <= bh
    except (
        KeyError,
        TypeError,
        ValueError,
        plistlib.InvalidFileException,
        struct.error,
    ):
        return False


# Original entries, explicit aliases and in-memory overlay sizes
@functools.lru_cache(maxsize=1)
def catalog():
    """Assemble original ZIP entries and explicit overlays without extracting media."""
    original = {
        p: r for p, r in records().items() if valid(p) and ArchivedAsset(r).is_file()
    }
    for entry, archive, member in entries(ROOT / "assets/archives"):
        if entry.is_dir() or not entry.filename.startswith("contents/"):
            continue
        logical = entry.filename.removeprefix("contents/")
        if valid(logical) and logical.split("/", 1)[0] in (
            "voice_root",
            "area_atlas_root",
            "single_image_root",
        ):
            original.setdefault(
                logical,
                {
                    "archive": str(archive.relative_to(ROOT)),
                    "member": member,
                    "size": entry.file_size,
                    "crc": entry.CRC,
                },
            )
        elif re.fullmatch(
            r"1/master/divide_novel_command_enc/novelCommand[0-9]+\.enc", logical
        ):
            original.setdefault(
                logical,
                {
                    "archive": str(archive.relative_to(ROOT)),
                    "member": member,
                    "size": entry.file_size,
                    "crc": entry.CRC,
                },
            )
        elif valid(logical) and logical.startswith("1/manifests/"):
            original.setdefault(
                logical,
                {
                    "archive": str(archive.relative_to(ROOT)),
                    "member": member,
                    "size": entry.file_size,
                    "crc": entry.CRC,
                },
            )
        elif (
            valid(logical)
            and "/files/character/novel_portrait/" in logical
            and logical.endswith(".cutout.plist")
            and logical not in original
        ):
            # Some original face-placement files have a different manifest MD5,
            # although the retained ZIP contains the matching portrait layout.
            # Expose these validated metadata files without extracting media.
            record = {
                "archive": str(archive.relative_to(ROOT)),
                "member": member,
                "size": entry.file_size,
                "crc": entry.CRC,
            }
            if valid_dialogue_cutout(logical, record, original):
                original[logical] = record

    # Missing historic event images use exact-name rerun art or distinct
    # retained substitutes, through explicit master-backed ZIP aliases.
    from event_item_icons import aliases as event_icon_aliases

    if "1/master/divide_enc/eventItem.enc" in original:
        original.update(event_icon_aliases(original))

    from local_downloads import voice_markers

    markers = voice_markers(original)
    result = dict(original)
    result.update(
        {
            path: {"size": len(data), "local_completion": data}
            for path, data in markers.items()
        }
    )
    # The native client searches phase 1 for media shared by later phases.
    # Explicit phase-1 files always win; otherwise the earliest phase wins.
    for p in sorted(original, key=lambda p: (not p[0].isdigit(), p)):
        if "/files/" in p:
            result.setdefault("1/" + p.split("/", 1)[1], original[p])
    from gacha_ticket_access import art_aliases as ticket_art_aliases

    if "1/master/divide_enc/lottery.enc" in result:
        result.update(ticket_art_aliases(result))
    for path, record in list(result.items()):
        if "/files/lwf/uiLwf/" in path:
            result[path.replace("/uiLwf/", "/uiLwf//")] = record
        if "/files/icon/lottery_scratch/" in path:
            result[path.replace("/lottery_scratch/", "/lottery_scratch//")] = record
    from gacha_ticket_access import PATH as ticket_path, master_asset as ticket_asset

    if ticket_path in result:
        result[ticket_path] = {
            **result[ticket_path],
            "size": ticket_asset().stat().st_size,
        }
    from anniversary_events import (
        MASTER,
        STAGE_MASTER,
        master_asset as anniversary_asset,
        stage_master_asset,
        SHOP_MASTERS,
        shop_master_asset,
    )

    if MASTER in result:
        result[MASTER] = {**result[MASTER], "size": anniversary_asset().stat().st_size}
    if STAGE_MASTER in result:
        result[STAGE_MASTER] = {
            **result[STAGE_MASTER],
            "size": stage_master_asset().stat().st_size,
        }
    for path in SHOP_MASTERS:
        if path in result:
            result[path] = {
                **result[path],
                "size": shop_master_asset(path).stat().st_size,
            }
    from gacha import master_asset, missing_text_layout, scratch_asset

    if "1/master/divide_enc/lottery.enc" in result:
        for phase in ("1", "3"):
            result[
                phase + "/files/ui_atlas/home_gacha/gacha_top_move_parts_text.json"
            ] = {"size": missing_text_layout().stat().st_size}
    if "1/master/divide_enc/lottery.enc" in result:
        result["1/master/divide_enc/lottery.enc"] = {
            **result["1/master/divide_enc/lottery.enc"],
            "size": master_asset().stat().st_size,
        }
    path = "1/master/divide_enc/lotteryScratch.enc"
    if path in result:
        result[path] = {**result[path], "size": scratch_asset().stat().st_size}
    from guild_quests import PATHS as guild_paths, asset as guild_asset

    for guild_path in guild_paths:
        result[guild_path] = {
            **result[guild_path],
            "size": guild_asset(guild_path).stat().st_size,
        }
    from guild_events import PATHS as event_paths, asset as event_asset

    for event_path in event_paths:
        result[event_path] = {
            **result[event_path],
            "size": event_asset(event_path).stat().st_size,
        }
    from tutorial_weights import PATH as weight_path, asset as weight_asset

    result[weight_path] = {"size": weight_asset().stat().st_size}
    from menu_pages import protected_support_layout

    for path, record in list(result.items()):
        protected = protected_support_layout(path, record)
        if protected is not None:
            result[path] = {
                **record,
                "archive_size": record["size"],
                "size": protected.stat().st_size,
            }
    from english_presentation import apply_catalog

    apply_catalog(result)
    return result


# Native index protocol and asset byte serving
@functools.lru_cache(maxsize=1)
def index_bytes():
    """Serialize logical paths and sizes for the native ZIP filesystem bridge."""
    result = bytearray(struct.pack("<I", len(catalog())))
    for path, record in sorted(catalog().items()):
        encoded = path.encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("Asset path too long")
        result.extend(struct.pack("<HQ", len(encoded), record["size"]))
        result.extend(encoded)
    return bytes(result)


def asset(path):
    """Serve generated bytes for overlays, otherwise the indexed original ZIP member."""
    path = str(PurePosixPath(path))
    if not valid(path):
        return None
    # English labels compose after the existing gameplay/date overlays.
    from english_presentation import (
        MASTER_PREFIX,
        text_policy,
        master_asset as english_master,
        image_asset,
    )

    if path.startswith(MASTER_PREFIX) and path.endswith(".enc"):
        name = path[len(MASTER_PREFIX) : -4]
        if name in text_policy():
            return english_master(name)
    record = catalog().get(path)
    if record:
        english_image = image_asset(record)
        if english_image is not None:
            return english_image
    from anniversary_events import (
        MASTER,
        STAGE_MASTER,
        master_asset as anniversary_asset,
        stage_master_asset,
        SHOP_MASTERS,
        shop_master_asset,
    )
    from guild_quests import PATHS as guild_paths, asset as guild_asset

    if path in guild_paths:
        return guild_asset(path)
    from tutorial_weights import PATH as weight_path, asset as weight_asset

    if path == weight_path:
        return weight_asset()
    from guild_events import PATHS as event_paths, asset as event_asset

    if path in event_paths:
        return event_asset(path)
    from gacha_ticket_access import PATH as ticket_path, master_asset as ticket_asset

    if path == ticket_path:
        return ticket_asset()
    if path == MASTER:
        return anniversary_asset()
    if path == STAGE_MASTER:
        return stage_master_asset()
    if path in SHOP_MASTERS:
        return shop_master_asset(path)
    if path == "1/master/divide_enc/lotteryScratch.enc":
        from gacha import scratch_asset

        return scratch_asset()
    if path == "1/master/divide_enc/lottery.enc":
        from gacha import master_asset

        return master_asset()
    if path in (
        "1/files/ui_atlas/home_gacha/gacha_top_move_parts_text.json",
        "3/files/ui_atlas/home_gacha/gacha_top_move_parts_text.json",
    ):
        from gacha import missing_text_layout

        return missing_text_layout()
    record = catalog().get(path)
    if record and "local_completion" in record:
        from asset_store import MemoryAsset

        return MemoryAsset(record["local_completion"])
    from menu_pages import protected_support_layout

    protected = protected_support_layout(path, record)
    if protected is not None:
        return protected
    return ArchivedAsset(record) if record else None
