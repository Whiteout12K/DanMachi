"""Losslessly repack retained ZIP assets; verify every file before replacement."""

# Reading guide: Optional ZIP repacker: retain every member payload while changing
# compression.
# Editing notes: This rewrites archives after verification. Do not run it as a routine
# readability or gameplay repair.
# Checks: offline/test_storage_maintenance.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy, hashlib, json, os, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repack(path):
    """Recompress a ZIP and verify original member bytes before replacing its output."""
    temporary = path.with_suffix(".repacking")
    before = path.stat().st_size
    expected = []
    try:
        with (
            zipfile.ZipFile(path) as source,
            zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
                allowZip64=True,
            ) as target,
        ):
            target.comment = source.comment
            for old in source.infolist():
                info = copy.copy(old)
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = 9
                digest = hashlib.sha256()
                with source.open(old) as incoming, target.open(info, "w") as outgoing:
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        digest.update(block)
                        outgoing.write(block)
                expected.append((old.filename, old.file_size, old.CRC, digest.digest()))
        with zipfile.ZipFile(temporary) as check:
            actual = check.infolist()
            if len(actual) != len(expected):
                raise ValueError("Asset count changed")
            for info, (name, size, crc, digest) in zip(actual, expected):
                if (info.filename, info.file_size, info.CRC) != (name, size, crc):
                    raise ValueError("Asset metadata changed: " + name)
                verified = hashlib.sha256()
                with check.open(info) as incoming:
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        verified.update(block)
                if verified.digest() != digest:
                    raise ValueError("Asset bytes changed: " + name)
        after = temporary.stat().st_size
        if after < before:
            with temporary.open("rb") as file:
                os.fsync(file.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        else:
            temporary.unlink()
            after = before
        return {
            "archive": path.name,
            "filesVerified": len(expected),
            "beforeBytes": before,
            "afterBytes": after,
            "savedBytes": before - after,
            "sha256VerifiedEveryMember": True,
        }
    finally:
        temporary.unlink(missing_ok=True)


def main():
    """Run the explicit lossless archive-repack maintenance action."""
    import fcntl

    report = []
    with (ROOT / "state/launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in sorted((ROOT / "assets/archives").glob("*.zip")):
            print("Compressing and verifying " + path.name, flush=True)
            report.append(repack(path))
            (ROOT / "state/logs/lossless-asset-recompression.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
            print(json.dumps(report[-1]), flush=True)


if __name__ == "__main__":
    main()
