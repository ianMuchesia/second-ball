"""Moment detector (Phase 3a): code decides what matters.

Watches a match's events (and the metrics computed from them) and fires a
Moment when something matters: a goal, a red card's impact, a momentum
swing, a pressure spike... Each Moment has an importance, the numbers before
and after, and the event ids behind them. Reads events and core.metrics only,
never engine internals. Thresholds: core/moments/config.yaml (red zone,
TUNABLE, owner: Ian).

    detector = MomentDetector()
    for event in feed:
        events.append(event)
        for moment in detector.update(events):
            ...

`moment.clock` is the match time the moment is about (for a red card's
impact: the red card itself, although it is detected 10 minutes later).
"""

from bisect import bisect_right
from collections import Counter
from functools import cache
from pathlib import Path

import yaml

from core.contracts import Clock, MetricValue, Moment
from core.metrics import basic, chaos, play, positional
from core.metrics.events import (
    DEFENSIVE_ACTIONS,
    PASSES,
    RESTARTS,
    SHOTS,
    TOUCHES,
    Events,
    is_goal,
)

KINDS = (
    "goal",
    "red_card_impact",
    "big_chance",
    "momentum_swing",
    "repeated_pattern",
    "control_shift",
    "pressure_spike",
    "shape_change",
    "openness_spike",
    "overload",
    "bad_situation",
    "player_milestone",
)


@cache
def config() -> dict:
    return yaml.safe_load((Path(__file__).resolve().parent / "config.yaml").read_text())


def span(ev: Events, t0: float, t1: float):
    """(view, lo): the events with t0 < elapsed <= t1, for window metrics."""
    hi = bisect_right(ev.elapsed, t1)
    lo = bisect_right(ev.elapsed, t0)
    return ev.upto(hi), lo


def at_window(fn, ev: Events, t0: float, t1: float, team=None):
    view, lo = span(ev, t0, t1)
    if lo >= len(view.items):
        return None
    return fn(view, lo, team)


def mv(v: float, evidence: list[str]) -> MetricValue:
    return MetricValue(value=v, evidence_event_ids=evidence)


