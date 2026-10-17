"""English display overlays without changing original media or gameplay rules.

Reading guide: display_name() supplies menu labels; master_asset() patches only
selected native display strings; image_asset() builds an English text card only
for image hashes explicitly identified by the offline artwork audit.
Editing notes: preserve original identities, aliases, costs, pools and audio.
Cards are code-generated UI, not recovered official artwork. They live in RAM.
Checks: test_english_presentation.py and the Gacha/event focused suites.
"""

import functools
import json
import re
import struct
import subprocess
import textwrap
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
MASTER_PREFIX = "1/master/divide_enc/"


@functools.lru_cache(maxsize=1)
def text_policy():
    """Load explicit English display changes, never player/account data."""
    return json.loads((ROOT / "english-text.json").read_text())["tables"]


def display_name(table, identity, original, column=2):
    """Keep English originals unless a reviewed label translation exists."""
    return (
        text_policy().get(table, {}).get(str(identity), {}).get(str(column), original)
    )


def patch_text(name, data):
    """Append replacement strings and retarget only their FlatBuffer fields.

    Appending allows longer English translations without moving existing rows.
    Original string storage stays intact; IDs and scalar field offsets do not move.
    """
    import rebuild_master as master
    from build_gacha import value
    from gacha import encode

    result = bytearray(data)
    changes = text_policy().get(name, {})
    for row in master.rows(data):
        translated = changes.get(str(value(data, row, 0)), {})
        for column, text in translated.items():
            if JAPANESE.search(text):
                raise ValueError("English display policy contains Japanese text")
            field = master.fields(data, row)[int(column)]
            if not field:
                raise ValueError("Display field is absent: " + name)
            # String vectors contain the encrypted UTF-8 payload length and bytes.
            encoded = encode(text.encode() + b"\0", master.INNER_KEY)
            result.extend(b"\0" * (-len(result) % 4))
            pointer = len(result)
            result.extend(struct.pack("<I", len(encoded)) + encoded + b"\0")
            struct.pack_into("<I", result, field, pointer - field)
    return bytes(result)


def crypt(data, decrypt=False):
    """Use the retained master encryption envelope with the system OpenSSL."""
    import rebuild_master as master

    args = ["/usr/bin/openssl", "enc"]
    if decrypt:
        args.append("-d")
    args += ["-aes-256-cbc", "-K", master.AES_KEY.hex(), "-iv", master.IV.hex()]
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


@functools.lru_cache(maxsize=8)
def master_asset(name):
    """Compose English labels after the existing availability/validity overlays."""
    from asset_store import MemoryAsset
    import rebuild_master as master

    if name == "lottery":
        from gacha import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "gachaTicket":
        from gacha_ticket_access import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "adventureEpisode":
        from anniversary_events import master_asset as base

        data = zlib.decompress(crypt(base().data, decrypt=True))
    elif name == "shop":
        from anniversary_events import shop_master_asset

        data = zlib.decompress(
            crypt(shop_master_asset(MASTER_PREFIX + name + ".enc").data, decrypt=True)
        )
    else:
        data = master.table(name)
    return MemoryAsset(crypt(zlib.compress(patch_text(name, data))))


@functools.lru_cache(maxsize=1)
def image_policy():
    """Load audited source hashes and English labels; no runtime OCR is required."""
    path = ROOT / "english-images.json"
    return json.loads(path.read_text())["images"] if path.exists() else {}


