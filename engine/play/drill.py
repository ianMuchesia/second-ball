"""Stage 1, the drill pitch: one attacker, one defender, one keeper, a loose ball.

The attacker drives at goal with the ball and takes a heavy touch. From then
on nobody is told who wins it: each player reads where the ball is going and
goes for the first point he can reach before it; whoever gets there and can
control it (close enough, low enough, slow enough) has it. Only then is an
event written. The same seed gives the same drill, byte for byte.

    uv run python -m engine.play --seed 3 --out runs/drill-3
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.contracts import Match, MatchEvent
from engine.core.lineup import lineup
from engine.core.motion import Sample, Tracks
from engine.core.pitch import GOAL_HALF_WIDTH, GOAL_Y, LENGTH, WIDTH, own, own_facing
from engine.core.sim import DEFAULT_KICKOFF, load_config
from engine.league import COMPETITION
from engine.play import referee
from engine.play.ball import Ball, predict
from engine.play.player import Player, intercept

CONFIG = Path(__file__).resolve().parents[1] / "config" / "play.yaml"
BOX_DEPTH, BOX_HALF = 16.5, 20.16
CROSSBAR = 2.44


def load_play(path=CONFIG):
    return yaml.safe_load(Path(path).read_text())


@dataclass
class DrillResult:
    match: Match
    events: list
    tracks: Tracks
    # attacker_kept | defender_won | keeper_claimed | keeper_won_at_feet | out_of_play | none
    outcome: str
    won_sample: int | None = None  # the sample where someone took control


class Drill:
    def __init__(self, home, away, seed, cfg=None):
        self.cfg = cfg or load_play()
        self.rng = random.Random(f"drill-{seed}")
        engine = load_config()
        self.under_pressure_m = engine["under_pressure_m"]
        self.keeper_ratio = engine["motion"]["keeper_ratio"]
        self.keeper_max_m = engine["motion"]["keeper_max_m"]
        sheets = [*lineup(home), *lineup(away)]
        self.match = Match(
            match_id=f"drill-{home.id}-{away.id}-{seed}",
            home_team=home.id,
            away_team=away.id,
            venue=home.stadium,
            kickoff=DEFAULT_KICKOFF,
            competition=COMPETITION,
            seed=seed,
            weather="dry",
            mode="free_simulation",
            home_strength=home.strength,
            away_strength=away.strength,
            lineups=sheets,
        )

        def pick(team, positions):
            for want in positions:
                for i, s in enumerate(sheets):
                    if s.team_id == team and s.starting and s.position == want:
                        return i, s
            raise ValueError(f"{team} has none of {positions}")

        r = self.rng
        ax, ay = r.uniform(58.0, 66.0), r.uniform(24.0, 44.0)
        dx, dy = ax + r.uniform(9.0, 18.0), ay + r.uniform(-9.0, 9.0)
        i, s = pick(home.id, ["ST", "AM", "LW", "RW"])
        self.attacker = Player((0, i), s.player_id, s.team_id, False, ax, ay, 5.0, 0.0)
        i, s = pick(away.id, ["CB", "RCB", "LCB"])
        self.defender = Player(
            (1, i), s.player_id, s.team_id, False, dx, dy, facing=180.0
        )
        i, s = pick(away.id, ["GK"])
        self.keeper = Player(
            (1, i), s.player_id, s.team_id, True, 103.5, GOAL_Y, facing=180.0
        )
        self.players = [self.attacker, self.defender, self.keeper]

        self.ball = Ball(ax + self.cfg["ball"]["carry_ahead"], ay)
        self.owner = self.attacker
        self.last_touch = self.attacker
        self.touch_t = -1.0
        self.dead = False
        self.t = 0.0
        self.events = []
        self.outcome = "none"
        self.won_at = None
        self.won_sample = None
        self.in_hands = False  # the keeper holds it (not at his feet)
        self.chasing = {}  # key -> seconds until he meets the ball
        slots = [s.player_id for s in sheets] + [referee.SLOT]
        self.ref = referee.make()
        self.slot = {pid: k for k, pid in enumerate(slots)}
        self.tracks = Tracks(hz=round(1 / self.cfg["dt"]), slots=slots)

    # ---- the loop ---------------------------------------------------------------

    def run(self):
        c = self.cfg
        dt = c["dt"]
        self.record()
        while self.t < c["drill"]["length_s"] - 1e-9:
            if (
                self.won_at is not None
                and self.t >= self.won_at + c["drill"]["after_control_s"]
            ):
                break
            if self.dead and self.t >= self.touch_t + 1.0 and self.won_at is None:
                break
            if (
                self.owner is self.attacker
                and self.t >= c["drill"]["touch_at_s"] - 1e-9
                and self.touch_t < 0
            ):
                self.heavy_touch()
            self.t = round(self.t + dt, 6)
            targets = self.decide()
            for pl in self.players:
                tgt, cap = targets[pl.key]
                p = c["player"]
                if pl is self.owner and self.in_hands:
                    # Gone down on the ball (a smother): he stops in a metre
                    # or two, he does not run on holding it.
                    p = {
                        **p,
                        "decel": p["smother_decel"],
                        "lateral": p["smother_decel"],
                    }
                pl.move(tgt, cap, dt, p, arrive_in=self.chasing.get(pl.key))
                pl.face(self.ball.pos, dt, c["player"])
            self.separate()
            referee.step(self.ref, self.ball.pos, dt, c["player"], c["referee"])
            if self.owner is not None:
                self.carry()
            else:
                self.ball.step(dt, c["ball"], c["substeps"])
                self.check_out()
            won = None if self.dead or self.owner is not None else self.control()
            self.record()
            if won is not None:
                self.take(won)
        return DrillResult(
            self.match, self.events, self.tracks, self.outcome, self.won_sample
        )

    def heavy_touch(self):
        """The attacker knocks it too far ahead: a loose ball (event first, so
        it sits on the sample where the ball is still at his feet)."""
        c, r = self.cfg["drill"], self.rng
        a = self.attacker
        to_goal = math.degrees(math.atan2(GOAL_Y - a.y, LENGTH - a.x))
        angle = to_goal + r.uniform(-c["touch_angle_deg"], c["touch_angle_deg"])
        speed = r.uniform(*c["touch_speed"])
        path_ball = self.ball.copy()
        path_ball.kick(speed, angle)
        p = self.cfg["predict"]
        rest = predict(
            path_ball, self.cfg["ball"], 30.0, p["step_s"], self.cfg["substeps"]
        )[-1]
        self.emit(
            a, "bad_touch", "fail", self.ball.pos, (rest[1], rest[2]), speed * 3.6
        )
        self.ball.kick(speed, angle)
        self.owner = None
        self.last_touch = a
        self.touch_t = self.t
        for pl in self.players:
            pl.react_at = self.t + self.cfg["player"]["reaction_s"]

    # ---- decisions ----------------------------------------------------------------

    def reach(self, pl):
        """(metres, height) he can play the ball within: hands for a keeper in his area."""
        k = self.cfg["control"]
        if pl.keeper and self.in_box(pl.pos) and self.in_box(self.stops_at(pl)):
            return k["keeper_hands_m"], k["keeper_height_m"]
        return k["feet_m"], k["feet_height_m"]

    def stops_at(self, pl):
        """Where a keeper going down on the ball now would come to rest."""
        v = pl.speed
        if v < 0.1:
            return pl.pos
        slide = v * v / (2.0 * self.cfg["player"]["smother_decel"])
        return pl.x + pl.vx / v * slide, pl.y + pl.vy / v * slide

    def in_box(self, pos):
        return pos[0] >= LENGTH - BOX_DEPTH and abs(pos[1] - GOAL_Y) <= BOX_HALF

    def decide(self):
        """Every player's (target, speed cap) for this step."""
        pc = self.cfg["player"]
        out = {}
        self.closing = {}
        if self.owner is None:
            pred = self.cfg["predict"]
            path = predict(
                self.ball,
                self.cfg["ball"],
                pred["horizon_s"],
                pred["step_s"],
                self.cfg["substeps"],
            )
            best = {}
            for pl in self.players:
                if self.t < pl.react_at:  # still reacting: carries on as he was
                    out[pl.key] = ((pl.x + pl.vx, pl.y + pl.vy), max(pl.speed, 0.5))
                    continue
                r, h = self.reach(pl)
                tau, point = intercept(pl, path, self.t, r, h, pc)
                if pl.keeper and not self.in_box(point):
                    continue  # a keeper leaves his area for nothing in a drill
                side = pl.key[0]
                if side not in best or tau < best[side][0]:
                    best[side] = (tau, pl, point)
            chasers = {b[1].key: b[2] for b in best.values()}
            self.chasing = {b[1].key: b[0] for b in best.values()}
            # The last few metres: straight at the ball, a little ahead of
            # where it rolls, a little faster than it (closes, never trails).
            ball = self.ball
            near = self.cfg["control"]["approach_m"]
            for side, (tau, pl, point) in best.items():
                if math.dist(pl.pos, ball.pos) <= near:
                    lead = self.cfg["control"]["approach_lead_s"]
                    chasers[pl.key] = (ball.x + ball.vx * lead, ball.y + ball.vy * lead)
                    self.chasing[pl.key] = 0.0
                    self.closing[pl.key] = min(
                        pc["top_speed"],
                        ball.ground_speed + self.cfg["control"]["approach_gain"],
                    )
            for pl in self.players:
                if pl.key in out:
                    continue
                if pl.key in chasers:
                    out[pl.key] = (
                        chasers[pl.key],
                        self.closing.get(pl.key, pc["top_speed"]),
                    )
                elif pl.keeper:
                    out[pl.key] = (self.keeper_spot(self.ball.pos), 5.5)
                else:
                    out[pl.key] = (self.goal_side(pl, self.ball.pos, 6.0), 5.5)
            return out
        self.chasing = {}
        o = self.owner
        for pl in self.players:
            if pl is o:
                out[pl.key] = self.on_ball(pl)
            elif pl.keeper:
                out[pl.key] = (self.keeper_spot(self.ball.pos), 5.5)
            elif self.in_hands:  # the keeper has it in his hands: give him room
                out[pl.key] = (self.away_from(pl, o.pos, 12.0), 4.0)
            else:  # close down, goal-side, at arm's length (no tackles yet)
                out[pl.key] = (self.goal_side(pl, o.pos, 1.5), pc["top_speed"])
        return out

    def on_ball(self, pl):
        pc = self.cfg["player"]
        if pl.keeper:
            return pl.pos, 0.0
        if pl.key[0] == 0:  # attacking +x: drive at goal
            return (min(pl.x + 8.0, LENGTH - 6.0), pl.y + (GOAL_Y - pl.y) * 0.3), pc[
                "dribble_speed"
            ]
        rival = self.attacker  # a defender with it shields, stepping away
        dx, dy = pl.x - rival.x, pl.y - rival.y
        d = math.hypot(dx, dy) or 1.0
        return (pl.x + dx / d * 3.0, pl.y + dy / d * 3.0), 2.0

    def goal_side(self, pl, of, gap):
        """`gap` metres from `of` towards the goal `pl` defends (negative: further away)."""
        goal = (LENGTH, GOAL_Y) if pl.key[0] == 1 else (0.0, GOAL_Y)
        dx, dy = goal[0] - of[0], goal[1] - of[1]
        d = math.hypot(dx, dy) or 1.0
        return of[0] + dx / d * gap, of[1] + dy / d * gap

    def away_from(self, pl, of, gap):
        """`gap` metres upfield of `of` (towards `pl`'s own goal), on `pl`'s
        side of it: he backs off round the man, not through him."""
        back = -1.0 if pl.key[0] == 0 else 1.0
        side = pl.y - of[1]
        if abs(side) < 2.0:
            side = 2.0 if side >= 0 else -2.0
        x, y = of[0] + back * gap, of[1] + side
        return min(max(x, 1.0), LENGTH - 1.0), min(max(y, 1.0), WIDTH - 1.0)

    def keeper_spot(self, ball):
        """On the line from the middle of the goal to the ball, off his line by
        a share of the ball's distance (the current engine's rule)."""
        gx, gy = LENGTH, GOAL_Y
        d = math.hypot(ball[0] - gx, ball[1] - gy) or 1.0
        r = max(1.5, min(self.keeper_max_m, self.keeper_ratio * d))
        return gx + (ball[0] - gx) / d * r, gy + (ball[1] - gy) / d * r

    def separate(self):
        """Bodies do not pass through each other: two players closer than
        `body_m` are eased apart along the line between them (half each)."""
        gap = self.cfg["player"]["body_m"]
        most = self.cfg["player"]["push_m"]
        for i, a in enumerate(self.players):
            for b in self.players[i + 1 :]:
                dx, dy = b.x - a.x, b.y - a.y
                d = math.hypot(dx, dy)
                if 0.0 < d < gap:
                    push = min(most, (gap - d) / 2.0)
                    a.x, a.y = a.x - dx / d * push, a.y - dy / d * push
                    b.x, b.y = b.x + dx / d * push, b.y + dy / d * push

    # ---- the ball ---------------------------------------------------------------

    def carry(self):
        o, b = self.owner, self.ball
        if self.in_hands:
            b.x, b.y, b.h = o.x, o.y, 1.1
        else:
            a = math.radians(o.facing)
            ahead = self.cfg["ball"]["carry_ahead"]
            b.x, b.y, b.h = o.x + ahead * math.cos(a), o.y + ahead * math.sin(a), 0.0
        b.vx, b.vy, b.vh = o.vx, o.vy, 0.0

    def control(self):
        """Who has the loose ball now: within reach, low enough and slow
        enough relative to him. The nearest such player; none if nobody."""
        k = self.cfg["control"]
        b = self.ball
        best = None
        for pl in self.players:
            if pl is self.last_touch and self.t - self.touch_t < 0.3:
                continue  # the ball has only just left his foot
            r, h = self.reach(pl)
            d = math.dist(pl.pos, b.pos)
            hands = r == k["keeper_hands_m"] and pl.keeper
            limit = k["keeper_speed"] if hands else k["feet_speed"]
            rel = math.hypot(b.vx - pl.vx, b.vy - pl.vy)
            if (
                d <= r
                and b.h <= h
                and rel <= limit
                and (best is None or (d, pl.key) < best[0])
            ):
                best = ((d, pl.key), pl)
        return None if best is None else best[1]

    def take(self, pl):
        """`pl` has it. An event only when the ball changes team."""
        lost = self.last_touch
        self.in_hands = (
            pl.keeper and self.reach(pl)[0] == self.cfg["control"]["keeper_hands_m"]
        )
        self.owner = pl
        self.last_touch = pl
        self.won_at = self.t
        self.won_sample = len(self.tracks.samples) - 1
        b = self.ball
        if pl.key[0] == lost.key[0]:
            self.outcome = "attacker_kept" if pl is self.attacker else "defender_won"
            return
        if self.in_hands:
            self.outcome = "keeper_claimed"
            self.emit(pl, "keeper_pick_up", "success", b.pos, b.pos, None, body="other")
        else:
            self.outcome = (
                "keeper_won_at_feet"
                if pl.keeper
                else "defender_won"
                if pl.key[0] == 1
                else "attacker_kept"
            )
            self.emit(pl, "interception", "success", b.pos, b.pos, None)
        self.carry()

    def check_out(self):
        b = self.ball
        r = 0.11  # the whole ball over the line
        if -r <= b.x <= LENGTH + r and -r <= b.y <= WIDTH + r:
            return
        if b.x > LENGTH and abs(b.y - GOAL_Y) < GOAL_HALF_WIDTH and b.h < CROSSBAR:
            self.outcome = "rolled_into_goal"
        else:
            self.outcome = "out_of_play"
        self.dead = True
        b.vx = b.vy = b.vh = 0.0

    # ---- records ----------------------------------------------------------------

    def record(self):
        players = [None] * len(self.tracks.slots)
        for pl in self.players:
            players[self.slot[pl.player_id]] = (pl.x, pl.y, pl.facing)
        players[self.slot[referee.SLOT]] = (self.ref.x, self.ref.y, self.ref.facing)
        b = self.ball
        self.tracks.samples.append(
            Sample(self.t, 1, players, (b.x, b.y, b.h), self.dead)
        )

    def emit(self, pl, type_, outcome, start, end, speed_kmh, body="foot_right"):
        side = pl.key[0]
        cm = lambda v: round(v, 2)
        frame, me, opp = [], None, []
        for q in self.players:
            fx, fy = own(side, q.x, q.y)
            frame.append(
                {
                    "player_id": q.player_id,
                    "team_id": q.team_id,
                    "x": cm(min(max(fx, 0.0), LENGTH)),
                    "y": cm(min(max(fy, 0.0), WIDTH)),
                    "facing_deg": round(own_facing(side, q.facing), 1) % 360,
                }
            )
            if q is pl:
                me = (fx, fy)
            elif q.key[0] != side:
                opp.append((fx, fy))
        sx, sy = own(side, *start)
        ex, ey = own(side, *end)
        clampx = lambda v: cm(min(max(v, 0.0), LENGTH))
        clampy = lambda v: cm(min(max(v, 0.0), WIDTH))
        n = len(self.events) + 1
        ev = MatchEvent(
            event_id=f"{self.match.match_id}-e{n:05d}",
            match_id=self.match.match_id,
            possession_id=f"{self.match.match_id}-p0001",
            period=1,
            minute=int(self.t // 60),
            second=int(self.t % 60),
            team_id=pl.team_id,
            player_id=pl.player_id,
            type=type_,
            outcome=outcome,
            body_part=body,
            start_x=clampx(sx),
            start_y=clampy(sy),
            end_x=clampx(ex),
            end_y=clampy(ey),
            under_pressure=min((math.dist(me, o) for o in opp), default=99.0)
            <= self.under_pressure_m,
            ball_speed_kmh=None if speed_kmh is None else round(speed_kmh, 1),
            qualifiers={"drill": True},
            freeze_frame=frame,
        )
        self.events.append(ev)
        self.tracks.events[ev.event_id] = len(self.tracks.samples) - 1


def run_drill(home, away, seed, cfg=None):
    return Drill(home, away, seed, cfg).run()
