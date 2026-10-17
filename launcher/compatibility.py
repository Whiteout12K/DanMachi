"""Reapply reviewed game-only patches after native extraction; retain APK inputs."""

# Reading guide: Native patch installer: ensure() accepts only the recorded original or
# patched library hash.
# Editing notes: Patch definitions belong in compatibility-patches.json and their
# generators. Byte lengths and output hashes must agree before a write.
# Checks: tools/maintain.py test native.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ensure():
    """Verify the whole native library and every original byte range before patching."""
    record = json.loads((ROOT / "launcher/compatibility-patches.json").read_text())
    paths = list(
        (ROOT / "DanMachi MF.app/Contents/Client/android/data/app").glob(
            "*/com.eu.danmore-*/lib/arm64/libapp.so"
        )
    )
    if len(paths) != 1:
        raise RuntimeError("Cannot locate the trial game native library.")
    path = paths[0]
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == record["patched_native_sha256"]:
        return
    if digest != record["input_native_sha256"]:
        raise RuntimeError(
            "Native library changed unexpectedly; compatibility patches were not applied."
        )
    result = bytearray(data)
    for change in record["changes"]:
        offset = int(change["offset"], 16)
        before = bytes.fromhex(change["before"])
        after = bytes.fromhex(change["after"])
        if len(before) != len(after) or result[offset : offset + len(before)] != before:
            raise RuntimeError("Compatibility patch does not match this game build.")
        result[offset : offset + len(after)] = after
    if hashlib.sha256(result).hexdigest() != record["patched_native_sha256"]:
        raise RuntimeError("Compatibility output verification failed.")
    path.write_bytes(result)


if __name__ == "__main__":
    ensure()
    print("Game native compatibility patches verified.")
