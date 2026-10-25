"""Run bundles and the broadcast API: judge mode plays a recorded run with no
model calls; evidence in plain words; producer actions are append-only."""

import json

import pytest
from fastapi.testclient import TestClient

from agents.live.record import fake_llm, record
from stream.api import TEST_LABEL, app
from tests.unit.test_narration_report import demo


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    data = demo()
    match_file = root / "match.jsonl"
    match_file.write_text(
        "\n".join(
            [data.match.model_dump_json()]
            + [e.model_dump_json() for e in data.events.items]
        )
    )
    record(match_file, root / "demo", fake_llm())
    return root


@pytest.fixture
def client(runs, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(runs))
    return TestClient(app)


def test_bundle_has_everything_the_screen_needs(runs):
    d = runs / "demo"
    names = {p.name for p in d.iterdir()}
    assert {
        "meta.json",
        "match.json",
        "events.jsonl",
        "moments.jsonl",
        "overlays.jsonl",
        "narrations.jsonl",
        "indicators.jsonl",
        "traces.jsonl",
        "audit.jsonl",
    } <= names
    meta = json.loads((d / "meta.json").read_text())
    assert meta["languages"] == ["en", "sw"]  # shipped languages only
    n = json.loads((d / "narrations.jsonl").read_text().splitlines()[0])
    assert {"verdicts", "insight", "latency_s", "met_target", "trace_id"} <= set(n)


def test_judge_mode_serves_the_run(client):
    r = client.get("/api/runs/demo").json()
    assert r["match"]["lineups"] and r["moments"] and r["indicators"]
    assert all("t" in o for o in r["overlays"])
    events = client.get("/api/runs/demo/events").json()
    assert events[0]["t"] == 0 and events[-1]["t"] > 5000


def test_evidence_in_plain_words_with_absolute_positions(client):
    r = client.get("/api/runs/demo").json()
    (red,) = [m for m in r["moments"] if m["kind"] == "red_card_impact"]
    (e,) = client.get(
        "/api/runs/demo/evidence", params={"ids": ",".join(red["evidence_event_ids"])}
    ).json()
    assert (
        e["words"]
        == "63:22 Ilya Stonebridge (Riverside, left centre-back) fouls: red card."
    )
    assert any(p["player_id"] == "riverside_athletic-5" for p in e["freeze_frame"])


def test_evidence_is_the_move_not_the_metric_windows(client):
    """The smallest set that proves the claim: the possession plus the regain,
    with each metric's window summarised apart, never merged in."""
    r = client.get("/api/runs/demo").json()
    events = {e["event_id"]: e for e in client.get("/api/runs/demo/events").json()}
    (goal,) = [
        m for m in r["moments"] if m["kind"] == "goal" and m["clock"]["minute"] == 34
    ]
    move = goal["move"]
    assert len(move["ids"]) < 20
    first, last = events[move["ids"][0]], events[move["ids"][-1]]
    assert move["regain_id"] == first["event_id"]
    assert first["team_id"] == "harbour_town" and first["type"] in (
        "tackle",
        "interception",
    )
    assert last["type"] == "shot" and last["outcome"] == "success"
    assert set(move["players"]) == {events[i]["player_id"] for i in move["ids"]}
    windows = {
        i for n in goal["metrics_after"].values() for i in n["evidence_event_ids"]
    }
    assert {n["events"] for n in goal["numbers"]} and not windows - set(events)
    # Labels are the registry's names, not the keys: "xG", never "Xg".
    assert {n["label"] for n in goal["numbers"]} == {"xG", "xG of the chance"}

    (red,) = [m for m in r["moments"] if m["kind"] == "red_card_impact"]
    ids = red["move"]["ids"]
    assert len(ids) < 20 and events[ids[-1]]["outcome"] == "red_card"
    assert events[ids[0]]["team_id"] == "harbour_town"  # the team that was fouled
    # The impact compares 10-minute windows: hundreds of events, none in the move.
    assert sum(n["events"] for n in red["numbers"]) > 100
    assert all(n["from_t"] <= n["to_t"] for n in red["numbers"])


