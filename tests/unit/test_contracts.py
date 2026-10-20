import pytest
from pydantic import ValidationError

from core.contracts import Insight, Match, MatchEvent, MatchState, Moment, Overlay

# Synthetic examples only.
EVIDENCE = ["ev-001", "ev-002"]
METRIC = {"value": 0.62, "evidence_event_ids": EVIDENCE}
CLOCK = {"period": 2, "minute": 67, "second": 12}


def freeze_frame(home=11, away=11):
    return [
        {
            "player_id": f"{team}-{n}",
            "team_id": team,
            "x": 10.0 + n,
            "y": 30.0,
            "facing_deg": 0.0,
        }
        for team, count in (("home", home), ("away", away))
        for n in range(count)
    ]


def match():
    return {
        "match_id": "m-001",
        "home_team": "home",
        "away_team": "away",
        "venue": "Synthetic Park",
        "kickoff": "2026-10-24T15:00:00+03:00",
        "competition": "Synthetic League",
        "seed": 42,
        "weather": "rain",
    }


def event():
    return {
        "event_id": "ev-001",
        "match_id": "m-001",
        "possession_id": "p-017",
        "period": 2,
        "minute": 67,
        "second": 12,
        "team_id": "home",
        "player_id": "home-9",
        "type": "pass",
        "outcome": "success",
        "body_part": "foot_right",
        "start_x": 52.5,
        "start_y": 34.0,
        "end_x": 80.0,
        "end_y": 20.0,
        "under_pressure": True,
        "ball_speed_kmh": 54.0,
        "qualifiers": {"through_ball": True},
        "freeze_frame": freeze_frame(),
    }


def state():
    return {
        "score": {"home": 1, "away": 0},
        "clock": CLOCK,
        "metrics": {"home": {"possession": METRIC}, "away": {"possession": METRIC}},
    }


def moment():
    return {
        "moment_id": "mo-001",
        "kind": "red_card_impact",
        "importance": 0.8,
        "metrics_before": {"possession": METRIC},
        "metrics_after": {"possession": METRIC},
        "evidence_event_ids": EVIDENCE,
    }


def insight():
    return {
        "claim": "Home lost control of midfield after the red card.",
        "mechanism": "Ten players left the gap between the lines unguarded.",
        "evidence_event_ids": EVIDENCE,
        "confidence": 0.7,
    }


def overlay():
    return {
        "overlay_id": "ov-001",
        "match_id": "m-001",
        "kind": "metric_card",
        "slot": "lower_third",
        "t_in": {"match": CLOCK, "wall": "2026-10-24T13:07:12Z"},
        "duration_ms": 8000,
        "priority": 1,
        "risk_tier": "low",
        "text": {"en": "Possession since the red card: 62%"},
        "values": {"possession": 0.62},
        "evidence_event_ids": EVIDENCE,
        "status": "pending",
    }


VALID = [
    (Match, match),
    (MatchEvent, event),
    (MatchState, state),
    (Moment, moment),
    (Insight, insight),
    (Overlay, overlay),
]


@pytest.mark.parametrize(
    ("model", "example"), VALID, ids=[m.__name__ for m, _ in VALID]
)
def test_valid_example(model, example):
    parsed = model.model_validate(example())
    assert parsed.schema_version == 1


def with_(example, **changes):
    data = example()
    data.update(changes)
    return data


INVALID = [
    (Match, with_(match, away_team="home"), "same team twice"),
    (MatchEvent, with_(event, start_x=105.1), "x off the 105 m pitch"),
    (
        MatchState,
        with_(state, metrics={"home": {"possession": {"value": 0.5}}}),
        "metric without evidence",
    ),
    (Moment, with_(moment, importance=1.5), "importance above 1"),
    (Insight, with_(insight, evidence_event_ids=[]), "empty evidence"),
    (Overlay, with_(overlay, status="live"), "unknown status"),
]


@pytest.mark.parametrize(
    ("model", "data", "why"),
    INVALID,
    ids=[f"{m.__name__}-{why}" for m, _, why in INVALID],
)
def test_invalid_example(model, data, why):
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_freeze_frame_after_red_card_has_21_players():
    MatchEvent.model_validate(with_(event, freeze_frame=freeze_frame(home=10)))


def test_freeze_frame_rejects_12_players_on_one_team():
    with pytest.raises(ValidationError):
        MatchEvent.model_validate(
            with_(event, freeze_frame=freeze_frame(home=12, away=10))
        )


def test_freeze_frame_rejects_duplicate_player():
    frame = freeze_frame()
    frame[1]["player_id"] = frame[0]["player_id"]
    with pytest.raises(ValidationError):
        MatchEvent.model_validate(with_(event, freeze_frame=frame))


def test_overlay_requires_english_text():
    with pytest.raises(ValidationError):
        Overlay.model_validate(with_(overlay, text={"sw": "Umiliki wa mpira: 62%"}))


def test_match_rejects_unknown_weather():
    with pytest.raises(ValidationError):
        Match.model_validate(with_(match, weather="snow"))


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Match.model_validate(with_(match, xg=0.3))


def test_facing_deg_must_be_below_360():
    frame = freeze_frame()
    frame[0]["facing_deg"] = 360.0
    with pytest.raises(ValidationError):
        MatchEvent.model_validate(with_(event, freeze_frame=frame))


def test_facing_deg_is_required():
    frame = freeze_frame()
    del frame[0]["facing_deg"]
    with pytest.raises(ValidationError):
        MatchEvent.model_validate(with_(event, freeze_frame=frame))
