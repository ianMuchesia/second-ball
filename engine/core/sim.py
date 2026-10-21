"""Possession-chain state machine. Same seed = identical match.

Each step the ball carrier picks pass / carry / take-on / shot (or clearance)
from zone, team style and pressure. Failed passes become interceptions,
tackles or loose balls and can open a counterpress window. Shots resolve
via xG. Late on, the leading team drops its block, the trailing team speeds
up, fatigue lowers the press, and red cards remove players.
"""

import collections
import itertools
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from core.contracts import Match, MatchEvent
from engine.core.models import fatigue, pass_success, pressure_load, xg
from engine.core.pitch import (
    GOAL_Y,
    LENGTH,
    WIDTH,
    clamp,
    dist,
    on_pitch,
    own,
    own_facing,
)
from engine.core.shape import TeamState, build_frame, centre_spot, keeper_spot
from engine.core.shapes import ball_side
from engine.league import COMPETITION
from engine.weather import load_weather

CONFIG = Path(__file__).parent.parent / "config" / "engine.yaml"
# What a real event feed carries. Every other label the engine knows (counter,
# channel, last_man, lines_broken, scenario_beat, ...) goes to the engine-truth
# sidecar, which only evals may read: the analyser sees events alone.
FEED_QUALIFIERS = frozenset({"xg", "assist", "length_m"})
DEFAULT_KICKOFF = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def load_config(path=CONFIG):
    return yaml.safe_load(Path(path).read_text())


@dataclass
class SimulatedMatch:
    match: Match
    events: list
    # Engine-only labels per event: [{"event_id": ..., **labels}]. Evals only.
    truth: list = field(default_factory=list)
    # Engine-internal mode switches (manage / protect / chase). Never emitted.
    mode_log: list = field(default_factory=list)

    def truth_by_event(self):
        return {t["event_id"]: t for t in self.truth}


def simulate_match(
    home,
    away,
    seed,
    weather="dry",
    kickoff=DEFAULT_KICKOFF,
    config=None,
    scenario=None,
):
    """Simulate one match between two ClubProfiles. Returns Match + list[MatchEvent].

    With a `scenario` (engine.scenarios.Scenario) the scripted beats are played
    at their minutes and the match is recorded as mode "scenario".
    """
    cfg = config or load_config()
    match = Match(
        match_id=f"m-{home.id}-{away.id}-{seed}",
        home_team=home.id,
        away_team=away.id,
        venue=home.stadium,
        kickoff=kickoff,
        competition=COMPETITION,
        seed=seed,
        weather=weather,
        mode="scenario" if scenario else "free_simulation",
    )
    sim = _Sim(match, home, away, cfg, load_weather()[weather], scenario)
    events = sim.run()
    if scenario:
        missed = [b.id for b in scenario.scripted() if b.id not in sim.done]
        if missed:
            raise RuntimeError(f"scenario beats never played: {missed}")
    return SimulatedMatch(match, events, sim.truth, sim.mode_log)


