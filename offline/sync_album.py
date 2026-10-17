"""Expose the original Album artwork without unpacking unrelated game assets."""

# Reading guide: Album asset planning: compare original hashes, prepare only needed
# artwork, and install the local payload.
# Editing notes: Keep portrait availability separate from unit ownership. Do not unpack
# unrelated archives for an Album request.
# Checks: offline/test_album_assets.py.
# Transport note: external_assets mode uses the virtual ZIP reader and returns
# before the retained legacy ADB install branch. Do not invoke old device helpers.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib, io, json, posixpath, subprocess, tarfile, threading
from pathlib import Path, PurePosixPath
from asset_store import resolve

ROOT = Path(__file__).resolve().parents[1]
ADB = [
    str(ROOT / "runtime/sdk/platform-tools/adb"),
    "-P",
    "5038",
    "-s",
    "emulator-5560",
]
PACKAGE = "com.eu.danmore"
ART_PREFIX = "files/character/lottery/"
ALBUM_FILES = frozenset(
    (
        "all_rectangle.png",
        "status_l.png",
        "bustup_s.png",
        "hex.png",
        "thumbnail_square.png",
        "thumbnail_square2.png",
        "thumbnail_rectangle.png",
        "texture.png",
        "texture.plist",
    )
)
MARKER = "files/local-album-art-v1"


def album_rows(manifests):
    """Select retained Album artwork entries from the supplied manifests."""
    rows = []
    for phase, assets in manifests.items():
        atlas_dirs = {
            n.rsplit("/", 1)[0]
            for n in assets
            if n.startswith(ART_PREFIX) and n.endswith("/texture.png")
        }
        for name, item in sorted(assets.items()):
            if not name.startswith(ART_PREFIX):
                continue
            parent, filename = name.rsplit("/", 1)
            if filename not in ALBUM_FILES and not (
                parent in atlas_dirs and filename in ("white.png", "withe.png")
            ):
                continue
            parts = PurePosixPath(name).parts
            if ".." in parts or any(c in name for c in "\0\r\n"):
                raise ValueError("Unsafe Album asset")
            rows.append(
                {
                    "phase": phase,
                    "name": name,
                    "md5": item["md5"],
                    "size": item["size"],
                    "item": item,
                }
            )
    return rows


def fingerprint(rows):
    """Build the comparison identity for the requested Album asset state."""
    return hashlib.sha256(
        json.dumps(
            [(r["phase"], r["name"], r["md5"], r["size"]) for r in rows]
        ).encode()
    ).hexdigest()


def parse_hashes(data):
    """Parse installed md5sum output into logical paths and checksums."""
    result = {}
    for line in data.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and len(fields[0]) == 32:
            path = fields[1].lstrip("*")
            if (
                path.startswith("files/contents/")
                and ".." not in PurePosixPath(path).parts
            ):
                result[path] = fields[0]
    return result


def installed_hashes():
    # Android's find -exec ... + exceeded its argument limit on this cache.
    """Historical device hash scan; bypassed by current external-assets mode."""
    command = "'find -L files/contents -type f -print0 | xargs -0 -n 64 md5sum'"
    result = subprocess.run(
        ADB + ["shell", "run-as", PACKAGE, "sh", "-c", command],
        capture_output=True,
        text=True,
        check=True,
    )
    if "Argument list too long" in result.stdout or "md5sum:" in result.stdout:
        raise RuntimeError("Installed asset comparison failed")
    return parse_hashes(result.stdout)


def plan(rows, observed):
    # Only verified, unchanged destinations may become shared-file targets.
    """Select only missing or mismatched Album assets from verified sources."""
    canonical = {}
    for row in rows:
        target = "files/contents/" + row["phase"] + "/" + row["name"]
        if observed.get(target) == row["md5"]:
            canonical.setdefault((row["md5"], row["size"]), target)
    operations = []
    for row in rows:
        target = "files/contents/" + row["phase"] + "/" + row["name"]
        identity = (row["md5"], row["size"])
        if observed.get(target) != row["md5"]:
            if identity in canonical:
                operations.append(("link", target, canonical[identity]))
            else:
                operations.append(("data", target, row))
                canonical[identity] = target
        alias = "files/contents/1/" + row["name"]
        if alias != target and observed.get(alias) != row["md5"]:
            operations.append(("link", alias, target))
    return operations


