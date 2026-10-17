"""Retained Guild monthly/limited availability, without inventing completion."""

# Reading guide: Guild availability: derive month windows and rewrite retained
# limited/monthly date fields.
# Editing notes: These overlays expose goals; they must not fabricate completion or
# claim rewards.
# Checks: offline/test_guild_quests.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import datetime
import functools
import struct
import subprocess
import zlib
from asset_store import MemoryAsset

ACHIEVEMENT = "1/master/divide_enc/achievement.enc"
MONTHLY = "1/master/divide_enc/monthlyAchievement.enc"
PATHS = (ACHIEVEMENT, MONTHLY)

LIMITED_BATCH_SIZE = 80


def month_window(number):
    """Return inclusive UTC start/end timestamps for a continuous month index."""
    year, zero_month = divmod(number, 12)
    next_year, next_zero = divmod(number + 1, 12)
    start = int(
        datetime.datetime(
            year, zero_month + 1, 1, tzinfo=datetime.timezone.utc
        ).timestamp()
    )
    end = (
        int(
            datetime.datetime(
                next_year, next_zero + 1, 1, tzinfo=datetime.timezone.utc
            ).timestamp()
        )
        - 1
    )
    return start, end


def limited_windows(data, current_month):
    """Map retained limited achievements to their scheduled availability windows."""
    import rebuild_master as m
    from build_gacha import value
    from guild_events import quest_episode

    limited = [
        t
        for t in m.rows(data)
        if value(data, t, 2) == 3
        and m.text(data, t, 7).strip()
        and quest_episode(data, t) is not None
    ]
    limited.sort(
        key=lambda t: (value(data, t, 13), value(data, t, 14), value(data, t, 0))
    )
    if not limited:
        raise ValueError("No retained event quests matched")
    batches = (len(limited) + LIMITED_BATCH_SIZE - 1) // LIMITED_BATCH_SIZE
    current_batch = current_month % batches
    return {
        t: month_window(
            current_month + (i // LIMITED_BATCH_SIZE - current_batch) % batches
        )
        for i, t in enumerate(limited)
    }


def patch_achievements(data, current_month=None):
    """Change availability fields without marking achievements complete."""
    import rebuild_master as m
    from build_gacha import value
    from gacha import encode

    current_month = month_number() if current_month is None else current_month
    rows = m.rows(data)
    windows = limited_windows(data, current_month)
    result = bytearray(data)
    for row in rows:
        kind = value(data, row, 2)
        if kind not in (3, 8):
            continue
        fields = m.fields(data, row)
        # Type 3 uses real positive dates. The native time-limited list hides
        # unrestricted zero dates; monthly retains its confirmed zero sentinel.
        dates = windows.get(row, (1, 1)) if kind == 3 else (0, 0)
        for col, date in zip((13, 14), dates):
            if fields[col]:
                old = m.decode(data[fields[col] : fields[col] + 12])
                if len(old) != 8:
                    raise ValueError("Guild availability scalar changed")
                result[fields[col] : fields[col] + 12] = encode(
                    struct.pack("<q", date), m.INNER_KEY
                )
            elif date != 0:
                raise ValueError("Limited quest date field missing")
    return bytes(result)


def month_number(date=None):
    """Convert a calendar year/month into the scheduler month index."""
    date = date or datetime.datetime.now(datetime.timezone.utc).date()
    return date.year * 12 + date.month - 1


def patch_months(data, current_month=None):
    """Apply the current monthly availability fields to retained records."""
    import rebuild_master as m
    from build_gacha import value
    from gacha import encode

    # Retain all three native categories for each schedule slot. A rolling
    # 53-month window also covers long sessions/year rollover without reload.
    current_month = month_number() if current_month is None else current_month
    rows = m.rows(data)
    original_months = sorted({value(data, t, 3) for t in rows})
    mapping = {old: current_month - 1 + i for i, old in enumerate(original_months)}
    result = bytearray(data)
    for row in rows:
        slot = mapping[value(data, row, 3)]
        year, zero_month = divmod(slot, 12)
        field = m.fields(data, row)[3]
        if not field:
            raise ValueError("Monthly calendar field missing")
        result[field : field + 8] = encode(
            struct.pack("<i", year * 100 + zero_month + 1), m.INNER_KEY
        )
    return bytes(result)


@functools.lru_cache(maxsize=2)
def _asset(path, month):
    """Encrypt patched master bytes using the original native format."""
    import rebuild_master as m

    name = "achievement" if path == ACHIEVEMENT else "monthlyAchievement"
    data = m.table(name)
    patched = (
        patch_achievements(data, month)
        if path == ACHIEVEMENT
        else patch_months(data, month)
    )
    encrypted = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-aes-256-cbc",
            "-K",
            m.AES_KEY.hex(),
            "-iv",
            m.IV.hex(),
        ],
        input=zlib.compress(patched),
        capture_output=True,
        check=True,
    ).stdout
    m.decode.cache_clear()
    return MemoryAsset(encrypted)


def asset(path):
    """Select and serve the requested Guild availability overlay."""
    if path not in PATHS:
        raise ValueError("Unsupported Guild table")
    return _asset(path, SESSION_MONTH)


# Keep asset bytes/index lengths stable throughout a running native session.
SESSION_MONTH = month_number()
