"""Validate the separate trial without launching or changing player data."""

# Reading guide: Bundle integrity checks: host compatibility, original input hashes, and
# folder-local links.
# Editing notes: Update inventories only for deliberate packaging changes; do not change
# expected hashes to hide an unexplained mismatch.
# Checks: tools/maintain.py check.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import hashlib, json, platform, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_MACOS = (26, 4)
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


def check_host(system=None, architecture=None, version=None, sandbox_exec=SANDBOX_EXEC):
    """Reject unsupported host architecture or operating system versions."""
    system = platform.system() if system is None else system
    architecture = platform.machine() if architecture is None else architecture
    version = platform.mac_ver()[0] if version is None else version
    if system != "Darwin":
        raise RuntimeError("This game folder runs on macOS only.")
    if architecture not in ("arm64", "aarch64"):
        raise RuntimeError("This game folder requires an Apple silicon Mac (arm64).")
    try:
        current = tuple(int(part) for part in version.split(".")[:2])
    except (AttributeError, ValueError):
        raise RuntimeError("Cannot determine the installed macOS version.")
    if current < MINIMUM_MACOS:
        raise RuntimeError("This game folder requires macOS 26.4 or later.")
    if not Path(sandbox_exec).is_file():
        raise RuntimeError(
            "Required macOS service /usr/bin/sandbox-exec is unavailable."
        )
    return {"architecture": "arm64", "minimumMacOS": "26.4", "macOS": version}


def check_local_symlinks(root=ROOT):
    """Check that dependency links remain inside the movable project folder."""
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(
                "Broken or invalid symlink: " + str(path.relative_to(root))
            ) from error
        if not target.is_relative_to(root):
            raise ValueError("Outside-folder symlink: " + str(path.relative_to(root)))


def check():
    """Validate required files, original inputs and internal links; return a summary."""
    host = check_host()
    if (ROOT / "DanMachi Mac.app").exists():
        raise ValueError("Obsolete second top-level app found; use DanMachi MF.app.")
    build = json.loads((ROOT / "offline/apks/build.json").read_text())
    for item in build["apks"]:
        path = ROOT / "offline/apks" / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Original APK mismatch: " + item["file"])
    patch = json.loads((ROOT / "launcher/compatibility-patches.json").read_text())
    native = next(
        (ROOT / "DanMachi MF.app/Contents/Client/android/data/app").glob(
            "*/com.eu.danmore-*/lib/arm64/libapp.so"
        )
    )
    if (
        hashlib.sha256(native.read_bytes()).hexdigest()
        != patch["patched_native_sha256"]
    ):
        raise ValueError("Trial native compatibility patch mismatch")
    archives = json.loads((ROOT / "launcher/assets-verified.json").read_text())
    for item in archives:
        path = ROOT / item["file"]
        if path.stat().st_size != item["bytes"]:
            raise ValueError("Archive size changed: " + item["file"])
    required = (
        "offline/english_presentation.py",
        "offline/english-text.json",
        "runtime/python/bin/python3.10",
        "runtime/Mac.apk.app/Contents/Resources/macapk-runtime",
        "runtime/DanMachi MF.app/Contents/MacOS/macapk-runtime",
        "launcher/mac_zip_reader.dylib",
        "launcher/window_fit.dylib",
        "launcher/stencil_support.dylib",
        "launcher/web_sections.dylib",
        "offline/web_pages.py",
        "launcher/video/movie-agent.jar",
        "launcher/video/movie-helper.jar",
        "launcher/compatibility-patches.json",
        "launcher/save_exit.py",
        "offline/user_data.py",
        "offline/asset_cache.py",
        "offline/play_days.py",
        "offline/shooting.py",
        "launcher/GameIcon.png",
        "DanMachi MF.app/Contents/MacOS/Launch",
        "state/native-client/android/data/data/com.eu.danmore_15.1.0/meta.json",
        "DanMachi MF.app/Contents/Resources/AppIcon.icns",
        "User Data/Export User.command",
        "User Data/Import User.command",
        "User Data/Delete User.command",
        "offline/server.py",
        "offline/gacha.py",
        "offline/gacha_rotation.py",
        "offline/gacha_ticket_access.py",
        "offline/event_box.py",
        "offline/event_item_icons.py",
        "launcher/grand_day_stage_list.py",
        "offline/local_downloads.py",
        "offline/anniversary_events.py",
        "state/offline/player-state.json",
        "state/offline/asset-sources.json.gz",
        "assets/archives/aliases.json.gz",
    )
    for name in required:
        if not (ROOT / name).is_file():
            raise ValueError("Required file missing: " + name)
    for name in ("runtime/sdk", "state/avd", "runtime/game-window"):
        if (ROOT / name).exists():
            raise ValueError("Unexpected emulator component: " + name)
    check_local_symlinks()
    return {
        "originalAPKsVerified": len(build["apks"]),
        "archiveSizesVerified": len(archives),
        "externalSymlinks": False,
        "brokenSymlinks": False,
        "emulatorIncluded": False,
        "hostRequirements": host,
        "playableVerified": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(check(), indent=2))
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print("Folder check failed:", error)
        sys.exit(1)
