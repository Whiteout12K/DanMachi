"""One-time lower-quality Vorbis conversion; optional tools are not play dependencies."""

# Reading guide: Optional audio conversion tool: preserve Ogg comments and update
# conversion metadata.
# Editing notes: This changes audio representation and is not required to launch.
# Inspect conversion inputs/outputs before use.
# Checks: offline/test_audio_profile.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import argparse, collections, copy, fcntl, gzip, hashlib, io, json, math, os, struct, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from audio_profile import EXTRA_ID
from deduplicate_assets import compressed_bytes

ROOT = Path(__file__).resolve().parents[1]
CRC_TABLE = []
for number in range(256):
    value = number << 24
    for _ in range(8):
        value = (
            (value << 1) ^ 0x04C11DB7 if value & 0x80000000 else value << 1
        ) & 0xFFFFFFFF
    CRC_TABLE.append(value)


def pages(data):
    """Iterate Ogg pages needed to retain stream metadata."""
    at = 0
    while at < len(data):
        if data[at : at + 4] != b"OggS" or at + 27 > len(data):
            raise ValueError("Invalid Ogg page")
        count = data[at + 26]
        laces = list(data[at + 27 : at + 27 + count])
        end = at + 27 + count + sum(laces)
        if end > len(data):
            raise ValueError("Truncated Ogg page")
        yield bytearray(data[at : at + 27]), laces, data[at + 27 + count : end]
        at = end


def comments(data):
    """Read original Vorbis comment packets before conversion."""
    packet = bytearray()
    for header, laces, body in pages(data):
        at = 0
        for size in laces:
            packet.extend(body[at : at + size])
            at += size
            if size < 255:
                if packet.startswith(b"\x03vorbis"):
                    position = 7
                    length = struct.unpack_from("<I", packet, position)[0]
                    position += 4 + length
                    count = struct.unpack_from("<I", packet, position)[0]
                    position += 4
                    result = []
                    if count > 10000:
                        raise ValueError("Invalid comment count")
                    for _ in range(count):
                        length = struct.unpack_from("<I", packet, position)[0]
                        position += 4
                        result.append(bytes(packet[position : position + length]))
                        position += length
                    return result
                packet.clear()
    raise ValueError("Missing Vorbis comments")


