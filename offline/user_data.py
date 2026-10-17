"""Validated export/import/reset of local player data, excluding game assets."""

# Reading guide: Account lifecycle: validate exports first, stop this game, then copy
# both server and native account data.
# Editing notes: Import/delete keep rollback snapshots and release the launch lock in
# finally blocks. Keep game assets outside account exports.
# Checks: offline/test_user_data.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import argparse, hashlib, io, json, os, signal, subprocess, sys, tarfile, tempfile, time, unicodedata, zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
import fcntl

PACKAGE = "com.eu.danmore"
CLIENT = ROOT / "state/native-client/android/data/data/com.eu.danmore_15.1.0"
_session_lock = None
WORK = ROOT / "state/offline"
CLIENT_PATHS = (
    "files/ldb",
    "files/kwlt",
    "files/commit_list.dat",
    "shared_prefs",
    "databases",
    "no_backup",
)
MAX_BYTES = 64 * 1024 * 1024


def validate_state(data):
    """Reject account exports without valid table and token containers."""
    value = json.loads(data)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("tables"), dict)
        or not isinstance(value.get("tokens"), dict)
    ):
        raise ValueError("Not a DanMachi player save.")
    if any(
        not isinstance(k, str) or not isinstance(v, list)
        for k, v in value["tables"].items()
    ):
        raise ValueError("Invalid player tables.")
    if any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in value["tokens"].items()
    ):
        raise ValueError("Invalid player tokens.")
    return value


def validate_client(data):
    """Reject unsafe TAR paths, links, unsupported files and oversized account data."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        total = 0
        seen = set()
        for item in archive:
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts or item.name in seen:
                raise ValueError("Unsafe client-save path.")
            if not any(
                item.name.rstrip("/") == p or item.name.startswith(p + "/")
                for p in CLIENT_PATHS
            ):
                raise ValueError("Save includes non-player files.")
            if not (item.isfile() or item.isdir()):
                raise ValueError("Save links and special files are not accepted.")
            total += item.size
            seen.add(item.name)
            if total > MAX_BYTES:
                raise ValueError("Client save is too large.")


def player_summary(state):
    """Extract a printable account name and optional rank for export labels."""
    rows = state["tables"].get("UserInfo", [])
    info = rows[0] if rows and isinstance(rows[0], dict) else {}
    name = info.get("name") or "NewPlayer"
    name = "".join(c for c in str(name) if c.isprintable()).strip()[:64] or "NewPlayer"
    status = info.get("playerStatus", {})
    rank = status.get("level") if isinstance(status, dict) else None
    return {"username": name, "rank": rank if isinstance(rank, int) else None}


def export_filename(summary, folder=None):
    """Choose a safe dated export name without overwriting an existing export."""
    folder = Path(folder) if folder else ROOT / "User Data/Exports"
    name = unicodedata.normalize("NFKC", summary["username"])
    name = (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-_")[:32]
        or "Player"
    )
    stem = name + "-" + time.strftime("%y%m%d")
    path = folder / (stem + ".zip")
    counter = 2
    while path.exists():
        path = folder / (stem + "-" + str(counter) + ".zip")
        counter += 1
    return path


def read_export(path):
    """Validate export structure, game build, payload hashes and account contents."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = {i.filename for i in entries}
        required = {"manifest.json", "player-state.json", "client.tar"}
        if len(entries) != len(names) or names not in (
            required,
            required | {"summary.txt"},
        ):
            raise ValueError("Not a complete DanMachi export.")
        if any(i.file_size > MAX_BYTES for i in entries):
            raise ValueError("Export is too large.")
        manifest = json.loads(archive.read("manifest.json"))
        if (
            manifest.get("format") != "danmachi-user-v1"
            or manifest.get("package") != PACKAGE
        ):
            raise ValueError("Incompatible save format.")
        if (
            manifest.get("gameSource")
            != json.loads((ROOT / "offline/apks/build.json").read_text())[
                "source_sha256"
            ]
        ):
            raise ValueError("Save was made for a different game build.")
        state = archive.read("player-state.json")
        client = archive.read("client.tar")
        payloads = [("player-state.json", state), ("client.tar", client)]
        if "summary.txt" in names:
            payloads.append(("summary.txt", archive.read("summary.txt")))
        elif "summary.txt" in manifest["sha256"]:
            raise ValueError("Player summary is missing.")
        for name, data in payloads:
            if hashlib.sha256(data).hexdigest() != manifest["sha256"].get(name):
                raise ValueError("Save integrity check failed.")
        validate_state(state)
        validate_client(client)
        return state, client