def write_tar(output, operations, version):
    """Write the selected verified Album payload into an installation TAR."""
    with tarfile.open(fileobj=output, mode="w|", format=tarfile.GNU_FORMAT) as tar:
        for kind, target, value in operations:
            entry = tarfile.TarInfo(target)
            entry.mode = 0o600
            if kind == "link":
                entry.type = tarfile.SYMTYPE
                entry.linkname = posixpath.relpath(value, posixpath.dirname(target))
                tar.addfile(entry)
            else:
                asset = resolve(value["phase"], value["name"], value["item"])
                if asset is None:
                    raise ValueError("Missing Album source: " + value["name"])
                data = asset.read_bytes()
                if (
                    len(data) != value["size"]
                    or hashlib.md5(data).hexdigest() != value["md5"]
                ):
                    raise ValueError("Album source checksum mismatch: " + value["name"])
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        data = (version + "\n").encode()
        entry = tarfile.TarInfo(MARKER)
        entry.mode = 0o600
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))


def ensure_album():
    """Make requested retained Album artwork available without changing ownership."""
    if (
        json.loads((ROOT / "offline/apks/build.json").read_text())
        .get("external_assets", {})
        .get("version")
        == 1
    ):
        return
    from sync_unit import manifests

    rows = album_rows(manifests())
    version = fingerprint(rows)
    receipt = subprocess.run(
        ADB + ["shell", "run-as", PACKAGE, "cat", MARKER],
        capture_output=True,
        text=True,
    )
    if receipt.returncode == 0 and receipt.stdout.strip() == version:
        return {"unchanged": True, "artworkFiles": len(rows)}
    unavailable = [
        r["name"] for r in rows if resolve(r["phase"], r["name"], r["item"]) is None
    ]
    if unavailable:
        raise ValueError(
            "Missing original Album sources: " + ", ".join(unavailable[:10])
        )
    observed = installed_hashes()
    operations = plan(rows, observed)
    subprocess.run(
        ADB + ["shell", "am", "force-stop", PACKAGE],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    # Remove changed file entries first so extraction cannot follow an old
    # asset symlink and overwrite its shared target. No player files are touched.
    paths = b"".join(target.encode() + b"\0" for _, target, _ in operations)
    if paths:
        subprocess.run(
            ADB + ["exec-in", "run-as", PACKAGE, "xargs", "-0", "-n", "64", "rm", "-f"],
            input=paths,
            capture_output=True,
            check=True,
        )
    process = subprocess.Popen(
        ADB + ["exec-in", "run-as", PACKAGE, "tar", "-xof", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    errors = bytearray()

    def drain_errors():
        for chunk in iter(lambda: process.stderr.read(4096), b""):
            errors.extend(chunk)
            if len(errors) > 65536:
                del errors[:-65536]

    reader = threading.Thread(target=drain_errors, daemon=True)
    reader.start()
    try:
        write_tar(process.stdin, operations, version)
        process.stdin.close()
        code = process.wait(timeout=120)
        reader.join(timeout=5)
        if errors:
            (ROOT / "state/logs/album-extraction.log").write_bytes(errors)
        if code:
            raise RuntimeError(
                "Album asset installation failed: " + errors.decode(errors="replace")
            )
    except BaseException:
        process.kill()
        process.wait()
        subprocess.run(
            ADB + ["shell", "run-as", PACKAGE, "rm", "-f", MARKER], capture_output=True
        )
        raise
    # Verify every original visible path, including reused files and links.
    checked = installed_hashes()
    failures = [
        r["name"]
        for r in rows
        if checked.get("files/contents/1/" + r["name"]) != r["md5"]
        or checked.get("files/contents/" + r["phase"] + "/" + r["name"]) != r["md5"]
    ]
    if failures:
        subprocess.run(
            ADB + ["shell", "run-as", PACKAGE, "rm", "-f", MARKER], capture_output=True
        )
        raise RuntimeError(
            "Album installed verification failed: " + ", ".join(failures[:10])
        )
    report = {
        "artworkFiles": len(rows),
        "unitArtworkDirectories": len({r["name"].rsplit("/", 1)[0] for r in rows}),
        "installedUniquePayloadBytes": sum(
            value["size"] for kind, _, value in operations if kind == "data"
        ),
        "installedUniquePayloadFiles": sum(kind == "data" for kind, _, _ in operations),
        "linksCreated": sum(kind == "link" for kind, _, _ in operations),
        "allVisibleHashesVerified": True,
        "externalDownloads": 0,
        "temporaryAssetArchivesCreated": 0,
        "playerFilesModified": False,
        "fingerprint": version,
    }
    (ROOT / "state/logs/album-installation.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


if __name__ == "__main__":
    print(json.dumps(ensure_album(), indent=2))