def preserve_comments(data, tags):
    """Carry original comment metadata into the converted Ogg stream."""
    vendor = b"DanMachi compact Vorbis"
    comment = (
        b"\x03vorbis"
        + struct.pack("<I", len(vendor))
        + vendor
        + struct.pack("<I", len(tags))
    )
    for tag in tags:
        comment += struct.pack("<I", len(tag)) + tag
    comment += b"\x01"
    out = bytearray()
    replaced = False
    for header, laces, body in pages(data):
        changed = False
        at = 0
        start = 0
        packet = bytearray()
        for position, size in enumerate(laces):
            packet.extend(body[at : at + size])
            at += size
            if size < 255:
                if packet.startswith(b"\x03vorbis"):
                    new_laces = [255] * (len(comment) // 255) + [len(comment) % 255]
                    laces = laces[:start] + new_laces + laces[position + 1 :]
                    body = body[: at - len(packet)] + comment + body[at:]
                    replaced = True
                    changed = True
                    break
                packet.clear()
                start = position + 1
        if len(laces) > 255:
            raise ValueError("Metadata exceeds page capacity")
        if changed:
            header[26] = len(laces)
            header[22:26] = b"\0" * 4
            page = header + bytes(laces) + body
            crc = 0
            for byte in page:
                crc = ((crc << 8) ^ CRC_TABLE[(crc >> 24) ^ byte]) & 0xFFFFFFFF
            struct.pack_into("<I", page, 22, crc)
            out.extend(page)
        else:
            out.extend(header + bytes(laces) + body)
    if not replaced:
        raise ValueError("Cannot preserve Ogg metadata")
    return bytes(out)


def convert(name, data):
    """Run the optional audio conversion for a selected input/output pair."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if not len(samples):
        return None
    if not np.isfinite(samples).all():
        raise ValueError("Invalid audio samples")
    tags = comments(data)
    target_rate = rate
    # Keep loop/cue sample coordinates intact. Voice clips normally have none.
    loops = any(
        b"LOOP" in tag.upper().split(b"=", 1)[0]
        or b"CUE" in tag.upper().split(b"=", 1)[0]
        for tag in tags
    )
    if "/voice" in name and rate > 22050 and not loops:
        target_rate = 22050
    frames = len(samples)
    channels = samples.shape[1]
    original_rms = float(np.sqrt(np.mean(samples * samples, dtype=np.float64)))
    if target_rate != rate:
        divisor = math.gcd(rate, target_rate)
        samples = resample_poly(
            samples, target_rate // divisor, rate // divisor, axis=0
        )
    output = io.BytesIO()
    # libVorbis uses stack buffers during initial extrapolation. Bound each
    # write rather than passing an entire long music track to the encoder.
    with sf.SoundFile(
        output,
        "w",
        samplerate=target_rate,
        channels=channels,
        format="OGG",
        subtype="VORBIS",
        compression_level=1.0,
    ) as writer:
        for start in range(0, len(samples), 8192):
            writer.write(samples[start : start + 8192])
    # Studio metadata and any game loop/cue tags survive conversion.
    tags = [tag for tag in tags if not tag.upper().startswith(b"ENCODER=")] + [
        b"ENCODER=libsndfile compact Vorbis"
    ]
    encoded = preserve_comments(output.getvalue(), tags)
    decoded, new_rate = sf.read(io.BytesIO(encoded), dtype="float32", always_2d=True)
    if new_rate != target_rate or decoded.shape[1] != channels:
        raise ValueError("Audio format changed unexpectedly")
    if abs(len(decoded) / new_rate - frames / rate) > 1 / new_rate + 1 / rate:
        raise ValueError("Audio duration changed")
    if not np.isfinite(decoded).all():
        raise ValueError("Invalid encoded audio")
    if (
        original_rms > 0.00001
        and float(np.sqrt(np.mean(decoded * decoded, dtype=np.float64)))
        < original_rms * 0.5
    ):
        return None
    if len(encoded) >= len(data):
        return None
    return encoded, {
        "md5": hashlib.md5(encoded).hexdigest(),
        "originalMd5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "rate": new_rate,
        "channels": channels,
        "frames": len(decoded),
        "originalSize": len(data),
        "originalRate": rate,
    }


def rewrite(path, executor, changes, stats):
    """Rewrite selected archive audio and its matching metadata."""
    temporary = path.with_suffix(".audio-converting")
    pending = collections.deque()
    expected = {}
    start = time.monotonic()
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(temporary, "w", allowZip64=True) as target,
    ):
        target.comment = source.comment

        def finish():
            info, future = pending.popleft()
            converted = None
            if future is not None:
                try:
                    converted = future.result()
                except Exception as error:
                    # An unusual or damaged source is retained byte-for-byte;
                    # a size reduction must never discard a playable original.
                    stats["conversionExceptions"] += 1
                    if len(stats["retainedExceptionSamples"]) < 50:
                        stats["retainedExceptionSamples"].append(
                            {"file": info.filename, "reason": str(error)}
                        )
                stats["audioFilesChecked"] += 1
            if converted:
                data, record = converted
                updated = copy.copy(info)
                updated.extra += struct.pack("<HH", EXTRA_ID, 16) + bytes.fromhex(
                    record["originalMd5"]
                )
                target.writestr(
                    updated, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6
                )
                actual = target.getinfo(info.filename)
                record["crc"] = actual.CRC
                changes[(path.name, info.filename)] = record
                stats["audioFilesReduced"] += 1
                stats["audioBytesBefore"] += record["originalSize"]
                stats["audioBytesAfter"] += record["size"]
                expected[info.filename] = ("audio", record["sha256"])
            else:
                if info.flag_bits & 9 or info.file_size >= zipfile.ZIP64_LIMIT:
                    raise ValueError("Unsupported ZIP member")
                updated = copy.copy(info)
                updated.header_offset = target.start_dir
                target._writecheck(updated)
                target._didModify = True
                target.fp.seek(target.start_dir)
                target.fp.write(updated.FileHeader(False))
                digest = hashlib.sha256()
                for block in compressed_bytes(source, info):
                    digest.update(block)
                    target.fp.write(block)
                target.start_dir = target.fp.tell()
                target.filelist.append(updated)
                target.NameToInfo[updated.filename] = updated
                expected[info.filename] = ("unchanged", digest.hexdigest())
            if future is not None and stats["audioFilesChecked"] % 1000 == 0:
                print(
                    json.dumps(
                        {
                            "archive": path.name,
                            "checked": stats["audioFilesChecked"],
                            "reduced": stats["audioFilesReduced"],
                            "audioBytesSaved": stats["audioBytesBefore"]
                            - stats["audioBytesAfter"],
                        }
                    ),
                    flush=True,
                )

        for info in source.infolist():
            future = (
                executor.submit(convert, info.filename, source.read(info))
                if info.filename.endswith(".ogg") and not info.is_dir()
                else None
            )
            pending.append((info, future))
            if len(pending) >= 16:
                finish()
        while pending:
            finish()
    with zipfile.ZipFile(temporary) as check:
        if len(check.infolist()) != len(expected):
            raise ValueError("ZIP member count changed")
        for info in check.infolist():
            mode, digest = expected[info.filename]
            if mode == "audio":
                actual = hashlib.sha256(check.read(info)).hexdigest()
            else:
                verified = hashlib.sha256()
                for block in compressed_bytes(check, info):
                    verified.update(block)
                actual = verified.hexdigest()
            if actual != digest:
                raise ValueError("Repacked asset changed: " + info.filename)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.chmod(path.stat().st_mode & 0o777)
    print(
        "Verified "
        + path.name
        + " in "
        + str(round(time.monotonic() - start))
        + " seconds.",
        flush=True,
    )
    return temporary


def main():
    """Run the explicit audio conversion maintenance command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-dir", type=Path, required=True)
    args = parser.parse_args()
    import sys

    sys.path.insert(0, str(args.tool_dir.resolve()))
    sys.path.insert(0, str(ROOT / "launcher"))
    import game

    if game.connected():
        raise RuntimeError("Close the game before changing audio.")
    if (ROOT / "assets/audio-quality.json").exists():
        raise RuntimeError(
            "Audio has already been converted; do not repeatedly degrade it."
        )
    folder = ROOT / "assets/archives"
    before = sum(p.stat().st_size for p in folder.glob("*.zip"))
    changes = {}
    prepared = {}
    backups = {}
    old_metadata = {}
    stats = {
        "audioFilesChecked": 0,
        "audioFilesReduced": 0,
        "audioBytesBefore": 0,
        "audioBytesAfter": 0,
        "conversionExceptions": 0,
        "retainedExceptionSamples": [],
    }
    with (ROOT / "state/launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                for path in sorted(folder.glob("*.zip")):
                    prepared[path] = rewrite(path, executor, changes, stats)
            metadata = {}
            index_path = ROOT / "state/offline/asset-sources.json.gz"
            old_metadata[index_path] = index_path.read_bytes()
            records = json.loads(gzip.decompress(old_metadata[index_path]))
            for phase in "12345678":
                path = ROOT / "contents" / phase / "project.manifest"
                old_metadata[path] = path.read_bytes()
                manifest = json.loads(old_metadata[path])
                for name, item in manifest["assets"].items():
                    record = records.get(phase + "/" + name)
                    changed = (
                        changes.get((Path(record["archive"]).name, record["member"]))
                        if record
                        else None
                    )
                    if changed:
                        if item["md5"] != changed["originalMd5"]:
                            raise ValueError(
                                "Original phase checksum does not match audio"
                            )
                        item["md5"] = changed["md5"]
                        item["size"] = changed["size"]
                metadata[path] = json.dumps(manifest, separators=(",", ":")).encode()
            for record in records.values():
                changed = changes.get((Path(record["archive"]).name, record["member"]))
                if changed:
                    for key in ("md5", "size", "crc"):
                        record[key] = changed[key]
            metadata[index_path] = gzip.compress(
                json.dumps(records, separators=(",", ":")).encode()
            )
            catalog_path = folder / "aliases.json.gz"
            old_metadata[catalog_path] = catalog_path.read_bytes()
            catalog = json.loads(gzip.decompress(old_metadata[catalog_path]))
            for description in catalog["sources"].values():
                for alias in description["aliases"].values():
                    changed = changes.get((alias["archive"], alias["member"]))
                    if changed:
                        for key in ("size", "crc", "sha256"):
                            alias[key] = changed[key]
            metadata[catalog_path] = gzip.compress(
                json.dumps(catalog, separators=(",", ":")).encode()
            )
            version = hashlib.sha256(
                json.dumps(
                    sorted((a, m, c["md5"]) for (a, m), c in changes.items())
                ).encode()
            ).hexdigest()
            after = sum(path.stat().st_size for path in prepared.values())
            if after >= before:
                raise ValueError("Conversion did not reduce storage")
            profile = {
                "format": 1,
                "version": version,
                "voiceSampleRateLimit": 22050,
                "codec": "Ogg Vorbis",
                "quality": "libsndfile maximum compression (Vorbis quality 0)",
                "musicEffectsSampleRatesPreserved": True,
                "channelCountsAndDurationsVerified": True,
                **stats,
                "archiveBytesBefore": before,
                "archiveBytesAfter": after,
                "archiveBytesSaved": before - after,
            }
            profile_path = ROOT / "assets/audio-quality.json"
            old_metadata[profile_path] = None
            metadata[profile_path] = json.dumps(profile, indent=2).encode() + b"\n"
            rollback = ROOT / "state/temp/audio-rollback"
            (rollback / "archives").mkdir(parents=True, exist_ok=True)
            for path, data in old_metadata.items():
                if data is not None:
                    backup = rollback / "metadata" / path.relative_to(ROOT)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(data)
            for path, temporary in prepared.items():
                backup = rollback / "archives" / path.name
                path.replace(backup)
                backups[path] = backup
                temporary.replace(path)
            for path, data in metadata.items():
                temporary = path.with_name(path.name + ".audio-updating")
                temporary.write_bytes(data)
                temporary.replace(path)
            # Keep the originals only until live game/audio validation succeeds.
            (ROOT / "state/logs/audio-conversion-pending.json").write_text(
                json.dumps(
                    {
                        "backups": {
                            str(p.relative_to(ROOT)): str(b.relative_to(ROOT))
                            for p, b in backups.items()
                        },
                        "profile": profile,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(json.dumps(profile), flush=True)
        except BaseException:
            for path, backup in backups.items():
                path.unlink(missing_ok=True)
                backup.replace(path)
            for path, data in old_metadata.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            raise
        finally:
            for temporary in prepared.values():
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
