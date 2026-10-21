import collections
import copy
import math
import time

import pytest
import yaml
from pydantic import ValidationError

from engine.core import score, simulate_match
from engine.core.pitch import LENGTH, WIDTH
from engine.core.sim import load_config
from engine.league import CLUBS_DIR, ClubProfile, load_league
from engine.weather import load_weather

LEAGUE = load_league()


def sample(seed=7, weather="dry", config=None, home="ashgrove", away="ironvale"):
    return simulate_match(
        LEAGUE[home], LEAGUE[away], seed, weather=weather, config=config
    )


@pytest.fixture(scope="module")
def match():
    return sample()


@pytest.fixture(scope="module")
def red_card_match():
    cfg = load_config()
    cfg["challenges"]["foul"] = 0.5
    cfg["challenges"]["red_per_foul"] = 1.0
    return sample(seed=3, config=cfg)


# ---- league and weather -----------------------------------------------------


def test_league_has_nine_clubs_and_skips_template():
    assert len(LEAGUE) == 9
    assert "kilele_chui" in LEAGUE
    assert "riverside_athletic" in LEAGUE
    assert (CLUBS_DIR / "_template.yaml").exists()


def test_club_knob_out_of_range_is_rejected():
    raw = yaml.safe_load((CLUBS_DIR / "ashgrove.yaml").read_text())
    raw["target_ppda"] = 50
    with pytest.raises(ValidationError):
        ClubProfile.model_validate(raw)


def test_club_shape_must_have_ten_outfield_players():
    raw = yaml.safe_load((CLUBS_DIR / "ashgrove.yaml").read_text())
    raw["formation"] = "4-4-3"
    with pytest.raises(ValidationError):
        ClubProfile.model_validate(raw)


def test_weather_config_covers_every_weather():
    assert set(load_weather()) == {"dry", "rain", "wind", "heat"}


# ---- determinism ------------------------------------------------------------


def dump(sim_match):
    return sim_match.match.model_dump(), [e.model_dump() for e in sim_match.events]


def test_same_seed_gives_identical_match(match):
    assert dump(sample()) == dump(match)


def test_different_seed_gives_different_match(match):
    assert dump(sample(seed=8)) != dump(match)


def test_match_records_weather_and_seed():
    m = sample(weather="rain")
    assert (m.match.weather, m.match.seed) == ("rain", 7)


# ---- freeze frames ----------------------------------------------------------


def test_every_frame_has_22_players_without_red_cards(match):
    assert not any(e.outcome == "red_card" for e in match.events)
    assert all(len(e.freeze_frame) == 22 for e in match.events)


def test_red_card_removes_a_player_from_later_frames(red_card_match):
    reds = 0
    for e in red_card_match.events:
        assert len(e.freeze_frame) == 22 - reds
        per_team = collections.Counter(p.team_id for p in e.freeze_frame)
        assert max(per_team.values()) <= 11
        if e.outcome == "red_card":
            reds += 1
    assert reds >= 1
    assert any(len(e.freeze_frame) == 21 for e in red_card_match.events)


def test_sent_off_player_never_appears_again(red_card_match):
    gone = set()
    for e in red_card_match.events:
        assert not gone & {p.player_id for p in e.freeze_frame}
        assert e.player_id not in gone
        if e.outcome == "red_card":
            gone.add(e.player_id)


def test_no_position_off_the_pitch(match, red_card_match):
    for e in match.events + red_card_match.events:
        points = [(e.start_x, e.start_y), (e.end_x, e.end_y)]
        points += [(p.x, p.y) for p in e.freeze_frame]
        assert all(0 <= x <= LENGTH and 0 <= y <= WIDTH for x, y in points)


def test_under_pressure_follows_ians_2m_rule(match):
    for e in match.events:
        me = next(p for p in e.freeze_frame if p.player_id == e.player_id)
        nearest = min(
            math.hypot(p.x - me.x, p.y - me.y)
            for p in e.freeze_frame
            if p.team_id != e.team_id
        )
        assert e.under_pressure == (nearest <= 2.0)


def test_events_are_in_time_order(match):
    times = [(e.period, e.minute * 60 + e.second) for e in match.events]
    assert times == sorted(times)


# ---- match flow -------------------------------------------------------------


def test_score_and_volume_are_plausible(match):
    counts = collections.Counter(e.type for e in match.events)
    assert 800 < len(match.events) < 2500
    assert counts["pass"] > 400
    assert sum(score(match)) <= 10
    assert {1, 2} == {e.period for e in match.events}


def test_rain_makes_more_loose_balls_than_dry():
    def bad_touches(weather):
        return sum(
            e.type == "bad_touch"
            for s in range(5)
            for e in sample(seed=s, weather=weather).events
        )

    assert bad_touches("rain") > bad_touches("dry")


def test_config_is_not_mutated_by_a_run():
    cfg = load_config()
    before = copy.deepcopy(cfg)
    sample(config=cfg)
    assert cfg == before


def test_sample_match_finishes_in_under_5_seconds():
    start = time.perf_counter()
    sample(seed=11, weather="heat", home="saltmere", away="quarry_end")
    assert time.perf_counter() - start < 5
