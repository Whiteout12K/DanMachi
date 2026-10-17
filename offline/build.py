"""Build the explicitly approved separate ARM64 offline research client."""

# Reading guide: Historical client build tool: apply reviewed service, DEX, native and
# manifest edits to a separate research APK.
# Editing notes: Not a normal launch step. Preserve original APK inputs and regenerate
# only an explicitly intended output.
# Checks: offline/test_bundle_check.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import tempfile
import zipfile
import zlib
from server import ROOT, backend as b

original_service_patch = b.patch_service_dependencies


def offline_service_patch(data):
    """Generate the local service implementation for the separate research build."""
    data = bytearray(original_service_patch(data))
    offset = 936248
    if struct.unpack_from("<HHHHII", data, offset) != (
        15,
        0,
        2,
        2,
        1318704,
        540,
    ) or data[offset + 16 : offset + 20] != bytes.fromhex("60003f1e"):
        raise ValueError("Emulator detector does not match the inspected source build")
    data[offset + 16 : offset + 20] = bytes.fromhex("12000f00")
    # Resume rendering immediately when Android brings the activity back,
    # rather than depending on an emulator window-focus callback arriving.
    resume = 0x1320A4
    expected = bytes.fromhex("6f10b20100006e104b3f00007010563f00000e00")
    if (
        struct.unpack_from("<4H", data, resume) != (1, 1, 1, 0)
        or struct.unpack_from("<I", data, resume + 12)[0] != 10
        or data[resume + 16 : resume + 16 + len(expected)] != expected
    ):
        raise ValueError("Cocos activity resume code does not match source")
    struct.pack_into("<H", data, resume, 2)
    units = (
        0x106F,
        0x01B2,
        0x0001,
        0x1012,
        0x105C,
        0x2D5D,
        0x1070,
        0x3F56,
        0x0001,
        0x000E,
    )
    struct.pack_into("<10H", data, resume + 16, *units)
    # All game downloads use the local bridge. Android's Wi-Fi status must
    # not pause those downloads when the host/guest has no internet.
    for at, registers, inputs, count, prefix in (
        (0xE6E6C, 1, 0, 11, bytes.fromhex("62000925")),
        (0xE6E94, 2, 1, 39, bytes.fromhex("1a000433")),
    ):
        if (
            struct.unpack_from("<HH", data, at) != (registers, inputs)
            or struct.unpack_from("<H", data, at + 6)[0] != 0
            or struct.unpack_from("<I", data, at + 12)[0] != count
            or data[at + 16 : at + 20] != prefix
        ):
            raise ValueError("Local download reachability code does not match source")
        data[at + 16 : at + 16 + count * 2] = bytes.fromhex("12200f00") + bytes(
            (count - 2) * 2
        )
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xFFFFFFFF)
    return bytes(data)


b.patch_service_dependencies = offline_service_patch

original_dex_patch = b.patch_dex


def offline_dex_patch(data):
    """Rewrite reviewed DEX call sites for the local offline service."""
    data = bytearray(original_dex_patch(data))
    # The shipped application calls an unavailable JNI memory callback in
    # its auxiliary process. Keep Android's superclass trimming and skip only
    # that broken call; no game state or asset handling is bypassed.
    trim = 0x4FDDB4
    expected = bytes.fromhex("6f200c01210013000a00340205007010daf901000e00")
    if data[trim + 16 : trim + 16 + len(expected)] != expected:
        raise ValueError("Application trim callback does not match source")
    data[trim + 30 : trim + 36] = bytes(6)
    data[12:32] = hashlib.sha1(data[32:]).digest()
    struct.pack_into("<I", data, 8, zlib.adler32(data[12:]) & 0xFFFFFFFF)
    return bytes(data)


b.patch_dex = offline_dex_patch

original_native_patch = b.patch_native_client


