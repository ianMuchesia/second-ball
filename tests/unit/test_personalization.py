"""Phase 5: personalization changes selection and wording, never facts.

Same insight and facts for every persona; every persona's wording passes the
Verifier; a favourite club changes order, not content; player cards, recaps
and pinned metrics come from code with their evidence."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agents.live.record import fake_llm, record
from agents.pipeline.facts import context_at
from agents.pipeline.player_recap import player_recap
from stream.api import app, favourite_first
from tests.unit.test_api import runs  # noqa: F401  (the recorded fake bundle)
from tests.unit.test_narration_report import demo

HOME, AWAY = "riverside_athletic", "harbour_town"


@pytest.fixture
def client(runs, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RUNS_DIR", str(runs))
    return TestClient(app)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out = tmp_path_factory.mktemp("runs") / "p5"
    data = demo()
    f = out.parent / "match.jsonl"
    f.write_text(
        "\n".join(
            [data.match.model_dump_json()]
            + [e.model_dump_json() for e in data.events.items]
        )
    )
    record(f, out, fake_llm())
    return out


def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_the_same_moment_has_identical_facts_for_every_persona(bundle):
    by_moment: dict[str, dict] = {}
    for n in rows(bundle / "narrations.jsonl"):
        if n.get("task"):
            by_moment.setdefault(n["task"]["moment"]["moment_id"], {})[n["persona"]] = n
    pairs = [x for x in by_moment.values() if len(x) == 2]
    assert len(pairs) >= 7
    for p in pairs:
        fan, analyst = p["casual"], p["analyst"]
        for key in ("moment", "context", "facts", "counts"):
            assert fan["task"][key] == analyst["task"][key], key
        assert fan["insight"] == analyst["insight"]  # one insight per moment
        # Only the wording differs, and each persona's passed the Verifier.
        assert fan["verdicts"][-1]["passed"] or fan["fallback"]
        assert analyst["verdicts"][-1]["passed"] or analyst["fallback"]


def test_a_favourite_club_changes_order_not_content():
    b = {
        "moments": [
            {"moment_id": "m1", "team": HOME},
            {"moment_id": "m2", "team": AWAY},
            {"moment_id": "m3", "team": AWAY},
        ],
        "events": [],
        "t": {},
    }

    def o(mid, priority, t):
        return {"overlay_id": f"{mid}-casual", "priority": priority, "aired_t": t}

    queue = [o("m1", 90, 10.0), o("m2", 90, 20.0), o("m3", 100, 30.0)]
    plain = favourite_first(queue, None, b)
    fav = favourite_first(queue, AWAY, b)
    fav_home = favourite_first(queue, HOME, b)
    ids = lambda xs: [x["overlay_id"][:2] for x in xs]
    assert sorted(map(json.dumps, fav)) == sorted(map(json.dumps, plain))
    assert ids(plain) == ["m3", "m1", "m2"]  # most important first, then earliest
    assert ids(fav) == ["m3", "m2", "m1"]  # within priority 90, Harbour first
    assert ids(fav_home) == ["m3", "m1", "m2"]  # never above a higher tier


def test_player_card_api(client):
    card = client.get("/api/runs/demo/players/harbour_town-8").json()
    assert card["group"] == "midfielder" and card["player"]["name"] == "Matthias Quill"
    stats = {s["name"]: s for s in card["stats"]}
    assert [n for n, s in stats.items() if s["fan"]] == [
        "passes_completed",
        "interceptions",
        "tackles",
    ]
    pct = stats["pass_pct"]["snapshots"][-1]
    assert pct["interval"][0] < pct["value"] < pct["interval"][1]
    # Every number that is not zero has the events behind it.
    for s in card["stats"]:
        if s["snapshots"] and s["snapshots"][-1]["value"]:
            assert s["events"] and all(e["event_ids"] for e in s["events"])
    assert card["touches"] and set(card["omitted"]) == {"headers", "distance_covered"}
    assert client.get("/api/runs/demo/players/nobody").status_code == 404


def test_a_pinned_metric_at_any_moment(client):
    r = client.get("/api/runs/demo/metrics/pass_accuracy", params={"t": 2100}).json()
    v = r["values"][HOME]
    assert v["interval"][0] < v["value"] < v["interval"][1]
    assert v["evidence_event_ids"] and v["events"] >= len(v["evidence_event_ids"])
    time_share = client.get(
        "/api/runs/demo/metrics/possession_time", params={"t": 2100}
    )
    assert time_share.json()["values"][HOME]["interval"] is None  # seconds, not k of n
    assert client.get("/api/runs/demo/metrics/nope", params={"t": 1}).status_code == 404
    names = {m["name"] for m in client.get("/api/registry").json()}
    assert "xg" in names and "pressure" not in names  # per-event ones not pinnable


def test_every_player_recap_is_verified_in_both_languages(bundle):
    recaps = rows(bundle / "player_recaps.jsonl")
    assert len(recaps) == 22 * 2 * 2
    assert all(r["passed"] and {"en", "sw"} <= set(r["text"]) for r in recaps)
    fan = {(r["player_id"], r["when"]): r for r in recaps if r["persona"] == "casual"}
    for r in recaps:
        if r["persona"] == "analyst":  # the analyst's card has every fan stat
            assert set(fan[(r["player_id"], r["when"])]["values"]) <= set(r["values"])


def test_a_model_written_player_recap_passes_the_verifier():
    data = demo()
    p = next(x for x in data.match.lineups if x.name == "Matthias Quill")
    ctx = context_at(data, data.moments[-1])
    out = asyncio.run(
        player_recap(fake_llm(), "full_time", data.events, ctx, p, "analyst", ["sw"])
    )
    assert out["passed"] and not out["fallback"] and {"en", "sw"} <= set(out["text"])
