"""The analyser must see events only: no engine internals in events, and no
analyser code (core/, stream/, agents/) that can reach the engine or its truth."""

import ast
from pathlib import Path

from engine.core import simulate_match
from engine.core.sim import FEED_QUALIFIERS
from engine.league import load_league
from engine.scenarios import load_scenario

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = load_league()
ENGINE_ONLY = {
    "counter",
    "channel",
    "last_man",
    "lines_broken",
    "scenario_beat",
    "mode",
    "threat",
}


def matches():
    sc = load_scenario("demo_riverside_harbour")
    scripted = simulate_match(
        LEAGUE[sc.home], LEAGUE[sc.away], sc.seed, weather=sc.weather, scenario=sc
    )
    free = simulate_match(LEAGUE["harbour_town"], LEAGUE["riverside_athletic"], 9)
    return scripted, free


def test_events_carry_only_feed_qualifiers():
    for m in matches():
        for e in m.events:
            assert set(e.qualifiers) <= FEED_QUALIFIERS, e.qualifiers
            dumped = e.model_dump_json()
            for word in ENGINE_ONLY:
                assert f'"{word}"' not in dumped, (word, e.event_id)


def test_engine_labels_are_kept_in_the_truth_sidecar():
    scripted, free = matches()
    assert any("scenario_beat" in t for t in scripted.truth)
    assert any("channel" in t for t in free.truth)
    ids = {e.event_id for e in scripted.events}
    assert all(t["event_id"] in ids for t in scripted.truth)


def imports_and_strings(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_analyser_code_cannot_reach_the_engine():
    for folder in ("core", "stream", "agents"):
        for path in (ROOT / folder).rglob("*.py"):
            for name in imports_and_strings(path):
                assert not name.startswith("engine"), (path, name)
                assert "engine_truth" not in name, (path, name)
