#!/usr/bin/env python3
"""Inspect the project and run focused checks without changing player progress."""

# Reading guide: Maintenance entry point: inspect account/banner summaries, validate
# packaging, or run focused test groups.
# Editing notes: SUITES defines the supported feature checks. Test subprocesses use a
# full Python installation and temporary fixtures, not the bundled minimal runtime.
# Checks: python3 tools/maintain.py test all.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "english": ("offline", "test_english_presentation.py"),
    "gacha": ("offline", "test_gacha*.py"),
    "boxes": ("offline", "test_event_box.py"),
    "events": (
        "offline",
        "test_anniversary_events.py",
        "test_guild_events.py",
        "test_event_item_icons.py",
    ),
    "native": (
        "launcher/tests",
        "test_grand_day_dispatch.py",
        "test_monthly_pass.py",
        "test_title_return.py",
    ),
    "saves": ("offline", "test_save_updates.py", "test_inventory_transactions.py"),
}


def main():
    """
    Dispatch read-only inspection, integrity checking or focused temporary-fixture
    tests.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "status", help="Read current account summary and maintenance evidence"
    )
    banners = sub.add_parser("banners", help="List planned banners for a UTC day")
    banners.add_argument(
        "--date", type=datetime.date.fromisoformat, help="UTC date in YYYY-MM-DD form"
    )
    sub.add_parser("check", help="Verify the retained bundle and original inputs")
    tests = sub.add_parser("test", help="Run a focused suite against temporary saves")
    tests.add_argument("suite", choices=(*SUITES, "all"))
    args = parser.parse_args()
    if args.command == "status":
        p = ROOT / "state/offline/player-state.json"
        state = json.loads(p.read_text()) if p.exists() else {}
        info = state.get("tables", {}).get("UserInfo", [{}])[0]
        summary = {
            "project": str(ROOT),
            "accountPresent": bool(info),
            "savedRank": info.get("playerStatus", {}).get("level"),
            "serverSaveBytes": p.stat().st_size if p.exists() else 0,
            "lastLaunch": (
                json.loads((ROOT / "state/last-launch.json").read_text())
                if (ROOT / "state/last-launch.json").exists()
                else None
            ),
            "verificationReports": [
                str(p.relative_to(ROOT))
                for p in sorted((ROOT / "state/verification").glob("**/*.json"))
            ],
            "guide": "docs/README.md",
            "history": "launcher/CURRENT_SETUP.md",
        }
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "banners":
        sys.path.insert(0, str(ROOT / "offline"))
        import gacha_rotation as rotation

        day = args.date or datetime.datetime.now(datetime.timezone.utc).date()
        timestamp = datetime.datetime.combine(
            day, datetime.time(12), datetime.timezone.utc
        ).timestamp()
        banners = rotation.active(0, timestamp)
        events = rotation.current_events(timestamp)
        print(
            f"Planned lineup for {day} UTC — {len(banners)} records (ticket visibility depends on inventory)"
        )
        for index, b in enumerate(banners):
            category = (
                "Ticket"
                if b["id"] in rotation.TICKET_BANNERS
                else (
                    "Current event"
                    if b["id"] in events
                    else (
                        "Anniversary"
                        if rotation.family(b["name"])
                        else "Regular" if index < 12 else "Daily general"
                    )
                )
            )
            print(f'{b["id"]}  {category:14}  {b["name"]}')
        return 0
    if args.command == "check":
        return subprocess.run(
            [
                str(ROOT / "runtime/python/bin/python3.10"),
                "-B",
                str(ROOT / "launcher/check_bundle.py"),
            ],
            cwd=ROOT,
        ).returncode
    if not importlib.util.find_spec("unittest"):
        parser.error(
            "This Python lacks unittest. Run this command with a full Python 3 installation, not the minimal game runtime."
        )
    suites = SUITES.values() if args.suite == "all" else [SUITES[args.suite]]
    for folder, *patterns in suites:
        for pattern in patterns:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    folder,
                    "-p",
                    pattern,
                ],
                cwd=ROOT,
            )
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