def test_unknown_run_or_event_is_404_and_names_are_checked(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2Fetc").status_code == 404
    assert client.get("/api/runs/demo/evidence", params={"ids": "x"}).status_code == 404


def test_producer_actions_append_to_the_audit_log(client):
    oid = client.get("/api/runs/demo").json()["overlays"][0]["overlay_id"]
    for action in ("approve", "reject"):
        r = client.post(
            f"/api/runs/demo/producer/{oid}",
            json={"action": action, "who": "Ian", "reason": "test"},
        )
        assert r.status_code == 200
    audit = client.get("/api/runs/demo/producer").json()["audit"]
    assert [a["action"] for a in audit[-2:]] == ["approve", "reject"]
    assert all(a["who"] == "Ian" and a["at"] for a in audit)
    assert (
        client.post(
            f"/api/runs/demo/producer/{oid}", json={"action": "delete", "who": "Ian"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/runs/demo/producer/{oid}", json={"action": "approve", "who": ""}
        ).status_code
        == 422
    )


def test_injected_test_error_is_labelled_and_rejected_by_the_real_verifier(client):
    r = client.post("/api/runs/demo/inject-test-error", json={"who": "Ian"}).json()
    assert r["label"] == TEST_LABEL
    assert r["injected"] != r["original"] and not r["verdict"]["passed"]
    audit = client.get("/api/runs/demo/producer").json()["audit"]
    assert audit[-1]["action"] == "inject_test_error"


def test_registry_and_detector_rules(client):
    m = client.get("/api/registry/control_index").json()
    assert m["definition"] and m["formula"].startswith("core.metrics")
    rule = client.get("/api/moment-rules/red_card_impact").json()
    assert rule["importance"] == 0.9 and rule["source"] == "core/moments/config.yaml"


def test_run_streams_as_server_sent_events(client):
    with client.stream(
        "GET", "/api/runs/demo/stream", params={"speed": 600, "start": 5600}
    ) as r:
        body = "".join(r.iter_text())
    assert body.startswith("event: meta")
    assert "event: event" in body and body.rstrip().endswith("}")
    assert "event: end" in body


def first_overlay(client):
    return client.get("/api/runs/demo").json()["overlays"][0]["overlay_id"]


def test_a_public_deployment_switches_producer_writes_off(client, monkeypatch):
    monkeypatch.setenv("PRODUCER_WRITES", "off")
    before = len(client.get("/api/runs/demo/producer").json()["audit"])
    oid = first_overlay(client)
    act = {"action": "approve", "who": "someone"}
    assert client.post(f"/api/runs/demo/producer/{oid}", json=act).status_code == 403
    assert client.post("/api/runs/demo/inject-test-error", json={}).status_code == 403
    assert len(client.get("/api/runs/demo/producer").json()["audit"]) == before
    assert client.get("/api/runs/demo").status_code == 200  # reading is open


def test_token_mode_needs_the_right_token(client, monkeypatch):
    monkeypatch.setenv("PRODUCER_WRITES", "token")
    monkeypatch.setenv("PRODUCER_TOKEN", "s3cret-for-test")
    oid = first_overlay(client)
    act = {"action": "approve", "who": "Ian"}
    url = f"/api/runs/demo/producer/{oid}"
    assert client.post(url, json=act).status_code == 401
    assert (
        client.post(url, json=act, headers={"X-Producer-Token": "wrong"}).status_code
        == 401
    )
    ok = client.post(url, json=act, headers={"X-Producer-Token": "s3cret-for-test"})
    assert ok.status_code == 200 and ok.json()["action"] == "approve"
    monkeypatch.setenv("PRODUCER_TOKEN", "")  # no token configured: nobody
    assert (
        client.post(url, json=act, headers={"X-Producer-Token": ""}).status_code == 401
    )


def test_health_says_the_app_can_read_its_runs(client):
    assert client.get("/api/health").json() == {"ok": True, "runs": 1}
