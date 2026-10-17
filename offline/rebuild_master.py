"""Rebuild server tables from verified original APK and archived game data.

Uses only the bundled Python and macOS OpenSSL; never edits the player save.
The decoder offsets are tied to the verified retained ARM64 APK build.
"""

# Reading guide: Binary master reader/builder: decrypt original tables, locate
# rows/fields, then build compact server definitions.
# Editing notes: Offsets and encryption keys are tied to the retained APK. Regeneration
# writes definitions, not the real player save.
# Checks: tools/maintain.py check and the affected feature suite.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import sys, zlib, struct, zipfile, subprocess, functools, json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "offline"))
from asset_store import records, ArchivedAsset

apk = ROOT / "offline/apks/config.arm64_v8a.apk"
expected = next(
    a["sha256"]
    for a in json.loads((ROOT / "offline/apks/build.json").read_text())["apks"]
    if a["file"] == apk.name
)
if hashlib.sha256(apk.read_bytes()).hexdigest() != expected:
    raise ValueError("Unexpected decoder APK")
with zipfile.ZipFile(apk) as archive:
    lib = archive.read("lib/arm64-v8a/libapp.so")
AES_KEY = bytes(
    lib[0x34EBDFB + (x ^ 0x42)] ^ 0x6E for x in lib[0x34991E3 : 0x34991E3 + 32]
)
IV = bytes(lib[0x34EBE7B + (x ^ 0xA8)] ^ 0xDB for x in lib[0x3498030 : 0x3498030 + 16])
INNER_KEY = struct.unpack(
    "<4I",
    bytes(lib[0x34A39AC + (x ^ 0x1F)] ^ 0x9A for x in lib[0x34A2C90 : 0x34A2C90 + 16]),
)
del lib


