"""Exercise close-window shutdown and the newer-window protection."""

# Regression checks for session shutdown.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file depends on the retired session module.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import importlib.util, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import session


class SessionTests(unittest.TestCase):
    def test_new_window_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / "game-window.pid").write_text("222")
            with (
                patch.object(session, "clean_temporary"),
                patch.object(session.game, "STATE", state),
                patch.object(sys, "argv", ["session.py", "111"]),
                patch.object(session, "alive", return_value=False),
                patch.object(session, "stop_server") as stop,
                patch.object(session.game, "connected") as connected,
            ):
                session.main()
                stop.assert_not_called()
                connected.assert_not_called()

    def test_client_stops_and_flushes_before_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / "game-window.pid").write_text("111")
            calls = []
            with (
                patch.object(session, "clean_temporary"),
                patch.object(session.game, "STATE", state),
                patch.object(sys, "argv", ["session.py", "111"]),
                patch.object(session, "alive", return_value=False),
                patch.object(session.game, "connected", return_value=True),
                patch.object(
                    session.game,
                    "device",
                    side_effect=lambda *a, **kwargs: calls.append(a),
                ),
                patch.object(session, "maintain", return_value={}),
                patch.object(session.game, "log"),
                patch.object(session.game, "wait_for_android_exit"),
                patch.object(session.game, "release_adb") as release,
                patch.object(session, "stop_server") as stop,
            ):
                session.main()
            release.assert_called_once()
            self.assertEqual(
                calls,
                [
                    ("shell", "am", "force-stop", session.game.PACKAGE),
                    ("shell", "sm", "fstrim"),
                    ("shell", "sync"),
                    ("emu", "kill"),
                ],
            )
            stop.assert_called_once()
            self.assertFalse((state / "game-window.pid").exists())

    def test_late_audio_failure_recovers_display_and_keeps_game(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / "logs").mkdir()
            (state / "game-window.pid").write_text("111")
            (state / "game-window-mode").write_text("audio")
            earlier = b"Old failure: Could not open audio device\n"
            (state / "logs/game-window.log").write_bytes(
                earlier + b"Could not open audio device\n"
            )
            with (
                patch.object(session, "clean_temporary"),
                patch.object(session.game, "STATE", state),
                patch.object(sys, "argv", ["session.py", "111", str(len(earlier))]),
                patch.object(session, "alive", return_value=False),
                patch.object(session.game, "connected", return_value=True),
                patch.object(session.game, "window") as window,
                patch.object(session.game, "watch_window") as watch,
                patch.object(session.game, "device") as device,
                patch.object(session.game, "log"),
                patch.object(session, "stop_server") as stop,
            ):
                session.main()
            window.assert_called_once_with(audio=False)
            watch.assert_called_once()
            device.assert_not_called()
            stop.assert_not_called()

    def test_unhealthy_android_still_stops_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / "game-window.pid").write_text("111")
            calls = []
            with (
                patch.object(session, "clean_temporary"),
                patch.object(session.game, "STATE", state),
                patch.object(sys, "argv", ["session.py", "111"]),
                patch.object(session, "alive", return_value=False),
                patch.object(session.game, "connected", return_value=True),
                patch.object(
                    session.game,
                    "device",
                    side_effect=lambda *a, **kwargs: calls.append(a),
                ),
                patch.object(
                    session,
                    "maintain",
                    side_effect=RuntimeError("services unavailable"),
                ),
                patch.object(session.game, "log"),
                patch.object(session.game, "wait_for_android_exit"),
                patch.object(session.game, "release_adb"),
                patch.object(session, "stop_server") as stop,
            ):
                session.main()
            self.assertIn(("emu", "kill"), calls)
            stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
