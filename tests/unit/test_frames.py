"""Frame trap guard: event x is in the ACTING team's frame (SPADL: it attacks
+x), in both halves. A team's touch in its own penalty area is its defensive
third, whichever team and whichever half; the screen's turned-round
coordinates must never reach a metric. Every positional check here runs for
both teams and both halves."""

import pytest

from core.metrics import Events
from core.metrics.basic import field_tilt
from tests.unit.test_phase2c import A, H, event

OWN_BOX_X = 10.0  # inside the team's own penalty area (own frame)
FINAL_THIRD_X = 95.0  # deep in the opponent's half (own frame)


def in_half(e, period):
    return e if period == 1 else e.model_copy(update={"period": 2, "minute": 50})


@pytest.mark.parametrize("period", [1, 2])
@pytest.mark.parametrize(("deep", "camped"), [(H, A), (A, H)])
def test_own_box_touch_is_defensive_for_both_teams_in_both_halves(period, deep, camped):
    events = [
        in_half(event(1, team=deep, at=(OWN_BOX_X, 34.0)), period),
        in_half(event(2, t=3, team=camped, at=(FINAL_THIRD_X, 34.0)), period),
    ]
    ev = Events.of((H, A), events)
    # The team passing in its own box is pinned back: no final-third share.
    assert field_tilt(ev, 0, deep).value == 0.0
    assert field_tilt(ev, 0, camped).value == 1.0


@pytest.mark.parametrize("period", [1, 2])
@pytest.mark.parametrize("team", [H, A])
def test_one_team_in_its_own_box_has_no_final_third_touch(period, team):
    ev = Events.of((H, A), [in_half(event(1, team=team, at=(OWN_BOX_X, 30.0)), period)])
    v = field_tilt(ev, 0, team)
    assert v is None or v.value == 0.0