# A small, self-contained 5x7 alphabet keeps generated UI independent of Pillow,
# installed fonts, graphics tools and extra runtime packages. Values are row bits.
FONT = {
    "A": (14, 17, 17, 31, 17, 17, 17),
    "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31),
    "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15),
    "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (31, 4, 4, 4, 4, 4, 31),
    "J": (7, 2, 2, 2, 18, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17),
    "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17),
    "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13),
    "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30),
    "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 21, 10),
    "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4),
    "Z": (31, 1, 2, 4, 8, 16, 31),
    "0": (14, 17, 19, 21, 25, 17, 14),
    "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (30, 1, 1, 14, 1, 1, 30),
    "4": (2, 6, 10, 18, 31, 2, 2),
    "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14),
    "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 1, 14),
    " ": (0, 0, 0, 0, 0, 0, 0),
    "-": (0, 0, 0, 31, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 6, 6),
    ":": (0, 6, 6, 0, 6, 6, 0),
    "'": (4, 4, 8, 0, 0, 0, 0),
    "/": (1, 2, 2, 4, 8, 8, 16),
    "&": (12, 18, 20, 8, 21, 18, 13),
    "!": (4, 4, 4, 4, 4, 0, 4),
    "?": (14, 17, 1, 2, 4, 0, 4),
    "(": (2, 4, 8, 8, 8, 4, 2),
    ")": (8, 4, 2, 2, 2, 4, 8),
    "+": (0, 4, 4, 31, 4, 4, 0),
    "[": (14, 8, 8, 8, 8, 8, 14),
    "]": (14, 2, 2, 2, 2, 2, 14),
}


def ascii_label(text):
    """Normalize English typography into the small renderer's supported alphabet."""
    import unicodedata

    text = (
        text.replace("★", "-STAR ")
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    )
    return "".join(c if c in FONT else " " for c in text)


@functools.lru_cache(maxsize=128)
def card_bytes(width, height, label, transparent=False):
    """Render a new English UI card at the original image dimensions, in RAM."""
    label = ascii_label(label)
    if not label.strip() or width < 1 or height < 1:
        raise ValueError("English card needs dimensions and a readable label")
    pixels = bytearray(width * height * 4)
    if not transparent:
        for y in range(height):
            shade = int(20 * y / max(1, height - 1))
            row = bytes((15 + shade, 27 + shade, 47 + shade, 255)) * width
            pixels[y * width * 4 : (y + 1) * width * 4] = row
        border = max(1, min(width, height) // 45)
        for y in range(height):
            for x in range(width):
                if min(x, y, width - x - 1, height - y - 1) < border:
                    pos = (y * width + x) * 4
                    pixels[pos : pos + 4] = bytes((212, 181, 101, 255))
    # Find the largest bitmap scale that fits the complete title, including
    # long special-ticket names. Nothing is silently truncated.
    for scale in range(max(1, min(width // 6, height // 9)), 0, -1):
        columns = max(1, (width - 4 * scale) // (6 * scale))
        lines = textwrap.wrap(label, width=columns) or [label]
        if len(lines) * 9 * scale <= max(height - 2 * scale, 7):
            break
    top = max(0, (height - len(lines) * 9 * scale) // 2)
    for index, line in enumerate(lines):
        left = max(0, (width - len(line) * 6 * scale) // 2)
        for col, char in enumerate(line):
            for row, bits in enumerate(FONT.get(char, FONT[" "])):
                for bit in range(5):
                    if bits & (1 << (4 - bit)):
                        for dy in range(scale):
                            y = top + index * 9 * scale + row * scale + dy
                            if y >= height:
                                continue
                            x = left + (col * 6 + bit) * scale
                            count = min(scale, width - x)
                            if count > 0:
                                pos = (y * width + x) * 4
                                pixels[pos : pos + 4 * count] = (
                                    bytes((248, 241, 215, 255)) * count
                                )

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\0" + pixels[y * width * 4 : (y + 1) * width * 4] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


@functools.lru_cache(maxsize=32)
def card_asset(digest):
    """Read a small generated card from the compact UI-only archive."""
    import zipfile
    from asset_store import MemoryAsset
    with zipfile.ZipFile(ROOT / "english-cards.zip") as archive:
        return MemoryAsset(archive.read(digest + ".png"))


def image_asset(record):
    """Serve an English card only for an explicitly audited original image hash."""
    digest = record.get("md5", "")
    if digest not in image_policy():
        return None
    return card_asset(digest)


def apply_catalog(catalogue):
    """Keep native file sizes consistent with the English bytes actually served."""
    for name in text_policy():
        path = MASTER_PREFIX + name + ".enc"
        if path in catalogue:
            catalogue[path] = {
                **catalogue[path],
                "size": master_asset(name).stat().st_size,
            }
    for path, record in list(catalogue.items()):
        replacement = image_asset(record)
        if replacement is not None:
            catalogue[path] = {
                **record,
                "archive_size": record["size"],
                "size": replacement.stat().st_size,
            }