class MomentDetector:
    """Stateful over one match; deterministic given the events."""

    def __init__(self):
        self.count = 0
        self.last_fired: dict[tuple[str, str | None], float] = {}
        self.next_minute = 60.0  # next minute boundary (elapsed seconds) to check
        self.reds: list[
            tuple[int, float]
        ] = []  # (event index, elapsed) awaiting impact
        self.cusum = {"home": 0.0, "away": 0.0}
        self.on_top: str | None = None  # last swing's winner
        self.counters: Counter = Counter()  # (defending team, side) -> counters
        self.pattern_at: dict = {}  # (defending team, side) -> last pattern moment
        self.player_counts: Counter = Counter()  # (player, "passes"/"shots")
        self.active: set[tuple[str, str | None]] = set()  # conditions now true
        # Block-drift CUSUM per (team, "deeper"/"higher"); per-minute depths.
        self.depths: dict[str, list[float]] = {}
        self.drift: dict[tuple[str, str], float] = {}
        self.drift_fired: set[tuple[str, str]] = set()

    def edge(
        self, kind: str, team: str | None, now_true: bool, still: bool | None = None
    ) -> bool:
        """True only when a condition becomes true (a spike fires once when
        it starts, not again every few minutes while it lasts). With `still`
        (hysteresis), an active condition stays active until `still` is false,
        so a value hovering at the threshold does not fire again and again."""
        key = (kind, team)
        was = key in self.active
        if now_true or (was and still):
            self.active.add(key)
        else:
            self.active.discard(key)
        return now_true and not was

    # ---- plumbing ------------------------------------------------------------------

    def fire(self, ev, kind, team, at_index, before, after, evidence, now=None):
        """A Moment, unless the same kind + team fired in the last 3 minutes."""
        t = ev.elapsed[at_index] if now is None else now
        key = (kind, team)
        if key in self.last_fired and t - self.last_fired[key] < config()["cooldown_s"]:
            return None
        ids = list(dict.fromkeys(evidence))
        if not ids:
            return None
        self.last_fired[key] = t
        self.count += 1
        e = ev.items[at_index]
        return Moment(
            moment_id=f"{e.match_id}-mo{self.count:03d}",
            kind=kind,
            team=team,
            clock=Clock(period=e.period, minute=e.minute, second=e.second),
            importance=config()["importance"][kind],
            metrics_before=before,
            metrics_after=after,
            evidence_event_ids=ids,
        )

    def update(self, ev: Events) -> list[Moment]:
        """Moments fired by the latest event (and by any minute just passed)."""
        i = len(ev.items) - 1
        out = [m for m in self.per_event(ev, i) if m is not None]
        while ev.now() >= self.next_minute:
            out += [m for m in self.per_minute(ev, self.next_minute) if m is not None]
            self.next_minute += 60.0
        return out

    # ---- per event ---------------------------------------------------------------

    def per_event(self, ev: Events, i: int):
        e = ev.items[i]
        c = config()
        if is_goal(e):
            scorer = ev.opponent(e.team_id) if e.outcome == "owngoal" else e.team_id
            before = basic.xg(ev.upto(i), 0, scorer) if i else None
            after = basic.xg(ev.upto(i + 1), 0, scorer)
            yield self.fire(
                ev,
                "goal",
                scorer,
                i,
                {"xg": before} if before else {},
                {"xg": after} if after else {},
                [e.event_id],
            )
        elif (
            e.type in SHOTS
            and float(e.qualifiers.get("xg", 0)) >= c["big_chance"]["xg"]
        ):
            xg = float(e.qualifiers["xg"])
            yield self.fire(
                ev,
                "big_chance",
                e.team_id,
                i,
                {},
                {"xg": mv(xg, [e.event_id])},
                [e.event_id],
            )
        if e.outcome == "red_card":
            self.reds.append((i, ev.elapsed[i]))
        yield self.counter(ev, i)
        if e.type in TOUCHES:
            o = positional.overload(ev, i)
            if o.value >= c["overload"]["min_danger"]:
                yield self.fire(
                    ev, "overload", e.team_id, i, {}, {"overload": o}, [e.event_id]
                )
            b = positional.bad_situation(ev, i)
            if b.value:
                after = {
                    "risk": positional.risk(ev, i),
                    "pressure": positional.pressure(ev, i),
                    "options": positional.options(ev, i),
                }
                yield self.fire(
                    ev, "bad_situation", e.team_id, i, {}, after, [e.event_id]
                )
        yield self.milestone(ev, i)

    def counter(self, ev: Events, i: int):
        """A counter in behind a full-back: the ball won in the team's own half,
        then within ~10 s a 15 m+ forward pass into a wide channel, ending
        behind the defender nearest that touchline (the full-back; a full-back
        pushed high leaves space in front of his centre-backs). The 2nd counter
        behind the same side of the same defence = repeated_pattern; while it
        keeps happening, again at most once per pattern_cooldown_s."""
        c = config()["counter"]
        e = ev.items[i]
        if e.type not in PASSES or e.type in RESTARTS:
            return None
        if e.end_x - e.start_x < c["min_forward_m"]:
            return None
        if e.end_y < c["wide_y"]:
            side, touchline = "left", 0.0  # attacker's right = defenders' LEFT
        elif e.end_y > 68.0 - c["wide_y"]:
            side, touchline = "right", 68.0
        else:
            return None
        _, _, opps = positional.sides(e)
        defenders = positional.outfield(opps, positional.THEIR_GOAL)
        if not defenders:
            return None
        full_back = min(defenders, key=lambda o: abs(o.y - touchline))
        if e.end_x <= full_back.x:
            return None
        won = self.regain_time(ev, i)
        if won is None or ev.elapsed[i] - won[1] > c["within_s"]:
            return None
        regain = ev.items[won[0]]
        # Won in the team's own half (the regain is the team's own action, so
        # its x is in the team's frame).
        if regain.start_x > c["regain_max_x"]:
            return None
        key = (ev.opponent(e.team_id), side)
        self.counters[key] += 1
        n = self.counters[key]
        last = self.pattern_at.get(key)
        if n < 2 or (
            last is not None and ev.elapsed[i] - last < c["pattern_cooldown_s"]
        ):
            return None
        moment = self.fire(
            ev,
            "repeated_pattern",
            e.team_id,
            i,
            {},
            {
                f"counters_behind_{side}_back": mv(
                    float(n), [regain.event_id, e.event_id]
                )
            },
            [regain.event_id, e.event_id],
        )
        if moment is not None:
            self.pattern_at[key] = ev.elapsed[i]
        return moment

    def regain_time(self, ev: Events, i: int):
        """(index, elapsed) of the open-play regain that started event i's
        possession: the other side's tackle/interception or its first touch."""
        e = ev.items[i]
        pid = e.possession_id
        k = i
        while k > 0 and ev.items[k - 1].possession_id == pid:
            k -= 1
        if ev.owner.get(pid) != e.team_id or k == 0:
            return None
        first, prev = ev.items[k], ev.items[k - 1]
        if first.type in RESTARTS or is_goal(prev):
            return None
        won = (
            k - 1 if prev.team_id == e.team_id and prev.type in DEFENSIVE_ACTIONS else k
        )
        return won, ev.elapsed[won]

    def milestone(self, ev: Events, i: int):
        c = config()["player_milestone"]
        e = ev.items[i]
        for what, types in (("passes", PASSES), ("shots", SHOTS)):
            if e.type not in types:
                continue
            self.player_counts[(e.player_id, what)] += 1
            n = self.player_counts[(e.player_id, what)]
            if n in c[what]:
                return self.fire(
                    ev,
                    "player_milestone",
                    e.team_id,
                    i,
                    {},
                    {f"{e.player_id}_{what}": mv(float(n), [e.event_id])},
                    [e.event_id],
                )
        return None

    # ---- per minute ----------------------------------------------------------------

    def per_minute(self, ev: Events, t: float):
        i = bisect_right(ev.elapsed, t) - 1  # last event at or before t
        if i < 0:
            return
        yield from self.red_card_impacts(ev, t)
        for team in ev.teams:
            yield self.control_shift(ev, i, t, team)
            yield self.control_vs_expected(ev, i, t, team)
            yield self.pressure_spike(ev, i, t, team)
            yield self.shape_change(ev, i, t, team)
            yield self.block_drift(ev, i, t, team)
        yield self.momentum_swing(ev, i, t)
        yield self.openness_spike(ev, i, t)

    def compare(self, fn, ev, t, recent, before, team):
        a = at_window(fn, ev, t - recent - before, t - recent, team)
        b = at_window(fn, ev, t - recent, t, team)
        return a, b

    def control_shift(self, ev, i, t, team):
        c = config()["control_shift"]
        w = c["window_min"] * 60
        if t < 2 * w:
            return None
        a, b = self.compare(chaos.control_index, ev, t, w, w, team)
        gained = (
            a is not None and b is not None and b.value - a.value >= c["min_change"]
        )
        if not self.edge("control_shift", team, gained):
            return None  # fired for the team that gained control
        return self.fire(
            ev,
            "control_shift",
            team,
            i,
            {"control_index": a},
            {"control_index": b},
            b.evidence_event_ids[-20:],
            now=t,
        )

    def control_vs_expected(self, ev, i, t, team):
        """From 15': the team's control (last 10 min) is clearly above what is
        usual for this fixture (min_z spreads above the baseline for its
        pre-match strength gap). Fires once while it lasts."""
        c = config()["control_shift"]
        if t < c["vs_expected_from_min"] * 60 or ev.strengths is None:
            return None
        view, lo = span(ev, t - c["window_min"] * 60, t)
        now = chaos.control_index(view, lo, team) if lo < len(view.items) else None
        s = dict(zip(ev.teams, ev.strengths, strict=True))
        usual = chaos.control_baseline()["buckets"][
            chaos.signed_gap_bucket(s[team] - s[ev.opponent(team)])
        ]
        z = None if now is None else (now.value - usual["mean"]) / usual["sd"]
        above = z is not None and z >= c["min_z"]
        still = z is not None and z >= c["release_z"]
        if not self.edge("control_vs_expected", team, above, still):
            return None
        expected = mv(usual["mean"], now.evidence_event_ids[-20:])
        return self.fire(
            ev,
            "control_shift",
            team,
            i,
            {"control_index_usual_for_fixture": expected},
            {"control_index": now},
            now.evidence_event_ids[-20:],
            now=t,
        )

    def block_drift(self, ev, i, t, team):
        """A gradual block drop (or step up): two-sided CUSUM on the team's
        per-minute back-line depth while defending (ball in the middle third),
        against its own average from before the last 10 minutes. Fires once
        per direction until the drift has gone (sum back to 0)."""
        c = config()["shape_change"]["drift"]
        line = self.back_line(ev, bisect_right(ev.elapsed, t - 60), i + 1, team)
        if line is None:
            return None
        depths = self.depths.setdefault(team, [])
        depths.append(line[1])
        ref_n = len(depths) - c["recent_min"]
        if ref_n < c["reference_min"]:
            return None
        ref = sum(depths[:ref_n]) / ref_n
        x = line[1]
        for direction, step in (("deeper", x - ref), ("higher", ref - x)):
            key = (team, direction)
            self.drift[key] = max(0.0, self.drift.get(key, 0.0) + step - c["slack_m"])
            if self.drift[key] == 0.0:
                self.drift_fired.discard(key)
            if self.drift[key] > c["threshold_m"] and key not in self.drift_fired:
                moment = self.fire(
                    ev,
                    "shape_change",
                    team,
                    i,
                    {"back_line_depth_x": mv(ref, line[2][-20:])},
                    {
                        "back_line_depth_x": mv(x, line[2][-20:]),
                        f"block_drift_{direction}_m": mv(
                            self.drift[key], line[2][-20:]
                        ),
                    },
                    line[2][-20:],
                    now=t,
                )
                if moment is not None:  # not lost to a cooldown
                    self.drift_fired.add(key)
                return moment
        return None

    def pressure_spike(self, ev, i, t, team):
        c = config()["pressure_spike"]
        recent, before = c["recent_min"] * 60, c["before_min"] * 60
        if t < recent + before:
            return None
        a, b = self.compare(play.final_third_pressures, ev, t, recent, before, team)
        spike = (
            b is not None
            and b.value >= c["min_per_min"]
            and (a is None or b.value >= c["ratio"] * a.value)
        )
        if not self.edge("pressure_spike", team, spike):
            return None
        before_d = {"final_third_pressures": a} if a else {}
        return self.fire(
            ev,
            "pressure_spike",
            team,
            i,
            before_d,
            {"final_third_pressures": b},
            b.evidence_event_ids,
            now=t,
        )

    def back_line(self, ev, lo, hi, team):
        """Mean back-line size and depth of `team` while defending (from the
        opponent's events), with the ball in the same zone (the attacker's
        middle third) so the ball's position does not fake a shape change."""
        lo_x, hi_x = config()["shape_change"]["ball_x"]
        sizes, depths, used = [], [], []
        for k in range(lo, hi):
            e = ev.items[k]
            if e.team_id == team or e.type not in TOUCHES:
                continue
            if not lo_x <= e.start_x <= hi_x:
                continue
            groups = positional.defending_line_groups(e)
            if len(groups) < 2:
                continue
            sizes.append(len(groups[-1]))
            depths.append(sum(groups[-1]) / len(groups[-1]))
            used.append(e.event_id)
        if not used:
            return None
        return sum(sizes) / len(sizes), sum(depths) / len(depths), used

    def shape_change(self, ev, i, t, team):
        """The team's back line gains/loses players, or drops/steps up (x is
        in the attacker's frame: deeper = higher x)."""
        c = config()["shape_change"]
        recent, before = c["recent_min"] * 60, c["before_min"] * 60
        if t < recent + before:
            return None
        lo_a = bisect_right(ev.elapsed, t - recent - before)
        mid = bisect_right(ev.elapsed, t - recent)
        hi = bisect_right(ev.elapsed, t)
        a, b = self.back_line(ev, lo_a, mid, team), self.back_line(ev, mid, hi, team)

        def moved(share):
            return (
                a is not None
                and b is not None
                and (
                    abs(b[0] - a[0]) >= share * c["back_line_players"]
                    or abs(b[1] - a[1]) >= share * c["block_drop_m"]
                )
            )

        if not self.edge("shape_change", team, moved(1.0), moved(c["release_share"])):
            return None
        return self.fire(
            ev,
            "shape_change",
            team,
            i,
            {
                "back_line_players": mv(a[0], a[2][-20:]),
                "back_line_depth_x": mv(a[1], a[2][-20:]),
            },
            {
                "back_line_players": mv(b[0], b[2][-20:]),
                "back_line_depth_x": mv(b[1], b[2][-20:]),
            },
            b[2][-20:],
            now=t,
        )

    def red_card_impacts(self, ev, t):
        c = config()["red_card_impact"]
        w = c["window_min"] * 60
        due = [(k, at) for k, at in self.reds if t >= at + w]
        self.reds = [r for r in self.reds if r not in due]
        for k, at in due:
            red = ev.items[k]
            team = red.team_id
            before, after = {}, {}
            for name, fn, owner in (
                ("control_index", chaos.control_index, team),
                ("pressure_on_ball", positional.mean_pressure_on_ball, team),
                ("defensive_line_gap", positional.team_line_gap, team),
                ("final_third_pressures", play.final_third_pressures, team),
            ):
                a = at_window(fn, ev, at - w, at, owner)
                b = at_window(fn, ev, at, at + w, owner)
                if a is not None and b is not None:
                    before[name], after[name] = a, b
            yield self.fire(
                ev, "red_card_impact", team, k, before, after, [red.event_id], now=t
            )

    def momentum_swing(self, ev, i, t):
        """Two-sided CUSUM on momentum sampled each minute; a swing fires when
        the side not currently on top builds up a sustained lead."""
        c = config()["momentum_swing"]
        m = play.momentum(ev.upto(i + 1), 0)
        if m is None:
            return None
        home, away = ev.teams
        self.cusum["home"] = max(0.0, self.cusum["home"] + m.value - c["drift"])
        self.cusum["away"] = max(0.0, self.cusum["away"] - m.value - c["drift"])
        for side, team in (("home", home), ("away", away)):
            if self.cusum[side] > c["threshold"] and self.on_top != team:
                self.on_top = team
                self.cusum = {"home": 0.0, "away": 0.0}
                return self.fire(
                    ev,
                    "momentum_swing",
                    team,
                    i,
                    {},
                    {"momentum": m},
                    m.evidence_event_ids[-20:],
                    now=t,
                )
        return None

    def openness_spike(self, ev, i, t):
        c = config()["openness_spike"]
        view = ev.upto(i + 1)
        lo = bisect_right(view.elapsed, view.now() - 600)
        v = chaos.openness_vs_expected(view, lo)
        spike = v is not None and v.value >= c["above_usual"]
        if not self.edge("openness_spike", None, spike):
            return None
        now = chaos.openness_index(view, lo)
        return self.fire(
            ev,
            "openness_spike",
            None,
            i,
            {},
            {"openness_index": now, "openness_vs_expected": v},
            now.evidence_event_ids[-20:],
            now=t,
        )


def detect(events: Events) -> list[Moment]:
    """All moments for a list of events (replays them through a detector)."""
    det, walk, out = (
        MomentDetector(),
        Events(teams=events.teams, strengths=events.strengths),
        [],
    )
    for e in events.items:
        walk.append(e)
        out += det.update(walk)
    return out


__all__ = ["KINDS", "MomentDetector", "config", "detect"]
