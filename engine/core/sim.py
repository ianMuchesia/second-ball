"""Possession-chain state machine. Same seed = identical match.

Each step the ball carrier picks pass / carry / take-on / shot (or clearance)
from zone, team style and pressure. Failed passes become interceptions,
tackles or loose balls and can open a counterpress window. Shots resolve
via xG. Late on, the leading team drops its block, the trailing team speeds
up, fatigue lowers the press, and red cards remove players.
"""

import math
import random
from dataclasses import dataclass
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
from engine.league import COMPETITION
from engine.weather import load_weather

CONFIG = Path(__file__).parent.parent / "config" / "engine.yaml"
DEFAULT_KICKOFF = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def load_config(path=CONFIG):
    return yaml.safe_load(Path(path).read_text())


@dataclass
class SimulatedMatch:
    match: Match
    events: list


def simulate_match(
    home, away, seed, weather="dry", kickoff=DEFAULT_KICKOFF, config=None
):
    """Simulate one match between two ClubProfiles. Returns Match + list[MatchEvent]."""
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
    )
    sim = _Sim(match, home, away, cfg, load_weather()[weather])
    return SimulatedMatch(match, sim.run())


class _Sim:
    def __init__(self, match, home, away, cfg, weather):
        self.match = match
        self.cfg = cfg
        self.wx = weather
        self.rng = random.Random(match.seed)
        self.teams = (TeamState.start(0, home), TeamState.start(1, away))
        self.events = []
        self.t = 0.0
        self.period = 1
        self.possessions = 0
        self.attack = 0
        self.carrier = 0
        self.ball = centre_spot()
        self.assist = "none"
        self.passes = 0
        self.counterpress = None  # (side, until_t)

    # ---- clock and game state -------------------------------------------------

    @property
    def minute(self):
        return int(self.t // 60)

    def tick(self, seconds):
        self.t += max(0.5, seconds)

    def late(self):
        return self.minute >= self.cfg["game_state"]["late_minute"]

    def lead(self, side):
        return self.teams[side].goals - self.teams[1 - side].goals

    def block_height(self, side):
        team = self.teams[side]
        drop = (
            team.profile.late_lead_block_drop
            if self.late() and self.lead(side) > 0
            else 0
        )
        return team.profile.block_height - drop

    def directness(self, side):
        extra = (
            self.cfg["game_state"]["trailing_directness"]
            if self.late() and self.lead(side) < 0
            else 0
        )
        return clamp(self.teams[side].profile.directness + extra, 0, 1)

    def seconds_per_action(self, side):
        spa = self.teams[side].profile.tempo.seconds_per_action
        if self.late() and self.lead(side) < 0:
            spa *= self.cfg["game_state"]["trailing_tempo"]
        return spa

    def legs(self):
        return fatigue(self.cfg, self.minute, self.wx.fatigue_rate)

    def press_intensity(self, side, carrier_x):
        """How hard `side` presses a carrier at carrier_x (carrier's frame)."""
        pr = self.cfg["pressing"]
        intensity = 1.0
        if carrier_x < pr["high_press_zone_x"]:
            intensity = pr["ppda_reference"] / self.teams[side].profile.target_ppda
        if self.late() and self.lead(side) > 0:
            intensity *= self.cfg["game_state"]["leading_press"]
        return intensity * self.legs()

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
        )
        return frame, presser_dist

    def step(self):
        attack, defence = self.attack, 1 - self.attack
        frame, presser_dist = self.frame()
        bx, by = own(attack, *self.ball)
        pressed = presser_dist <= self.cfg["under_pressure_m"]

        regain = self.cfg["pressing"]["counterpress_regain"] * self.legs()
        if pressed and self.counterpressing(defence) and self.rng.random() < regain:
            presser, _ = frame.nearest(defence, self.ball)
            self.challenge(frame, presser)
            return

        choice = self.choose_action(bx, by, pressed)
        if choice == "shot":
            self.shot(frame)
        elif choice == "carry":
            self.carry(frame, pressed)
        elif choice == "take_on":
            self.take_on(frame, presser_dist)
        elif choice == "clearance":
            self.clearance(frame)
        else:
            self.pass_(frame, presser_dist)

    def choose_action(self, bx, by, pressed):
        shots = self.cfg["shots"]
        target = self.teams[self.attack].profile.tempo.passes_per_possession
        w = {
            "pass": 1.0 * (1.2 if self.passes < target else 1.0),
            "carry": (0.15 if pressed else 0.45) * (0.3 if bx > 95 else 1.0),
            "take_on": 0.05 + (0.15 if pressed and bx > 55 else 0.0),
            "clearance": 0.6 if pressed and bx < 25 else 0.0,
            "shot": 0.0,
        }
        if bx >= shots["min_x"]:
            header = self.assist == "cross"
            chance = xg(self.cfg, bx, by, header, self.assist)
            boost = 3.0 if self.assist in ("cross", "through_ball") else 1.0
            w["shot"] = shots["bias"] * chance * boost * (0.6 if pressed else 1.0)
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
        """Record one event in the acting team's SPADL frame."""
        me = (side, player)
        pos = frame.positions.get(me, start)
        nearest = min(
            (dist(pos, p) for (s, _), p in frame.positions.items() if s != side),
            default=math.inf,
        )
        sx, sy = own(side, *on_pitch(*start))
        ex, ey = own(side, *on_pitch(*end))
        players = []
        for (s, pl), (x, y) in frame.positions.items():
            fx, fy = own(side, x, y)
            players.append(
                {
                    "player_id": self.teams[s].profile.player_id(pl),
                    "team_id": self.teams[s].profile.id,
                    "x": fx,
                    "y": fy,
                    "facing_deg": own_facing(side, frame.facing[(s, pl)]),
                }
            )
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
            qualifiers=qual,
            freeze_frame=players,
        )
        self.events.append(event)
        return event

    def foot(self):
        return "foot_right" if self.rng.random() < 0.7 else "foot_left"

    # ---- restarts -------------------------------------------------------------

    def kickoff(self, side):
        self.counterpress = None
        team = self.teams[side]
        self.new_possession(side, team.on_pitch[-1], centre_spot())
        frame, _ = self.frame(pressed=False)
        self.pass_(frame, 10.0, kind="pass", restart=True, backwards=True)

    def goalkick(self, side):
        self.counterpress = None
        self.new_possession(side, self.teams[side].keeper, keeper_spot(side))
        frame, _ = self.frame(pressed=False)
        self.pass_(frame, 10.0, kind="goalkick", restart=True)

    def throw_in(self, side, at):
        self.counterpress = None
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
        self.counterpress = None
        self.new_possession(
            side,
            self.carrier if self.attack == side else self.teams[side].on_pitch[-1],
            at,
        )
        bx, by = own(side, *at)
        frame, _ = self.frame(pressed=False)
        if bx > 80 and abs(by - GOAL_Y) < 15 and self.rng.random() < 0.3:
            self.assist = "set_piece"
            self.shot(frame, kind="shot_freekick")
        else:
            self.pass_(frame, 10.0, kind="freekick_short", restart=True)

    def corner(self, side):
        self.counterpress = None
        y_own = 0.0 if self.rng.random() < 0.5 else WIDTH
        spot = own(side, LENGTH, y_own)
        frame, _ = self.frame(pressed=False)
        taker, _ = frame.nearest(
            side, spot, outfield_only=True, keeper=self.teams[side].keeper
        )
        self.new_possession(side, taker, spot)
        frame, _ = self.frame(pressed=False)
        target = own(side, self.rng.uniform(95, 101), self.rng.uniform(28, 40))
        ok = (
            self.rng.random()
            < self.cfg["shots"]["corner_success"] * self.wx.cross_accuracy
        )
        self.emit(
            frame,
            side,
            taker,
            "corner_crossed",
            "success" if ok else "fail",
            spot,
            target,
            self.foot(),
            70.0,
        )
        self.tick(4)
        if ok:
            receiver, _ = frame.nearest(side, target, exclude={(side, taker)})
            self.new_possession(side, receiver, target, assist="cross", same=True)
        else:
            defender, _ = frame.nearest(1 - side, target)
            self.turnover(1 - side, defender, target)

    # ---- actions --------------------------------------------------------------

    def pass_(self, frame, presser_dist, kind="pass", restart=False, backwards=False):
        side, carrier = self.attack, self.carrier
        start = self.ball
        bx, by = own(side, *start)
        directness = self.directness(side)

        cross = (
            kind == "pass"
            and bx > 78
            and (by < 16 or by > WIDTH - 16)
            and self.rng.random() < self.cfg["cross_share"]
        )
        if cross:
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
        )
        p *= self.wx.pass_success
        if d > 30:
            p *= self.wx.long_pass_accuracy
        if cross:
            p *= self.wx.cross_accuracy
        ok = self.rng.random() < p

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
        self.failed_pass(frame, side, receiver, start, target)

    def pick_receiver(self, frame, side, carrier, bx, directness, backwards):
        team = self.teams[side]
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
            names.append(pl)
            weights.append(max(w, 1e-6))
            spots.append(pos)
        i = self.rng.choices(range(len(names)), weights=weights)[0]
        return names[i], spots[i]

    def failed_pass(self, frame, side, receiver, start, target):
        defence = 1 - side
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

    def challenge(self, frame, defender):
        """`defender` goes in on the carrier: foul (maybe a card) or a won tackle."""
        side, defence = self.attack, 1 - self.attack
        at = self.ball
        frame.positions[(defence, defender)] = at
        ch = self.cfg["challenges"]
        if self.rng.random() < ch["foul"]:
            r = self.rng.random()
            team = self.teams[defence]
            can_send_off = (
                len(team.on_pitch) > ch["min_players"] and defender != team.keeper
            )
            if r < ch["red_per_foul"] and can_send_off:
                outcome = "red_card"
            elif r < ch["red_per_foul"] + ch["yellow_per_foul"]:
                outcome = "yellow_card"
            else:
                outcome = "fail"
            self.emit(frame, defence, defender, "foul", outcome, at, at, self.foot())
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

    def shot(self, frame, kind="shot"):
        side, defence = self.attack, 1 - self.attack
        bx, by = own(side, *self.ball)
        header = kind == "shot" and self.assist == "cross" and self.rng.random() < 0.6
        chance = xg(self.cfg, bx, by, header, self.assist)
        goal = self.rng.random() < chance
        on_target = goal or self.rng.random() < self.cfg["shots"]["save_share"]
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
            self.tick(20)
            self.goalkick(defence)


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
