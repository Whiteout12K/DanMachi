"""Media saturation must avoid the unsafe Android 11 media_session command."""

# Regression checks for audio volume.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.
# Historical coverage: this file depends on the retired launcher/audio.py device helper.
# It is not in the current focused Mac suites; keep it as reference, not a
# reason to restore an emulator/device dependency.

import sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from audio import full_media_volume, media_level


def dump(level, muted=False):
    return (
        "- STREAM_MUSIC:\n Muted: "
        + str(muted).lower()
        + "\n Muted Internally: false\n Min: 0\n Max: 15\n streamVolume:"
        + str(level)
        + "\n- STREAM_ALARM:\n Max: 7\n"
    )


class VolumeTest(unittest.TestCase):
    def test_full_volume_requires_no_key_events(self):
        calls = []

        def device(*args):
            calls.append(args)
            return dump(15)

        self.assertEqual(full_media_volume(device)["current"], 15)
        self.assertEqual(calls, [("shell", "dumpsys", "audio")])

    def test_low_volume_uses_normal_media_keys_and_verifies_result(self):
        calls = []
        responses = iter(
            [
                dump(5),
                "mCurrentFocus=Window{1 u0 com.eu.danmore/net.wrightflyer.toybox.AppActivity}",
                "",
                dump(15),
            ]
        )

        def device(*args):
            calls.append(args)
            return next(responses)

        self.assertEqual(full_media_volume(device)["current"], 15)
        self.assertEqual(calls[2], ("shell", "input", "keyevent", *(["24"] * 11)))
        self.assertFalse(any("media_session" in x for x in calls))

    def test_failed_or_muted_volume_is_not_reported_as_full(self):
        with (
            patch("audio.time.monotonic", side_effect=[0, 31]),
            self.assertRaises(RuntimeError),
        ):
            full_media_volume(lambda *args: dump(5))
        self.assertTrue(media_level(dump(15, True))["muted"])

    def test_no_input_is_sent_until_game_window_has_focus(self):
        focused = False
        polls = 0
        events = []
        level = 5

        def device(*args):
            nonlocal focused, polls, level
            if args[1:] == ("dumpsys", "audio"):
                return dump(level)
            if args[1:] == ("dumpsys", "window", "displays"):
                polls += 1
                focused = polls >= 3
                return (
                    "mCurrentFocus=Window{1 u0 com.eu.danmore/net.wrightflyer.toybox.AppActivity}"
                    if focused
                    else "mCurrentFocus=null\nmFocusedApp=com.eu.danmore/net.wrightflyer.toybox.AppActivity"
                )
            if args[1:3] == ("input", "keyevent"):
                self.assertTrue(
                    focused, "Input during startup causes Android no-focused-window ANR"
                )
                events.append(args)
                level = 15
                return ""
            raise AssertionError(args)

        with patch("audio.time.sleep"):
            self.assertEqual(full_media_volume(device)["current"], 15)
        self.assertEqual(len(events), 1)
        self.assertEqual(polls, 3)
