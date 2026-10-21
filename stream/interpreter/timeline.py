"""Minute-by-minute metric timeline (CSV) for one match.

Rebuilt from the stored events with the same core.metrics code the live
interpreter uses, so it shows exactly the numbers MatchState had at the end of
each minute. Goals and red cards (events too) are added as markers.
"""

import csv
from pathlib import Path

from core.metrics import Events, compute_all
from core.metrics.events import is_goal

FIELDS = ["minute", "clock", "period", "owner", "metric", "value", "evidence_count"]


def rows(events: Events):
    """One row per (minute, owner, metric); minute = elapsed match minutes."""
    walk = Events(teams=events.teams)
    out = []

    def snapshot():
        last = walk.items[-1]
        minute = int(walk.now() // 60)
        for owner, metrics in compute_all(walk).items():
            for name, v in metrics.items():
                out.append(
                    {
                        "minute": minute,
                        "clock": f"{last.minute}:{last.second:02d}",
                        "period": last.period,
                        "owner": owner,
                        "metric": name,
                        "value": round(v.value, 4),
                        "evidence_count": len(v.evidence_event_ids),
                    }
                )

    for i, e in enumerate(events.items):
        walk.append(e)
        marker = (
            "goal" if is_goal(e) else "red_card" if e.outcome == "red_card" else None
        )
        if marker:
            scorer = walk.opponent(e.team_id) if e.outcome == "owngoal" else e.team_id
            out.append(
                {
                    "minute": walk.now() / 60,
                    "clock": f"{e.minute}:{e.second:02d}",
                    "period": e.period,
                    "owner": scorer,
                    "metric": marker,
                    "value": 1,
                    "evidence_count": 1,
                }
            )
        nxt = events.elapsed[i + 1] if i + 1 < len(events.items) else None
        if nxt is None or int(nxt // 60) != int(walk.now() // 60):
            snapshot()
    return out


def write_timeline(events: Events, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows(events))
