"""The game window starts with fitted landscape dimensions and no fullscreen."""

# Regression checks for game window.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import game


class WindowTests(unittest.TestCase):
    def test_launcher_uses_windowed_landscape_that_fits_game_aspect(self):
        self.assertEqual(
            game.DISPLAY_OPTIONS,
            ("--orientation", "landscape", "--width", "800", "--height", "450"),
        )
        self.assertEqual(
            game.DISPLAY_ENV,
            {
                "MACAPK_FULLSCREEN": "0",
                "MACAPK_FIT_WINDOW_TO_ASPECT": "1",
                "MACAPK_LETTERBOX_ASPECT": "1.7777778",
                "MACAPK_SIZE_COMPAT_UPSCALE": "always",
                "MACAPK_IGNORE_ORIENTATION_REQUEST": "1",
            },
        )


if __name__ == "__main__":
    unittest.main()
