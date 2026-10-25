"""Stage 2: playing on after possession. The attack.

A Riverside midfielder plays the striker in against a Harbour centre-back, a
Harbour midfielder (the outlet) and the keeper. Nothing is scripted after the
first pass: every player looks at the live ball, his opponents, the space and
the goal about every 0.4 s (and at once when the ball changes hands) and
decides what to do next.

- The carrier dribbles touch by touch (the ball is out of his feet between
  touches), picks a heading by space and progress (and keeps it unless a new
  one is clearly better), knocks it past a man who is off balance or flat,
  passes when a safe pass beats carrying, shoots when the chance is good.
- The defender closes, jockeys goal-side and lunges when the ball is exposed;
  a lunge that reaches the ball wins it or pokes it loose, one that misses
  leaves him off balance.
- The keeper sets on the ball-goal line, comes off it one-on-one, reads a shot
  a beat late and dives for the point on its path he can reach; the ball
  meeting his hands is a save (held or parried), the ball over the line between
  the posts and under the bar is a goal.
- Whoever wins the ball plays on: carries away from pressure, passes to the
  outlet, or (a keeper) distributes.

Events are written as things happen. A pass or shot is stamped at the strike
(its sample and its second) but written once its result is known, before the
save, interception or goal that follows it, so the record stays in order.
"""

import math
import random
from dataclasses import dataclass, field

from core.contracts import Match, MatchEvent
from engine.core.lineup import lineup
from engine.core.models import xg
from engine.core.motion import Sample, Tracks
from engine.core.pitch import GOAL_HALF_WIDTH, GOAL_Y, LENGTH, WIDTH, own, own_facing
from engine.core.sim import DEFAULT_KICKOFF, load_config
from engine.league import COMPETITION
from engine.play import referee
from engine.play.ball import Ball, predict
from engine.play.drill import BOX_DEPTH, BOX_HALF, load_play
from engine.play.player import Player, intercept

BALL_R = 0.11
POST_R = 0.06
CROSSBAR = 2.44
GOAL_X = {0: LENGTH, 1: 0.0}  # the goal each side attacks


def unit(dx, dy):
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-9 else (0.0, 0.0)


def seg_dist(p, a, b):
    """Distance from point p to the segment a-b."""
    ax, ay = a
    bx, by = b
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    if L2 < 1e-12:
        return math.dist(p, a)
    u = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / L2))
    return math.dist(p, (ax + (bx - ax) * u, ay + (by - ay) * u))


@dataclass
class Mind:
    """What a player is doing, and when he next decides."""

    intent: str = (
        "hold"  # carry chase press support outlet cover keep dive lunge celebrate hold
    )
    heading: float = 0.0  # carry direction (degrees)
    spot: tuple = (0.0, 0.0)
    cap: float = 4.0
    next_think: float = 0.0
    lunge_until: float = -1.0
    stun_until: float = -1.0
    cool_until: float = -1.0
    exposed_since: float | None = None
    jockey_since: float | None = None
    misses: list = field(default_factory=list)  # times his lunges failed lately
    spot_front: bool = False
    knock_cool: float = -1.0
    beaten: set = field(default_factory=set)  # defenders he has gone past this spell


@dataclass
class GameResult:
    match: Match
    events: list
    tracks: Tracks
    outcome: str
    counts: dict
    changes: list = field(default_factory=list)  # times control changed team