def diagnostic_native_patch(data, abi):
    """Apply the exact diagnostic native changes expected by this build."""
    data = bytearray(original_native_patch(data, abi))
    if abi != "arm64-v8a":
        return bytes(data)
    # Let Android retain a native crash trace instead of the obsolete remote
    # crash uploader swallowing it. This does not suppress game failures.
    if data[0x22A3324:0x22A3328] != bytes.fromhex("ff8303d1"):
        raise ValueError("Crash reporter entry does not match source")
    data[0x22A3324:0x22A3328] = bytes.fromhex("c0035fd6")
    # Redirect the error logger to Android logcat. Preserve all validators;
    # this exposes the first consistency failure instead of hiding C002.
    offset = 0x207D1BC
    expected = bytes.fromhex(
        "ff8302d1f53b00f9f44f08a9fd7b09a9fd43029154d03bd5881640f9f30300aaa8831df8"
    )
    replacement = bytes.fromhex(
        "0800403902040091090840f91f0100724200899ac000805261a300f021e81a91457ab317"
    )
    if data[offset : offset + len(expected)] != expected:
        raise ValueError("Native diagnostic logger does not match the verified build")
    data[offset : offset + len(expected)] = replacement
    for at in (0x22C0C38, 0x22C0D14):
        old = struct.pack("<I", 0x94000000 | (((0x2A2FAB4 - at) >> 2) & 0x3FFFFFF))
        if data[at : at + 4] != old:
            raise ValueError("Missing-file diagnostic call does not match source")
        data[at : at + 4] = struct.pack(
            "<I", 0x94000000 | (((offset - at) >> 2) & 0x3FFFFFF)
        )
    # Log the existing pull-parser error string after its normal copy.
    # Preserve the original error dispatch and validation result.
    at = 0x20BEA2C
    stub = 0x207D1E0
    old = struct.pack("<I", 0x94000000 | (((0x13A1878 - at) >> 2) & 0x3FFFFFF))
    if data[at : at + 4] != old:
        raise ValueError("Pull diagnostic call mismatch")
    code = bytearray(bytes.fromhex("e07bbfa900000094e00340f900000094e07bc1a8c0035fd6"))
    for pos, target in ((4, 0x13A1878), (12, offset)):
        struct.pack_into(
            "<I", code, pos, 0x94000000 | (((target - stub - pos) >> 2) & 0x3FFFFFF)
        )
    data[stub : stub + len(code)] = code
    data[at : at + 4] = struct.pack("<I", 0x94000000 | (((stub - at) >> 2) & 0x3FFFFFF))
    # A failed sprite can otherwise become a later null-pointer crash with
    # no filename. Record its original path while preserving the failure.
    at = 0x2D90008
    stub = 0x207D200
    if data[at : at + 4] != bytes.fromhex("680240f9"):
        raise ValueError("Sprite failure entry does not match source")
    code = bytearray(bytes.fromhex("e07bbfa9e00314aa00000094e07bc1a8680240f900000014"))
    struct.pack_into(
        "<I", code, 8, 0x94000000 | (((offset - stub - 8) >> 2) & 0x3FFFFFF)
    )
    struct.pack_into(
        "<I", code, 20, 0x14000000 | (((at + 4 - stub - 20) >> 2) & 0x3FFFFFF)
    )
    data[stub : stub + len(code)] = code
    data[at : at + 4] = struct.pack("<I", 0x14000000 | (((stub - at) >> 2) & 0x3FFFFFF))
    # The results view assumes the original tutorial awarded Hestia. The local
    # tutorial may award a different unit, so its empty-list portrait fallback
    # must use Bell, who is present in every bootstrapped party.
    fallback = 1011001001
    for at, old, new in (
        (0x1D1FF1C, 0x5289CF29, 0x52800009 | ((fallback & 0xFFFF) << 5)),
        (0x1D1FF24, 0x72A78A49, 0x72A00009 | ((fallback >> 16) << 5)),
    ):
        if struct.unpack_from("<I", data, at)[0] != old:
            raise ValueError("Quest result fallback instruction mismatch")
        struct.pack_into("<I", data, at, new)
    return bytes(data)


b.patch_native_client = diagnostic_native_patch

original_manifest_patch = b.patch_manifest


