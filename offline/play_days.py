"""Observed local calendar days, persisted with each player's save."""

# Reading guide: Local attendance: record observed calendar days and update matching
# monthly login goals.
# Editing notes: A login records the day actually observed; reopening repeatedly must
# not count extra days.
# Checks: offline/test_play_days.py.
# Project navigation: docs/README.md and docs/05-source-guide.md.

import copy, datetime, hashlib, time, functools
from save_store import pack, copy_state


@functools.lru_cache(maxsize=1)
def monthly_login_goals():
    """Read the original monthly attendance goals eligible for local day tracking."""
    import rebuild_master as m
    from build_gacha import value

    b = m.table("achievement")
    return {
        value(b, r, 0): value(b, r, 9)
        for r in m.rows(b)
        if value(b, r, 2) == 8 and value(b, r, 4) == 3105
    }


def record(store, now=None, login=False):
    """Persist an observed local day once and update matching login progress."""
    now = time.time() if now is None else now
    today = datetime.datetime.fromtimestamp(now).date().isoformat()
    with store.lock:
        rows = store.state["tables"].get("UserStatus", [])
        if not rows:
            return {}
        state = copy_state(
            store.state,
            ("UserStatus", "UserAchievement"),
            ("playDays", "monthlyPlayDays"),
        )
        status = state["tables"]["UserStatus"][0]
        if (
            "playDays" not in state
            and status.get("totalLoginDays", 0) > 0
            and status.get("lastLoginedDateAt", 0) > 0
        ):
            prior = (
                datetime.datetime.fromtimestamp(status["lastLoginedDateAt"])
                .date()
                .isoformat()
            )
            if prior <= today:
                state["playDays"] = {
                    "baseline": status["totalLoginDays"] - 1,
                    "dates": [prior],
                    "lastObservedDay": prior,
                    "streak": max(1, status.get("continuousLogin", 0)),
                }
        meta = state.setdefault(
            "playDays",
            {
                "baseline": max(0, status.get("totalLoginDays", 0)),
                "dates": [],
                "lastObservedDay": None,
                "streak": max(0, status.get("continuousLogin", 0)),
            },
        )
        dates = meta["dates"]
        previous = meta["lastObservedDay"]
        if today not in dates and (previous is None or today > previous):
            dates.append(today)
            dates.sort()
            if previous is None or today > previous:
                gap = (
                    (
                        datetime.date.fromisoformat(today)
                        - datetime.date.fromisoformat(previous)
                    ).days
                    if previous
                    else None
                )
                meta["streak"] = meta["streak"] + 1 if gap == 1 else 1
                meta["lastObservedDay"] = today
        status["totalLoginDays"] = meta["baseline"] + len(dates)
        status["continuousLogin"] = meta["streak"]
        status["totalLogin"] = max(
            status.get("totalLogin", 0), status["totalLoginDays"]
        )
        # Keep the greatest observed day on backward clock changes.
        day = meta["lastObservedDay"]
        midnight = int(
            datetime.datetime.combine(
                datetime.date.fromisoformat(day), datetime.time()
            ).timestamp()
        )
        status["lastLoginedDateAt"] = midnight
        if login or not meta.get("lastLoginAt"):
            meta["previousLoginDayAt"] = meta.get("lastLoginDayAt", 0)
            meta["lastLoginDayAt"] = midnight
            meta["lastLoginAt"] = max(meta.get("lastLoginAt", 0), int(now))
        status["lastLoginedAt"] = meta["lastLoginAt"]
        # Monthly quests begin with the first day observed by this counter,
        # including today, rather than days elapsed since that first login.
        month = today[:7]
        monthly = state.setdefault("monthlyPlayDays", {"month": month, "dates": []})
        if month > monthly["month"]:
            monthly.update(month=month, dates=[])
        if month == monthly["month"] and today not in monthly["dates"]:
            monthly["dates"].append(today)
            monthly["dates"].sort()
        count = len(monthly["dates"])
        goals = monthly_login_goals()
        for row in state["tables"].get("UserAchievement", []):
            target = goals.get(row["achievementId"])
            if target is None or month != monthly["month"]:
                continue
            reset_month = (
                datetime.datetime.fromtimestamp(row.get("lastResetAt", 0))
                .date()
                .isoformat()[:7]
            )
            if row.get("state") == 4 and reset_month == month:
                continue
            row["progressParam"] = count
            row["state"] = 3 if count >= target else 2
            row["completedAt"] = (
                row.get("completedAt", 0) or int(now) if count >= target else 0
            )
            row["lastResetAt"] = int(
                datetime.datetime.combine(
                    datetime.date.fromisoformat(month + "-01"), datetime.time()
                ).timestamp()
            )
        changed = {}
        for table in ("UserStatus", "UserAchievement"):
            table_rows = state["tables"].get(table, [])
            if table_rows:
                state["tokens"][table] = hashlib.md5(pack(table_rows)).hexdigest()
                changed[table] = copy.deepcopy(table_rows)
        if state != store.state:
            store._write(state)
        return changed