def pause():
    """Stop only this trial's launcher, then hold its actual launch lock."""
    global _session_lock
    expected = str(ROOT / "launcher/game.py")
    for line in subprocess.check_output(
        ["/bin/ps", "-axo", "pid=,command="], text=True
    ).splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or "python" not in fields[1]:
            continue
        matches = fields[1].endswith(expected)
        if fields[1].endswith(" -B launcher/game.py"):
            cwd = subprocess.check_output(
                ["/usr/sbin/lsof", "-a", "-p", fields[0], "-d", "cwd", "-Fn"], text=True
            )
            matches = ("n" + str(ROOT)) in cwd.splitlines()
        if matches:
            os.kill(int(fields[0]), signal.SIGTERM)
    lock = (ROOT / "state/launch.lock").open("a")
    deadline = time.monotonic() + 20
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() > deadline:
                lock.close()
                raise RuntimeError("Close DanMachi Mac before managing player data.")
            time.sleep(0.1)
    _session_lock = lock


def resume():
    """
    Release the launch lock held by an account operation; it does not launch the
    game.
    """
    global _session_lock
    if _session_lock:
        _session_lock.close()
        _session_lock = None


def client_snapshot(path):
    """Archive only approved native player paths, then validate the snapshot."""
    with tarfile.open(path, "w", format=tarfile.GNU_FORMAT) as archive:
        for name in CLIENT_PATHS:
            source = CLIENT / name
            if source.is_symlink():
                raise ValueError("Client save contains a link.")
            if source.exists():
                archive.add(source, arcname=name, recursive=True)
    data = Path(path).read_bytes()
    validate_client(data)
    return data


def safe_client_root():
    """Reject symlinks that could redirect account changes outside the project."""
    if not CLIENT.is_relative_to(ROOT):
        raise ValueError("Client root must be inside the project.")
    for p in (CLIENT, *CLIENT.parents):
        if p == ROOT:
            break
        if p.is_symlink():
            raise ValueError("Client root must not be a symlink.")
    for name in CLIENT_PATHS:
        target = CLIENT / name
        for ancestor in (target, *target.parents):
            if ancestor == CLIENT:
                break
            if ancestor.is_symlink():
                raise ValueError("Client save contains a link.")


def clear_client():
    """Remove only approved native account paths after containment validation."""
    import shutil

    safe_client_root()
    for name in CLIENT_PATHS:
        target = CLIENT / name
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)


def install_archive(path):
    """Install a validated native account TAR only beneath approved player paths."""
    data = Path(path).read_bytes()
    validate_client(data)
    safe_client_root()
    CLIENT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for item in archive:
            target = CLIENT / item.name
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source, target.open("wb") as dest:
                    import shutil

                    shutil.copyfileobj(source, dest)
                target.chmod(0o600)