def debug_manifest(data):
    """Create the separate research manifest rather than editing the original APK."""
    parts = b.xml_chunks(original_manifest_patch(data))
    pool = next(p for k, p in parts if k == 1)
    count, styles, flags, start, style_start = struct.unpack_from("<IIIII", pool, 8)
    offsets = list(struct.unpack_from(f"<{count}I", pool, 28))
    strings = []
    for offset in offsets:
        at = start + offset
        length = struct.unpack_from("<H", pool, at)[0]
        strings.append(pool[at + 2 : at + 2 + length * 2].decode("utf-16le"))
    text = bytearray(pool[start:])
    offsets.append(len(text))
    value = "debuggable"
    text += struct.pack("<H", len(value)) + value.encode("utf-16le") + b"\0\0"
    text += b"\0" * (-len(text) % 4)
    new_start = 28 + len(offsets) * 4
    pool[:] = (
        struct.pack(
            "<HHIIIIII",
            1,
            28,
            new_start + len(text),
            len(offsets),
            0,
            flags,
            new_start,
            0,
        )
        + struct.pack(f"<{len(offsets)}I", *offsets)
        + text
    )
    resource = next(p for k, p in parts if k == 0x180)
    ids = list(struct.unpack_from(f"<{(len(resource)-8)//4}I", resource, 8))
    ids.extend([0] * (count - len(ids)))
    ids.append(0x0101000F)
    resource[:] = struct.pack("<HHI", 0x180, 8, 8 + len(ids) * 4) + struct.pack(
        f"<{len(ids)}I", *ids
    )
    for kind, part in parts:
        if (
            kind != 0x102
            or strings[struct.unpack_from("<I", part, 20)[0]] != "application"
        ):
            continue
        number = struct.unpack_from("<H", part, 28)[0]
        attrs = [bytes(part[36 + i * 20 : 56 + i * 20]) for i in range(number)]
        if any(ids[struct.unpack_from("<I", a, 4)[0]] == 0x0101000F for a in attrs):
            raise ValueError("Existing debug attribute")
        namespace = struct.unpack_from("<I", attrs[0])[0]
        attrs.append(
            struct.pack(
                "<IIIHBBI", namespace, count, 0xFFFFFFFF, 8, 0, 0x12, 0xFFFFFFFF
            )
        )
        attrs.sort(key=lambda a: ids[struct.unpack_from("<I", a, 4)[0]])
        part[:] = part[:36] + b"".join(attrs)
        struct.pack_into("<I", part, 4, len(part))
        struct.pack_into("<H", part, 28, number + 1)
    payload = b"".join(p for k, p in parts)
    return struct.pack("<HHI", 3, 8, len(payload) + 8) + payload


from telemetry_patch import patch_ad_event_queue

b.patch_offline_event_queue = patch_ad_event_queue
from game_shell import game_manifest

b.patch_manifest = lambda data: game_manifest(debug_manifest(data))


def main():
    """Build and record the separate patched output from retained original inputs."""
    source = ROOT / "assets/source/DanMachi-ARM64-EU-15.1.0.xapk"
    if b.sha256(source) != b.ARM64_XAPK_SHA256:
        raise ValueError("Source bundle hash does not match the reviewed build")
    java = Path("/Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home/bin/java")
    keytool = java.parent / "keytool"
    tools = ROOT / "offline/build-tools"
    signing = b.WORK / "signing"
    signing.mkdir(exist_ok=True)
    signing.chmod(0o700)
    key = signing / "local.p12"
    password_file = signing / "password"
    if key.exists() != password_file.exists():
        raise ValueError("Incomplete signing identity")
    if not key.exists():
        password_file.write_text(secrets.token_hex(24))
        password_file.chmod(0o600)
        env = dict(os.environ, DANMEMORE_KEY_PASSWORD=password_file.read_text())
        b.run(
            [
                keytool,
                "-genkeypair",
                "-keystore",
                key,
                "-storetype",
                "PKCS12",
                "-alias",
                "danmemore-local",
                "-storepass:env",
                "DANMEMORE_KEY_PASSWORD",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "3650",
                "-dname",
                "CN=DanMemoRe Local Client",
            ],
            env=env,
        )
        key.chmod(0o600)
    output = ROOT / "offline/apks"
    output.mkdir(exist_ok=True)
    results = []
    with (
        tempfile.TemporaryDirectory(dir=b.WORK) as tmp,
        zipfile.ZipFile(source) as bundle,
    ):
        for name in b.ARM64_APKS:
            extracted = Path(tmp) / name
            extracted.write_bytes(bundle.read(name))
            changes, signer = b.patch_and_sign_apk(
                extracted,
                output / name,
                name == "com.eu.danmemo.apk",
                (
                    tools / "zipalign",
                    tools / "aapt",
                    tools / "lib/apksigner.jar",
                    java,
                    keytool,
                ),
                key,
                password_file.read_text(),
            )
            results.append(
                {
                    "file": name,
                    "sha256": b.sha256(output / name),
                    "signer": signer,
                    "changes": changes,
                }
            )
    if len({x["signer"] for x in results}) != 1:
        raise ValueError("Split signer mismatch")
    (output / "build.json").write_text(
        json.dumps(
            {
                "source_sha256": b.sha256(source),
                "reference": "https://github.com/MadlyMoe/DanMemoRe",
                "package": b.PRIVATE_PACKAGE,
                "apks": results,
                "gameplay_verified": False,
            },
            indent=2,
        )
    )
    print("Built and verified six signed ARM64 APK splits. Gameplay not yet tested.")


if __name__ == "__main__":
    main()
