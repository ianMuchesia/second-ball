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
  - ESPN public match summaries (site.api.espn.com, an unofficial API):
    possession, total and accurate passes. FBref, the usual source, removed its
    advanced stats in January 2026 and blocks automated access (HTTP 403).
"""

import csv
import gzip
import io
import json
import statistics
import sys
import time
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
ESPN = {
    "Premier League": "eng.1",
    "La Liga": "esp.1",
    "Bundesliga": "ger.1",
    "Serie A": "ita.1",
    "Ligue 1": "fra.1",
}
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_SEASON = 2024  # = 2024/25
ESPN_DELAY_S = 0.3  # unofficial public API: be polite
NO_REFERENCE = {}


def fetch(url, refresh, headers=None, delay=0.0):
    """Download once; cache the body and its access date."""
    CACHE.mkdir(exist_ok=True)
    name = url.split("//", 1)[1].replace("/", "_").replace("?", "_").replace("=", "_")
    body, meta = CACHE / name, CACHE / (name + ".meta.json")
    if refresh or not body.exists():
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        time.sleep(delay)
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
    # Per team: each team's average shots per match (home + away).
    team_shots = {}
    for r in shots:
        for team, col in ((r["HomeTeam"], "HS"), (r["AwayTeam"], "AS")):
            n, total_shots = team_shots.get(team, (0, 0))
            team_shots[team] = (n + 1, total_shots + int(r[col]))
    averages = [t / n for n, t in team_shots.values()]
    values["team_shots_per_match"] = sum(averages) / len(averages)
    values["team_shots_range"] = max(averages) - min(averages)
    used = {
        "goals_per_match": len(goals),
        "shots_per_match": len(shots),
        "on_target_share": len(on_target),
        "fouls_per_match": len(fouls),
        "yellow_cards_per_match": len(cards),
        "red_cards_per_match": len(cards),
        "team_shots_per_match": len(shots),
        "team_shots_range": len(shots),
    }
    return used, values


def espn_league(code, refresh):
    """Possession and passing for one league-season from ESPN's public match
    summaries (an unofficial API). Teams come from the current team list, so
    matches between two clubs no longer in the league are missed (counted)."""
    teams_body, accessed = fetch(f"{ESPN_API}/{code}/teams", refresh)
    teams = json.loads(teams_body)["sports"][0]["leagues"][0]["teams"]
    event_ids = set()
    for t in teams:
        url = f"{ESPN_API}/{code}/teams/{t['team']['id']}/schedule?season={ESPN_SEASON}"
        body, _ = fetch(url, refresh, delay=ESPN_DELAY_S)
        for e in json.loads(body).get("events", []):
            done = e["competitions"][0]["status"]["type"].get("completed")
            if done and e.get("season", {}).get("year") == ESPN_SEASON:
                event_ids.add(e["id"])
    possession, passes, accurate, matches = {}, 0, 0, 0
    for eid in sorted(event_ids):
        body, _ = fetch(
            f"{ESPN_API}/{code}/summary?event={eid}", refresh, delay=ESPN_DELAY_S
        )
        sides = json.loads(body).get("boxscore", {}).get("teams", [])
        stats = []
        for side in sides:
            st = {x["name"]: x.get("displayValue") for x in side.get("statistics", [])}
            stats.append((side["team"]["displayName"], st))
        try:
            rows = [
                (
                    name,
                    float(st["possessionPct"]),
                    int(st["totalPasses"]),
                    int(st["accuratePasses"]),
                )
                for name, st in stats
            ]
        except (KeyError, TypeError, ValueError):
            continue
        if len(rows) != 2:
            continue
        matches += 1
        for name, poss, total, ok in rows:
            possession.setdefault(name, []).append(poss / 100)
            passes += total
            accurate += ok
    team_means = [sum(v) / len(v) for v in possession.values() if len(v) >= 10]
    return (
        matches,
        {
            "possession_spread": statistics.pstdev(team_means),
            "pass_completion": accurate / passes,
            "passes_per_match": passes / matches,
        },
        accessed,
    )


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
    "team_shots_per_match": (
        "football-data.co.uk",
        "Mean over teams of each team's shots per match.",
    ),
    "team_shots_range": (
        "football-data.co.uk",
        "Highest minus lowest team average shots per match in the league.",
    ),
    "possession_spread": (
        "site.api.espn.com (unofficial)",
        "Standard deviation of the teams' season-average possession.",
    ),
    "pass_completion": (
        "site.api.espn.com (unofficial)",
        "League accurate passes / total passes (ESPN match box scores).",
    ),
    "passes_per_match": (
        "site.api.espn.com (unofficial)",
        "Total passes per match, both teams (ESPN match box scores).",
    ),
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
    for league, code in ESPN.items():
        n, values, accessed = espn_league(code, refresh)
        for m, v in values.items():
            per_league[m][league] = round(v, 4)
            sources[m].append(
                {
                    "url": f"{ESPN_API}/{code}/summary",
                    "accessed": accessed,
                    "matches": n,
                }
            )
        print(f"espn {league}: {n} matches", file=sys.stderr)
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
