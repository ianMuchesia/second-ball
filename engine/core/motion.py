"""Player and ball movement, simulated in 0.1 s steps.

Between the engine's events every player and the ball keep moving. Each
player gets a target from his role (the team's shape around the live ball,
plus support angles, runs in behind, overlaps, pressing, cover, recovery and
the keeper's angle) or from an order the match gives him (meet this pass,
intercept here, close down the carrier, celebrate). Simple physics moves him
there: acceleration, deceleration and a top speed per pace. An event's freeze
frame is this state at that instant: one source, no noise, no teleports.

Decisions (who passes, whether it works) stay in sim.py; this module only
moves bodies. It has its own random stream, so movement never changes a
decision. All positions are absolute (home attacks +x).
"""

import math
import random
from dataclasses import dataclass, field

from engine.core.pitch import GOAL_Y, LENGTH, WIDTH, clamp, dist, own
from engine.core.shape import Frame, anchors

DT = 0.1  # seconds per step (10 Hz)
BRAIN_EVERY = 2  # role targets are recomputed every this many steps (0.2 s)
GOAL_LINE = {0: LENGTH, 1: 0.0}  # the goal each side attacks (absolute x)


@dataclass
class Body:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    facing: float = 0.0  # degrees, absolute frame
    leaving: bool = False  # sent off, walking to the touchline

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)


@dataclass
class Order:
    """A job that overrides a player's role until done or `until`."""

    target: tuple | None  # a fixed point, or None to follow `chase`
    pace: str
    until: float
    chase: tuple | None = None  # ("player", key) or ("ball",)
    offset: float = 0.0  # stop this far short of a chased player (m)


@dataclass
class Flight:
    start: tuple
    end: tuple
    t0: float
    t1: float
    peak: float  # metres; 0 for a ground pass
    h0: float = 0.0  # height when it left (a ball played on from the air)


@dataclass
class Sample:
    t: float
    period: int
    players: list  # per slot: (x, y, facing) or None when off the pitch
    ball: tuple  # (x, y, h)
    dead: bool  # ball out of play (a restart is being set up)


@dataclass
class Tracks:
    """10 Hz movement for a whole match (written for recorded runs only)."""

    hz: int
    slots: list  # player_id per slot, home XI then away XI
    samples: list = field(default_factory=list)
    events: dict = field(default_factory=dict)  # event_id -> sample index


