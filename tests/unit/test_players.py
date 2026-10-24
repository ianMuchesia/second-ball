"""Player cards (Phase 5): every stat is counted from events the engine really
produces, no stat is shown without an event source, omissions are
documented, and rates carry a correct Wilson interval."""

from pathlib import Path

import pytest

from core.metrics import Events
from core.players import (
    STATS,
    card_stats,
    config,
    contributions,
    group_of,
    snapshots,
    total,
    wilson,
)
from engine.core.sim import simulate_match
from engine.league import load_league
from tests.unit.test_narration_report import demo

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def free_matches():
    league = load_league()
    return [
        simulate_match(league["ashgrove"], league["ironvale"], seed)
        for seed in (1, 2, 3)
    ]


def offered() -> set[str]:
    return {n for g in config()["groups"].values() for n in g["fan"] + g["analyst"]}


def test_every_offered_stat_has_events_the_engine_produces(free_matches):
    produced = {e.type for r in free_matches for e in r.events}
    for name in offered():
        assert STATS[name].sources & produced, name
    # And each one actually counts something in free play.
    seen = set()
    for r in free_matches:
        ev = Events.for_match(r.match, r.events)
        for p in r.match.lineups:
            parts = contributions(ev, p.player_id, p.team_id)
            seen |= {n for n in offered() if parts[n]}
    assert seen == offered(), offered() - seen


def test_no_stat_is_shown_without_an_event_source():
    data = demo()
    ev = data.events
    by_id = {e.event_id: e for e in ev.items}
    for p in data.match.lineups:
        parts = contributions(ev, p.player_id, p.team_id)
        for name in card_stats(p.position, "analyst"):
            row = total(STATS[name], parts[name])
            if row["value"]:
                assert row["evidence_event_ids"], (p.name, name)
                types = {by_id[i].type for i in row["evidence_event_ids"]}
                assert types <= STATS[name].sources, (p.name, name, types)


def test_omitted_stats_are_never_offered_and_are_documented():
    omitted = set(config()["omitted"])
    assert omitted == {"headers", "distance_covered"}
    assert not omitted & offered() and not omitted & set(STATS)
    sheet = (ROOT / "docs" / "DATASHEET.md").read_text()
    assert "Distance covered" in sheet and "Headers" in sheet


def test_cards_by_position_fan_top_three():
    assert group_of("ST") == group_of("LM") == "attacker"
    assert group_of("DM") == group_of("RCM") == "midfielder"
    assert group_of("RWB") == group_of("CB") == "defender"
    assert card_stats("ST", "casual") == ["goals", "shots", "chances_created"]
    assert card_stats("GK", "casual") == ["saves", "goals_conceded"]
    assert len(card_stats("RCM", "analyst")) == 6


def test_wilson_interval():
    lo, hi = wilson(14, 18)
    assert (round(lo, 2), round(hi, 2)) == (0.55, 0.91)
    assert wilson(0, 0) is None
    assert wilson(18, 18)[1] == 1.0


def test_the_34th_minute_goal_and_its_chance():
    data = demo()
    ev = data.events
    fenmore = next(p for p in data.match.lineups if p.name == "Lars Fenmore")
    quill = next(p for p in data.match.lineups if p.name == "Matthias Quill")
    f = contributions(ev, fenmore.player_id, fenmore.team_id)
    q = contributions(ev, quill.player_id, quill.team_id)
    goal = next(c for c in f["goals"])
    assert ev.items[goal.index].minute == 34
    # Quill's pass found Fenmore, who carried and scored: a chance, an assist.
    assert any(ev.items[c.index].minute == 34 for c in q["assists"])
    assert any(ev.items[c.index].minute == 34 for c in q["chances_created"])


def test_snapshots_end_at_the_total():
    data = demo()
    ev = data.events
    p = next(p for p in data.match.lineups if p.name == "Matthias Quill")
    parts = contributions(ev, p.player_id, p.team_id)
    for name in ("passes_completed", "pass_pct"):
        snaps = snapshots(STATS[name], parts[name], ev.elapsed)
        assert [s["t"] for s in snaps] == sorted(s["t"] for s in snaps)
        end = total(STATS[name], parts[name])
        assert snaps[-1]["value"] == end["value"]
        assert snaps[-1]["interval"] == end["interval"]