class _Sim:
    def __init__(self, match, home, away, cfg, weather, scenario=None):
        self.match = match
        self.scenario = scenario
        self.done = set()  # scripted beats already played
        self.just_won = False  # possession was just won in open play
        self.cfg = cfg
        self.wx = weather
        self.rng = random.Random(match.seed)
        self.teams = (TeamState.start(0, home), TeamState.start(1, away))
        self.events = []
        self.truth = []
        self.samples = collections.deque()  # (t, side in possession, ball x)
        self.mode_log = []  # engine-internal mode switches (never emitted)
        self.t = 0.0
        self.period = 1
        self.possessions = 0
        self.attack = 0
        self.carrier = 0
        self.ball = centre_spot()
        self.assist = "none"
        self.passes = 0
        self.counterpress = None  # (side, until_t)
        self.transition_until = -1.0  # both teams in transition shape until then
        self.previous = None  # last frame's shape positions, for smooth movement

    # ---- clock and game state -------------------------------------------------

    @property
    def minute(self):
        return int(self.t // 60)

    def tick(self, seconds):
        self.t += max(0.5, seconds)

    def lead(self, side):
        return self.teams[side].goals - self.teams[1 - side].goals

    def effect(self, side, key, default):
        """A mode effect from game_state.<mode>.<key> (engine-internal)."""
        mode = self.teams[side].mode
        return self.cfg["game_state"].get(mode, {}).get(key, default)

    def block_height(self, side):
        team = self.teams[side]
        drop = self.effect(side, "block_drop_m", 0.0)
        if team.mode == "protect":
            drop = team.profile.late_lead_block_drop
        return team.profile.block_height - drop - self.scripted_drop(side)

    def push(self, side):
        return self.effect(side, "fullback_push_m", 0.0)

    def scripted_drop(self, side):
        if not self.scenario:
            return 0.0
        team = "home" if side == 0 else "away"
        return sum(
            b.extra_drop_m
            for b in self.scenario.beats
            if b.action == "block_drop"
            and b.team == team
            and b.minute[0] <= self.minute <= b.minute[1]
        )

    def directness(self, side):
        extra = self.effect(side, "directness", 0.0)
        return clamp(self.teams[side].profile.directness + extra, 0, 1)

    def seconds_per_action(self, side):
        spa = self.teams[side].profile.tempo.seconds_per_action
        return spa * self.effect(side, "tempo", 1.0)

    def legs(self):
        return fatigue(self.cfg, self.minute, self.wx.fatigue_rate)

    def press_intensity(self, side, carrier_x):
        """How hard `side` presses a carrier at carrier_x (carrier's frame)."""
        pr = self.cfg["pressing"]
        intensity = 1.0
        if carrier_x < pr["high_press_zone_x"]:
            intensity = pr["ppda_reference"] / self.teams[side].profile.target_ppda
        intensity *= self.effect(side, "press", 1.0)
        return intensity * self.legs()

    # ---- match modes (engine-internal: never emitted) -------------------------

    def territory(self, side):
        """Share of the last threat window the opponent had the ball in `side`'s
        defensive third. The engine's own signal; the analyser never sees it."""
        gs = self.cfg["game_state"]
        lo = self.t - gs["threat_window_s"]
        inside = 0.0
        for (t0, attack, bx), (t1, _, _) in itertools.pairwise(
            [*self.samples, (self.t, None, None)]
        ):
            a, b = max(t0, lo), t1
            if b <= a or attack != 1 - side:
                continue
            if own(side, bx, GOAL_Y)[0] < gs["defensive_third_x"]:
                inside += b - a
        return inside / gs["threat_window_s"]

    def update_modes(self):
        gs = self.cfg["game_state"]
        self.samples.append((self.t, self.attack, self.ball[0]))
        while (
            len(self.samples) > 2
            and self.samples[1][0] < self.t - gs["threat_window_s"]
        ):
            self.samples.popleft()
        for side in (0, 1):
            team = self.teams[side]
            lead = self.lead(side)
            late = self.minute >= gs["from_minute"]
            if not late or lead == 0 or abs(lead) >= gs["comfortable_margin"]:
                base = "normal"
            elif lead > 0:
                base = "manage"
            else:
                base = "chase" if -lead <= gs["chase_max_deficit"] else "normal"

            if base != "manage":
                if team.mode != base:
                    self.set_mode(team, base, "score_or_clock")
                continue
            if team.mode not in ("manage", "protect"):
                self.set_mode(team, "manage", "score_or_clock")
                continue

            share = self.territory(side)
            settled = self.t - team.mode_since >= gs["min_mode_s"]
            if team.mode == "manage":
                opp = self.teams[1 - side].profile.strength
                stronger = opp > team.profile.strength + gs["stronger_by"]
                limit = (
                    gs["escalate_share_vs_stronger"]
                    if stronger
                    else gs["escalate_share"]
                )
                if share >= limit and settled:
                    self.set_mode(team, "protect", "threat")
            else:
                if share < gs["calm_share"]:
                    team.calm_since = (
                        team.calm_since if team.calm_since is not None else self.t
                    )
                else:
                    team.calm_since = None
                calm = (
                    team.calm_since is not None
                    and self.t - team.calm_since >= gs["calm_s"]
                )
                if calm and settled:
                    self.set_mode(team, "manage", "calm")

    def set_mode(self, team, mode, reason):
        team.mode, team.mode_since, team.calm_since = mode, self.t, None
        self.mode_log.append(
            {"t": self.t, "team": team.profile.id, "mode": mode, "reason": reason}
        )

    def counterpressing(self, side):
        return (
            self.counterpress is not None
            and self.counterpress[0] == side
            and self.t <= self.counterpress[1]
        )

    # ---- main loop ------------------------------------------------------------

    def run(self):
        lo, hi = self.cfg["stoppage_minutes"]
        for period, start in ((1, 0), (2, 45 * 60)):
            self.period = period
            self.t = float(start)
            end = start + 45 * 60 + self.rng.randint(lo, hi) * 60
            self.kickoff(0 if period == 1 else 1)
            while self.t < end:
                self.step()
        return self.events

    def new_possession(self, side, carrier, ball, assist="none", same=False):
        if not same:
            self.possessions += 1
        self.attack, self.carrier, self.ball = side, carrier, on_pitch(*ball)
        self.assist = assist
        self.passes = 0

    def turnover(self, side, player, ball):
        lost = 1 - side
        self.new_possession(side, player, ball)
        self.transition_until = self.t + self.cfg["shapes"]["transition_s"]
        self.just_won = True
        cp = self.teams[lost].profile.counterpress
        if self.rng.random() < cp.probability * self.legs():
            self.counterpress = (lost, self.t + cp.duration_s)
        else:
            self.counterpress = None

    def frame(self, pressed=None):
        """Freeze frame around the current carrier. Returns (frame, presser_distance)."""
        pr = self.cfg["pressing"]
        bx, _ = own(self.attack, *self.ball)
        defence = 1 - self.attack
        if pressed is None:
            p = pr["base_probability"] * self.press_intensity(defence, bx)
            if bx > pr["deep_zone_x"]:
                p *= pr["deep_zone_press"]  # defences crowd their own box
            if self.counterpressing(defence):
                p = max(p, pr["counterpress_probability"])
            pressed = self.rng.random() < min(p, 0.95)
        lo, hi = pr["close_distance_m"] if pressed else pr["open_distance_m"]
        presser_dist = self.rng.uniform(lo, hi)
        fb = self.cfg["facing_back"]
        back_p = (
            fb["pressed_in_own_half"]
            if pressed and bx < LENGTH / 2
            else fb["otherwise"]
        )
        blocks = {s: self.block_height(s) for s in (0, 1)}
        transition = self.t < self.transition_until
        phases = {
            self.attack: "transition" if transition else "in_possession",
            defence: "transition" if transition else "out_of_possession",
        }
        frame = build_frame(
            self.rng,
            self.cfg,
            self.teams,
            self.attack,
            self.carrier,
            self.ball,
            presser_dist,
            self.rng.random() < back_p,
            blocks,
            phases,
            self.previous,
            {s: self.push(s) for s in (0, 1)},
        )
        self.previous = frame.shape_positions
        return frame, presser_dist

    def step(self):
        self.update_modes()
        beat = self.due_beat()
        if beat is not None:
            self.play_beat(beat)
            return
        won_ball, self.just_won = self.just_won, False
        attack, defence = self.attack, 1 - self.attack
        frame, presser_dist = self.frame()
        bx, by = own(attack, *self.ball)
        pressed = presser_dist <= self.cfg["under_pressure_m"]

        regain = self.cfg["pressing"]["counterpress_regain"] * self.legs()
        if pressed and self.counterpressing(defence) and self.rng.random() < regain:
            presser, _ = frame.nearest(defence, self.ball)
            self.challenge(frame, presser)
            return

        team = self.teams[attack]
        won_ball = won_ball and (
            team.profile.on_regain is not None
            or self.effect(attack, "counter_probability", 0.0) > 0
            or self.cfg["style"]["direct_counter"] * team.profile.directness > 0
        )
        choice = self.choose_action(bx, by, pressed, won_ball)
        if choice == "shot":
            self.shot(frame)
        elif choice == "carry":
            self.carry(frame, pressed)
        elif choice == "take_on":
            self.take_on(frame, presser_dist)
        elif choice == "clearance":
            self.clearance(frame)
        else:
            self.pass_(frame, presser_dist, regain=won_ball)

    def choose_action(self, bx, by, pressed, regain=False):
        shots = self.cfg["shots"]
        target = self.teams[self.attack].profile.tempo.passes_per_possession
        w = {
            "pass": (3.0 if regain else 1.0)
            * (
                self.cfg["style"]["pass_weight_before_target"]
                if self.passes < target
                else self.cfg["style"]["pass_weight_after_target"]
            ),
            "carry": (0.15 if pressed else 0.45) * (0.3 if bx > 95 else 1.0),
            "take_on": 0.05 + (0.15 if pressed and bx > 55 else 0.0),
            "clearance": (0.6 if pressed and bx < 25 else 0.0)
            * self.effect(self.attack, "clearance", 1.0),
            "shot": 0.0,
        }
        if bx >= shots["min_x"]:
            header = self.assist in ("cross", "set_piece")
            chance = xg(self.cfg, bx, by, header, self.assist)
            boost = (
                3.0 if self.assist in ("cross", "through_ball", "set_piece") else 1.0
            )
            w["shot"] = shots["bias"] * chance * boost * (0.6 if pressed else 1.0)
            w["shot"] *= self.effect(self.attack, "shot_bias", 1.0)
            direct = self.teams[self.attack].profile.directness
            w["shot"] *= 1.0 + self.cfg["style"]["direct_shot_bonus"] * direct
            if self.passes >= target:
                w["shot"] *= 1.3
        names = list(w)
        return self.rng.choices(names, weights=[w[n] for n in names])[0]

    # ---- events ---------------------------------------------------------------

    def emit(
        self,
        frame,
        side,
        player,
        type_,
        outcome,
        start,
        end,
        body_part="foot_right",
        speed=None,
        **qual,
    ):
        """Record one event in the acting team's SPADL frame.

        Positions are rounded to the centimetre and facing to 0.1 degree;
        under_pressure is computed from the rounded frame, exactly as stored.
        """
        sx, sy = _cm(*own(side, *on_pitch(*start)))
        ex, ey = _cm(*own(side, *on_pitch(*end)))
        players, me, opponents = [], (sx, sy), []
        for (s, pl), (x, y) in frame.positions.items():
            fx, fy = _cm(*own(side, x, y))
            players.append(
                {
                    "player_id": self.teams[s].profile.player_id(pl),
                    "team_id": self.teams[s].profile.id,
                    "x": fx,
                    "y": fy,
                    "facing_deg": round(own_facing(side, frame.facing[(s, pl)]), 1)
                    % 360,
                }
            )
            if (s, pl) == (side, player):
                me = (fx, fy)
            elif s != side:
                opponents.append((fx, fy))
        nearest = min((dist(me, p) for p in opponents), default=math.inf)
        event = MatchEvent(
            event_id=f"{self.match.match_id}-e{len(self.events) + 1:05d}",
            match_id=self.match.match_id,
            possession_id=f"{self.match.match_id}-p{self.possessions:04d}",
            period=self.period,
            minute=self.minute,
            second=int(self.t % 60),
            team_id=self.teams[side].profile.id,
            player_id=self.teams[side].profile.player_id(player),
            type=type_,
            outcome=outcome,
            body_part=body_part,
            start_x=sx,
            start_y=sy,
            end_x=ex,
            end_y=ey,
            under_pressure=nearest <= self.cfg["under_pressure_m"],
            ball_speed_kmh=None
            if speed is None
            else round(speed * self.wx.ball_speed, 1),
            qualifiers={k: v for k, v in qual.items() if k in FEED_QUALIFIERS},
            freeze_frame=players,
        )
        self.events.append(event)
        labels = {k: v for k, v in qual.items() if k not in FEED_QUALIFIERS}
        if labels:
            self.truth.append({"event_id": event.event_id, **labels})
        return event

    def foot(self):
        return "foot_right" if self.rng.random() < 0.7 else "foot_left"

    # ---- restarts -------------------------------------------------------------

    def restart(self, snap=False):
        """Play stops: no counterpress or transition; `snap` resets players to shape."""
        self.counterpress = None
        self.transition_until = -1.0
        if snap:
            self.previous = None

    def kickoff(self, side):
        self.restart(snap=True)
        self.new_possession(side, self.teams[side].front_player, centre_spot())
        frame, _ = self.frame(pressed=False)
        self.pass_(frame, 10.0, kind="pass", restart=True, backwards=True)

    def goalkick(self, side):
        self.restart(snap=True)
        self.new_possession(side, self.teams[side].keeper, keeper_spot(side))
        frame, _ = self.frame(pressed=False)
        self.pass_(frame, 10.0, kind="goalkick", restart=True)

    def throw_in(self, side, at):
        self.restart()
        x, _ = at
        y = 0.0 if at[1] < GOAL_Y else WIDTH
        frame, _ = self.frame(pressed=False)
        taker, _ = frame.nearest(
            side, (x, y), outfield_only=True, keeper=self.teams[side].keeper
        )
        self.new_possession(side, taker, (x, y))
        frame, _ = self.frame(pressed=False)
        self.pass_(frame, 10.0, kind="throw_in", restart=True)

    def free_kick(self, side, at):
        self.restart()
        self.new_possession(
            side,
            self.carrier if self.attack == side else self.teams[side].front_player,
            at,
        )
        bx, by = own(side, *at)
        sp = self.cfg["set_pieces"]
        late_leader = self.minute >= sp["late_minute"] and self.lead(side) > 0
        if late_leader and bx > LENGTH * 2 / 3:
            self.tick(sp["late_extra_s"])  # no hurry: run the clock
        frame, _ = self.frame(pressed=False)
        if bx > 80 and abs(by - GOAL_Y) < 15 and self.rng.random() < 0.3:
            self.assist = "set_piece"
            self.shot(frame, kind="shot_freekick")
        elif bx > LENGTH * 2 / 3 and (
            late_leader or self.rng.random() < sp["wide_free_kick_cross"]
        ):
            self.delivery(side, at, "freekick_crossed")
        else:
            self.pass_(frame, 10.0, kind="freekick_short", restart=True)

    def corner(self, side):
        self.restart()
        y_own = 0.0 if self.rng.random() < 0.5 else WIDTH
        self.delivery(side, own(side, LENGTH, y_own), "corner_crossed")

    def delivery(self, side, spot, kind):
        """A set-piece ball into the box (corner or wide free kick). Better
        set-piece clubs find a teammate more often and make better chances."""
        frame, _ = self.frame(pressed=False)
        taker, _ = frame.nearest(
            side, spot, outfield_only=True, keeper=self.teams[side].keeper
        )
        self.new_possession(side, taker, spot)
        frame, _ = self.frame(pressed=False)
        target = own(side, self.rng.uniform(95, 101), self.rng.uniform(28, 40))
        threat = self.teams[side].profile.set_pieces.threat
        p = (
            self.cfg["shots"]["corner_success"]
            * (0.6 + self.cfg["set_pieces"]["threat_delivery"] * threat)
            * self.wx.cross_accuracy
        )
        ok = self.rng.random() < p
        self.emit(
            frame,
            side,
            taker,
            kind,
            "success" if ok else "fail",
            spot,
            target,
            self.foot(),
            70.0,
        )
        self.tick(4)
        if ok:
            receiver, _ = frame.nearest(side, target, exclude={(side, taker)})
            self.new_possession(side, receiver, target, assist="set_piece", same=True)
        else:
            defender, _ = frame.nearest(1 - side, target)
            self.turnover(1 - side, defender, target)

    # ---- actions --------------------------------------------------------------

    def pass_(
        self,
        frame,
        presser_dist,
        kind="pass",
        restart=False,
        backwards=False,
        regain=False,
        forced=None,
        qual=None,
    ):
        """A pass. `forced` = {"receiver", "target", "ok"} for scripted passes."""
        side, carrier = self.attack, self.carrier
        start = self.ball
        bx, by = own(side, *start)
        directness = self.directness(side)
        qual = dict(qual or {})

        channel = None
        on_regain = self.teams[side].profile.on_regain
        counter_p = max(
            on_regain.channel_probability if on_regain else 0.0,
            self.effect(side, "counter_probability", 0.0),
            self.cfg["style"]["direct_counter"] * self.teams[side].profile.directness,
        )
        wants_channel = forced is None and regain and kind == "pass" and counter_p > 0
        if wants_channel and self.rng.random() < counter_p:
            channel = self.channel_target(frame, side)

        cross = (
            forced is None
            and channel is None
            and kind == "pass"
            and bx > 78
            and (by < 16 or by > WIDTH - 16)
            and self.rng.random() < self.cfg["cross_share"]
        )
        if forced is not None:
            receiver, target = forced["receiver"], forced["target"]
        elif channel is not None:
            receiver, target, label = channel
            qual.update(counter=True, channel=label)
        elif cross:
            target = own(side, self.rng.uniform(92, 101), self.rng.uniform(26, 42))
            receiver, _ = frame.nearest(side, target, exclude={(side, carrier)})
            kind = "cross"
        else:
            receiver, target = self.pick_receiver(
                frame, side, carrier, bx, directness, backwards
            )

        rx, _ = own(side, *target)
        d = dist(start, target)
        gain = rx - bx
        lines = sum(
            1
            for (s, _), p in frame.positions.items()
            if s != side and gain > 0 and bx < own(side, *p)[0] < rx
        )
        _, receiver_gap = frame.nearest(1 - side, target)
        p = pass_success(
            self.cfg,
            d,
            pressure_load(presser_dist),
            pressure_load(receiver_gap),
            max(0.0, gain / d) if d > 0 else 0.0,
            lines,
            cross,
            restart,
            # Quality shows in keeping the ball; near the box defences crowd everyone.
            self.teams[side].profile.strength
            if bx <= self.cfg["style"]["final_third_x"]
            else 0.5,
        )
        p *= self.wx.pass_success
        if d > 30:
            p *= self.wx.long_pass_accuracy
        if cross:
            p *= self.wx.cross_accuracy
        ok = forced["ok"] if forced is not None else self.rng.random() < p

        speed = min(120.0, (35 + 1.3 * d) * self.rng.uniform(0.9, 1.1))
        body = "other" if kind == "throw_in" else self.foot()
        through = not cross and lines >= 2 and gain > 15
        self.emit(
            frame,
            side,
            carrier,
            kind,
            "success" if ok else "fail",
            start,
            target,
            body,
            speed,
            length_m=round(d, 1),
            lines_broken=lines,
            **qual,
        )
        self.tick(
            self.seconds_per_action(side) * self.rng.uniform(0.6, 1.4)
            + d / (speed / 3.6)
        )

        if ok:
            self.carrier, self.ball = receiver, target
            self.passes += 1
            self.assist = "cross" if cross else ("through_ball" if through else "pass")
            return
        self.failed_pass(frame, side, receiver, start, target, kind)

    def pick_receiver(self, frame, side, carrier, bx, directness, backwards):
        team = self.teams[side]
        style = self.cfg["style"]
        if bx > style["final_third_x"]:
            # In the final third every team combines; long balls stop here.
            directness = min(directness, style["final_third_directness"])
        ppp = team.profile.tempo.passes_per_possession
        patience = style["safe_pass_bonus"] * max(0.0, (ppp - 5.0) / 5.0)
        # Past its usual number of passes, a team goes long and forward.
        go_long = self.passes >= ppp and bx <= style["final_third_x"] and not backwards
        if go_long:
            directness = max(directness, style["go_long_directness"])
        names, weights, spots = [], [], []
        for (s, pl), pos in frame.positions.items():
            if s != side or pl == carrier:
                continue
            if pl == team.keeper and bx > 40:
                continue
            rx, _ = own(side, *pos)
            d = dist(self.ball, pos)
            gain = rx - bx
            if backwards:
                w = 1.0 if gain < 0 else 0.05
            else:
                w = math.exp(-d / (10 + 25 * directness)) * math.exp(
                    directness * gain / 12
                )
                if d < 3:
                    w *= 0.2
                if self.passes < ppp and d < 20 and gain < 5:
                    w *= 1.0 + patience  # possession teams recycle safely
                if go_long and gain < 0:
                    w *= style["go_long_backward"]
                w *= self.build_up_weight(team, bx, pos, gain)
            names.append(pl)
            weights.append(max(w, 1e-6))
            spots.append(pos)
        i = self.rng.choices(range(len(names)), weights=weights)[0]
        return names[i], spots[i]

    def build_up_weight(self, team, bx, pos, gain):
        """Short through the back early on, then towards the ball-side flank."""
        bu = team.profile.build_up
        if bu is None:
            return 1.0
        if bx < bu.short_until_x:
            return 1.5 if gain < 10 and dist(self.ball, pos) < 25 else 0.5
        _, by = own(team.side, *self.ball)
        _, ry = own(team.side, *pos)
        same_flank = abs(ry - GOAL_Y) > 18 and (ry - GOAL_Y) * (by - GOAL_Y) > 0
        return 1.0 + 2.0 * bu.flank_bias if same_flank and gain > 0 else 1.0

    def failed_pass(self, frame, side, receiver, start, target, kind="pass"):
        defence = 1 - side
        if kind == "cross":
            sp = self.cfg["set_pieces"]
            seeking = self.teams[side].profile.set_pieces.corner_seeking
            if self.rng.random() < sp["cross_to_corner"] * (1 + seeking):
                self.tick(10)
                self.corner(side)  # cleared behind
                return
        fp = self.cfg["failed_pass"]
        _, receiver_gap = frame.nearest(defence, target)
        weights = {
            "interception": fp["interception"],
            "tackle": fp["tackle"] if receiver_gap < 5 else fp["tackle"] * 0.2,
            "loose_ball": fp["loose_ball"] * self.wx.loose_ball,
        }
        outcome = self.rng.choices(list(weights), weights=list(weights.values()))[0]

        if outcome == "interception":
            mid = ((start[0] + target[0]) / 2, (start[1] + target[1]) / 2)
            defender, _ = frame.nearest(defence, mid)
            frame.positions[(defence, defender)] = mid
            self.emit(
                frame,
                defence,
                defender,
                "interception",
                "success",
                mid,
                mid,
                self.foot(),
            )
            self.tick(1)
            self.turnover(defence, defender, mid)
        elif outcome == "tackle":
            self.carrier, self.ball = receiver, target
            frame.positions[(side, receiver)] = target
            defender, _ = frame.nearest(defence, target)
            self.challenge(frame, defender)
        else:
            frame.positions[(side, receiver)] = target
            self.emit(
                frame, side, receiver, "bad_touch", "fail", target, target, self.foot()
            )
            self.tick(2)
            r = self.rng.random()
            if r < self.cfg["loose_ball_out_of_play"]:
                self.throw_in(defence, target)
            elif (
                r
                < self.cfg["loose_ball_out_of_play"] + self.cfg["loose_ball_kept"] * 0.8
            ):
                self.carrier, self.ball = receiver, target
            else:
                defender, _ = frame.nearest(defence, target)
                self.turnover(defence, defender, target)

    def challenge(self, frame, defender, card=None, **qual):
        """`defender` goes in on the carrier: foul (maybe a card) or a won tackle.

        `card` forces a foul with that outcome (scripted). In scenario mode the
        engine shows no red cards of its own.
        """
        side, defence = self.attack, 1 - self.attack
        at = self.ball
        frame.positions[(defence, defender)] = at
        ch = self.cfg["challenges"]
        team = self.teams[defence]
        foul_p = ch["foul"]
        if own(side, *at)[0] > LENGTH * 2 / 3:
            sp = self.cfg["set_pieces"]
            drawing = self.teams[side].profile.set_pieces.foul_drawing
            foul_p *= 1 + sp["foul_drawing"] * drawing
            if self.minute >= sp["late_minute"] and self.lead(side) > 0:
                foul_p *= sp["late_leader_fouls"]
        if card is not None or self.rng.random() < min(foul_p, 0.95):
            r = 1.0 if card is not None else self.rng.random()
            can_send_off = (
                len(team.on_pitch) > ch["min_players"]
                and defender != team.keeper
                and self.scenario is None
            )
            if card is not None:
                outcome = card
            elif r < ch["red_per_foul"] and can_send_off:
                outcome = "red_card"
            elif r < ch["red_per_foul"] + ch["yellow_per_foul"]:
                outcome = "yellow_card"
            else:
                outcome = "fail"
            self.emit(
                frame, defence, defender, "foul", outcome, at, at, self.foot(), **qual
            )
            self.tick(25)
            if outcome == "red_card":
                team.send_off(defender)
                self.tick(60)
            self.free_kick(side, at)
            return
        self.emit(frame, defence, defender, "tackle", "success", at, at, self.foot())
        self.tick(1.5)
        self.turnover(defence, defender, at)

    def carry(self, frame, pressed):
        side = self.attack
        bx, by = own(side, *self.ball)
        length = self.rng.uniform(4, 12)
        angle = math.radians(
            self.rng.gauss(0, 35) if bx < 95 else self.rng.choice((-80, 80))
        )
        end = on_pitch(
            *own(side, bx + length * math.cos(angle), by + length * math.sin(angle))
        )
        self.emit(
            frame,
            side,
            self.carrier,
            "dribble",
            "success",
            self.ball,
            end,
            self.foot(),
            12.0,
        )
        self.tick(dist(self.ball, end) / 5.5)
        self.ball = end
        if pressed and self.rng.random() < 0.15:
            frame.positions[(side, self.carrier)] = end
            defender, _ = frame.nearest(1 - side, end)
            self.challenge(frame, defender)

    def take_on(self, frame, presser_dist):
        side = self.attack
        ok = self.rng.random() < 0.55 - 0.25 * pressure_load(presser_dist)
        bx, by = own(side, *self.ball)
        end = (
            on_pitch(
                *own(side, bx + self.rng.uniform(3, 6), by + self.rng.uniform(-3, 3))
            )
            if ok
            else self.ball
        )
        self.emit(
            frame,
            side,
            self.carrier,
            "take_on",
            "success" if ok else "fail",
            self.ball,
            end,
            self.foot(),
        )
        self.tick(2)
        if ok:
            self.ball = end
        else:
            defender, _ = frame.nearest(1 - side, self.ball)
            self.challenge(frame, defender)

    def clearance(self, frame):
        side, defence = self.attack, 1 - self.attack
        bx, by = own(side, *self.ball)
        end = on_pitch(
            *own(side, bx + self.rng.uniform(35, 55), by + self.rng.gauss(0, 12))
        )
        self.emit(
            frame,
            side,
            self.carrier,
            "clearance",
            "success",
            self.ball,
            end,
            self.foot(),
            80.0,
        )
        self.tick(4)
        if self.rng.random() < 0.15:
            self.throw_in(defence, end)
            return
        keep = self.rng.random() < self.cfg["clearance_kept"]
        who = side if keep else defence
        player, _ = frame.nearest(
            who, end, outfield_only=True, keeper=self.teams[who].keeper
        )
        if keep:
            self.new_possession(side, player, end, same=True)
        else:
            self.turnover(defence, player, end)

    def shot(self, frame, kind="shot", forced=None, min_xg=None, **qual):
        """A shot. `forced` True/False scripts the result; `min_xg` raises its xG.

        In scenario mode the engine scores no goals of its own.
        """
        side, defence = self.attack, 1 - self.attack
        bx, by = own(side, *self.ball)
        header = (
            kind == "shot"
            and self.assist in ("cross", "set_piece")
            and self.rng.random() < 0.6
        )
        bonus = 0.0
        if self.assist == "set_piece":
            threat = self.teams[side].profile.set_pieces.threat
            bonus = self.cfg["set_pieces"]["threat_xg"] * (threat - 0.5)
        chance = xg(self.cfg, bx, by, header, self.assist, bonus)
        if min_xg is not None:
            chance = max(chance, min_xg)
        if forced is None:
            goal = self.rng.random() < chance and self.scenario is None
        else:
            goal = forced
        on_target = (
            goal
            or forced is False
            or self.rng.random() < self.cfg["shots"]["save_share"]
        )
        aim_y = (
            GOAL_Y + self.rng.uniform(-3.5, 3.5)
            if on_target
            else GOAL_Y + self.rng.choice((-1, 1)) * self.rng.uniform(4, 9)
        )
        end = own(side, LENGTH, aim_y)
        self.emit(
            frame,
            side,
            self.carrier,
            kind,
            "success" if goal else "fail",
            self.ball,
            end,
            "head" if header else self.foot(),
            self.rng.uniform(60, 110),
            xg=round(chance, 3),
            assist=self.assist,
            **qual,
        )
        self.tick(3)
        if goal:
            self.teams[side].goals += 1
            self.tick(50)
            self.kickoff(defence)
        elif on_target:
            keeper = self.teams[defence].keeper
            spot = own(side, LENGTH - 1, aim_y)
            frame.positions[(defence, keeper)] = spot
            self.emit(
                frame, defence, keeper, "keeper_save", "success", spot, spot, "other"
            )
            self.tick(3)
            if self.rng.random() < self.cfg["shots"]["corner_after_save"]:
                self.corner(side)
            else:
                self.turnover(defence, keeper, spot)
        else:
            sp = self.cfg["set_pieces"]
            seeking = self.teams[side].profile.set_pieces.corner_seeking
            if self.rng.random() < sp["shot_to_corner"] * (1 + seeking):
                self.tick(15)
                self.corner(side)
            else:
                self.tick(20)
                self.goalkick(defence)

    # ---- counters and scripted beats -----------------------------------------

    def channel_target(self, frame, side, behind=None):
        """(runner, target, label): a ball into the channel behind the opponent's
        full-back (`behind`, or the ball-side / more advanced one), or None."""
        opp = 1 - side
        fullbacks = self.teams[opp].fullbacks()
        if not fullbacks:
            return None
        if behind is None:
            _, by = own(opp, *self.ball)
            behind = ball_side(by, self.cfg)
            if behind not in fullbacks:
                behind = max(
                    fullbacks,
                    key=lambda s: own(opp, *frame.positions[(opp, fullbacks[s])])[0],
                )
        if behind not in fullbacks:
            return None
        fx, fy = own(opp, *frame.positions[(opp, fullbacks[behind])])
        tx = clamp(fx - 15, 12, 80)
        ty = clamp(fy + (-4 if fy > GOAL_Y else 4), 6, WIDTH - 6)
        target = on_pitch(*own(opp, tx, ty))

        team = self.teams[side]
        n = team.profile.on_regain.runners if team.profile.on_regain else 2
        outfield = [p for (s, p) in frame.positions if s == side and p != team.keeper]
        outfield.sort(key=lambda p: (-own(side, *frame.positions[(side, p)])[0], p))
        runner = min(
            outfield[:n], key=lambda p: (dist(frame.positions[(side, p)], target), p)
        )
        return runner, target, f"behind_{behind}_fullback"

    def due_beat(self):
        if not self.scenario:
            return None
        for beat in self.scenario.scripted():
            lo, hi = beat.minute
            if beat.id not in self.done and lo <= self.minute <= hi:
                return beat
        return None

    def play_beat(self, beat):
        """Script: the victim attacks down `behind` with the full-back high, loses
        the ball, and the other team counters into the channel behind that
        full-back. Then a goal, a miss, or a last-man red card."""
        self.done.add(beat.id)
        named = 0 if beat.team == "home" else 1
        victim = named if beat.action == "red_card_last_man" else 1 - named
        counter = 1 - victim
        tag = {"scenario_beat": beat.id}
        flank = 54.0 if beat.behind == "left" else WIDTH - 54.0

        # 1. Victim attacking on that flank; the forward pass is intercepted.
        self.restart()
        start = own(victim, 68.0, flank)
        self.new_possession(victim, self.teams[victim].front_player, start)
        frame, _ = self.frame(pressed=False)
        self.carrier, _ = frame.nearest(
            victim, start, outfield_only=True, keeper=self.teams[victim].keeper
        )
        frame, _ = self.frame(pressed=False)
        aim = own(victim, 84.0, flank + (-8 if beat.behind == "left" else 8))
        self.emit(
            frame,
            victim,
            self.carrier,
            "pass",
            "fail",
            start,
            aim,
            self.foot(),
            50.0,
            **tag,
        )
        mid = ((start[0] + aim[0]) / 2, (start[1] + aim[1]) / 2)
        interceptor, _ = frame.nearest(counter, mid)
        frame.positions[(counter, interceptor)] = mid
        self.emit(
            frame,
            counter,
            interceptor,
            "interception",
            "success",
            mid,
            mid,
            self.foot(),
            **tag,
        )
        self.tick(2)
        self.turnover(counter, interceptor, mid)
        self.just_won = False

        # 2. Long ball into the channel behind the full-back.
        frame, _ = self.frame(pressed=False)
        runner, target, label = self.channel_target(frame, counter, beat.behind)
        self.pass_(
            frame,
            10.0,
            forced={"receiver": runner, "target": target, "ok": True},
            qual={**tag, "counter": True, "channel": label},
        )

        # 3a. Last-man foul.
        if beat.action == "red_card_last_man":
            frame, _ = self.frame(pressed=False)
            by_role = {r: p for p, r in self.teams[victim].roles.items()}
            defender = by_role.get(beat.role)
            if defender is None:
                defender, _ = frame.nearest(
                    victim,
                    self.ball,
                    outfield_only=True,
                    keeper=self.teams[victim].keeper,
                )
            self.challenge(frame, defender, card="red_card", last_man=True, **tag)
            return

        # 3b. Carry towards goal, then the shot.
        frame, _ = self.frame(pressed=False)
        _, cy = own(counter, *self.ball)
        end = own(counter, 93.0, GOAL_Y + clamp(cy - GOAL_Y, -7, 7))
        self.emit(
            frame,
            counter,
            self.carrier,
            "dribble",
            "success",
            self.ball,
            end,
            self.foot(),
            14.0,
            counter=True,
            **tag,
        )
        self.tick(dist(self.ball, end) / 7.0)
        self.ball = end
        frame, _ = self.frame(pressed=False)
        self.shot(
            frame,
            forced=beat.action == "counter_goal",
            min_xg=beat.min_xg,
            counter=True,
            **tag,
        )


def _cm(x, y):
    return round(x, 2), round(y, 2)


def score(sim_match):
    """(home goals, away goals) from the events."""
    home = sim_match.match.home_team
    goals = [
        e
        for e in sim_match.events
        if e.type.startswith("shot") and e.outcome == "success"
    ]
    h = sum(1 for e in goals if e.team_id == home)
    return h, len(goals) - h


__all__ = ["SimulatedMatch", "load_config", "score", "simulate_match"]
