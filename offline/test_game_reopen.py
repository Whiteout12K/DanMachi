"""A force-stopped Home game must be explicitly opened before resolving Home."""

# Regression checks for game reopen.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file expects retired device activity/boot controls rather
# than the Mac launcher.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import game


class ReopenTests(unittest.TestCase):
    def test_stopped_game_home_is_resolved_after_explicit_launch(self):
        calls = []
        resolutions = iter(["No activity found", game.ACTIVITY])

        def device(*args, **kwargs):
            calls.append(args)
            if "resolve-activity" in args:
                return next(resolutions)
            return ""

        with patch.object(game, "device", side_effect=device):
            game.game_only()
        self.assertEqual(
            calls.count(("shell", "am", "start", "-W", "-n", game.ACTIVITY)), 1
        )

    def test_existing_home_needs_no_extra_launch(self):
        calls = []

        def device(*args, **kwargs):
            calls.append(args)
            return game.ACTIVITY if "resolve-activity" in args else ""

        with patch.object(game, "device", side_effect=device):
            game.game_only()
        self.assertNotIn(("shell", "am", "start", "-W", "-n", game.ACTIVITY), calls)

    def test_verified_persistent_profile_skips_system_package_changes(self):
        calls = []

        def device(*args, **kwargs):
            calls.append(args)
            if "cat" in args:
                return "verified-policy"
            if "resolve-activity" in args:
                return game.ACTIVITY
            if args[-3:] == ("list", "packages", "-d"):
                return "package:com.android.settings\npackage:com.google.android.inputmethod.latin"
            return ""

        with (
            patch("startup_cache.signature", return_value="verified-policy"),
            patch.object(game, "device", side_effect=device),
        ):
            game.game_only()
        self.assertFalse(
            any("uninstall" in call or "disable-user" in call for call in calls)
        )

    def test_locked_profile_restores_support_and_starts_direct_boot_activity(self):
        calls = []

        def device(*args, **kwargs):
            calls.append(args)
            if args[-3:] == ("list", "packages", "-d"):
                return "package:com.android.systemui\npackage:com.android.settings"
            if args[-1] == "sys.boot_completed":
                return ""
            return ""

        with patch.object(game, "device", side_effect=device):
            game.restore_boot_ui()
        self.assertIn(
            ("shell", "pm", "enable", "--user", "0", "com.android.systemui"), calls
        )
        self.assertIn(
            ("shell", "pm", "enable", "--user", "0", "com.android.settings"), calls
        )
        self.assertEqual(
            calls[-1],
            ("shell", "am", "start", "-n", "com.android.settings/.FallbackHome"),
        )
        self.assertFalse(any("reboot" in call for call in calls))

    def test_healthy_profile_does_not_start_fallback_activity(self):
        with patch.object(
            game,
            "device",
            side_effect=["package:com.google.android.inputmethod.latin", "1"],
        ) as device:
            game.restore_boot_ui()
        self.assertEqual(device.call_count, 2)

    def test_boot_retries_recovery_after_android_service_restart(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            avd = Path(folder)
            (avd / "qemu-version.txt").write_text("2")
            flags = iter(["", "", "1"])
            recoveries = []

            def device(*args, **kwargs):
                if args[-1] == "sys.boot_completed":
                    return next(flags)
                if args[-1] == "system_server":
                    return "42"
                if "path" in args:
                    return "package:/system/framework/framework-res.apk"
                return ""

            ticks = iter(range(0, 1000, 6))

            def recover():
                recoveries.append(1)
                if len(recoveries) == 1:
                    raise RuntimeError("Android service restarting")

            with (
                patch.object(game, "AVD", avd),
                patch.object(game, "prepare"),
                patch.object(game, "adb"),
                patch.object(game, "connected", return_value=True),
                patch.object(game, "device", side_effect=device),
                patch.object(game, "restore_boot_ui", side_effect=recover),
                patch.object(game.time, "monotonic", side_effect=lambda: next(ticks)),
                patch.object(game.time, "sleep"),
            ):
                game.boot()
            self.assertGreaterEqual(len(recoveries), 2)


if __name__ == "__main__":
    unittest.main()