class Game:
    def __init__(self, home, away, seed, cfg=None):
        self.cfg = cfg or load_play()
        self.engine = load_config()
        self.rng = random.Random(f"attack-{seed}")
        sheets = [*lineup(home), *lineup(away)]
        self.match = Match(
            match_id=f"attack-{home.id}-{away.id}-{seed}",
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

        def pick(team, positions, taken=()):
            for want in positions:
                for i, s in enumerate(sheets):
                    if (
                        s.team_id == team
                        and s.starting
                        and s.position == want
                        and s.player_id not in taken
                    ):
                        return i, s
            raise ValueError(f"{team} has none of {positions}")

        r = self.rng
        sx, sy = r.uniform(64.0, 71.0), r.uniform(22.0, 46.0)
        fx, fy = (
            sx - r.uniform(12.0, 16.0),
            min(60.0, max(8.0, sy + r.uniform(-9.0, 9.0))),
        )
        dx = sx + r.uniform(11.0, 15.0)
        dy = sy + (GOAL_Y - sy) * 0.3 + r.uniform(-3.0, 3.0)
        ox, oy = (
            r.uniform(48.0, 56.0),
            min(60.0, max(8.0, WIDTH - sy + r.uniform(-6.0, 6.0))),
        )

        def make(team, positions, x, y, keeper=False, facing=0.0, taken=()):
            i, s = pick(team, positions, taken)
            side = 0 if team == home.id else 1
            return Player(
                (side, i), s.player_id, s.team_id, keeper, x, y, facing=facing
            )

        self.striker = make(home.id, ["ST", "AM", "LW", "RW"], sx, sy)
        self.feeder = make(home.id, ["RCM", "LCM", "CM", "DM", "AM"], fx, fy)
        self.defender = make(away.id, ["CB", "RCB", "LCB"], dx, dy, facing=180.0)
        self.outlet = make(
            away.id, ["CM", "RCM", "LCM", "DM", "RM", "LM"], ox, oy, facing=180.0
        )
        self.keeper = make(away.id, ["GK"], 103.5, GOAL_Y, keeper=True, facing=180.0)
        self.keepers = {1: self.keeper}  # side -> its keeper on the pitch
        self.period = 1
        self.qual = {"drill": True}  # marks every event of a drill or attack
        self.players = [
            self.feeder,
            self.striker,
            self.defender,
            self.outlet,
            self.keeper,
        ]
        self.striker.vx = 1.5
        self.mind = {
            p.key: Mind(next_think=0.1 * i) for i, p in enumerate(self.players)
        }
        for p in self.players:
            self.mind[p.key].heading = 0.0 if p.key[0] == 0 else 180.0
        self.mind[self.feeder.key].next_think = 0.6  # a look up before the first pass

        self.ball = Ball(fx + self.cfg["ball"]["carry_ahead"], fy)
        self.owner = self.feeder
        self.in_hands = False
        self.touch_phase = 0.0
        self.last_touch = self.feeder
        self.kicked_at = {}
        self.pending = None  # a pass or shot awaiting its result
        self.saved_by = None  # the keeper who just took a shot (no pick-up event too)
        self.net_x = None  # a goal: the back of the net stops the ball
        self.opening = (
            True  # the scenario's first move: the feeder plays the striker in
        )
        self.carry = None  # the carry under way (written when it ends)
        self.possessions = 1
        self.changes = []
        self.dead = False
        self.t = 0.0
        self.end_at = None
        self.outcome = "timeout"
        self.counts = dict.fromkeys(
            [
                "passes",
                "passes_completed",
                "take_ons",
                "tackles_won",
                "lunges_missed",
                "shots",
                "goals",
                "saves_held",
                "saves_parried",
                "blocks",
                "interceptions",
                "knocks",
            ],
            0,
        )
        self.events, self.outbox = [], []
        slots = [s.player_id for s in sheets] + [referee.SLOT]
        self.ref = referee.make()
        self.slot = {pid: k for k, pid in enumerate(slots)}
        self.tracks = Tracks(hz=round(1 / self.cfg["dt"]), slots=slots)
        self.prev_ball = self.ball.pos

    # ---- the loop ---------------------------------------------------------------

    def run(self):
        g = self.cfg["game"]
        self.start_carry(self.owner)
        self.record()
        while self.t < g["length_s"] - 1e-9:
            if self.end_at is not None and self.t >= self.end_at:
                break
            self.step()
        if self.carry is not None:
            self.flush_carry()
            self.post()
        return GameResult(
            self.match,
            self.events,
            self.tracks,
            self.outcome,
            self.counts,
            self.changes,
        )

    def step(self):
        c = self.cfg
        dt = c["dt"]
        for pl in self.players:  # decisions use the state at the start of the step
            m = self.mind[pl.key]
            if self.t >= m.next_think - 1e-9:
                m.next_think = self.t + c["game"]["think_s"]
                self.think(pl)
        self.t = round(self.t + dt, 6)
        self.prev_ball = self.ball.pos
        for pl in self.players:
            tgt, cap, p, arrive = self.target(pl)
            pl.move(tgt, cap, dt, p, arrive_in=arrive)
            pl.face(self.ball.pos, dt, c["player"])
        self.separate()
        referee.step(self.ref, self.ball.pos, dt, c["player"], c["referee"])
        self.move_ball()
        if not self.dead:
            self.lines()
        if not self.dead:
            self.shot_contacts()
            self.lunges()
            self.control()
            self.take_ons()
        self.record()
        self.post()

    def urgent(self):
        """Everyone re-decides now (the ball changed hands or was struck)."""
        for i, pl in enumerate(self.players):
            self.mind[pl.key].next_think = self.t + 0.02 * i

    # ---- decisions --------------------------------------------------------------

    def think(self, pl):
        if self.end_at is not None:
            return self.after_end(pl)
        if self.t < pl.react_at:
            return
        m = self.mind[pl.key]
        if self.t < m.stun_until or self.t < m.lunge_until:
            return
        if m.intent == "dive" and self.pending and self.pending["kind"] == "shot":
            return
        if pl is self.owner:
            return self.on_ball(pl)
        if self.owner is None:
            return self.loose(pl)
        if self.owner.key[0] == pl.key[0]:
            return self.support(pl)
        return self.defend(pl)

    def opponents(self, pl):
        return [q for q in self.players if q.key[0] != pl.key[0]]

    def mates(self, pl):
        return [q for q in self.players if q.key[0] == pl.key[0] and q is not pl]

    def goal_of(self, side):
        return (GOAL_X[side], GOAL_Y)

    def pressure(self, pl):
        """Distance to the nearest outfield opponent."""
        return min(
            (math.dist(pl.pos, q.pos) for q in self.opponents(pl) if not q.keeper),
            default=99.0,
        )

    def on_ball(self, pl):
        m = self.mind[pl.key]
        if self.in_hands:
            if self.t >= m.spot[0]:  # spot[0] holds his release time
                self.distribute(pl)
            return
        if self.opening and pl is self.feeder:
            target = self.lead_point(pl, self.striker)
            if self.safe(pl, self.striker, target):
                self.opening = False
                return self.pass_ball(pl, self.striker)
        shot = self.shot_value(pl)
        if shot is not None:
            return self.shoot(pl, shot)
        heading, carry_score = self.best_heading(pl)
        pass_to, pass_score = self.best_pass(pl)
        pressed = self.pressure(pl) <= 3.0
        clearing = self.clearing(pl)
        pass_score += self.pass_bias(pl)
        if pass_to is not None and (
            clearing
            or (pressed and pass_score > carry_score - 0.05)
            or pass_score > carry_score + 0.15
        ):
            return self.pass_ball(pl, pass_to)
        if (
            clearing
            and self.pressure(pl) <= self.cfg["clear"]["pressed_m"]
            and self.in_own_third(pl)
            and pass_to is None
        ):
            return self.clear(pl)
        if self.knock_on(pl):
            return
        m.intent = "carry"
        m.heading = heading
        m.cap = self.cfg["carry"]["speed_close" if pressed else "speed_open"]

    def loose(self, pl):
        """Nobody has it: the best-placed of each team goes for it; the rest
        take up their places."""
        m = self.mind[pl.key]
        if self.pending and self.pending["kind"] == "shot" and pl.keeper:
            return
        best = self.chasers()
        if pl.key in best:
            m.intent = "chase"
            return
        self.positions(pl)

    def path(self):
        """The ball's predicted path from now (worked out once per moment:
        every player reads the same one)."""
        b = self.ball
        key = (self.t, b.x, b.y, b.h, b.vx, b.vy, b.vh)
        if getattr(self, "_path_key", None) != key:
            pred = self.cfg["predict"]
            self._path = predict(
                b,
                self.cfg["ball"],
                pred["horizon_s"],
                pred["step_s"],
                self.cfg["substeps"],
            )
            self._path_key = key
        return self._path

    def chasers(self):
        """Who goes for the loose ball (one per team), worked out once per moment."""
        path = self.path()
        key = (
            self._path_key,
            tuple(self.mind[p.key].stun_until > self.t for p in self.players),
        )
        if getattr(self, "_chasers_key", None) == key:
            return self._chasers
        self._chasers = self._chasers_now(path)
        self._chasers_key = key
        return self._chasers

    def _chasers_now(self, path):
        times = []
        for pl in self.players:
            if self.mind[pl.key].stun_until > self.t:
                continue
            r, h = self.reach(pl)
            tau, point = intercept(pl, path, self.t, r, h, self.cfg["player"])
            times.append((tau, pl, point))
        k = self.cfg["keeper"]
        best = {}
        for tau, pl, point in times:
            side = pl.key[0]
            if pl.keeper:
                # He leaves his goal only for a ball in his area that he gets
                # to clearly first, when no defender of his can get there in
                # time: otherwise he guards the goal and lets them deal with it.
                theirs = min((t for t, q, _ in times if q.key[0] != side), default=99.0)
                ours = min(
                    (t for t, q, _ in times if q.key[0] == side and not q.keeper),
                    default=99.0,
                )
                if (
                    not self.in_box(point, side)
                    or tau + k["come_margin_s"] > theirs
                    or ours <= theirs
                ):
                    continue
            if side not in best or tau < best[side][0]:
                best[side] = (tau, pl.key)
        return {key for _, key in best.values()}

    def support(self, pl):
        """A teammate has it: offer something."""
        m = self.mind[pl.key]
        o = self.owner
        side = pl.key[0]
        if pl.keeper:
            m.intent = "keep"
            return
        fwd = 1.0 if side == 0 else -1.0
        if pl is self.striker and o is self.feeder:
            # Show for it, moving towards goal (onto the pass).
            m.intent, m.spot, m.cap = (
                "support",
                (min(pl.x + fwd * 6.0, LENGTH - 20.0), pl.y),
                4.0,
            )
        elif pl is self.feeder:
            # Behind the ball and to the side: a lay-off if he is stuck.
            sy = 1.0 if o.y < GOAL_Y else -1.0
            m.intent, m.spot, m.cap = (
                "support",
                (o.x - 11.0, min(60.0, max(8.0, o.y + sy * 8.0))),
                5.0,
            )
        else:
            # Harbour: show upfield for the out-ball, away from the striker.
            away = 1.0 if pl.y >= GOAL_Y else -1.0
            m.intent = "support"
            m.spot = (
                max(30.0, min(o.x - 16.0, 70.0)),
                min(60.0, max(8.0, o.y + away * 14.0)),
            )
            m.cap = 5.5

    def defend(self, pl):
        """The other team has it: the nearest presses; the rest hold their jobs."""
        m = self.mind[pl.key]
        if pl.keeper:
            m.intent = "keep"
            return
        o = self.owner
        mine = [q for q in self.players if q.key[0] == pl.key[0] and not q.keeper]
        presser = min(mine, key=lambda q: (math.dist(q.pos, self.ball.pos), q.key))
        if pl is presser:
            m.intent = "press"
            return
        if pl is self.feeder:
            # Riverside lost it: cut the lane to the outlet.
            out = self.outlet
            m.intent, m.cap = "support", 6.5
            m.spot = (o.x + (out.x - o.x) * 0.45, o.y + (out.y - o.y) * 0.45)
            return
        self.positions(pl)

    def positions(self, pl):
        """Where he stands when not on the ball or chasing it."""
        m = self.mind[pl.key]
        if pl.keeper:
            m.intent = "keep"
        elif pl is self.outlet:
            m.intent, m.spot, m.cap = "support", (52.0, pl.y), 4.0
        elif pl is self.feeder:
            m.intent, m.spot, m.cap = (
                "support",
                (min(self.ball.x - 12.0, 80.0), pl.y),
                5.0,
            )
        elif pl is self.defender:
            m.intent = "press"
        else:
            # The striker while the ball is loose: ahead of it, towards the
            # middle, ready for it to be won.
            b = self.ball
            spot = (min(b.x + 12.0, LENGTH - 11.0), b.y + (GOAL_Y - b.y) * 0.5)
            m.intent, m.spot, m.cap = "support", spot, 5.0

    def after_end(self, pl):
        m = self.mind[pl.key]
        if m.intent == "celebrate":
            return
        if pl is not self.owner:
            m.intent, m.spot, m.cap = "support", (pl.x, pl.y), 1.5

    # ---- the carrier's options ---------------------------------------------------

    def best_heading(self, pl):
        """(heading, score): where to carry it. Progress towards goal (or,
        for the defending team, away from the danger) plus room, minus the
        cost of turning; the current heading is kept unless clearly beaten."""
        c = self.cfg["carry"]
        m = self.mind[pl.key]
        side = pl.key[0]
        goal = self.goal_of(side)
        opps = [
            q
            for q in self.opponents(pl)
            if not q.keeper or self.in_box(q.pos, 1 - side)
        ]
        attacking = self.attacking(pl)
        w_prog, w_space = (0.55, 0.45) if attacking else (0.25, 0.75)

        # Attackers carry towards a point on the goal's centre line about
        # 12 m ahead (never nearer goal than 6 m): straight at goal from
        # midfield, inside (not down the byline) when wide and deep.
        if attacking:
            fwd = 1.0 if side == 0 else -1.0
            ahead = pl.x + fwd * 12.0
            stop = GOAL_X[side] - fwd * 6.0
            aim = (min(ahead, stop) if side == 0 else max(ahead, stop), GOAL_Y)
        else:
            aim = goal

        def score(ang):
            ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            px, py = pl.x + ux * 5.0, pl.y + uy * 5.0
            if not (2.0 <= px <= LENGTH - 2.0 and 2.0 <= py <= WIDTH - 2.0):
                return -9.0
            prog = (math.dist(pl.pos, aim) - math.dist((px, py), aim)) / 5.0
            room = min(
                (
                    math.dist((px, py), (q.x + q.vx * 0.6, q.y + q.vy * 0.6))
                    for q in opps
                ),
                default=10.0,
            )
            turn = abs((ang - m.heading + 540.0) % 360.0 - 180.0) / 180.0
            return w_prog * prog + w_space * min(1.0, room / 8.0) - 0.25 * turn

        n = c["directions"]
        cands = [(score(360.0 * k / n), 360.0 * k / n) for k in range(n)]
        best_s, best_a = max(cands)
        cur = score(m.heading)
        if cur >= best_s - c["stick"]:
            return m.heading, cur
        return best_a, best_s

    def parry(self, out, side):
        """(angle, share of speed kept) of a parried shot: `out` away from his
        goal along x, `side` the way the ball was going across him."""
        k = self.cfg["keeper"]
        ang = math.degrees(math.atan2(side * 0.9, out * 0.6)) + self.rng.uniform(
            -20.0, 20.0
        )
        return ang, k["parry_keep"]

    def lunge_range(self):
        return self.cfg["defend"]["lunge_range_m"]

    def pass_style(self, pl):
        """(longest pass, weight on going forward, players to look for first)."""
        return self.cfg["passing"]["max_m"], 0.5, None

    def pass_bias(self, pl):
        """How much more a pass is worth than its score says (keeping the
        ball). In the attack: nothing extra."""
        return 0.0

    def hold_line(self, pl):
        """How near his goal (m) a jockeying defender gives ground before he
        stands; None: he keeps backing off (the attack drill)."""

    def must_react(self):
        """Must a player have reacted to a fast ball before he can take it?
        (In the attack drill: no.)"""
        return False

    def going_past(self, pl, o):
        """Is carrier `o` going past defender `pl` right now (alongside him,
        on his way by)? Then he gets a foot in. In the attack: not used."""
        return False

    def tight(self, pl):
        """Does `pl` go in for a ball that is merely unshielded (not only one
        clearly off the carrier's foot)? In the attack: always."""
        return True

    def engaging(self, q):
        """Is defender `q` taking the carrier on (for counting a take-on)?"""
        return True

    def attacking(self, pl):
        """Does `pl`'s team carry the ball forward (or just away from danger)?"""
        return pl.key[0] == 0

    def clearing(self, pl):
        """Is `pl`'s team getting the ball away (passing out, clearing)?"""
        return pl.key[0] == 1

    def chance(self, side, pos):
        """The xG of a shot from `pos` (the current engine's model)."""
        bx, by = own(side, *pos)
        return xg(self.engine, min(bx, LENGTH - 0.5), by, False, "none")

    def best_pass(self, pl):
        """(mate, value) of the best safe pass, or (None, -9). Safe: by the
        ball's real path, he gets to it before any opponent, with margin."""
        p = self.cfg["passing"]
        side = pl.key[0]
        goal = self.goal_of(side)
        best, value = None, -9.0
        max_m, prog_w, prefer = self.pass_style(pl)
        for mate in self.mates(pl):
            if mate.keeper:
                continue
            d = math.dist(pl.pos, mate.pos)
            if not p["min_m"] <= d <= max_m:
                continue
            target = self.lead_point(pl, mate)
            if not self.safe(pl, mate, target):
                continue
            prog = (math.dist(pl.pos, goal) - math.dist(target, goal)) / 30.0
            room = min(
                1.0, min(math.dist(target, q.pos) for q in self.opponents(pl)) / 10.0
            )
            v = prog_w * prog + 0.4 * room + (0.3 if self.clearing(pl) else 0.0)
            if prefer and mate.key in prefer:
                v += 0.4
            if v > value:
                best, value = mate, v
        return best, value

    def lead_point(self, pl, mate):
        t = math.dist(pl.pos, mate.pos) / 14.0
        for _ in range(2):
            tx, ty = mate.x + mate.vx * t, mate.y + mate.vy * t
            t = math.dist(pl.pos, (tx, ty)) / 14.0
        return min(max(tx, 1.0), LENGTH - 1.0), min(max(ty, 1.0), WIDTH - 1.0)

    def pass_speed(self, d):
        p = self.cfg["passing"]
        return min(
            p["max_ms"],
            math.sqrt(p["arrive_ms"] ** 2 + 2 * self.cfg["ball"]["roll_decel"] * d)
            * 1.1,
        )

    def safe(self, pl, mate, target):
        b = Ball(*self.ball.pos)
        ang = math.degrees(math.atan2(target[1] - b.y, target[0] - b.x))
        b.kick(self.pass_speed(math.dist(b.pos, target)), ang)
        pred = self.cfg["predict"]
        path = predict(
            b, self.cfg["ball"], pred["horizon_s"], pred["step_s"], self.cfg["substeps"]
        )
        pc = self.cfg["player"]
        # A body already on the line, near the start, just blocks it.
        for q in self.opponents(pl):
            if seg_dist(q.pos, self.ball.pos, target) <= self.cfg["passing"]["block_m"]:
                along = (q.x - self.ball.x) * (target[0] - self.ball.x) + (
                    q.y - self.ball.y
                ) * (target[1] - self.ball.y)
                if along > 0:
                    return False
        mine, _ = intercept(mate, path, self.t, *self.reach(mate), pc)
        # Opponents read the pass a beat after it is struck.
        later = self.t + pc["reaction_s"]
        theirs = min(
            intercept(self.reacting(q, later), path, self.t, *self.reach(q), pc)[0]
            for q in self.opponents(pl)
        )
        return mine + self.cfg["passing"]["safe_margin_s"] <= theirs

    @staticmethod
    def reacting(q, at):
        """A copy of `q` who cannot respond before `at`."""
        return Player(
            q.key,
            q.player_id,
            q.team_id,
            q.keeper,
            q.x,
            q.y,
            q.vx,
            q.vy,
            q.facing,
            max(q.react_at, at),
        )

    def shot_value(self, pl):
        """(xG-like quality) if he should shoot now, else None."""
        s = self.cfg["shoot"]
        side = pl.key[0]
        gx, gy = self.goal_of(side)
        d = math.dist(pl.pos, (gx, gy))
        if d > 30.0:
            return None
        q, blockers = self.quality(pl, pl.pos)
        pressed = self.pressure(pl) <= 2.5
        if d <= s["close_m"] and blockers == 0:
            return q
        if q >= s["good_quality"] or (pressed and q >= s["min_quality"]):
            return q
        # Shoot now, or carry on for a better one? Carrying on is worth the
        # chance a few metres on, discounted by the risk of losing it first.
        if q >= s["min_quality"]:
            heading, _ = self.best_heading(pl)
            ux, uy = math.cos(math.radians(heading)), math.sin(math.radians(heading))
            on = (pl.x + ux * s["carry_on_m"], pl.y + uy * s["carry_on_m"])
            later, _ = self.quality(pl, on)
            keep = min(1.0, self.pressure(pl) / s["safe_m"])
            if q >= s["shoot_vs_carry"] * later * keep:
                return q
        return None

    def quality(self, pl, at):
        """(chance, bodies in the way) of a shot from `at`: the current
        engine's xG, cut for each outfield body in the lane, raised when the
        keeper is out of position (not between the ball and the goal)."""
        s = self.cfg["shoot"]
        side = pl.key[0]
        gx, gy = self.goal_of(side)
        d = math.dist(at, (gx, gy))
        bx, by = own(side, *at)
        q = xg(self.engine, min(bx, LENGTH - 0.5), by, False, "none")
        blockers = sum(
            1
            for o in self.opponents(pl)
            if not o.keeper
            and seg_dist(o.pos, at, (gx, gy)) <= s["lane_block_m"]
            and math.dist(o.pos, (gx, gy)) < d
        )
        k = next((o for o in self.opponents(pl) if o.keeper), None)
        if k is not None:
            off_line = seg_dist(k.pos, at, (gx, gy))
            if off_line > s["keeper_beaten_m"] or math.dist(k.pos, (gx, gy)) > d:
                q = max(q, s["open_goal"] * math.exp(-d / s["open_goal_scale_m"]))
        return q * 0.6**blockers, blockers

    def knock_on(self, pl):
        """Knock it past a man who is off balance, flat-footed or diving in."""
        c = self.cfg["carry"]
        m = self.mind[pl.key]
        if self.t < m.knock_cool:
            return False
        side = pl.key[0]
        goal = self.goal_of(side)
        gdir = math.degrees(math.atan2(goal[1] - pl.y, goal[0] - pl.x))
        for q in self.opponents(pl):
            if q.keeper:
                continue
            d = math.dist(pl.pos, q.pos)
            if not 1.5 <= d <= 6.0:
                continue
            qa = math.degrees(math.atan2(q.y - pl.y, q.x - pl.x))
            if abs((qa - gdir + 540) % 360 - 180) > 60:
                continue  # not in his way
            qm = self.mind[q.key]
            flat = q.speed < 1.2 or self.t < qm.stun_until or self.t < qm.lunge_until
            if not flat:
                continue
            for sgn in (1, -1) if (q.y < pl.y) == (side == 0) else (-1, 1):
                ang = gdir + sgn * 40.0
                ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                land = (pl.x + ux * c["knock_m"], pl.y + uy * c["knock_m"])
                if not (
                    3.0 <= land[0] <= LENGTH - 3.0 and 3.0 <= land[1] <= WIDTH - 3.0
                ):
                    continue
                if (
                    min(math.dist(land, o.pos) for o in self.opponents(pl))
                    < c["roll_space_m"] * 0.5
                ):
                    continue
                speed = (
                    math.sqrt(
                        pl.speed**2 + 2 * self.cfg["ball"]["roll_decel"] * c["knock_m"]
                    )
                    + 2.5
                )
                self.release(pl)
                self.ball.kick(speed, ang)
                self.kicked_at[pl.key] = self.t
                m.knock_cool = self.t + c["knock_cooldown_s"]
                m.intent = "chase"
                self.counts["knocks"] += 1
                self.urgent()
                return True
        return False

    # ---- actions ------------------------------------------------------------------

    def release(self, pl):
        """The ball leaves him (a pass, shot or knock): it rolls from where it is."""
        self.flush_carry()
        self.owner = None
        self.in_hands = False
        self.last_touch = pl
        for q in self.players:
            if q is not pl:
                q.react_at = self.t + self.cfg["player"]["reaction_s"]

    def pass_ball(self, pl, mate, throw=False):
        p = self.cfg["passing"]
        target = self.lead_point(pl, mate)
        d = math.dist(self.ball.pos, target)
        err = p["err_deg"] + (
            p["err_pressure_deg"] if self.pressure(pl) <= 3.0 else 0.0
        )
        ang = math.degrees(math.atan2(target[1] - self.ball.y, target[0] - self.ball.x))
        ang += self.rng.gauss(0.0, err)
        speed = self.pass_speed(d)
        start = self.ball.pos
        self.pending = self.strike_record(
            pl, "pass", start, target, speed, body="other" if throw else "foot_right"
        )
        self.pending["to"] = mate.key
        self.release(pl)
        if throw:
            self.ball.h = 1.6
            self.ball.kick(min(speed, 16.0), ang, lift=2.5)
        else:
            self.ball.kick(speed, ang)
        self.kicked_at[pl.key] = self.t
        self.counts["passes"] += 1
        self.mind[mate.key].intent = "chase"
        self.urgent()

    def in_own_third(self, pl):
        return abs(pl.x - GOAL_X[1 - pl.key[0]]) <= LENGTH / 3.0

    def clear(self, pl):
        """No pass on and a man on him in his own third: put it up the pitch,
        high and long, towards the touchline on his side."""
        c = self.cfg["clear"]
        side = pl.key[0]
        up = -1.0 if side == 1 else 1.0
        wide = 1.0 if pl.y >= GOAL_Y else -1.0
        tx = pl.x + up * self.rng.uniform(*c["length_m"])
        ty = min(WIDTH - 6.0, max(6.0, pl.y + wide * self.rng.uniform(5.0, 15.0)))
        d = math.dist(self.ball.pos, (tx, ty))
        T = d / c["speed"]
        lift = 0.5 * self.cfg["ball"]["gravity"] * T
        start = self.ball.pos
        self.flush_carry()
        self.write_record(
            self.strike_record(pl, "clearance", start, (tx, ty), c["speed"]), "success"
        )
        self.release(pl)
        self.ball.kick(
            c["speed"],
            math.degrees(math.atan2(ty - start[1], tx - start[0])),
            lift=min(lift, 14.0),
        )
        self.kicked_at[pl.key] = self.t
        self.counts["clearances"] = self.counts.get("clearances", 0) + 1
        self.end("defended_cleared_long")
        self.urgent()

    def distribute(self, pl):
        mate, _ = self.best_pass(pl)
        mate = mate or self.outlet
        self.pass_ball(pl, mate, throw=True)

    def shoot(self, pl, quality):
        s = self.cfg["shoot"]
        r = self.rng
        side = pl.key[0]
        gx = GOAL_X[side]
        k = self.keepers.get(1 - side)
        # The side of the goal the keeper covers least, from where he stands.
        best_y, best_gap = GOAL_Y, -1.0
        for y in (
            GOAL_Y - GOAL_HALF_WIDTH + s["aim_in_m"],
            GOAL_Y + GOAL_HALF_WIDTH - s["aim_in_m"],
        ):
            gap = seg_dist(k.pos, pl.pos, (gx, y)) if k else 1.0
            if gap > best_gap:
                best_y, best_gap = y, gap
        d = math.dist(pl.pos, (gx, best_y))
        err = (
            s["err_deg"]
            + s["err_deg_per_m"] * d
            + (s["err_pressure_deg"] if self.pressure(pl) <= 2.5 else 0.0)
        )
        ang = math.degrees(
            math.atan2(best_y - self.ball.y, gx - self.ball.x)
        ) + r.gauss(0.0, err)
        speed = r.uniform(*s["speed"])
        h_at = r.uniform(*s["height"])
        T = d / speed
        lift = (h_at + 0.5 * self.cfg["ball"]["gravity"] * T * T) / T
        self.pending = self.strike_record(
            pl, "shot", self.ball.pos, (gx, best_y), speed, xg=round(quality, 3)
        )
        self.release(pl)
        self.ball.kick(speed, ang, lift=lift)
        self.kicked_at[pl.key] = self.t
        self.counts["shots"] += 1
        self.urgent()
        kp = self.keepers.get(1 - side)
        if kp is None:
            return
        km = self.mind[kp.key]
        kp.react_at = self.t + self.cfg["keeper"]["reaction_s"]
        km.intent = "dive"
        km.spot = self.dive_point(kp)
        km.next_think = kp.react_at

    def dive_point(self, kp):
        """The first point of the shot's path he can get his hands to, or (if
        none) where it crosses his line: he goes there, at full stretch."""
        k = self.cfg["keeper"]
        b = self.ball.copy()
        path = predict(b, self.cfg["ball"], 2.0, self.cfg["dt"], self.cfg["substeps"])
        react = k["reaction_s"]
        gx = GOAL_X[1 - kp.key[0]]  # the goal he guards
        beyond = (lambda x: x >= LENGTH) if gx == LENGTH else (lambda x: x <= 0.0)
        for tau, x, y, h in path:
            if tau < react or h > k["jump_m"]:
                continue
            t = tau - react
            reach = (
                0.5 * k["dive_accel"] * t * t
                if t < k["dive_speed"] / k["dive_accel"]
                else (
                    k["dive_speed"] ** 2 / (2 * k["dive_accel"])
                    + k["dive_speed"] * (t - k["dive_speed"] / k["dive_accel"])
                )
            )
            if math.dist(kp.pos, (x, y)) - (k["hands_m"] + k["dive_extra_m"]) <= reach:
                return (x, y)
            if (x - gx) * (kp.x - gx) < 0 or beyond(x):
                break
        last = path[-1]
        for tau, x, y, h in path:
            if beyond(x):
                last = (tau, x, y, h)
                break
        lx = min(last[1], LENGTH - 0.3) if gx == LENGTH else max(last[1], 0.3)
        return (lx, last[2])

    # ---- per-step targets ---------------------------------------------------------

    def target(self, pl):
        """(target, speed cap, movement params, arrive_in) for this step."""
        c = self.cfg
        pc = c["player"]
        m = self.mind[pl.key]
        if self.t < m.stun_until:
            return pl.pos, 0.0, pc, None
        if self.t < m.lunge_until:
            b = self.ball
            return (
                (b.x + b.vx * 0.15, b.y + b.vy * 0.15),
                c["defend"]["lunge_speed"],
                {**pc, "accel": 8.0},
                0.0,
            )
        if pl is self.owner and self.in_hands:
            return (
                pl.pos,
                0.0,
                {**pc, "decel": pc["smother_decel"], "lateral": pc["smother_decel"]},
                None,
            )
        if m.intent == "dive":
            k = c["keeper"]
            return (
                m.spot,
                k["dive_speed"],
                {
                    **pc,
                    "accel": k["dive_accel"],
                    "decel": k["dive_accel"],
                    "lateral": k["dive_accel"],
                },
                0.0,
            )
        if m.intent == "celebrate":
            return m.spot, pc["top_speed"] * 0.85, pc, None
        if pl is self.owner and m.intent == "carry":
            ux, uy = (
                math.cos(math.radians(m.heading)),
                math.sin(math.radians(m.heading)),
            )
            return (pl.x + ux * 6.0, pl.y + uy * 6.0), m.cap, pc, 0.0
        if m.intent == "chase" and self.owner is None:
            return self.chase_target(pl)
        if (
            m.intent == "press"
            and self.owner is not None
            and self.owner.key[0] != pl.key[0]
        ):
            return self.press_target(pl)
        if m.intent == "press":  # nobody to press yet: hold goal-side of the ball
            goal = self.goal_of(1 - pl.key[0])
            ux, uy = unit(goal[0] - self.ball.x, goal[1] - self.ball.y)
            return (self.ball.x + ux * 6.0, self.ball.y + uy * 6.0), 5.5, pc, None
        if m.intent == "keep" or pl.keeper:
            return self.keeper_spot(pl), 5.5, pc, None
        return m.spot, m.cap, pc, None

    def chase_target(self, pl):
        pc = self.cfg["player"]
        b = self.ball
        if math.dist(pl.pos, b.pos) <= self.cfg["control"]["approach_m"]:
            lead = self.cfg["control"]["approach_lead_s"]
            cap = min(
                pc["top_speed"], b.ground_speed + self.cfg["control"]["approach_gain"]
            )
            return (b.x + b.vx * lead, b.y + b.vy * lead), max(cap, 3.0), pc, 0.0
        path = self.path()
        r, h = self.reach(pl)
        tau, point = intercept(pl, path, self.t, r, h, pc)
        return point, pc["top_speed"], pc, tau

    def press_target(self, pl):
        """Close him down, then jockey: goal-side, a step inside, matching his
        pace. Beaten: race back goal-side of him."""
        d = self.cfg["defend"]
        pc = self.cfg["player"]
        o = self.owner
        goal = self.goal_of(o.key[0])
        ux, uy = unit(goal[0] - o.x, goal[1] - o.y)
        ahead = (o.x + o.vx * 0.3, o.y + o.vy * 0.3)
        goal_side = (pl.x - o.x) * ux + (pl.y - o.y) * uy
        dist = math.dist(pl.pos, o.pos)
        inside = 1.0 if o.y < GOAL_Y else -1.0
        jock = (
            ahead[0] + ux * d["jockey_m"],
            ahead[1] + uy * d["jockey_m"] + inside * d["inside_m"],
        )
        if pl.keeper:
            return self.keeper_spot(pl), 5.5, pc, None
        hold = self.hold_line(pl)
        if hold is not None and goal_side >= -0.5:
            # He gives ground only to here, then stands his ground: the
            # carrier has to beat him at the edge of the box, not walk in.
            gx = goal[0]
            if abs(jock[0] - gx) < hold:
                jock = (gx + math.copysign(hold, o.x - gx), jock[1])
        if goal_side < -0.5:  # beaten: get back goal-side
            return (ahead[0] + ux * 3.0, ahead[1] + uy * 3.0), pc["top_speed"], pc, 0.0
        if dist > d["engage_m"]:
            return jock, pc["top_speed"], pc, 0.0
        return jock, min(pc["top_speed"], o.speed + 1.5), pc, None

    def keeper_spot(self, pl):
        """On the line from his goal to the ball; further off it when a man is
        through on him (one-on-one)."""
        k = self.cfg["keeper"]
        side = pl.key[0]
        gx, gy = GOAL_X[1 - side], GOAL_Y
        bx, by = self.ball.pos
        d = math.hypot(bx - gx, by - gy) or 1.0
        ratio = self.engine["motion"]["keeper_ratio"]
        top = self.engine["motion"]["keeper_max_m"]
        o = self.owner
        if o is not None and o.key[0] != side and d < 25.0:
            covered = any(
                q is not pl
                and q.key[0] == side
                and math.dist(q.pos, (gx, gy)) < math.dist(o.pos, (gx, gy))
                and seg_dist(q.pos, o.pos, (gx, gy)) < 3.0
                for q in self.players
            )
            if not covered:
                ratio, top = k["ratio_1v1"], k["max_1v1_m"]
        r = max(1.5, min(top, ratio * d))
        return gx + (bx - gx) / d * r, gy + (by - gy) / d * r

    # ---- the ball -----------------------------------------------------------------

    def move_ball(self):
        c = self.cfg
        b = self.ball
        o = self.owner
        if o is not None and self.in_hands:
            b.x, b.y, b.h = o.x, o.y, 1.1
            b.vx, b.vy, b.vh = o.vx, o.vy, 0.0
            return
        if o is not None:
            # Touch by touch: out from his feet and back, further in space.
            k = c["carry"]
            pressed = self.pressure(o) <= 4.0
            period = k["touch_s"][0] if pressed else k["touch_s"][1]
            gap = k["close_m"] if pressed else k["open_m"]
            self.touch_phase = (self.touch_phase + c["dt"]) % period
            off = 0.35 + (gap - 0.35) * math.sin(math.pi * self.touch_phase / period)
            if o.speed > 0.5:
                ux, uy = o.vx / o.speed, o.vy / o.speed
            else:
                ux, uy = (
                    math.cos(math.radians(o.facing)),
                    math.sin(math.radians(o.facing)),
                )
            # He keeps it in: never out over a line in front of him.
            for lim, pos, u in (
                (LENGTH, o.x, ux),
                (0.0, o.x, ux),
                (WIDTH, o.y, uy),
                (0.0, o.y, uy),
            ):
                if u > 1e-6 and lim > pos:
                    off = min(off, max(0.0, (lim - 0.3 - pos) / u))
                elif u < -1e-6 and lim < pos:
                    off = min(off, max(0.0, (lim + 0.3 - pos) / u))
            nx, ny = o.x + ux * off, o.y + uy * off
            # Turning with it, he rolls it round (it never flips to his new
            # front in one step): at most his speed plus a touch per step.
            most = (o.speed + c["carry"]["turn_touch_ms"]) * c["dt"]
            gap = math.dist((nx, ny), b.pos)
            if gap > most:
                nx, ny = b.x + (nx - b.x) * most / gap, b.y + (ny - b.y) * most / gap
            b.vx, b.vy = (nx - b.x) / c["dt"], (ny - b.y) / c["dt"]
            b.x, b.y, b.h, b.vh = nx, ny, 0.0, 0.0
            return
        b.step(c["dt"], c["ball"], c["substeps"])
        self.keep_in_net()

    def keep_in_net(self):
        """After a goal the ball is in the net (a box behind the goal line):
        its back, sides and roof stop it."""
        b = self.ball
        if self.net_x is not None:
            lo, hi = sorted((GOAL_X[0] if self.net_x > LENGTH else 0.0, self.net_x))
            if b.x < lo or b.x > hi:
                b.x = min(max(b.x, lo), hi)
                b.vx = 0.0
            side = GOAL_HALF_WIDTH - BALL_R
            if abs(b.y - GOAL_Y) > side:
                b.y = GOAL_Y + math.copysign(side, b.y - GOAL_Y)
                b.vy = 0.0
            if b.h > CROSSBAR - BALL_R:
                b.h, b.vh = CROSSBAR - BALL_R, min(0.0, b.vh)

    def lines(self):
        """The ball over a line: a goal, the post, or out of play."""
        b = self.ball
        (x0, y0), (x1, y1) = self.prev_ball, b.pos
        for gx in (0.0, LENGTH):
            beyond = x1 > gx + BALL_R if gx == LENGTH else x1 < gx - BALL_R
            before = x0 <= gx + BALL_R if gx == LENGTH else x0 >= gx - BALL_R
            if not (beyond and before):
                continue
            u = (gx - x0) / (x1 - x0) if x1 != x0 else 1.0
            yc = y0 + (y1 - y0) * u
            for post in (GOAL_Y - GOAL_HALF_WIDTH, GOAL_Y + GOAL_HALF_WIDTH):
                if abs(yc - post) <= BALL_R + POST_R and b.h <= CROSSBAR:
                    b.x = gx - (0.3 if gx == LENGTH else -0.3)
                    b.vx = -b.vx * 0.5
                    b.vy += self.rng.uniform(-2.0, 2.0)
                    self.resolve_shot("post", None)
                    return
            if abs(yc - GOAL_Y) < GOAL_HALF_WIDTH - BALL_R and b.h < CROSSBAR - BALL_R:
                self.goal(gx, yc)
                return
            self.out(f"over the goal line at y={yc:.1f}")
            return
        if b.y < -BALL_R or b.y > WIDTH + BALL_R:
            self.out("over the touchline")

    def goal(self, gx, yc):
        p = self.pending
        if p is None or p["kind"] != "shot":
            self.out("into the goal without a shot")
            return
        side = p["player"].key[0]
        if GOAL_X[side] != gx:
            self.out("into his own goal")
            return
        p["qual"]["goal_line_s"] = round(self.t - p["t"], 1)
        self.counts["goals"] += 1
        self.outcome = "goal"  # a goal is the ending, whatever came before it
        self.resolve_shot("goal", None)
        self.dead = True
        self.net_x = gx + (2.0 if gx == LENGTH else -2.0)  # the back of the net
        b = self.ball
        b.y = min(
            max(b.y, GOAL_Y - GOAL_HALF_WIDTH + BALL_R),
            GOAL_Y + GOAL_HALF_WIDTH - BALL_R,
        )
        self.end("goal")
        scorer = p["player"]
        sm = self.mind[scorer.key]
        sm.intent = "celebrate"
        sm.spot = (
            LENGTH - 2.0 if side == 0 else 2.0,
            2.0 if scorer.y < GOAL_Y else WIDTH - 2.0,
        )
        for q in self.mates(scorer):
            if not q.keeper:
                qm = self.mind[q.key]
                qm.intent, qm.spot = (
                    "celebrate",
                    (sm.spot[0] + (-3.0 if side == 0 else 3.0), sm.spot[1]),
                )

    def out(self, why):
        if self.pending is not None:
            if self.pending["kind"] == "shot" and self.outcome == "timeout":
                self.outcome = "shot_missed"
            self.resolve_pending(None)
        self.flush_carry()
        self.dead = True
        b = self.ball
        b.vx = b.vy = b.vh = 0.0
        self.owner = None
        self.end("out_of_play" if self.outcome == "timeout" else self.outcome)

    def shot_contacts(self):
        """A shot in flight meets the keeper's hands or a body in the way."""
        p = self.pending
        if p is None or p["kind"] != "shot" or self.owner is not None:
            return
        b = self.ball
        k = self.cfg["keeper"]
        kp = self.keepers.get(1 - p["player"].key[0])
        seg = (self.prev_ball, b.pos)
        if kp is not None and self.t >= kp.react_at - 1e-9:
            diving = self.mind[kp.key].intent == "dive"
            reach = (
                k["hands_m"] + k["dive_extra_m"] if diving else k["standing_reach_m"]
            )
            near = seg_dist(kp.pos, *seg)
            if (
                not p.get("keeper_tried")
                and near <= reach
                and b.h <= k["jump_m"]
                and self.in_box(kp.pos, kp.key[0])
            ):
                # One go at it: near his body he saves it; at full stretch,
                # against a fast ball, it often beats him.
                p["keeper_tried"] = True
                stretch = max(
                    0.0, (near / reach - k["easy_share"]) / (1.0 - k["easy_share"])
                )
                speed = math.hypot(b.ground_speed, b.vh)
                chance = (
                    k["save_easy"]
                    - k["save_drop"] * stretch
                    - k["save_per_ms"] * max(0.0, speed - 20.0)
                )
                if self.rng.random() < chance:
                    return self.save(kp)
        for q in self.opponents(p["player"]):
            if q.keeper or self.t - self.kicked_at.get(p["player"].key, -9) < 0.05:
                continue
            if b.h <= 1.8 and seg_dist(q.pos, *seg) <= self.cfg["shoot"]["block_m"]:
                self.counts["blocks"] += 1
                self.resolve_shot("blocked", None)
                v = b.ground_speed
                ux, uy = unit(b.x - q.x, b.y - q.y)
                ang = math.degrees(math.atan2(uy, ux)) + self.rng.uniform(-50.0, 50.0)
                b.kick(v * 0.3, ang, lift=b.vh * 0.2)
                self.last_touch = q
                self.kicked_at[q.key] = self.t
                return

    def save(self, kp):
        k = self.cfg["keeper"]
        b = self.ball
        speed = math.hypot(b.ground_speed, b.vh)
        near = seg_dist(kp.pos, self.prev_ball, b.pos) <= k["catch_m"]
        held = speed <= k["catch_speed"] and near
        self.resolve_shot("saved", (kp, held))
        if held:
            self.counts["saves_held"] += 1
            self.take(kp, hands=True, quiet=True)
        else:
            self.counts["saves_parried"] += 1
            # Parried: away from goal and wide, slower.
            out = -1.0 if kp.key[0] == 1 else 1.0
            side = 1.0 if b.y >= kp.y else -1.0
            ang, keep = self.parry(out, side)
            # From where his hands met it (it never jumps to him).
            b.kick(speed * keep, ang, lift=1.0)
            self.last_touch = kp
            self.kicked_at[kp.key] = self.t
            self.mind[kp.key].intent = "keep"
            self.urgent()

    def lunges(self):
        """Defenders go in when the ball is off the carrier's foot near them;
        a lunge that reaches the ball wins it or pokes it loose."""
        d = self.cfg["defend"]
        o = self.owner
        b = self.ball
        for pl in self.players:
            m = self.mind[pl.key]
            if self.t < m.lunge_until:
                if math.dist(pl.pos, b.pos) <= d["lunge_reach_m"] and b.h <= 1.0:
                    m.lunge_until = -1.0
                    m.cool_until = self.t + d["cooldown_s"]
                    self.tackle(pl)
                    return
                continue
            if m.lunge_until > 0 and self.t >= m.lunge_until:  # missed
                m.lunge_until = -1.0
                self.beaten_again(pl)
                continue
            if (
                o is None
                or self.in_hands
                or pl.key[0] == o.key[0]
                or m.intent != "press"
                or self.t < m.cool_until
                or self.t < m.stun_until
            ):
                m.exposed_since = None
                continue
            near = math.dist(pl.pos, b.pos)
            # He can get to it: it is off the carrier's foot, or as near him
            # as the carrier (not shielded), or the carrier is nearly in on
            # goal and a jockeying defender has to commit.
            wary = any(self.t - t <= d["wary_s"] for t in m.misses)
            exposed = (
                math.dist(o.pos, b.pos) >= d["exposed_m"]
                or (
                    not wary
                    and self.tight(pl)
                    and (
                        near <= math.dist(o.pos, b.pos) + d["unshielded_m"]
                        or o.speed < 1.5
                    )
                )
                or (not wary and self.going_past(pl, o))
            )
            goal = self.goal_of(o.key[0])
            if wary:
                m.jockey_since = None
            elif near <= self.lunge_range() and math.dist(o.pos, goal) <= d["commit_m"]:
                if m.jockey_since is None:
                    m.jockey_since = self.t
                if self.t - m.jockey_since >= d["commit_after_s"]:
                    exposed = True
            else:
                m.jockey_since = None
            if near <= self.lunge_range() and exposed:
                if m.exposed_since is None:
                    m.exposed_since = self.t
                if self.t - m.exposed_since >= d["react_s"] - 1e-9:
                    m.lunge_until = self.t + d["lunge_s"]
                    m.exposed_since = None
                    m.jockey_since = None
                    # The carrier sees him coming (a beat later).
                    om = self.mind[o.key]
                    om.next_think = min(
                        om.next_think, self.t + self.cfg["player"]["reaction_s"]
                    )
            else:
                m.exposed_since = None

    def beaten_again(self, pl):
        """His lunge missed (or the carrier rode it): off balance, and wary.
        For a while he only goes in for a ball clearly off the man's foot,
        and waits longer between tries."""
        d = self.cfg["defend"]
        m = self.mind[pl.key]
        m.misses = [t for t in m.misses if self.t - t <= d["wary_s"]] + [self.t]
        m.stun_until = self.t + d["stun_s"]
        m.cool_until = self.t + d["cooldown_s"] * len(m.misses)
        self.counts["lunges_missed"] += 1

    def tackle(self, pl):
        """His lunge reached the ball. How it goes depends on how loose the
        ball was off the carrier's foot and where the tackle came from: won
        clean, poked loose, or the carrier rides it (and the defender is left
        off balance)."""
        o = self.owner
        b = self.ball
        d = self.cfg["defend"]
        if o is not None:
            loose = max(0.0, min(1.0, (math.dist(o.pos, b.pos) - 0.35) / 0.8))
            ux, uy = unit(o.vx, o.vy) if o.speed > 0.5 else unit(*self.mind[o.key].spot)
            front = ux * (pl.x - o.x) + uy * (pl.y - o.y)
            angle = (
                d["front_bonus"]
                if front > 0.5
                else (-d["front_bonus"] if front < -0.5 else 0.0)
            )
            win = d["win_base"] + d["win_loose"] * loose + angle
            r = self.rng.random()
            if r >= win + d["poke"]:  # he rides it
                self.beaten_again(pl)
                return
            clean = r < win
        else:
            clean = False
        self.counts["tackles_won"] += 1
        if clean:
            self.flush_carry()
            self.emit(pl, "tackle", "success", b.pos, b.pos, None)
            self.owner, self.in_hands = None, False
            self.take(pl, quiet=True)
            return
        self.flush_carry()
        self.emit(pl, "tackle", "success", b.pos, b.pos, None)
        if o is not None:
            self.mind[o.key].stun_until = self.t + 0.3  # knocked off it
        self.owner, self.in_hands = None, False
        ux, uy = unit(b.x - pl.x, b.y - pl.y)
        ang = math.degrees(math.atan2(uy, ux)) + self.rng.uniform(-35.0, 35.0)
        b.kick(self.rng.uniform(*d["poke_ms"]), ang)
        self.last_touch = pl
        self.kicked_at[pl.key] = self.t
        self.urgent()

    def control(self):
        """A loose ball is had by whoever gets to it first and can control it
        (feet, or a keeper's hands in his area if he stops inside it)."""
        if self.owner is not None:
            return
        k = self.cfg["control"]
        b = self.ball
        p = self.pending
        if (
            p is not None
            and p["kind"] == "shot"
            and b.ground_speed > k["shot_settled_ms"]
        ):
            return  # a shot still flying is met by the save (or block), not picked up
        best = None
        for pl in self.players:
            if self.t - self.kicked_at.get(pl.key, -9.0) < 0.3:
                continue
            if self.t < self.mind[pl.key].stun_until:
                continue
            if self.must_react() and self.t < pl.react_at and b.ground_speed > 6.0:
                continue  # a pass flying past a man who has not reacted to it yet
            r, h = self.reach(pl)
            hands = pl.keeper and r == k["keeper_hands_m"]
            d = (
                seg_dist(pl.pos, self.prev_ball, b.pos)
                if b.ground_speed > 6.0
                else math.dist(pl.pos, b.pos)
            )
            limit = k["keeper_speed"] if hands else k["feet_speed"]
            rel = math.hypot(b.vx - pl.vx, b.vy - pl.vy)
            if (
                d <= r
                and b.h <= h
                and rel <= limit
                and (best is None or (d, pl.key) < best[0])
            ):
                best = ((d, pl.key), pl, hands)
        if best is not None:
            pl = best[1]
            if b.ground_speed > 6.0:
                # He met a fast ball on its way through this step: it is
                # where he met it (it does not jump back to him from beyond).
                (ax, ay), (bx, by) = self.prev_ball, b.pos
                L2 = (bx - ax) ** 2 + (by - ay) ** 2
                if L2 > 1e-12:
                    u = ((pl.x - ax) * (bx - ax) + (pl.y - ay) * (by - ay)) / L2
                    u = max(0.0, min(1.0, u))
                    b.x, b.y = ax + (bx - ax) * u, ay + (by - ay) * u
            self.take(pl, hands=best[2])

    def take(self, pl, hands=False, quiet=False):
        """`pl` has the ball now."""
        b = self.ball
        prev = self.last_touch
        if self.pending is not None:
            self.resolve_pending(pl)
        changed = prev is None or prev.key[0] != pl.key[0]
        self.owner, self.in_hands = pl, hands
        if changed:  # a moment to settle before anyone can go in on him
            for q in self.opponents(pl):
                qm = self.mind[q.key]
                qm.cool_until = max(
                    qm.cool_until, self.t + self.cfg["defend"]["grace_s"]
                )
        self.last_touch = pl
        self.touch_phase = 0.0
        if changed:
            self.possessions += 1
            self.changes.append(self.t)
        if self.saved_by is pl:
            quiet = True
        self.saved_by = None
        if not quiet and changed:
            if hands:
                self.emit(
                    pl, "keeper_pick_up", "success", b.pos, b.pos, None, body="other"
                )
            else:
                self.counts["interceptions"] += 1
                self.emit(pl, "interception", "success", b.pos, b.pos, None)
        m = self.mind[pl.key]
        m.beaten = set()
        if hands:
            lo, hi = self.cfg["keeper"]["hold_s"]
            m.spot = (self.t + self.rng.uniform(lo, hi), 0.0)
            m.intent = "hold"
            b.vx = b.vy = b.vh = 0.0
        else:
            m.heading = (
                math.degrees(math.atan2(pl.vy, pl.vx)) if pl.speed > 0.5 else pl.facing
            )
        self.start_carry(pl)
        self.urgent()
        if (
            pl.key[0] == 1
            and not hands
            and self.end_at is None
            and self.outcome == "timeout"
        ):
            pass  # Harbour plays on; the attack ends when it gets the ball away

    def take_ons(self):
        """The carrier has gone past a defender who was in front of him."""
        o = self.owner
        if o is None or self.in_hands:
            return
        m = self.mind[o.key]
        goal = self.goal_of(o.key[0])
        ux, uy = unit(goal[0] - o.x, goal[1] - o.y)
        for q in self.opponents(o):
            if q.keeper or q.key in m.beaten or not self.engaging(q):
                continue
            ahead = (q.x - o.x) * ux + (q.y - o.y) * uy
            close = math.dist(q.pos, o.pos)
            qm = self.mind[q.key]
            if ahead > 0.5 and close < 3.5:
                qm.spot_front = True
            elif qm.spot_front and ahead < -1.0:
                qm.spot_front = False
                m.beaten.add(q.key)
                self.counts["take_ons"] += 1
                self.flush_carry()
                self.emit(o, "take_on", "success", self.ball.pos, self.ball.pos, None)
                self.start_carry(o)
            elif close > 8.0:
                qm.spot_front = False

    # ---- the record ---------------------------------------------------------------

    def strike_record(self, pl, kind, start, end, speed, body="foot_right", **qual):
        """A pass or shot, stamped now; written when its result is known."""
        return {
            "kind": kind,
            "player": pl,
            "start": start,
            "end": end,
            "speed": speed,
            "body": body,
            "t": self.t,
            "sample": len(self.tracks.samples) - 1,
            "frame": self.snapshot(),
            "qual": dict(qual),
        }

    def resolve_pending(self, taker):
        """A pass reached someone (or did not): write it."""
        p = self.pending
        if p is None:
            return
        if p["kind"] == "shot":
            keeper = (
                taker is not None
                and taker.keeper
                and taker.key[0] != p["player"].key[0]
            )
            if keeper:
                self.counts["saves_held"] += 1
                self.resolve_shot("saved", (taker, True))
                self.saved_by = taker
            else:
                self.resolve_shot("off_target" if taker is None else "blocked", None)
            return
        ok = taker is not None and taker.key[0] == p["player"].key[0]
        if ok:
            self.counts["passes_completed"] += 1
        self.write_record(p, "success" if ok else "fail")
        self.pending = None
        if ok and taker.key[0] == 1 and self.end_at is None:
            self.end(
                "defended_cleared" if not p["player"].keeper else "keeper_distributed"
            )

    def resolve_shot(self, how, save):
        p = self.pending
        if p is None or p["kind"] != "shot":
            return
        p["qual"]["result"] = how
        self.write_record(p, "success" if how == "goal" else "fail")
        self.pending = None
        if save is not None:
            kp, held = save
            self.emit(
                kp,
                "keeper_save",
                "success",
                self.ball.pos,
                self.ball.pos,
                None,
                body="other",
                held=held,
            )
            if held and self.end_at is None:
                self.outcome = "saved_held"
        if how == "goal":
            pass

    def write_record(self, p, outcome):
        self.outbox.append(
            {
                "player": p["player"],
                "type": p["kind"],
                "outcome": outcome,
                "start": p["start"],
                "end": p["end"],
                "speed": p["speed"] * 3.6,
                "body": p["body"],
                "t": p["t"],
                "sample": p["sample"],
                "frame": p["frame"],
                "qual": p["qual"],
            }
        )

    def start_carry(self, pl):
        self.carry = {
            "player": pl,
            "start": self.ball.pos,
            "t": self.t,
            "sample": len(self.tracks.samples),  # the sample this step records
            "frame": self.snapshot(),
        }

    def flush_carry(self):
        """A carry of 3 m or more is a dribble (stamped where it began)."""
        c = self.carry
        self.carry = None
        if c is None or self.in_hands or c["player"].keeper:
            return
        if math.dist(c["start"], self.ball.pos) < 3.0:
            return
        self.outbox.append(
            {
                "player": c["player"],
                "type": "dribble",
                "outcome": "success",
                "start": c["start"],
                "end": self.ball.pos,
                "speed": None,
                "body": "foot_right",
                "t": c["t"],
                "sample": c["sample"],
                "frame": c["frame"],
                "qual": {},
            }
        )

    def emit(self, pl, type_, outcome, start, end, speed, body="foot_right", **qual):
        """An event that happens now (stamped on this step's sample). A pass
        or shot still in the air is settled first: what happened to it is
        what `pl` just did (a tackle on it, say), so it is written before."""
        if self.pending is not None:
            self.resolve_pending(pl)
        self.outbox.append(
            {
                "player": pl,
                "type": type_,
                "outcome": outcome,
                "start": start,
                "end": end,
                "speed": speed,
                "body": body,
                "t": self.t,
                "sample": None,  # this step's
                "frame": None,
                "qual": qual,
            }
        )

    def end(self, outcome):
        if self.end_at is None:
            self.end_at = self.t + self.cfg["game"]["end_after_s"]
            if self.outcome == "timeout":
                self.outcome = outcome

    def post(self):
        """Write the events of this step, in order, to the record."""
        here = len(self.tracks.samples) - 1
        for e in self.outbox:
            sample = here if e["sample"] is None else e["sample"]
            frame = e["frame"] or self.snapshot()
            self.write(e, sample, frame)
        self.outbox = []
        if (
            self.end_at is None
            and self.owner is not None
            and self.owner.key[0] == 1
            and not self.in_hands
        ):
            near = min(
                math.dist(self.owner.pos, q.pos) for q in self.opponents(self.owner)
            )
            if near >= 15.0:
                self.end("defended_away")

    def snapshot(self):
        return [
            (p.player_id, p.team_id, p.key[0], p.x, p.y, p.facing) for p in self.players
        ]

    def write(self, e, sample, frame):
        pl = e["player"]
        side = pl.key[0]
        cm = lambda v: round(v, 2)
        ff, me, opp = [], None, []
        for pid, team, s, x, y, facing in frame:
            fx, fy = own(side, x, y)
            ff.append(
                {
                    "player_id": pid,
                    "team_id": team,
                    "x": cm(min(max(fx, 0.0), LENGTH)),
                    "y": cm(min(max(fy, 0.0), WIDTH)),
                    "facing_deg": round(own_facing(side, facing), 1) % 360,
                }
            )
            if pid == pl.player_id:
                me = (fx, fy)
            elif s != side:
                opp.append((fx, fy))
        sx, sy = own(side, *e["start"])
        ex, ey = own(side, *e["end"])
        clampx = lambda v: cm(min(max(v, 0.0), LENGTH))
        clampy = lambda v: cm(min(max(v, 0.0), WIDTH))
        n = len(self.events) + 1
        t = self.tracks.samples[sample].t
        ev = MatchEvent(
            event_id=f"{self.match.match_id}-e{n:05d}",
            match_id=self.match.match_id,
            possession_id=f"{self.match.match_id}-p{self.possessions:04d}",
            period=self.period,
            minute=int(t // 60),
            second=int(t % 60),
            team_id=pl.team_id,
            player_id=pl.player_id,
            type=e["type"],
            outcome=e["outcome"],
            body_part=e["body"],
            start_x=clampx(sx),
            start_y=clampy(sy),
            end_x=clampx(ex),
            end_y=clampy(ey),
            under_pressure=min((math.dist(me, o) for o in opp), default=99.0)
            <= self.engine["under_pressure_m"],
            ball_speed_kmh=None if e["speed"] is None else round(e["speed"], 1),
            qualifiers={**self.qual, **e["qual"]},
            freeze_frame=ff,
        )
        self.events.append(ev)
        self.tracks.events[ev.event_id] = sample

    def record(self):
        players = [None] * len(self.tracks.slots)
        for pl in self.players:
            players[self.slot[pl.player_id]] = (pl.x, pl.y, pl.facing)
        players[self.slot[referee.SLOT]] = (self.ref.x, self.ref.y, self.ref.facing)
        b = self.ball
        self.tracks.samples.append(
            Sample(self.t, self.period, players, (b.x, b.y, b.h), self.dead)
        )

    # ---- shared helpers -----------------------------------------------------------

    def reach(self, pl):
        k = self.cfg["control"]
        if (
            pl.keeper
            and self.in_box(pl.pos, pl.key[0])
            and self.in_box(self.stops_at(pl), pl.key[0])
        ):
            return k["keeper_hands_m"], k["keeper_height_m"]
        return k["feet_m"], k["feet_height_m"]

    def stops_at(self, pl):
        v = pl.speed
        if v < 0.1:
            return pl.pos
        slide = v * v / (2.0 * self.cfg["player"]["smother_decel"])
        return pl.x + pl.vx / v * slide, pl.y + pl.vy / v * slide

    def in_box(self, pos, side):
        """In the penalty area `side` defends."""
        gx = GOAL_X[1 - side]
        return abs(pos[0] - gx) <= BOX_DEPTH and abs(pos[1] - GOAL_Y) <= BOX_HALF

    def separate(self):
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


def run_attack(home, away, seed, cfg=None):
    return Game(home, away, seed, cfg).run()
