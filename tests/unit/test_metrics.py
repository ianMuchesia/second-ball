"""Phase 2a metrics on tiny hand-built matches; every answer worked out by hand
in the comments."""

import pytest

from core.contracts import MatchEvent, PlayerPosition
from core.metrics import METRICS, WINDOWS, Events, compute_all, get, match_state

H, A = "home", "away"


def ev(n, t, team, type_, pid, outcome="success", x=50.0, period=1, **qual):
    minute, second = divmod(t, 60)
    return MatchEvent(
        event_id=f"e{n}",
        match_id="m",
        possession_id=pid,
        period=period,
        minute=minute,
        second=second,
        team_id=team,
        player_id=f"{team}-1",
        type=type_,
        outcome=outcome,
        body_part="foot",
        start_x=x,
        start_y=34.0,
        end_x=x,
        end_y=34.0,
        under_pressure=False,
        qualifiers=qual,
        freeze_frame=[
            PlayerPosition(player_id=f"{team}-1", team_id=team, x=x, y=34, facing_deg=0)
        ],
    )


# 0'00 home pass (p1) ... home keeps it 30 s, away tackles at 0'30, away has it
# 0'30-0'40, a throw-in (dead ball) at 1'00, home shoots and scores at 1'20.
MATCH_A = [
    ev(1, 0, H, "pass", "p1", x=40),
    ev(2, 10, H, "pass", "p1", x=75),  # final third
    ev(3, 20, H, "pass", "p1", outcome="fail", x=80),  # final third
    ev(4, 30, A, "tackle", "p1", x=25),  # in away's frame, x 25 = deep
    ev(5, 32, A, "pass", "p2", x=30),
    ev(6, 40, A, "pass", "p2", outcome="fail", x=35),
    ev(7, 60, H, "throw_in", "p3", x=60),
    ev(8, 70, H, "pass", "p3", x=72),  # final third
    ev(9, 80, H, "shot", "p3", outcome="fail", x=95, xg=0.3),
    ev(10, 80, H, "shot", "p3", outcome="success", x=96, xg=0.25),
]


def events(items=MATCH_A):
    return Events.of((H, A), items)


def val(name, team=None, items=MATCH_A, minutes=None):
    v = get(name).compute(events(items), team, minutes)
    return v and round(v.value, 4)


def ids(name, team=None, items=MATCH_A):
    return get(name).compute(events(items), team).evidence_event_ids


def test_possession_owner_ignores_the_tackle_that_ends_it():
    e = events()
    assert e.owner == {"p1": H, "p2": A, "p3": H}


def test_possession_time_by_hand():
    # In-play gaps: e1-e2 10 H, e2-e3 10 H, e3-e4 10 H, e4-e5 2 H (tackle is in
    # p1, still home's possession), e5-e6 8 A, e6-e7 not counted (throw-in),
    # e7-e8 10 H, e8-e9 10 H, e9-e10 0 H. Home 52 of 60 s.
    assert val("possession_time", H) == round(52 / 60, 4)
    assert val("possession_time", A) == round(8 / 60, 4)
    assert ids("possession_time", A) == ["e5"]


def test_possession_passes_excludes_throw_ins():
    # Passes: home e1 e2 e3 e8 = 4, away e5 e6 = 2. Throw-in e7 not a pass.
    assert val("possession_passes", H) == round(4 / 6, 4)
    assert ids("possession_passes", A) == ["e5", "e6"]


def test_passes_per_possession():
    # Home owns p1 and p3 with 4 passes; away owns p2 with 2.
    assert val("passes_per_possession", H) == 2.0
    assert val("passes_per_possession", A) == 2.0


def test_shots_and_xg():
    assert val("shots", H) == 2
    assert val("xg", H) == 0.55
    assert ids("xg", H) == ["e9", "e10"]
    # Zero still points at the events that were checked.
    assert val("shots", A) == 0
    assert ids("shots", A) == ["e4", "e5", "e6"]


def test_ppda():
    # Away pressing: home open-play passes in home's own 60% (x < 63): e1 only
    # (e2, e3, e8 are higher). Away defensive actions at x > 42 in away's frame:
    # the tackle is at x 25, so none -> undefined.
    assert val("ppda", A) is None
    deep_tackle = [*MATCH_A[:3], ev(4, 30, A, "tackle", "p1", x=60), *MATCH_A[4:]]
    assert val("ppda", A, deep_tackle) == 1.0
    assert ids("ppda", A, deep_tackle) == ["e1", "e4"]


def test_possession_changes_per_minute():
    # Owners in order: p1 H, p2 A, p3 H -> 2 changes over 80 s.
    assert val("possession_changes_per_min") == round(2 / (80 / 60), 4)
    assert ids("possession_changes_per_min") == ["e5", "e7"]


def test_field_tilt():
    # Final-third touches (x >= 70): home passes e2 e3 e8 and shots e9 e10;
    # away none (a tackle is not a touch).
    assert val("field_tilt", H) == 1.0
    assert val("field_tilt", A) == 0.0
    assert ids("field_tilt", H) == ["e2", "e3", "e8", "e9", "e10"]


def test_window_last_minute():
    # Last 1 min = (20 s, 80 s]: e4..e10. Shots still 2; home passes e8 only.
    assert val("shots", H, minutes=1) == 2
    assert val("possession_passes", H, minutes=1) == round(1 / 3, 4)


def test_score_and_clock():
    state = match_state(events())
    assert (state.score.home, state.score.away) == (1, 0)
    assert (state.clock.minute, state.clock.second) == (1, 20)


def test_own_goal_counts_for_the_other_team():
    og = [ev(1, 5, A, "clearance", "p1", outcome="owngoal")]
    assert match_state(events(og)).score.home == 1


def test_second_half_clock_continues_after_first_half_stoppage():
    # First half ends at 46'00; second half restarts at 45'00 = 46 min played.
    items = [ev(1, 46 * 60, H, "pass", "p1"), ev(2, 45 * 60, A, "pass", "p2", period=2)]
    e = events(items)
    assert e.elapsed == [46 * 60, 46 * 60]
    # A gap across half-time is not playing time.
    assert get("possession_time").compute(e, H) is None


def test_every_number_carries_evidence():
    out = compute_all(events())
    assert out[H] and out[A] and out["match"]
    for metrics in out.values():
        for v in metrics.values():
            assert v.evidence_event_ids


def test_registry_declares_everything_once():
    analyst_only = {"possession_changes_per_min", "short_possessions", "loose_balls"}
    for m in METRICS.values():
        assert m.definition and m.unit
        personas = {"analyst"} if m.name in analyst_only else {"analyst", "casual"}
        assert set(m.display_name) == personas, m.name
        assert m.formula.startswith("core.metrics.")
    assert METRICS["ppda"].display_name["casual"] == "How hard they're pressing"
    assert None in WINDOWS and {5, 10, 15} <= set(WINDOWS)


@pytest.mark.parametrize("name", sorted(METRICS))
def test_metrics_are_pure(name):
    e = events()
    m = get(name)
    team = None if m.grain == "match" else H
    assert m.compute(e, team) == m.compute(e, team)
    assert len(e.items) == len(MATCH_A)


def test_rates_carry_numerator_and_denominator():
    # Possession (passes): home 4 of 6 passes.
    v = get("possession_passes").compute(events(), H)
    assert (v.numerator, v.denominator) == (4, 6)
    # Counts are not rates.
    assert get("shots").compute(events(), H).denominator is None
