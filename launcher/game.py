"""Launch the separate Mac.apk trial and its own loopback-only save server."""

# Reading guide: Startup coordinator: main() checks the bundle, owns the launch lock,
# starts the local server, and supervises the Mac.apk process.
# Editing notes: Window options and containment rules are near the top; process cleanup
# is inside main(). Keep shutdown/checkpoint ordering intact.
# Checks: launcher tests and tools/maintain.py test native.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import fcntl, json, os, signal, socket, subprocess, sys, time, urllib.request, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
SAVE_CLOSE_EXIT_CODE = 75
DISPLAY_OPTIONS = ("--orientation", "landscape", "--width", "800", "--height", "450")
DISPLAY_ENV = {
    "MACAPK_FULLSCREEN": "0",
    "MACAPK_FIT_WINDOW_TO_ASPECT": "1",
    "MACAPK_LETTERBOX_ASPECT": "1.7777778",
    "MACAPK_SIZE_COMPAT_UPSCALE": "always",
    "MACAPK_IGNORE_ORIENTATION_REQUEST": "1",
}


def local_shared_folders():
    # Mac.apk recreates host shared-folder symlinks at startup. Remove only
    # those links, never their destinations or the user's files.
    """Replace runtime-created shared-folder links with local empty directories."""
    sd = ROOT / "state/native-client/android/sdcard"
    for name in ("Music", "Pictures", "Download", "Movies", "Documents"):
        path = sd / name
        if path.is_symlink():
            path.unlink()
        path.mkdir(parents=True, exist_ok=True)


def bounded(path):
    """Trim a previous log to a small tail before starting another session."""
    if path.is_file() and path.stat().st_size > 16384:
        with path.open("r+b") as f:
            f.seek(-8192, 2)
            data = f.read()
            data = data.partition(b"\n")[2]
            f.seek(0)
            f.write(data)
            f.truncate()


def stream_log(process, path):
    # One writer owns the file offset; cap it while running, not only on exit.
    """Keep bounded live logs and a separate tail of diagnostic error lines."""
    diagnostic = path.with_name(path.stem + "-errors.log")
    diagnostic.write_bytes(b"")
    pending_line = b""
    diagnostic_tail = b""
    with path.open("wb") as log:
        tail = b""
        for chunk in iter(lambda: process.stdout.read1(4096), b""):
            tail = (tail + chunk)[-8192:]
            pending_line += chunk
            lines = pending_line.split(b"\n")
            pending_line = lines.pop()[-16384:]
            diagnostic_changed = False
            for line in lines:
                lowered = line.lower()
                if any(
                    marker in lowered
                    for marker in (
                        b"__assert",
                        b"assertion",
                        b"failed",
                        b"exception",
                        b"missing",
                        b"error",
                        b"abort()",
                    )
                ):
                    diagnostic_tail = (diagnostic_tail + line + b"\n")[-16384:]
                    diagnostic_changed = True
            if diagnostic_changed:
                diagnostic.write_bytes(diagnostic_tail)
            log.write(chunk)
            log.flush()
            if log.tell() > 16384:
                log.seek(0)
                log.write(tail)
                log.truncate()
                log.flush()


def settle_shared_folders():
    # Mac.apk creates these links during initialization. Keep their replacements
    # local while startup finishes, as well as before launch and after exit.
    """
    Repeat containment cleanup briefly while the runtime creates its shared folders.
    """
    for _ in range(30):
        local_shared_folders()
        time.sleep(0.5)


def cloud_storage_read_rules(home, root):
    """Allow this project while excluding sibling cloud-drive file contents."""
    cloud_storage = Path(home) / "Library/CloudStorage"
    try:
        project_relative = Path(root).relative_to(cloud_storage)
    except ValueError:
        return ["(deny file-read* (subpath " + json.dumps(str(cloud_storage)) + "))"]
    metadata_exceptions = [cloud_storage]
    ancestor = cloud_storage
    for part in project_relative.parts[:-1]:
        ancestor = ancestor / part
        metadata_exceptions.append(ancestor)
    metadata_exceptions = " ".join(
        "(literal " + json.dumps(str(path)) + ")" for path in metadata_exceptions
    )
    cloud_path = json.dumps(str(cloud_storage))
    project_path = json.dumps(root)
    return [
        "(deny file-read-data (require-all (subpath "
        + cloud_path
        + ") (require-not (subpath "
        + project_path
        + "))))",
        "(deny file-read-metadata (require-all (subpath "
        + cloud_path
        + ") (require-not (require-any "
        + metadata_exceptions
        + " (subpath "
        + project_path
        + ")))))",
    ]


