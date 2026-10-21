import json

import pytest
from pydantic import ValidationError

from engine.core import score, simulate_match
from engine.generate import main as generate
from engine.league import load_league
from engine.scenarios import Beat, expected_moments, load_scenario

LEAGUE = load_league()
DEMO = load_scenario("demo_riverside_harbour")


def play(scenario=DEMO):
    return simulate_match(
        LEAGUE[scenario.home],
        LEAGUE[scenario.away],
        scenario.seed,
        weather=scenario.weather,
        kickoff=scenario.kickoff,
        scenario=scenario,
    )


@pytest.fixture(scope="module")
def demo():
    return play()


def goals(m):
    return [e for e in m.events if e.type.startswith("shot") and e.outcome == "success"]


def test_demo_has_exactly_the_scripted_goals(demo):
    assert score(demo) == (0, 2)
    scored = goals(demo)
    assert [(e.team_id, e.qualifiers["scenario_beat"]) for e in scored] == [
        ("harbour_town", "counter_goal_34"),
        ("harbour_town", "counter_goal_88"),
    ]
    assert 34 <= scored[0].minute <= 35
    assert 88 <= scored[1].minute <= 89


def test_demo_has_exactly_one_red_card_at_63_for_riverside_lcb(demo):
    reds = [e for e in demo.events if e.outcome == "red_card"]
    assert len(reds) == 1
    red = reds[0]
    assert 63 <= red.minute <= 64
    assert red.team_id == "riverside_athletic"
    lcb = next(p for p in LEAGUE["riverside_athletic"].players if p.role == "LCB")
    assert red.player_id == f"riverside_athletic-{lcb.number}"
    assert red.qualifiers["last_man"] is True


def test_riverside_play_with_ten_after_the_red_card(demo):
    red_at = next(i for i, e in enumerate(demo.events) if e.outcome == "red_card")
    for e in demo.events[red_at + 1 :]:
        riverside = [p for p in e.freeze_frame if p.team_id == "riverside_athletic"]
        assert len(riverside) == 10


def test_counters_go_behind_riversides_left_back(demo):
    lb = next(p for p in LEAGUE["riverside_athletic"].players if p.role == "LB")
    lb_id = f"riverside_athletic-{lb.number}"
    scripted = [
        e
        for e in demo.events
        if e.qualifiers.get("channel") and "scenario_beat" in e.qualifiers
    ]
    assert len(scripted) == 4  # 34', 50-60', 63', 88'
    for e in scripted:
        assert e.qualifiers["channel"] == "behind_left_fullback"
        full_back = next(p for p in e.freeze_frame if p.player_id == lb_id)
        # Harbour's frame: Riverside's goal is at x = 105, so behind = larger x.
        assert e.end_x > full_back.x


def test_second_counter_is_a_chance_not_a_goal(demo):
    shots = [
        e
        for e in demo.events
        if e.qualifiers.get("scenario_beat") == "counter_chance_50_60"
        and e.type == "shot"
    ]
    assert len(shots) == 1 and shots[0].outcome == "fail"
    assert 50 <= shots[0].minute <= 60


def test_same_seed_same_scenario_match(demo):
    again = play()
    assert again.match == demo.match
    assert [e.model_dump() for e in again.events] == [
        e.model_dump() for e in demo.events
    ]


def test_match_records_its_mode(demo):
    assert demo.match.mode == "scenario"
    free = simulate_match(LEAGUE["harbour_town"], LEAGUE["saltmere"], 3)
    assert free.match.mode == "free_simulation"


def test_expected_moments_answer_key(demo):
    key = expected_moments(DEMO, demo.match)
    assert key["mode"] == "scenario"
    assert key["match_id"] == demo.match.match_id
    goal_keys = [m for m in key["moments"] if m["kind"] == "goal"]
    assert [m["minute"] for m in goal_keys] == [[34, 35], [88, 89]]
    assert {m["team"] for m in key["moments"]} <= {
        "riverside_athletic",
        "harbour_town",
        None,
    }


def test_generate_writes_match_and_answer_key(tmp_path):
    generate(["--demo", "--out", str(tmp_path)])
    lines = (tmp_path / "match.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["mode"] == "scenario"
    key = json.loads((tmp_path / "expected_moments.json").read_text())
    assert key["scenario"] == "demo_riverside_harbour"


def test_harbour_go_behind_the_full_back_in_free_play_too():
    free = simulate_match(LEAGUE["harbour_town"], LEAGUE["saltmere"], 4)
    channel = [e for e in free.events if e.qualifiers.get("channel")]
    assert channel
    assert {e.team_id for e in channel} == {"harbour_town"}
    assert all("scenario_beat" not in e.qualifiers for e in free.events)


def test_missed_beat_is_an_error():
    late = DEMO.model_copy(
        update={
            "beats": [
                Beat(id="never", minute=(95, 95), action="counter_goal", team="away")
            ]
        }
    )
    with pytest.raises(RuntimeError, match="never"):
        play(late)


def test_red_card_beat_needs_a_role():
    with pytest.raises(ValidationError):
        Beat(id="x", minute=(63, 64), action="red_card_last_man", team="home")
