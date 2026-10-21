"""Fetch real-football reference bands into evals/realism/reference.yaml.

Every number in reference.yaml comes from a download made by this script, with
its URL and access date. Nothing is typed in by hand. Raw downloads are cached
in evals/realism/.cache/ (not committed). Only league totals are kept: no
player- or match-level real data is stored in the repo.

    uv run python -m evals.realism.fetch_reference [--refresh]

Sources (season 2024/25, top five European leagues):
  - football-data.co.uk match CSVs: goals, shots, shots on target, fouls, cards.
  - Understat league data: xG per shot (player season totals summed per league)
    and PPDA (team-match ppda att/def summed per league).
  - FBref blocks automated access (HTTP 403) and removed its advanced stats in
    January 2026, so possession and passing have no reference here.
"""

import csv
import gzip
import io
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import yaml

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
OUT = HERE / "reference.yaml"
SEASON = "2024/25"
UA = "Mozilla/5.0 (X11; Linux x86_64) second-ball-realism/0.1 (synthetic-data research)"

FOOTBALL_DATA = {
    "Premier League": "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
    "La Liga": "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
    "Bundesliga": "https://www.football-data.co.uk/mmz4281/2425/D1.csv",
    "Serie A": "https://www.football-data.co.uk/mmz4281/2425/I1.csv",
    "Ligue 1": "https://www.football-data.co.uk/mmz4281/2425/F1.csv",
}
UNDERSTAT = {
    "Premier League": "https://understat.com/getLeagueData/EPL/2024",
    "La Liga": "https://understat.com/getLeagueData/La_liga/2024",
    "Bundesliga": "https://understat.com/getLeagueData/Bundesliga/2024",
    "Serie A": "https://understat.com/getLeagueData/Serie_A/2024",
    "Ligue 1": "https://understat.com/getLeagueData/Ligue_1/2024",
}
NO_REFERENCE = {
    "pass_completion": "FBref removed its advanced (Opta) stats in Jan 2026 and blocks "
    "automated access (HTTP 403); no other free source found.",
    "passes_per_match": "Same as pass_completion: no free current source found.",
    "possession_spread": "FBref possession not reachable by script (HTTP 403); "
    "football-data.co.uk and Understat do not publish possession.",
}


def fetch(url, refresh, headers=None):
    """Download once; cache the body and its access date."""
    CACHE.mkdir(exist_ok=True)
    name = url.split("//", 1)[1].replace("/", "_")
    body, meta = CACHE / name, CACHE / (name + ".meta.json")
    if refresh or not body.exists():
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        body.write_bytes(data)
        meta.write_text(
            json.dumps({"url": url, "accessed": datetime.now(UTC).date().isoformat()})
        )
    return body.read_bytes(), json.loads(meta.read_text())["accessed"]


def football_data_league(text):
    """League values, using only matches that have the columns each metric needs."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    rows = [r for r in rows if r.get("FTHG") not in (None, "")]

    def complete(*cols):
        return [r for r in rows if all(r.get(c, "") != "" for c in cols)]

    def total(rs, *cols):
        return sum(int(r[c]) for r in rs for c in cols)

    goals = complete("FTHG", "FTAG")
    shots = complete("HS", "AS")
    on_target = complete("HS", "AS", "HST", "AST")
    fouls = complete("HF", "AF")
    cards = complete("HY", "AY", "HR", "AR")
    values = {
        "goals_per_match": total(goals, "FTHG", "FTAG") / len(goals),
        "shots_per_match": total(shots, "HS", "AS") / len(shots),
        "on_target_share": total(on_target, "HST", "AST")
        / total(on_target, "HS", "AS"),
        "fouls_per_match": total(fouls, "HF", "AF") / len(fouls),
        "yellow_cards_per_match": total(cards, "HY", "AY") / len(cards),
        "red_cards_per_match": total(cards, "HR", "AR") / len(cards),
    }
    used = {
        "goals_per_match": len(goals),
        "shots_per_match": len(shots),
        "on_target_share": len(on_target),
        "fouls_per_match": len(fouls),
        "yellow_cards_per_match": len(cards),
        "red_cards_per_match": len(cards),
    }
    return used, values


def understat_league(data):
    players = data["players"]
    shots = sum(int(p["shots"]) for p in players)
    xg = sum(float(p["xG"]) for p in players)
    att = sum(h["ppda"]["att"] for t in data["teams"].values() for h in t["history"])
    dfn = sum(h["ppda"]["def"] for t in data["teams"].values() for h in t["history"])
    return {"xg_per_shot": xg / shots, "ppda": att / dfn}


METRICS = {
    "goals_per_match": ("football-data.co.uk", "Goals per match (both teams)."),
    "shots_per_match": ("football-data.co.uk", "Shots per match (both teams)."),
    "on_target_share": ("football-data.co.uk", "Share of shots on target."),
    "fouls_per_match": ("football-data.co.uk", "Fouls per match (both teams)."),
    "yellow_cards_per_match": ("football-data.co.uk", "Yellow cards per match."),
    "red_cards_per_match": ("football-data.co.uk", "Red cards per match."),
    "xg_per_shot": (
        "understat.com",
        "League xG / league shots (player season totals).",
    ),
    "ppda": (
        "understat.com",
        (
            "League PPDA = sum of opponent passes / sum of defensive actions over "
            "all team-matches. Understat does not publish its zone; the standard "
            "definition (opponent passes in the 60% of the pitch nearest the "
            "defending team's attacking goal; tackles, interceptions, challenges, "
            "fouls) is assumed."
        ),
    ),
}


def main(argv=None):
    refresh = "--refresh" in (argv if argv is not None else sys.argv[1:])
    per_league = {m: {} for m in METRICS}
    sources = {m: [] for m in METRICS}
    for league, url in FOOTBALL_DATA.items():
        body, accessed = fetch(url, refresh)
        used, values = football_data_league(body.decode("utf-8", errors="replace"))
        for m, v in values.items():
            per_league[m][league] = round(v, 4)
            sources[m].append({"url": url, "accessed": accessed, "matches": used[m]})
    for league, url in UNDERSTAT.items():
        body, accessed = fetch(url, refresh, {"X-Requested-With": "XMLHttpRequest"})
        for m, v in understat_league(json.loads(body)).items():
            per_league[m][league] = round(v, 4)
            sources[m].append({"url": url, "accessed": accessed})

    reference = {
        "season": SEASON,
        "band_rule": "band = [lowest, highest] of the five league values",
        "metrics": {},
    }
    for m, (publisher, definition) in METRICS.items():
        values = per_league[m]
        reference["metrics"][m] = {
            "status": "ok",
            "publisher": publisher,
            "definition": definition,
            "band": [min(values.values()), max(values.values())],
            "per_league": values,
            "sources": sources[m],
        }
    for m, reason in NO_REFERENCE.items():
        reference["metrics"][m] = {"status": "no_reference", "reason": reason}

    header = (
        "# GENERATED by evals/realism/fetch_reference.py. Do not edit by hand.\n"
        "# Every number below was downloaded from the source URL on the access date.\n"
    )
    OUT.write_text(
        header + yaml.safe_dump(reference, sort_keys=False, allow_unicode=True)
    )
    print(f"wrote {OUT.relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
