import yaml

from evals.realism.fetch_reference import OUT as REFERENCE
from evals.realism.fetch_reference import football_data_league
from evals.realism.report import ORDER, fixtures, metric_values, summarise, verdict

REF = yaml.safe_load(REFERENCE.read_text())


def test_every_metric_has_a_sourced_band_or_says_no_reference():
    assert set(REF["metrics"]) == set(ORDER)
    for name, m in REF["metrics"].items():
        if m["status"] == "ok":
            lo, hi = m["band"]
            assert lo == min(m["per_league"].values()), name
            assert hi == max(m["per_league"].values()), name
            assert m["sources"], name
            for src in m["sources"]:
                assert src["url"].startswith("https://"), name
                assert src["accessed"], name
        else:
            assert m["status"] == "no_reference" and m["reason"], name


def test_football_data_parsing_skips_incomplete_rows():
    header = "Div,HomeTeam,AwayTeam,FTHG,FTAG,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR\n"
    full = "X,A,B,2,1,10,8,4,3,11,12,5,4,2,1,0,0\n"
    missing = "X,A,B,1,1,,,,,,,,,,,,\n"
    used, values = football_data_league(header + full + missing)
    assert used["goals_per_match"] == 2
    assert used["shots_per_match"] == 1
    assert values["goals_per_match"] == 2.5
    assert values["shots_per_match"] == 18
    assert values["team_shots_range"] == 2  # A 10, B 8


def test_verdicts():
    ok = {"status": "ok", "band": [2.5, 3.1]}
    assert verdict(ok, 2.6, 3.0, 2.8) == "PASS"
    assert verdict(ok, 2.4, 3.0, 2.7).startswith("FAIL (mean in band")
    assert verdict(ok, 3.2, 3.4, 3.3) == "FAIL"
    assert verdict({"status": "no_reference"}, 0, 1, 0.5) == "no reference"


def test_fixtures_are_fixed_and_cover_pairs():
    a, b = fixtures(20), fixtures(20)
    assert a == b
    assert all(h != w for h, w, _ in a)
    assert [s for _, _, s in a] == list(range(10_000, 10_020))


def test_metrics_from_a_small_sample():
    sample = [summarise(f) for f in fixtures(3)]
    values, clubs = metric_values(sample)
    assert set(values) == set(ORDER)
    assert 0 < values["pass_completion"] < 1
    assert values["shots_per_match"] > 0
    assert sum(c["matches"] for c in clubs.values()) == 6