class Motion:
    def __init__(self, sim, record=False):
        self.sim = sim
        self.cfg = sim.cfg["motion"]
        self.rng = random.Random(f"motion-{sim.match.seed}")
        self.bodies: dict = {}
        self.orders: dict = {}
        self.ball = [LENGTH / 2, GOAL_Y, 0.0]
        self.owner = None  # (side, player) with the ball at his feet
        self.flight: Flight | None = None
        self.dead = False
        self.press_close = False  # the nearest defender closes right in
        self.targets: dict = {}
        self.steps = 0
        self.t = sim.t
        keys = [(s, pl) for s in (0, 1) for pl in sorted(sim.teams[s].on_pitch)]
        self.slot = {k: i for i, k in enumerate(keys)}
        self.tracks = (
            Tracks(
                hz=round(1 / DT),
                slots=[sim.teams[s].profile.player_id(pl) for s, pl in keys],
            )
            if record
            else None
        )

    # ---- set-up --------------------------------------------------------------

    def kickoff_spots(self, side_with_ball):
        """Both teams in their own half around the centre spot."""
        spots = {}
        centre = (LENGTH / 2, GOAL_Y)
        for team in self.sim.teams:
            phase = (
                "in_possession" if team.side == side_with_ball else "out_of_possession"
            )
            block = self.sim.block_height(team.side)
            for pl, (x, y) in anchors(team, centre, phase, block, self.sim.cfg).items():
                if team.side == 0:
                    x = min(x, LENGTH / 2 - 1.0)
                else:
                    x = max(x, LENGTH / 2 + 1.0)
                spots[(team.side, pl)] = (x, y)
            if team.side == side_with_ball:
                # The taker stands over the ball when the whistle goes.
                spots[(team.side, team.front_player)] = centre
        return spots

    def start_period(self, side_with_ball):
        """Kick-off of a half. The first: everyone starts in place. The second:
        they walked there at the end of the first half (walk_to_kickoff)."""
        self.t = self.sim.t
        if not self.bodies:
            self.bodies = {
                k: Body(x, y, facing=0.0 if k[0] == 0 else 180.0)
                for k, (x, y) in self.kickoff_spots(side_with_ball).items()
            }
        self.orders.clear()
        self.flight, self.owner, self.dead = None, None, True
        self.ball = [LENGTH / 2, GOAL_Y, 0.0]

    # ---- what the match tells it -------------------------------------------------

    def place_ball(self, at):
        """A dead ball going to its restart spot: it rolls there (thrown back by
        a ball boy or a player), it never jumps."""
        self.owner, self.dead = None, True
        start = (self.ball[0], self.ball[1])
        d = dist(start, at)
        if d < 0.05:
            self.flight = None
            return
        roll = d / self.cfg["ball_return_ms"]
        self.flight = Flight(
            start, (at[0], at[1]), self.t, self.t + roll, 0.0, self.ball[2]
        )

    def ball_settled(self):
        return self.flight is None and self.ball[2] == 0.0

    def give(self, key):
        """`key` is now meant to have the ball; he gathers it if not at it."""
        if self.owner != key:
            self.owner = None
        if key not in self.bodies:
            return
        if self.flight is None and dist(self.bodies[key].pos, self.ball) <= 1.2:
            self.owner = key
            self.dead = False
        else:
            self.order(key, None, "sprint", 8.0, chase=("ball",))

    def kick(self, end, speed_kmh, receiver=None, lofted=False, cap_ms=None):
        """The ball leaves the carrier towards `end`. A lofted ball travels
        slower than a driven one, and no ball goes faster than a real one."""
        start = (self.ball[0], self.ball[1])
        d = dist(start, end)
        v = max(1.0, speed_kmh / 3.6)
        if lofted:
            v = min(v, self.cfg["lofted_ms"])
        if cap_ms is not None:
            v = min(v, cap_ms)
        flight = max(0.15, d / v)
        peak = min(16.0, 0.2 * d) if lofted else 0.0
        # Launch speed (along the ground and up) within a real ball's.
        top = self.cfg["ball_max_ms"]
        if peak:
            peak = min(peak, math.sqrt(max(0.0, top**2 - v**2)) * flight / 4)
        self.flight = Flight(start, end, self.t, self.t + flight, peak, self.ball[2])
        self.owner, self.dead = None, False
        if receiver is not None and receiver in self.bodies:
            need = dist(self.bodies[receiver].pos, end) / flight
            self.order(receiver, end, self.pace_for(need), flight + 2.0)
        return flight

    def stop_ball(self):
        """The ball is stopped where it is now (intercepted, blocked, caught);
        if it was in the air it drops, it does not vanish to the ground."""
        self.flight = None

    def carry(self, key, end, speed):
        """The carrier runs the ball to `end` at about `speed` m/s."""
        self.order(key, end, self.pace_for(speed), 30.0)

    def order(self, key, target, pace, seconds, chase=None, offset=0.0):
        if key in self.bodies:
            self.orders[key] = Order(target, pace, self.t + seconds, chase, offset)

    def send_off(self, key):
        b = self.bodies.get(key)
        if b is not None:
            b.leaving = True
            self.order(key, (b.x, 0.0 if b.y < GOAL_Y else WIDTH), "walk", 120.0)

    def mark(self, event_id):
        if self.tracks is not None:
            self.tracks.events[event_id] = len(self.tracks.samples) - 1

    def pace_for(self, speed):
        caps = self.cfg["pace"]
        for name in ("walk", "jog", "run", "sprint"):
            if speed <= caps[name]:
                return name
        return "sprint"

    # ---- the clock ---------------------------------------------------------------

    def advance(self, seconds):
        """Move everything forward `seconds` (whole steps); returns the time moved."""
        n = max(1, round(seconds / DT))
        for _ in range(n):
            self.step()
        return n * DT

    def step(self):
        self.t += DT
        self.move_ball()
        if self.steps % BRAIN_EVERY == 0:
            self.targets = self.roles()
        self.steps += 1
        for key, body in list(self.bodies.items()):
            target, pace = self.target_for(key)
            self.move(body, target, pace)
            if body.leaving and (body.y <= 0.3 or body.y >= WIDTH - 0.3):
                del self.bodies[key]
                self.orders.pop(key, None)
        self.face()
        self.check_control()
        self.record()

    def move_ball(self):
        f = self.flight
        if f is not None:
            u = clamp((self.t - f.t0) / (f.t1 - f.t0), 0.0, 1.0)
            self.ball[0] = f.start[0] + (f.end[0] - f.start[0]) * u
            self.ball[1] = f.start[1] + (f.end[1] - f.start[1]) * u
            # Its arc, plus whatever height it started at, fading out.
            self.ball[2] = 4 * f.peak * u * (1 - u) + f.h0 * (1 - u)
            if u >= 1.0:
                self.flight = None
        elif self.ball[2] > 0.0:  # dropping after it was stopped in the air
            self.ball[2] = max(0.0, self.ball[2] - self.cfg["ball_drop_ms"] * DT)
        elif self.owner in self.bodies:
            b = self.bodies[self.owner]
            a = math.radians(b.facing)
            self.ball[0] = clamp(b.x + 0.5 * math.cos(a), 0.0, LENGTH)
            self.ball[1] = clamp(b.y + 0.5 * math.sin(a), 0.0, WIDTH)

    def check_control(self):
        """A player meant to have the loose ball takes it when he reaches it."""
        if self.flight is not None or self.owner is not None or self.dead:
            return
        sim = self.sim
        key = (sim.attack, sim.carrier)
        b = self.bodies.get(key)
        if b is not None and dist(b.pos, self.ball) <= 1.2:
            self.owner = key
            self.orders.pop(key, None)

    def record(self):
        if self.tracks is None:
            return
        players = [None] * len(self.tracks.slots)
        for key, b in self.bodies.items():
            players[self.slot[key]] = (b.x, b.y, b.facing)
        self.tracks.samples.append(
            Sample(self.t, self.sim.period, players, tuple(self.ball), self.dead)
        )

    # ---- physics -----------------------------------------------------------------

    def move(self, b, target, pace):
        # The hot loop (about 1.3M calls a match): plain arithmetic, settings
        # read once; the same numbers as before, step for step.
        cfg = self.cfg
        caps = cfg["pace"]
        cap = caps[pace]
        dx, dy = target[0] - b.x, target[1] - b.y
        d = math.hypot(dx, dy)
        if d < 0.15 and b.vx == 0.0 and b.vy == 0.0:
            return  # standing on his spot: nothing would change
        # Arrive: slow down in time to stop on the target.
        want = 0.0 if d < 0.15 else min(cap, math.sqrt(2 * cfg["decel"] * d) * 0.9)
        wx, wy = (dx / d * want, dy / d * want) if d >= 0.15 else (0.0, 0.0)
        ax, ay = (wx - b.vx) / DT, (wy - b.vy) / DT
        a = math.hypot(ax, ay)
        limit = cfg["accel"] if want > math.hypot(b.vx, b.vy) else cfg["decel"]
        if pace == "dive":  # a keeper's dive: explosive, short
            limit = cfg["dive_accel"]
        if a > limit:
            ax, ay = ax * limit / a, ay * limit / a
        b.vx += ax * DT
        b.vy += ay * DT
        s = math.hypot(b.vx, b.vy)
        top = max(caps["sprint"], cap)
        if s > top:
            b.vx, b.vy = b.vx * top / s, b.vy * top / s
        x, y = b.x + b.vx * DT, b.y + b.vy * DT  # kept on the pitch
        b.x = 0.0 if x < 0.0 else LENGTH if x > LENGTH else x  # noqa: FURB136 - hot loop: no min/max calls
        b.y = 0.0 if y < 0.0 else WIDTH if y > WIDTH else y  # noqa: FURB136 - hot loop

    def face(self):
        """Face where you run; when slow, face the ball (the carrier: forward)."""
        step = self.cfg["turn_deg_s"] * DT
        for key, b in self.bodies.items():
            speed = math.hypot(b.vx, b.vy)
            if key == self.owner and speed < 1.0:
                want = 0.0 if key[0] == 0 else 180.0
            elif speed >= 1.0 and not self.is_keeper(key):
                want = math.degrees(math.atan2(b.vy, b.vx)) % 360
            else:
                want = (
                    math.degrees(math.atan2(self.ball[1] - b.y, self.ball[0] - b.x))
                    % 360
                )
            turn = (want - b.facing + 540) % 360 - 180
            turn = -step if turn < -step else step if turn > step else turn  # noqa: FURB136 - hot loop
            b.facing = (b.facing + turn) % 360

    def is_keeper(self, key):
        return key[1] == self.sim.teams[key[0]].keeper

    # ---- targets -------------------------------------------------------------------

    def target_for(self, key):
        o = self.orders.get(key)
        if o is not None:
            if self.t > o.until:
                del self.orders[key]
            else:
                if o.chase == ("ball",):
                    return (self.ball[0], self.ball[1]), o.pace
                if o.chase and o.chase[0] == "player" and o.chase[1] in self.bodies:
                    p = self.bodies[o.chase[1]].pos
                    me = self.bodies[key].pos
                    d = dist(me, p)
                    if d > o.offset and d > 0:
                        k = (d - o.offset) / d
                        return (
                            me[0] + (p[0] - me[0]) * k,
                            me[1] + (p[1] - me[1]) * k,
                        ), o.pace
                    return me, o.pace
                return o.target, o.pace
        return self.targets.get(key, (self.bodies[key].pos, "walk"))

    def roles(self):
        """Every player's role target and pace, from the live ball and shape."""
        sim, cfg = self.sim, self.cfg
        attack, defence = sim.attack, 1 - sim.attack
        ball = (self.ball[0], self.ball[1])
        if self.flight is not None:  # shape follows where the ball is going
            ball = self.flight.end
        transition = sim.t < sim.transition_until
        phases = {
            attack: "transition" if transition else "in_possession",
            defence: "transition" if transition else "out_of_possession",
        }
        out = {}
        for team in sim.teams:
            spots = anchors(
                team,
                ball,
                phases[team.side],
                sim.block_height(team.side),
                sim.cfg,
                sim.push(team.side),
            )
            for pl, spot in spots.items():
                key = (team.side, pl)
                if key in self.bodies:
                    d = dist(self.bodies[key].pos, spot)
                    pace = (
                        "walk"
                        if d < cfg["walk_within_m"]
                        else "jog"
                        if d < cfg["run_beyond_m"]
                        else "run"
                    )
                    out[key] = (spot, pace)
        if self.dead:
            return out
        # The player on the ball shields it and edges forward until he acts;
        # in the box he holds it (he does not walk it to the byline).
        if self.owner in self.bodies:
            fx, fy = own(self.owner[0], *self.bodies[self.owner].pos)
            out[self.owner] = (
                own(self.owner[0], max(fx, min(fx + 1.5, cfg["edge_until_x"])), fy),
                "walk",
            )
        self.attacking_roles(out, attack, ball)
        self.defending_roles(out, defence, ball, transition)
        for side in (0, 1):
            self.keeper(out, side, ball)
        return out

    def outfield(self, side):
        team = self.sim.teams[side]
        return [
            k
            for k in self.bodies
            if k[0] == side and k[1] != team.keeper and not self.bodies[k].leaving
        ]

    def attacking_roles(self, out, side, ball):
        cfg, sim = self.cfg, self.sim
        team = sim.teams[side]
        carrier = (side, sim.carrier)
        bx, by = own(side, *ball)
        free = [k for k in self.outfield(side) if k != carrier and k not in self.orders]
        # Support: the two nearest teammates offer an angle either side, ahead.
        if carrier in self.bodies:
            cx, cy = own(side, *self.bodies[carrier].pos)
            near = sorted(
                free, key=lambda k: dist(self.bodies[k].pos, self.bodies[carrier].pos)
            )[:2]
            for k in near:
                ax, ay = own(side, *out[k][0])
                sx = cx + cfg["support_m"] * math.cos(math.radians(35))
                sy = cy + math.copysign(
                    cfg["support_m"] * math.sin(math.radians(35)), ay - cy or 1
                )
                spot = own(side, (sx + ax) / 2, (sy + ay) / 2)
                out[k] = (spot, "run")
        # Runs in behind: forwards go to the defensive line (onside) when the
        # ball is in the middle or final third.
        if 30.0 <= bx <= 92.0:
            line = self.offside_line(side)
            for k in free:
                role = team.roles.get(k[1])
                depth = (
                    team.table[("in_possession", "centre")].get(role, (0, 0))[0]
                    if role
                    else 0
                )
                if depth >= cfg["runner_depth"]:
                    ax, ay = own(side, *out[k][0])
                    tx = clamp(
                        max(ax, line - 1.0), ax, min(ax + cfg["run_ahead_m"], 100.0)
                    )
                    out[k] = (own(side, tx, ay), "sprint" if tx - ax > 4 else "run")
        # Overlap: the ball-side full-back goes past the ball in the final 40%.
        if bx >= 62.0:
            flank = "left" if by > GOAL_Y else "right"
            fb = team.fullbacks().get(flank)
            if fb is not None and (side, fb) in free:
                ty = WIDTH - 5.0 if flank == "left" else 5.0
                out[(side, fb)] = (own(side, min(bx + 8.0, 96.0), ty), "sprint")

    def offside_line(self, side):
        """The second-last defender's depth, in the attacking team's frame."""
        xs = sorted(
            (own(side, *self.bodies[k].pos)[0] for k in self.bodies if k[0] != side),
            reverse=True,
        )
        return xs[1] if len(xs) > 1 else LENGTH / 2

    def defending_roles(self, out, side, ball, transition):
        cfg = self.cfg
        goal = (0.0 if side == 0 else LENGTH, GOAL_Y)
        free = [k for k in self.outfield(side) if k not in self.orders]
        if not free:
            return
        by_dist = sorted(free, key=lambda k: dist(self.bodies[k].pos, ball))
        # The nearest presses (goal-side of the ball); the next covers behind him.
        gx, gy = goal[0] - ball[0], goal[1] - ball[1]
        g = math.hypot(gx, gy) or 1.0
        gap = cfg["press_close_m"] if self.press_close else cfg["press_hold_m"]
        out[by_dist[0]] = (
            (ball[0] + gx / g * gap, ball[1] + gy / g * gap),
            "sprint" if self.press_close else "run",
        )
        if len(by_dist) > 1:
            c = cfg["cover_m"]
            out[by_dist[1]] = ((ball[0] + gx / g * c, ball[1] + gy / g * c), "run")
        # Recovery: after losing the ball, anyone caught upfield runs back.
        if transition:
            bx_own = own(side, *ball)[0]
            for k in by_dist[2:]:
                if own(side, *self.bodies[k].pos)[0] > bx_own:
                    out[k] = (out[k][0], "sprint")

    def keeper(self, out, side, ball):
        team = self.sim.teams[side]
        key = (side, team.keeper)
        if key not in self.bodies or key in self.orders or key == self.owner:
            return
        goal = (0.0 if side == 0 else LENGTH, GOAL_Y)
        d = dist(goal, ball)
        r = clamp(self.cfg["keeper_ratio"] * d, 1.5, self.cfg["keeper_max_m"])
        ux, uy = (ball[0] - goal[0]) / (d or 1.0), (ball[1] - goal[1]) / (d or 1.0)
        out[key] = ((goal[0] + ux * r, goal[1] + uy * r), "run")

    # ---- a frame ----------------------------------------------------------------

    def snapshot(self):
        """The freeze frame now: positions and facing of everyone on the pitch."""
        positions = {k: (b.x, b.y) for k, b in self.bodies.items() if not b.leaving}
        facing = {k: b.facing for k, b in self.bodies.items() if not b.leaving}
        return Frame(positions, facing, dict(positions))
