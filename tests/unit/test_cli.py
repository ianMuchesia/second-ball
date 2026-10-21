import json

import pyarrow.parquet as pq
import pytest

from core.contracts import Match, MatchEvent
from engine.cli import fixtures, main


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("ds")
    main(
        [
            "generate",
            "--matches",
            "2",
            "--seed",
            "7",
            "--out",
            str(out),
            "--workers",
            "2",
        ]
    )
    return out


def test_files_and_manifest(dataset):
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert manifest["matches"] == 2 and manifest["synthetic"] is True
    assert manifest["mode"] == "free_simulation"
    assert len(list((dataset / "jsonl").glob("*.jsonl"))) == 2


def test_parquet_matches_jsonl(dataset):
    matches = pq.read_table(dataset / "matches.parquet").to_pylist()
    events = pq.read_table(dataset / "events.parquet").to_pylist()
    assert len(matches) == 2
    assert sum(m["events"] for m in matches) == len(events)
    first = matches[0]
    lines = (dataset / "jsonl" / f"{first['match_id']}.jsonl").read_text().splitlines()
    assert Match.model_validate_json(lines[0]).seed == 7
    from_jsonl = MatchEvent.model_validate_json(lines[1])
    row = next(e for e in events if e["event_id"] == from_jsonl.event_id)
    row["qualifiers"] = json.loads(row["qualifiers"])
    assert MatchEvent.model_validate(row) == from_jsonl


def test_same_arguments_same_data(dataset, tmp_path):
    main(
        [
            "generate",
            "--matches",
            "2",
            "--seed",
            "7",
            "--out",
            str(tmp_path),
            "--no-jsonl",
        ]
    )
    for name in ("matches.parquet", "events.parquet"):
        assert pq.read_table(tmp_path / name).equals(pq.read_table(dataset / name))
    assert not (tmp_path / "jsonl").exists()


def test_mixed_weather_is_seeded():
    a = fixtures(12, 7, "mixed")
    assert a == fixtures(12, 7, "mixed")
    assert len({w for *_, w in a}) > 1


def test_rejects_zero_matches(tmp_path):
    with pytest.raises(SystemExit):
        main(["generate", "--matches", "0", "--seed", "1", "--out", str(tmp_path)])
