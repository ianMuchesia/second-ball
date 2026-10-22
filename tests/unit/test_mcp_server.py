"""Football MCP server: each tool on the demo match, and nothing can write."""

import asyncio
import inspect

import psycopg
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from agents.mcp_server import TOOLS, MatchData, build
from agents.mcp_server.data import read_only
from engine.generate import main as generate
from stream.interpreter.store import Store

R, HT = "riverside_athletic", "harbour_town"


@pytest.fixture(scope="module")
def demo_file(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    generate(["--demo", "--out", str(out)])
    return out / "match.jsonl"


@pytest.fixture(scope="module")
def data(demo_file):
    return MatchData.from_file(demo_file)


@pytest.fixture(scope="module")
def server(data):
    return build(data)


def call(server, tool, /, **args):
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error
    return result.structured_content


def test_exactly_the_read_only_tools(server):
    tools = asyncio.run(server.list_tools())
    assert sorted(t.name for t in tools) == sorted(TOOLS)
    for t in tools:
        ann = t.annotations
        assert ann.read_only_hint and not ann.destructive_hint, t.name
        params = set(t.input_schema.get("properties", {}))
        assert not params & {"query", "sql", "statement", "code"}, t.name


def test_get_metric(server, data):
    out = call(server, "get_metric", name="ppda", team=HT, window="10")
    assert out["value"] == pytest.approx(out["numerator"] / out["denominator"])
    assert out["evidence_event_ids"]
    assert set(out["evidence_event_ids"]) <= set(data.by_id)
    match = call(server, "get_metric", name="momentum")
    assert match["team"] is None and match["evidence_event_ids"]


def refused(server, tool, why, **args):
    with pytest.raises(ToolError) as err:
        call(server, tool, **args)
    assert why in str(err.value.__cause__)


def test_get_metric_rejects_bad_requests(server):
    refused(server, "get_metric", "unknown metric", name="drop table", team=R)
    refused(server, "get_metric", "needs team", name="shots")
    refused(
        server,
        "get_metric",
        "supports windows",
        name="control_index",
        team=R,
        window="match",
    )


def test_compare_windows(server):
    out = call(
        server, "compare_windows", metric_name="xg", team=HT, a=[0, 30], b=[30, 40]
    )
    # Harbour's first goal (34') is a counter in the second window.
    assert out["value_b"] > out["value_a"]
    assert out["change"] == pytest.approx(out["value_b"] - out["value_a"])
    assert out["evidence_event_ids_b"]


def test_get_sequence(server, data):
    centre = data.events.items[100].event_id
    out = call(server, "get_sequence", event_id=centre, before=3, after=2)
    ids = [e["event_id"] for e in out["events"]]
    assert ids == [e.event_id for e in data.events.items[97:103]]
    assert out["evidence_event_ids"] == ids
    with pytest.raises(ToolError):
        call(server, "get_sequence", event_id=centre, before=50)


def test_get_freeze_frame(server, data):
    e = data.events.items[10]
    out = call(server, "get_freeze_frame", event_id=e.event_id)
    assert len(out["players"]) == len(e.freeze_frame)
    assert 0 <= out["pressure"] <= 1 and 0 <= out["risk"] <= 1
    assert out["evidence_event_ids"] == [e.event_id]


def test_get_player_context(server, data):
    shooter = next(e for e in data.events.items if e.type == "shot").player_id
    out = call(server, "get_player_context", player_id=shooter)
    mine = [e for e in data.events.items if e.player_id == shooter]
    assert out["shots"] == sum(e.type == "shot" for e in mine)
    assert out["evidence_event_ids"] == [e.event_id for e in mine]
    refused(server, "get_player_context", "unknown player_id", player_id="nobody")


def test_list_moments(server):
    late = call(server, "list_moments", since_minute=85)["moments"]
    assert late and all(m["clock"]["minute"] >= 85 for m in late)
    assert any(m["kind"] == "goal" for m in late)  # Harbour's 88' goal
    assert all(m["evidence_event_ids"] for m in late)


def test_tools_never_change_the_data(server, data):
    before = [e.model_dump() for e in data.events.items]
    for tool, args in [
        ("get_metric", {"name": "xg", "team": R}),
        ("list_moments", {}),
        ("get_freeze_frame", {"event_id": data.events.items[5].event_id}),
    ]:
        call(server, tool, **args)
    assert [e.model_dump() for e in data.events.items] == before


def test_no_tool_function_has_a_writer():
    src = inspect.getsource(build)
    for word in ("insert", "update ", "delete", "save_state", "record_event", "write"):
        assert word not in src.lower(), word


def test_postgres_source_is_read_only(demo_file, database_url):
    # The interpreter writes a match; the MCP server's connection cannot.
    data = MatchData.from_file(demo_file)
    store = Store(database_url)
    store.record_match(data.match)
    for e in data.events.items[:50]:
        store.record_event(e)
    store.close()
    loaded = MatchData.from_postgres(database_url)
    assert loaded.match == data.match and len(loaded.events.items) == 50
    with (
        read_only(database_url) as conn,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        conn.execute("delete from interpreter_events")
