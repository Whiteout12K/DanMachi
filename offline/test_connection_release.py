"""Stop orphan helpers without disconnecting any active Android device."""

# Regression checks for connection release.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file expects the retired device/ADB process controls in
# launcher/game.py.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import game


class ConnectionReleaseTest(unittest.TestCase):
    def test_shutdown_waits_for_connection_to_disappear(self):
        with (
            patch.object(
                game,
                "adb",
                side_effect=[
                    "emulator-5560\tdevice",
                    "emulator-5560\toffline",
                    "List of devices attached",
                ],
            ) as connected,
            patch.object(game.time, "sleep") as sleep,
        ):
            game.wait_for_android_exit()
        self.assertEqual(connected.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_idle_connection_daemon_is_released(self):
        with patch.object(
            game, "adb", return_value="List of devices attached\n"
        ) as adb:
            self.assertTrue(game.release_adb())
        self.assertEqual(adb.call_args_list[-1].args, ("kill-server",))

    def test_live_device_keeps_connection_daemon(self):
        with patch.object(
            game, "adb", return_value="List of devices attached\nemulator-5560\tdevice"
        ) as adb:
            self.assertFalse(game.release_adb())
        self.assertEqual(adb.call_count, 1)

    def test_stop_also_cleans_helpers_when_android_is_already_gone(self):
        import user_data

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(game, "STATE", Path(directory)),
            patch.object(sys, "argv", ["game.py", "--stop"]),
            patch.object(game, "check_runtime"),
            patch.object(game, "connected", return_value=False),
            patch.object(game, "close_window") as close,
            patch.object(user_data, "stop_server") as server,
            patch.object(game, "release_adb") as release,
            patch.object(game, "log"),
        ):
            game.main()
        close.assert_called_once()
        server.assert_called_once()
        release.assert_called_once()