def main():
    """
    Own this instance lock, start checked local processes and finish coordinated
    shutdown.
    """
    from check_bundle import check_host

    check_host()
    for name in ("logs", "temp"):
        (STATE / name).mkdir(exist_ok=True)
    with (STATE / "launch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("The separate Mac.apk trial is already running.")
            return 0
        # Never reuse a listener belonging to the Drive game or another copy.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", 28766))
            except OSError:
                raise RuntimeError(
                    "Port 28766 is occupied. Close the other Mac.apk trial before retrying."
                )
        from compatibility import ensure

        ensure()
        local_shared_folders()
        # Rebase the containment profile when this whole project is moved.
        home = str(Path.home())
        root = str(ROOT)
        rules = [
            "(version 1)",
            "(allow default)",
            "(deny network-outbound)",
            '(allow network-outbound (remote ip "localhost:*"))',
            "(deny file-write* (subpath " + json.dumps(home) + "))",
            "(allow file-write* (subpath " + json.dumps(root) + "))",
        ]
        rules.extend(cloud_storage_read_rules(home, root))
        rules.extend(
            "(deny file-read* (subpath " + json.dumps(home + "/" + name) + "))"
            for name in (
                "Library/Application Support/Mac.apk",
                "Music",
                "Pictures",
                "Movies",
                "Documents",
                "Downloads",
            )
        )
        rules.append("(allow file-read* (subpath " + json.dumps(root) + "))")
        rules.append(
            "(allow file-read-metadata (literal "
            + json.dumps(home + "/Downloads")
            + "))"
        )
        (ROOT / "launcher/offline.sb").write_text("\n".join(rules) + "\n")
        env = dict(
            os.environ,
            TMPDIR=str(STATE / "temp"),
            TMP=str(STATE / "temp"),
            TEMP=str(STATE / "temp"),
            MACAPK_MAX_FPS="30",
            MACAPK_MIC="0",
            MACAPK_LOG_LEVEL="5",
            MACAPK_APP_LABEL="DanMachi MF",
            MACAPK_APP_ICON=str(ROOT / "launcher/GameIcon.png"),
            DANMACHI_RESYNC="1",
            **DISPLAY_ENV,
        )
        env["JAVA_TOOL_OPTIONS"] = (
            '"-javaagent:'
            + str(ROOT / "launcher/video/movie-agent.jar")
            + "="
            + str(ROOT / "launcher/video/movie-helper.jar")
            + '"'
        )
        env.pop("LD_PRELOAD", None)
        env.pop("DYLD_INSERT_LIBRARIES", None)
        policy = ["/usr/bin/sandbox-exec", "-f", str(ROOT / "launcher/offline.sb")]
        processes = []

        def stop(signum=None, frame=None):
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        start = time.time()
        try:
            for name in ("macapk.log", "offline-server.log", "launcher.log"):
                bounded(STATE / "logs" / name)
            server = subprocess.Popen(
                policy + [sys.executable, "-B", str(ROOT / "offline/server.py")],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            server_logger = threading.Thread(
                target=stream_log,
                args=(server, STATE / "logs/offline-server.log"),
                daemon=True,
            )
            server_logger.start()
            processes.append(server)
            for _ in range(120):
                if server.poll() is not None:
                    raise RuntimeError(
                        "The separate offline server failed; see state/logs/offline-server.log."
                    )
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:28766/health", timeout=1
                    ) as response:
                        if json.load(response).get("status") == "ok":
                            break
                except (OSError, ValueError):
                    time.sleep(0.5)
            else:
                raise RuntimeError("The offline server did not become ready.")
            app = ROOT / "state/native-client/android"
            apk = (
                app
                / "data/app/~~m4c4pk0Zx9AbC1dEfGhIjw==/com.eu.danmore-Qm4c4pk0Zx9AbC1dEfGh8Q==/base.apk"
            )
            runtime = ROOT / "runtime/DanMachi MF.app/Contents/MacOS/macapk-runtime"
            game_env = dict(
                env,
                DYLD_INSERT_LIBRARIES=(
                    str(ROOT / "launcher/mac_zip_reader.dylib")
                    + ":"
                    + str(ROOT / "launcher/window_fit.dylib")
                    + ":"
                    + str(ROOT / "launcher/stencil_support.dylib")
                    + ":"
                    + str(ROOT / "launcher/web_sections.dylib")
                ),
                DANMACHI_ASSET_ROOT=str(
                    app / "data/data/com.eu.danmore_15.1.0/files/contents"
                ),
            )
            from tutorial_setup import SetupReload

            save_path = STATE / "offline/player-state.json"

            def setup_state():
                return (
                    json.loads(save_path.read_text())
                    if save_path.exists()
                    else {"tables": {}}
                )

            setup_reload = SetupReload(setup_state())
            stopping = False
            original_stop = stop

            def stop(signum=None, frame=None):
                nonlocal stopping
                stopping = True
                original_stop(signum, frame)

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            while True:
                game = subprocess.Popen(
                    policy
                    + [
                        "/usr/bin/env",
                        "DYLD_INSERT_LIBRARIES="
                        + (
                            str(ROOT / "launcher/mac_zip_reader.dylib")
                            + ":"
                            + str(ROOT / "launcher/window_fit.dylib")
                            + ":"
                            + str(ROOT / "launcher/stencil_support.dylib")
                            + ":"
                            + str(ROOT / "launcher/web_sections.dylib")
                        ),
                        str(runtime),
                        "--apk",
                        str(apk),
                        "--android-root",
                        str(app),
                        *DISPLAY_OPTIONS,
                    ],
                    cwd=ROOT,
                    env=game_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                game_logger = threading.Thread(
                    target=stream_log,
                    args=(game, STATE / "logs/macapk.log"),
                    daemon=True,
                )
                game_logger.start()
                threading.Thread(target=settle_shared_folders, daemon=True).start()
                processes.append(game)
                reload_setup = False
                while game.poll() is None:
                    try:
                        reload_setup = (
                            setup_reload.enabled
                            and not setup_reload.used
                            and setup_reload.observe(setup_state(), time.monotonic())
                        )
                    except (OSError, ValueError):
                        reload_setup = False
                    if reload_setup and not stopping:
                        print(
                            "Completing first-player starter setup with one clean reload.",
                            flush=True,
                        )
                        game.terminate()
                        try:
                            game.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            game.kill()
                            game.wait()
                        break
                    time.sleep(0.5)
                code = game.wait()
                game_logger.join(timeout=2)
                # The user wants Settings > To Title to save and close.
                if code == SAVE_CLOSE_EXIT_CODE and not stopping:
                    from save_exit import save_before_close

                    save_before_close(app / "data/data/com.eu.danmore_15.1.0")
                    print("Game saved and closed.", flush=True)
                    code = 0
                    break
                if stopping or not reload_setup:
                    break
                local_shared_folders()
            (STATE / "last-launch.json").write_text(
                json.dumps(
                    {
                        "exitCode": code,
                        "seconds": round(time.time() - start, 2),
                        "runtime": "Mac.apk 1.0.1732",
                        "playableVerified": False,
                    },
                    indent=2,
                )
                + "\n"
            )
            if code:
                import shutil

                shutil.copy2(STATE / "logs/macapk.log", STATE / "logs/last-crash.log")
                print(
                    "Mac.apk could not run this game. See launcher/CURRENT_SETUP.md and state/logs/macapk.log."
                )
            return 0 if code == 0 else 1
        finally:
            stop()
            for p in reversed(processes):
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            # Bound diagnostics on exit; no save/cache deletion.
            for name in ("macapk.log", "offline-server.log", "launcher.log"):
                bounded(STATE / "logs" / name)
            local_shared_folders()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print("Launch failed:", error)
        sys.exit(1)
