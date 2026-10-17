"""Permanent offline ticket validity and retained banner-art fallbacks."""

# Reading guide: Ticket compatibility: master_asset() changes native validity;
# art_aliases() supplies explicit missing banner images.
# Editing notes: Keep original ticket identities and pools. Zero native validity means
# expired; the server separately treats owned tickets as non-expiring.
# Checks: tools/maintain.py test gacha.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import functools
import subprocess
import zlib

PATH = "1/master/divide_enc/gachaTicket.enc"
# The native client treats zero as immediately expired, not unlimited.
# Keep the backend non-expiring; expose its longest signed duration to native UI.
NATIVE_VALIDITY_SECONDS = 2147483647


@functools.lru_cache(maxsize=1)
def master_asset():
    """
    Patch only the native ticket validity field and return encrypted in-memory
    bytes.
    """
    import rebuild_master as m
    from gacha import encode
    from asset_store import MemoryAsset

    data = bytearray(m.table("gachaTicket"))
    for row in m.rows(data):
        field = m.fields(data, row)[4]
        if field:
            data[field : field + 8] = encode(
                NATIVE_VALIDITY_SECONDS.to_bytes(4, "little"), m.INNER_KEY
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
        input=zlib.compress(data),
        capture_output=True,
        check=True,
    ).stdout
    return MemoryAsset(encrypted)


def art_aliases(sources):
    """Supply named missing ticket backgrounds while preserving every existing image."""
    import gacha

    aliases = {}
    for identity, donor in gacha.definitions().get("ticketArtFallbacks", {}).items():
        path = f"1/files/lottery/background/{identity}.png"
        source = f"1/files/lottery/background/{donor}.png"
        if path not in sources:
            if source not in sources:
                raise ValueError("Missing ticket-banner fallback artwork: " + source)
            aliases[path] = sources[source]
    return aliases