@functools.lru_cache(maxsize=100000)
def decode(data):
    """Decrypt an original inner-field payload with the retained word-based cipher."""
    v = list(struct.unpack("<" + "I" * (len(data) // 4), data))
    n = len(v)
    s = ((6 + 52 // n) * 0x9E3779B9) & 0xFFFFFFFF
    y = v[0]
    while s:
        e = (s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ (
                (s ^ y) + (INNER_KEY[(p & 3) ^ e] ^ z)
            )
            v[p] = (v[p] - mx) & 0xFFFFFFFF
            y = v[p]
        z = v[-1]
        mx = (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ (
            (s ^ y) + (INNER_KEY[e] ^ z)
        )
        v[0] = (v[0] - mx) & 0xFFFFFFFF
        y = v[0]
        s = (s - 0x9E3779B9) & 0xFFFFFFFF
    b = struct.pack("<" + "I" * n, *v)
    ln = v[-1]
    if not len(b) - 7 <= ln <= len(b) - 4:
        raise ValueError("Invalid inner table length")
    return b[:ln]


def fields(b, t):
    """Locate a row field vector using the original table offsets."""
    v = t - struct.unpack_from("<i", b, t)[0]
    n = struct.unpack_from("<H", b, v)[0]
    return [
        (
            t + struct.unpack_from("<H", b, v + 4 + i * 2)[0]
            if struct.unpack_from("<H", b, v + 4 + i * 2)[0]
            else 0
        )
        for i in range((n - 4) // 2)
    ]


def rows(b):
    """Locate each row in the decoded original master table."""
    t = struct.unpack_from("<I", b)[0]
    f = fields(b, t)[0]
    v = f + struct.unpack_from("<I", b, f)[0]
    n = struct.unpack_from("<I", b, v)[0]
    return [
        v + 4 + 4 * i + struct.unpack_from("<I", b, v + 4 + 4 * i)[0] for i in range(n)
    ]


def table(name):
    """Read and decrypt a named original master from the checked asset source."""
    record = records()["1/master/divide_enc/" + name + ".enc"]
    data = ArchivedAsset(record).read_bytes()
    if hashlib.md5(data).hexdigest() != record["md5"]:
        raise ValueError("Master asset checksum mismatch: " + name)
    p = subprocess.run(
        [
            "/usr/bin/openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-K",
            AES_KEY.hex(),
            "-iv",
            IV.hex(),
        ],
        input=data,
        capture_output=True,
        check=True,
    ).stdout
    return zlib.decompress(p)


def scalar(b, t, i, width=4):
    """Decode a field as a signed scalar of the requested byte width."""
    ff = fields(b, t)
    f = ff[i] if i < len(ff) else 0
    if not f:
        return 0
    d = decode(b[f : f + width + 4])
    assert len(d) == width
    return int.from_bytes(d, "little", signed=True)


def text(b, t, i):
    """Decode an original text field, returning empty text for an absent field."""
    ff = fields(b, t)
    f = ff[i] if i < len(ff) else 0
    if not f:
        return ""
    p = f + struct.unpack_from("<I", b, f)[0]
    ln = struct.unpack_from("<I", b, p)[0]
    return decode(b[p + 4 : p + 4 + ln]).decode().rstrip("\0")


def build():
    """Regenerate compact server definitions from retained original master tables."""
    aliases = {}
    names = (
        "currency",
        "statusBoardItem",
        "staminaTicket",
        "expItem",
        "gachaTicket",
        "adventureTicket",
        "keyItem",
        "heroSublimateItem",
        "heroSublimateUnlockItem",
        "limitBreakItem",
        "cpItem",
        "equipmentEvolveItem",
        "equipmentMaterial",
        "familiaDonationItem",
        "takarakujiItem",
        "equipmentEnhanceItem",
        "memoriaExpItem",
        "unionRaidMedal",
        "generalLimitBreakItem",
        "alarmVoiceItem",
    )
    for name in names:
        if "1/master/divide_enc/" + name + ".enc" not in records():
            continue
        b = table(name)
        for t in rows(b):
            alias = text(b, t, 2 if name == "memoriaExpItem" else 1)
            if alias:
                value = scalar(b, t, 0)
                if alias in aliases and aliases[alias] != value:
                    raise ValueError("Ambiguous reward alias: " + alias)
                aliases[alias] = value
    for name, column in [("pc", 8), ("memoria", 2)]:
        b = table(name)
        for t in rows(b):
            aliases[text(b, t, column)] = scalar(b, t, 0)

    def item(alias, amount):
        if alias not in aliases:
            raise ValueError("Unknown original reward alias: " + alias)
        return {"itemId": aliases[alias], "amount": amount}

    b = table("pc")
    pcs = {
        str(scalar(b, t, 0)): {"attack": scalar(b, t, 22), "counter": scalar(b, t, 27)}
        for t in rows(b)
    }
    stages = {}
    b = table("adventureStage")
    for t in rows(b):
        value = {}
        first = text(b, t, 19)
        task = text(b, t, 22)
        if first and scalar(b, t, 18):
            value["first"] = item(first, scalar(b, t, 20))
        if task and scalar(b, t, 21):
            value["allTasks"] = item(task, scalar(b, t, 23))
        # Individual mission rewards come from adventureStageTask, not the all-missions bonus.
        stages[str(scalar(b, t, 0, 8))] = value
    b = table("adventureStageTask")
    checked_tasks = 0
    for t in rows(b):
        sid = str(scalar(b, t, 1, 8))
        if sid in stages and "allTasks" in stages[sid]:
            stages[sid].setdefault("taskIds", []).append(scalar(b, t, 0, 8))
        alias = text(b, t, 12)
        if not alias or not scalar(b, t, 11):
            continue
        sid = str(scalar(b, t, 1, 8))
        reward = item(alias, scalar(b, t, 13))
        if sid not in stages:
            raise ValueError("Task refers to absent stage: " + sid)
        if "task" in stages[sid] and stages[sid]["task"] != reward:
            raise ValueError("Stage task rewards differ: " + sid)
        stages[sid]["task"] = reward
        checked_tasks += 1
    b = table("achievement")
    achievements = {}
    for t in rows(b):
        aid = str(scalar(b, t, 0, 8))
        typ = scalar(b, t, 15)
        alias = text(b, t, 16)
        amount = scalar(b, t, 17)
        if typ == 10:
            achievements[aid] = {"stamina": amount}
        elif alias:
            achievements[aid] = item(alias, amount)
        elif typ:
            raise ValueError("Missing achievement reward identity: " + aid)
    outputs = {
        "master-rewards.json": {"stages": stages},
        "master-pc-attacks.json": {"pcs": pcs},
        "master-achievement-rewards.json": {"achievements": achievements},
    }
    # Independent previously retained regression expectations, not reconstruction inputs.
    assert stages["1010000101101"]["first"] == {"itemId": 205000002, "amount": 10000}
    assert achievements["6050000001"] == {"itemId": 294000001, "amount": 10}
    assert achievements["6010000001"] == {"stamina": 50}
    assert pcs["1011099002"] == {"attack": 109001039, "counter": 109001039}
    provenance = {
        "method": "Original APK AES-CBC and XXTEA decoding of CRC/MD5-verified retained FlatBuffers tables",
        "decoderApkSHA256": expected,
        "stages": len(stages),
        "pcs": len(pcs),
        "achievements": len(achievements),
        "originalTaskRewardsValidated": checked_tasks,
        "outputs": {},
    }
    for name, value in outputs.items():
        data = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        p = ROOT / "offline" / name
        tmp = p.with_suffix(".json.tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
        provenance["outputs"][name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    (ROOT / "offline/master-reconstruction.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    build()