def write_state(data):
    """Validate and atomically replace the server account file."""
    validate_state(data)
    WORK.mkdir(parents=True, exist_ok=True)
    temp = WORK / "player-state.importing"
    with temp.open("wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    temp.replace(WORK / "player-state.json")
    (WORK / "reset-account.pending").unlink(missing_ok=True)


def export_user(path=None):
    """Stop this game and export both halves of the account with checked hashes."""
    path = Path(path).expanduser().resolve() if path else None
    if path and path.exists():
        raise ValueError("Export already exists; choose a new filename.")
    pause()
    try:
        state = (WORK / "player-state.json").read_bytes()
        summary = player_summary(validate_state(state))
        path = path or export_filename(summary)
        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        description = (
            "DanMachi player: "
            + summary["username"]
            + "\nRank: "
            + str(summary["rank"] or "New player")
            + "\nSaved: "
            + created
            + "\nContains player data only; game assets are not included.\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as temp:
            client = client_snapshot(Path(temp) / "client.tar")
        manifest = {
            "format": "danmachi-user-v1",
            "package": PACKAGE,
            "gameSource": json.loads((ROOT / "offline/apks/build.json").read_text())[
                "source_sha256"
            ],
            "created": created,
            "player": summary,
            "sha256": {
                n: hashlib.sha256(d).hexdigest()
                for n, d in [
                    ("player-state.json", state),
                    ("client.tar", client),
                    ("summary.txt", description),
                ]
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("player-state.json", state)
            archive.writestr("client.tar", client)
            archive.writestr("summary.txt", description)
        read_export(partial)
        partial.replace(path)
        path.chmod(0o600)
    finally:
        resume()
    return path


def import_user(path):
    """Validate first, then replace both account halves with rollback on failure."""
    state, client = read_export(
        path
    )  # Fully validate before pausing or changing the current player.
    pause()
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as temp:
            folder = Path(temp)
            original = (WORK / "player-state.json").read_bytes()
            old = client_snapshot(folder / "rollback.tar")
            restore = folder / "client.tar"
            restore.write_bytes(client)
            try:
                clear_client()
                install_archive(restore)
                write_state(state)
            except Exception:
                clear_client()
                install_archive(folder / "rollback.tar")
                write_state(original)
                raise
    finally:
        resume()


def delete_user():
    """Reset both account halves while retaining rollback data until success."""
    pause()
    try:
        with tempfile.TemporaryDirectory(dir=ROOT / "state/temp") as temp:
            folder = Path(temp)
            original = (WORK / "player-state.json").read_bytes()
            client_snapshot(folder / "rollback.tar")
            try:
                clear_client()
                os.sync()
                fresh = {
                    "tables": {},
                    "tokens": {},
                    "generation": json.loads(original).get("generation", 0) + 1,
                }
                write_state(json.dumps(fresh, separators=(",", ":")).encode())
            except Exception:
                clear_client()
                install_archive(folder / "rollback.tar")
                write_state(original)
                raise
    finally:
        resume()


def main():
    """
    Validate CLI input and confirmation, then serialize export/import/delete
    actions.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "import", "delete"])
    parser.add_argument("--file")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    source = args.file
    if args.action == "import" and not source:
        try:
            source = subprocess.check_output(
                [
                    "/usr/bin/osascript",
                    "-e",
                    'POSIX path of (choose file with prompt "Choose a DanMachi user export")',
                ],
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
        except subprocess.CalledProcessError as error:
            if "-128" in error.stderr:
                print("Cancelled.")
                return
            raise
    if args.action in ("import", "delete") and not args.yes:
        word = args.action.upper()
        if args.action == "import":
            incoming, _ = read_export(source)
            summary = player_summary(validate_state(incoming))
            print(
                "Import player: "
                + summary["username"]
                + " (rank "
                + str(summary["rank"] or "new")
                + ")"
            )
        if (
            input(
                (
                    "Replace the current player"
                    if args.action == "import"
                    else "Delete the local player permanently"
                )
                + "? Type "
                + word
                + ": "
            ).strip()
            != word
        ):
            print("Cancelled.")
            return
    import fcntl

    with (ROOT / "state/user-data.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "export":
            path = source
            result = export_user(path)
            print("User exported to: " + str(result))
            subprocess.run(["/usr/bin/open", "-R", str(result)])
        elif args.action == "import":
            import_user(source)
            print("User imported. Open DanMachi Mac to continue.")
        else:
            delete_user()
            print(
                "User deleted. Assets retained. Open DanMachi Mac to start a new player."
            )


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
        tarfile.TarError,
        KeyError,
    ) as error:
        print("User data operation failed: " + str(error))
        sys.exit(1)
