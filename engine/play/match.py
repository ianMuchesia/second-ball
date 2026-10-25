"""Phase 6: the full 11-a-side match on the physics-first engine.

Everything the attack (engine/play/game.py) does, for 22 players over two
halves: the ball's physics, winning it by getting there, dribbling touch by
touch, jockeying and tackling, passing only when safe, shooting when the
chance is good, the keeper's dive, clearances. Around that, the team:

- Shape: every player's place comes from his club's own shape tables
  (engine.core.shape.anchors, as the current engine), around the live ball,
  in possession or out of it.
- Jobs, re-planned all the time: the nearest player presses the ball, the
  next covers goal-side of him, the two nearest teammates of the carrier
  offer angles, forwards hold the last defender's shoulder, the rest keep
  the shape. A loose ball: the best-placed of each team goes for it.
- Restarts are walked to, never jumped: the ball rolls (a ball boy) to its
  spot, the taker goes to it, then throws, kicks or crosses it. Throw-ins,
  goal kicks, corners, free kicks (a foul from behind), kick-offs after a
  goal and at each half.
- The clock: two halves of 45 minutes; at half-time everyone walks back to
  his kick-off place. Goals are the ball over the line, as in the attack.

Not done yet (reported, not faked): offside, cards, penalties, headers, the
scripted storyline beats. The current engine stays the default; this one
runs behind ENGINE=physics (engine.generate).
"""

import math
import random

from core.contracts import Match
from engine.core.lineup import lineup
from engine.core.motion import Tracks
from engine.core.pitch import GOAL_Y, LENGTH, WIDTH
from engine.core.shape import TeamState, anchors
from engine.core.sim import DEFAULT_KICKOFF, load_config, underdog_caution
from engine.league import COMPETITION
from engine.play import referee
from engine.play.ball import Ball
from engine.play.drill import load_play
from engine.play.game import GOAL_X, Game, GameResult, Mind, unit
from engine.play.player import Player

CENTRE = (LENGTH / 2, GOAL_Y)
HALF_S = 45 * 60.0


class FullMatch(Game):
    """A whole match. Built from scratch (not Game's five-player set-up)."""

    def __init__(
        self,
        home,
        away,
        seed,
        weather="dry",
        kickoff=DEFAULT_KICKOFF,
        cfg=None,
        half_s=HALF_S,
    ):
        self.cfg = cfg or load_play()
        # In a match a man under pressure shoots only at a fair chance.
        self.cfg = {
            **self.cfg,
            "shoot": {
                **self.cfg["shoot"],
                "min_quality": self.cfg["match"]["shoot_pressed_q"],
                # Real finishing: about a third of shots on target.
                "err_deg": self.cfg["match"]["shot_err_deg"],
                "err_deg_per_m": self.cfg["match"]["shot_err_deg_per_m"],
                "err_pressure_deg": self.cfg["match"]["shot_err_pressure_deg"],
            },
        }
        self.engine = load_config()
        self.rng = random.Random(f"match-{seed}")
        self.half_s = half_s
        sheets = [*lineup(home), *lineup(away)]
        self.match = Match(
            match_id=f"m-{home.id}-{away.id}-{seed}",
            home_team=home.id,
            away_team=away.id,
            venue=home.stadium,
            kickoff=kickoff,
            competition=COMPETITION,
            seed=seed,
            weather=weather,
            mode="free_simulation",
            home_strength=home.strength,
            away_strength=away.strength,
            lineups=sheets,
        )
        self.teams = (TeamState.start(0, home), TeamState.start(1, away))
        self.players = []
        self.keepers = {}
        first = self.rng.choice((0, 1))  # who kicks off the first half
        spots = self.kickoff_spots(first)
        for team in self.teams:
            for idx in team.on_pitch:
                x, y = spots[(team.side, idx)]
                pl = Player(
                    (team.side, idx),
                    team.profile.player_id(idx),
                    team.profile.id,
                    idx == team.keeper,
                    x,
                    y,
                    facing=0.0 if team.side == 0 else 180.0,
                )
                self.players.append(pl)
                if pl.keeper:
                    self.keepers[team.side] = pl
        self.by_key = {p.key: p for p in self.players}
        self.mind = {
            p.key: Mind(next_think=0.04 * i) for i, p in enumerate(self.players)
        }
        for p in self.players:
            self.mind[p.key].heading = 0.0 if p.key[0] == 0 else 180.0
        self.period = 1
        self.qual = {}
        self.ball = Ball(*CENTRE)
        self.owner = None
        self.in_hands = False
        self.touch_phase = 0.0
        self.last_touch = None
        self.kicked_at = {}
        self.pending = None
        self.saved_by = None
        self.net_x = None
        self.opening = False
        self.carry = None
        self.possessions = 0
        self.changes = []
        self.dead = True
        self.t = 0.0
        self.end_at = None
        self.outcome = "full_time"
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
                "clearances",
                "fouls",
                "corners",
                "throw_ins",
                "goal_kicks",
            ],
            0,
        )
        self.score = [0, 0]
        self.poss = first
        self.events, self.outbox = [], []
        slots = [s.player_id for s in sheets] + [referee.SLOT]
        self.slot = {pid: k for k, pid in enumerate(slots)}
        self.tracks = Tracks(hz=round(1 / self.cfg["dt"]), slots=slots)
        self.ref = referee.make()
        self.prev_ball = self.ball.pos
        self.restart = None
        self.shape_cache = {}
        self.first = first
        self.half_time_done = False
        # Each club's own tactics (engine/league/clubs/*.yaml).
        for side in (0, 1):
            self.teams[side].caution = underdog_caution(
                self.engine,
                self.teams[side].profile.strength,
                self.teams[1 - side].profile.strength,
            )
        self.counterpress = {0: -1.0, 1: -1.0}  # side -> hunting the ball until
        self.transition_until = -1.0
        self.regain = {0: None, 1: None}  # side -> (won at, look for the runners first)
        self.owned_since = 0.0
        self.territory = []  # (t, side whose third the ball is in), for game state
        self.next_mode_check = 0.0
        self.mode_log = []
        self.set_restart("kickoff", first, CENTRE, delay=2.0)

    # ---- the clock ----------------------------------------------------------------

    def run(self):
        self.record()
        while True:
            if self.period == 1 and self.t >= self.half_s and self.can_stop():
                self.half_time()
            elif self.period == 2 and self.t >= 2 * self.half_s and self.can_stop():
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

    def can_stop(self):
        """The whistle waits for a shot in flight to land."""
        return self.pending is None or self.pending["kind"] != "shot"

    def half_time(self):
        """Everyone walks back to his kick-off place; the ball is brought to
        the centre; the other team kicks off the second half at 45:00."""
        self.flush_carry()
        self.post()
        self.owner, self.in_hands, self.pending = None, False, None
        self.dead = True
        second = 1 - self.first
        spots = self.kickoff_spots(second)
        self.restart = None
        # The break, recorded: everyone goes back to his place (jogging if
        # far away) before the second half starts.
        for _ in range(int(self.cfg["match"]["kickoff_wait_s"] / self.cfg["dt"])):
            self.t = round(self.t + self.cfg["dt"], 6)
            self.prev_ball = self.ball.pos
            for pl in self.players:
                far = math.dist(pl.pos, spots[pl.key])
                pl.move(
                    spots[pl.key],
                    4.0 if far > 8.0 else 1.9,
                    self.cfg["dt"],
                    self.cfg["player"],
                )
                pl.face(CENTRE, self.cfg["dt"], self.cfg["player"])
            referee.step(
                self.ref,
                CENTRE,
                self.cfg["dt"],
                self.cfg["player"],
                self.cfg["referee"],
            )
            self.roll_ball(CENTRE)
            self.record()
            if all(
                math.dist(p.pos, spots[p.key]) < 0.3 for p in self.players
            ) and self.ball_at(CENTRE):
                break
        for pl in self.players:
            pl.vx = pl.vy = 0.0
        self.period = 2
        self.t = self.half_s
        self.poss = second
        self.set_restart("kickoff", second, CENTRE, delay=1.0)
        self.record()

    # ---- kick-off places and shape ------------------------------------------------

    def kickoff_spots(self, side_with_ball):
        """Both teams in their own half, the other team outside the circle;
        the kicker on the spot."""
        spots = {}
        for team in self.teams:
            phase = (
                "in_possession" if team.side == side_with_ball else "out_of_possession"
            )
            for idx, (x, y) in anchors(
                team, CENTRE, phase, team.profile.block_height, self.engine
            ).items():
                x = (
                    min(x, LENGTH / 2 - 1.0)
                    if team.side == 0
                    else max(x, LENGTH / 2 + 1.0)
                )
                if team.side != side_with_ball and math.dist((x, y), CENTRE) < 9.5:
                    ux, uy = unit(x - CENTRE[0], y - CENTRE[1])
                    if ux == uy == 0.0:
                        ux = -1.0 if team.side == 0 else 1.0
                    x, y = CENTRE[0] + ux * 9.5, CENTRE[1] + uy * 9.5
                spots[(team.side, idx)] = (x, y)
        kicker = self.teams[side_with_ball].front_player
        spots[(side_with_ball, kicker)] = (
            CENTRE[0] - (0.6 if side_with_ball == 0 else -0.6),
            CENTRE[1],
        )
        return spots

    def shape(self, side):
        """This team's shape spots for the live ball (in or out of possession)."""
        key = (side, round(self.t, 1))
        if key not in self.shape_cache:
            if len(self.shape_cache) > 64:
                self.shape_cache.clear()
            team = self.teams[side]
            if self.t < self.transition_until:
                phase = "transition"  # the seconds after the ball changed hands
            else:
                phase = "in_possession" if self.poss == side else "out_of_possession"
            self.shape_cache[key] = anchors(
                team,
                self.ball.pos,
                phase,
                self.block(side),
                self.engine,
                self.effect(side, "fullback_push_m", 0.0),
            )
        return self.shape_cache[key]

    # ---- the clubs' tactics -------------------------------------------------------

    def effect(self, side, key, default):
        """A game-state effect (game_state.<mode>.<key> in engine.yaml)."""
        mode = self.teams[side].mode
        return self.engine["game_state"].get(mode, {}).get(key, default)

    def block(self, side):
        """How deep the team defends (the club's block height, dropped when
        managing or protecting a lead, and a little when the underdog)."""
        team = self.teams[side]
        drop = self.effect(side, "block_drop_m", 0.0)
        if team.mode == "protect":
            drop = team.profile.late_lead_block_drop
        drop += team.caution * self.engine["underdog"]["block_drop_m"]
        return team.profile.block_height - drop

    def intensity(self, side):
        """How hard the team presses: the club's target PPDA (10 = 1.0)."""
        team = self.teams[side]
        ref = self.engine["pressing"]["ppda_reference"]
        return ref / team.profile.target_ppda * self.effect(side, "press", 1.0)

    def directness(self, side):
        d = self.teams[side].profile.directness + self.effect(side, "directness", 0.0)
        return min(max(d, 0.0), 1.0)

    def press_line(self, side):
        """How far from its own goal the team starts to press the ball."""
        c = self.cfg["match"]
        return (
            self.block(side)
            + c["press_from_block_m"]
            + c["press_per_intensity_m"] * (self.intensity(side) - 1.0)
        )

    def own_x(self, side, pos):
        """Distance from `side`'s own goal line."""
        return abs(pos[0] - GOAL_X[1 - side])

    def update_modes(self):
        """Late in the game the score changes how a team plays (as the
        current engine): leading 1-3 after 65', manage (deeper, safer); if
        the opponent camps in its third, protect (the club's back-five shape,
        clear more); trailing 1-2, chase (its chasing shape, press harder)."""
        gs = self.engine["game_state"]
        minute = (self.t - (self.half_s if self.period == 2 else 0.0)) / 60 + (
            45 if self.period == 2 else 0
        )
        self.territory = [
            x for x in self.territory if x[0] >= self.t - gs["threat_window_s"]
        ]
        for side in (0, 1):
            team = self.teams[side]
            lead = self.score[side] - self.score[1 - side]
            if (
                minute < gs["from_minute"]
                or lead == 0
                or abs(lead) >= gs["comfortable_margin"]
            ):
                mode = "normal"
            elif lead < 0:
                mode = "chase" if -lead <= gs["chase_max_deficit"] else "normal"
            else:
                share = sum(1 for _, s in self.territory if s == side) / max(
                    1, len(self.territory)
                )
                stronger = self.teams[1 - side].profile.strength > team.profile.strength
                limit = (
                    gs["escalate_share_vs_stronger"]
                    if stronger
                    else gs["escalate_share"]
                )
                mode = "protect" if share >= limit else "manage"
            if mode != team.mode:
                team.mode = mode
                self.mode_log.append(
                    {"t": self.t, "team": team.profile.id, "mode": mode}
                )

    def pace(self, pl, spot):
        d = math.dist(pl.pos, spot)
        return 1.9 if d < 3.0 else 4.0 if d < 12.0 else 5.5

    # ---- hooks Game asks -----------------------------------------------------------

    def attacking(self, pl):
        return not self.clearing(pl)

    def clearing(self, pl):
        """In his own third with a man near: get it away (pass out or clear).
        A team that builds up short only clears when really in trouble; one
        protecting a lead clears sooner."""
        if not self.in_own_third(pl):
            return False
        team = self.teams[pl.key[0]]
        near = self.cfg["match"]["clear_when_m"]
        if team.profile.build_up is not None:
            near = self.cfg["match"]["clear_when_building_m"]
        near *= self.effect(pl.key[0], "clearance", 1.0)
        return self.pressure(pl) <= near

    def hold_line(self, pl):
        return self.cfg["match"]["hold_line_m"]

    def parry(self, out, side):
        """A keeper in a match pushes it wide, towards the byline (often
        behind for a corner), not back into the six-yard box."""
        c = self.cfg["match"]
        ang = math.degrees(math.atan2(side, out * 0.25)) + self.rng.uniform(-15.0, 15.0)
        return ang, c["parry_keep"]

    def lunge_range(self):
        return self.cfg["match"]["lunge_range_m"]

    def pass_bias(self, pl):
        """A team keeps the ball: a safe pass is preferred to running at
        people (about 85% of real on-ball actions are passes); patient clubs
        more so, and nobody holds it much past the club's tempo."""
        c = self.cfg["match"]
        side = pl.key[0]
        bias = c["pass_bias"] + c["pass_bias_patience"] * (1.0 - self.directness(side))
        spa = self.teams[side].profile.tempo.seconds_per_action * self.effect(
            side, "tempo", 1.0
        )
        if self.t - self.owned_since > spa:
            bias += c["pass_bias_overdue"]
        # A set defender in front of him near the box: move the ball on,
        # do not run into him.
        if self.own_x(1 - side, pl.pos) <= LENGTH / 3:
            goal = self.goal_of(side)
            gx, gy = unit(goal[0] - pl.x, goal[1] - pl.y)
            for q in self.opponents(pl):
                if q.keeper:
                    continue
                ahead = (q.x - pl.x) * gx + (q.y - pl.y) * gy
                if 0.0 < ahead and math.dist(q.pos, pl.pos) <= c["set_defender_m"]:
                    bias += c["pass_bias_set_defender"]
                    break
        return bias

    def pass_style(self, pl):
        """Direct clubs look forward and longer; a club that builds up short
        keeps it short in its own zone; just after winning the ball a
        counter-attacking club looks for its runners first."""
        c = self.cfg["match"]
        side = pl.key[0]
        team = self.teams[side]
        d = self.directness(side)
        max_m = c["pass_m"][0] + (c["pass_m"][1] - c["pass_m"][0]) * d
        bu = team.profile.build_up
        if bu is not None and self.own_x(side, pl.pos) < bu.short_until_x:
            max_m = min(max_m, c["build_up_pass_m"])
        prefer = None
        reg = self.regain[side]
        if reg is not None and reg[1] and self.t - reg[0] <= c["counter_s"]:
            prefer = set(self.counter_runners(side))
            max_m = max(max_m, c["pass_m"][1])
        return max_m, 0.3 + 0.6 * d, prefer

    def on_ball(self, pl):
        """As in the attack, plus the long ball of a direct club."""
        if not self.in_hands and self.long_ball_due(pl):
            return self.long_ball(pl)
        if not self.in_hands and self.clear_due(pl):
            return self.clear(pl)
        return super().on_ball(pl)

    def clear_due(self, pl):
        """Near his own goal with a man on him, a defender of a club that
        does not build up short puts it away rather than passing it out."""
        c = self.cfg["match"]
        side = pl.key[0]
        if self.teams[side].profile.build_up is not None:
            return False
        goal = (GOAL_X[1 - side], GOAL_Y)
        return math.dist(pl.pos, goal) <= c["clear_box_m"] and self.clearing(pl)

    def long_ball_due(self, pl):
        """A direct club in its own half hits it long: at once after winning
        it (when its counter is on), or under pressure, by its directness."""
        c = self.cfg["match"]
        side = pl.key[0]
        d = self.directness(side)
        if d < c["long_ball_directness"] or self.own_x(side, pl.pos) > LENGTH / 2:
            return False
        reg = self.regain[side]
        if reg is not None and reg[1] and self.t - reg[0] <= c["counter_s"]:
            return True
        return (
            self.pressure(pl) <= c["long_ball_pressed_m"]
            and self.rng.random() < d * c["long_ball_rate"]
        )

    def long_ball(self, pl):
        """Over the top, into the space in front of the most advanced forward
        (his run), high enough to clear the midfield: a contest when it lands."""
        c = self.cfg["match"]
        side = pl.key[0]
        fwd = 1.0 if side == 0 else -1.0
        runner = self.by_key[self.counter_runners(side)[0]]
        tx = runner.x + fwd * c["long_ball_lead_m"]
        tx = min(tx, LENGTH - 6.0) if side == 0 else max(tx, 6.0)
        target = self.on_pitch((tx, runner.y))
        d = math.dist(self.ball.pos, target)
        speed = min(c["long_ball_ms"], max(12.0, d / 2.2))
        T = d / speed
        lift = min(0.5 * self.cfg["ball"]["gravity"] * T, 14.0)
        start = self.ball.pos
        self.flush_carry()
        self.pending = self.strike_record(pl, "pass", start, target, speed)
        self.pending["to"] = runner.key
        self.release(pl)
        ang = math.degrees(math.atan2(target[1] - start[1], target[0] - start[0]))
        self.ball.kick(speed, ang, lift=lift)
        self.kicked_at[pl.key] = self.t
        self.counts["passes"] += 1
        self.regain[side] = None
        self.mind[runner.key].intent = "chase"
        self.urgent()

    def counter_runners(self, side):
        """The club's counter runners: its most advanced outfield players."""
        team = self.teams[side]
        n = team.profile.on_regain.runners if team.profile.on_regain else 2
        mine = [p for p in self.players if p.key[0] == side and not p.keeper]
        mine.sort(key=lambda p: (-self.own_x(side, p.pos), p.key))
        return [p.key for p in mine[:n]]

    def shot_value(self, pl):
        """As in the attack, plus the shot from distance: 16-25 m out, a
        clear lane and a fair chance, he sometimes lets fly."""
        q = super().shot_value(pl)
        if q is not None:
            return q
        c = self.cfg["match"]
        side = pl.key[0]
        d = math.dist(pl.pos, self.goal_of(side))
        if not c["long_shot_m"][0] <= d <= c["long_shot_m"][1]:
            return None
        q, blockers = self.quality(pl, pl.pos)
        if (
            blockers == 0
            and q >= c["long_shot_q"]
            and self.rng.random() < c["long_shot_p"]
        ):
            return q
        return None

    def must_react(self):
        """A pass is taken by someone who has read it, not by whoever it
        happens to fly past (the passer's safety check assumes the same)."""
        return True

    def going_past(self, pl, o):
        """The carrier is going by him, close: he does not stand and watch."""
        if o.speed < 1.0:
            return False
        ux, uy = o.vx / o.speed, o.vy / o.speed
        ahead = (pl.x - o.x) * ux + (
            pl.y - o.y
        ) * uy  # how far in front of the carrier he is
        return (
            ahead < self.cfg["match"]["past_ahead_m"]
            and math.dist(pl.pos, o.pos) <= self.lunge_range() + 0.5
        )

    def tight(self, pl):
        """Only in his own third does a defender go in for a merely
        unshielded ball; elsewhere he contains and waits for a loose touch."""
        return self.in_own_third(pl)

    def engaging(self, q):
        return self.mind[q.key].intent == "press"

    def end(self, outcome):
        """A goal or a held save does not end a match; the clock does."""

    def post(self):
        here = len(self.tracks.samples) - 1
        for e in self.outbox:
            sample = here if e["sample"] is None else e["sample"]
            self.write(e, sample, e["frame"] or self.snapshot())
        self.outbox = []

    # ---- decisions off the ball ---------------------------------------------------

    def think(self, pl):
        if self.restart is not None:
            return self.restart_role(pl)
        if self.dead:
            return
        m = self.mind[pl.key]
        if m.intent == "celebrate" and self.net_x is not None:
            return
        return super().think(pl)

    def support(self, pl):
        """A teammate has it: the two nearest offer angles, forwards hold the
        last defender's shoulder, everyone else keeps the shape."""
        m = self.mind[pl.key]
        if pl.keeper:
            m.intent = "keep"
            return
        o = self.owner
        side = pl.key[0]
        fwd = 1.0 if side == 0 else -1.0
        spot = self.shape(side)[pl.key[1]]
        near = sorted(
            (q for q in self.mates(o) if not q.keeper),
            key=lambda q: (math.dist(q.pos, o.pos), q.key),
        )[:2]
        if pl in near:
            # An angle ahead and to one side of the carrier, 12 m away.
            sy = 1.0 if spot[1] >= o.y else -1.0
            a = math.radians(35.0)
            angle = (o.x + fwd * 12.0 * math.cos(a), o.y + sy * 12.0 * math.sin(a))
            spot = ((spot[0] + angle[0]) / 2, (spot[1] + angle[1]) / 2)
        team = self.teams[side]
        role = team.roles.get(pl.key[1])
        depth = (
            team.table[("in_possession", "centre")].get(role, (0, 0))[0] if role else 0
        )
        reg = self.regain[side]
        if (
            reg is not None
            and self.t - reg[0] <= self.cfg["match"]["counter_s"]
            and pl.key in self.counter_runners(side)
            and (team.profile.on_regain is not None or self.directness(side) >= 0.7)
        ):
            # The counter: sprint in behind, as far as the last line allows.
            line = self.last_line(1 - side)
            sx = (
                min(line - 0.5, pl.x + 20.0)
                if side == 0
                else max(line + 0.5, pl.x - 20.0)
            )
            spot = self.on_pitch((sx, pl.y + (o.y - pl.y) * 0.2))
            m.intent, m.spot, m.cap = "support", spot, self.cfg["player"]["top_speed"]
            return
        if depth >= self.engine["motion"]["runner_depth"]:
            # Forwards: on the last defender's shoulder, never offside.
            line = self.last_line(1 - side)
            sx = (
                min(spot[0] + 8.0, line - 0.5)
                if side == 0
                else max(spot[0] - 8.0, line + 0.5)
            )
            spot = (sx, spot[1])
        spot = self.on_pitch(spot)
        m.intent, m.spot, m.cap = "support", spot, max(4.0, self.pace(pl, spot))

    def defend(self, pl):
        """They have it: the nearest presses, the next covers goal-side, the
        rest keep the shape (out of possession)."""
        m = self.mind[pl.key]
        if pl.keeper:
            m.intent = "keep"
            return
        side = pl.key[0]
        mine = sorted(
            (q for q in self.players if q.key[0] == side and not q.keeper),
            key=lambda q: (math.dist(q.pos, self.ball.pos), q.key),
        )
        goal = (GOAL_X[1 - side], GOAL_Y)
        c = self.cfg["match"]
        # How many go to the ball: the club's press decides where it starts
        # and how many; a counter-press hunts it with three; near his own
        # goal a second man always closes the carrier too.
        ball_x = self.own_x(side, self.ball.pos)
        danger = math.dist(self.ball.pos, goal) <= c["double_m"]
        if self.t < self.counterpress[side]:
            n = 3
        elif ball_x > self.press_line(side):
            n = 0  # not this high: hold the shape and shuffle across
        else:
            n = 2 if (self.intensity(side) >= c["two_press_intensity"] or danger) else 1
        pressers = mine[:n]
        if pl in pressers:
            m.intent = "press"
            return
        if n == 0 and pl is mine[0]:
            # Screens the carrier from in front, keeping his place in the block.
            spot = self.shape(side)[pl.key[1]]
            ux, uy = unit(self.ball.x - spot[0], self.ball.y - spot[1])
            spot = self.on_pitch((spot[0] + ux * 3.0, spot[1] + uy * 3.0))
            m.intent, m.spot, m.cap = "support", spot, 5.0
            return
        cover = mine[len(pressers)] if len(mine) > len(pressers) else None
        if pl is cover:
            ux, uy = unit(goal[0] - self.ball.x, goal[1] - self.ball.y)
            # Covering: 8 m goal-side; near the box, in the shooting lane,
            # close enough to block it.
            gap = (
                c["lane_cover_m"]
                if math.dist(self.ball.pos, goal) <= c["lane_zone_m"]
                else 8.0
            )
            spot = (self.ball.x + ux * gap, self.ball.y + uy * gap)
            m.intent, m.spot, m.cap = "support", self.on_pitch(spot), 6.0
            return
        marked = self.marks(side, mine[: len(pressers) + 1]).get(pl.key)
        if marked is not None:
            # Goal-side of his man, an arm's length off.
            q = self.by_key[marked]
            ux, uy = unit(goal[0] - q.x, goal[1] - q.y)
            gap = self.cfg["match"]["mark_m"]
            spot = (q.x + q.vx * 0.3 + ux * gap, q.y + q.vy * 0.3 + uy * gap)
            m.intent, m.spot, m.cap = "support", self.on_pitch(spot), 7.0
            return
        spot = self.shape(side)[pl.key[1]]
        m.intent, m.spot, m.cap = "support", spot, self.pace(pl, spot)

    def marks(self, side, busy):
        """Who marks whom (worked out once per moment): attackers within
        `mark_zone_m` of goal, most dangerous first, each picked up by the
        nearest free defender whose place is in his own half."""
        key = (side, self.t)
        if getattr(self, "_marks_key", None) == key:
            return self._marks
        c = self.cfg["match"]
        goal = (GOAL_X[1 - side], GOAL_Y)
        carrier = self.owner.key if self.owner is not None else None
        threats = sorted(
            (
                q
                for q in self.players
                if q.key[0] != side
                and not q.keeper
                and q.key != carrier
                and math.dist(q.pos, goal) <= c["mark_zone_m"]
            ),
            key=lambda q: (math.dist(q.pos, goal), q.key),
        )
        shape = self.shape(side)
        free = [
            q
            for q in self.players
            if q.key[0] == side
            and not q.keeper
            and q not in busy
            and abs(shape[q.key[1]][0] - goal[0]) <= LENGTH / 2
        ]
        out = {}
        for t in threats:
            if not free:
                break
            d = min(free, key=lambda q: (math.dist(q.pos, t.pos), q.key))
            out[d.key] = t.key
            free.remove(d)
        self._marks, self._marks_key = out, key
        return out

    def positions(self, pl):
        """A loose ball he is not chasing: his place in the shape."""
        m = self.mind[pl.key]
        if pl.keeper:
            m.intent = "keep"
            return
        spot = self.shape(pl.key[0])[pl.key[1]]
        m.intent, m.spot, m.cap = "support", spot, self.pace(pl, spot)

    def last_line(self, side):
        """The x of `side`'s second-last player (keeper included): the line."""
        xs = sorted(
            (q.x for q in self.players if q.key[0] == side), reverse=(side == 1)
        )
        return xs[1] if len(xs) > 1 else CENTRE[0]

    def on_pitch(self, p):
        return min(max(p[0], 1.0), LENGTH - 1.0), min(max(p[1], 1.0), WIDTH - 1.0)

    def distribute(self, pl):
        """A keeper with it in his hands: throw it to a free man, else kick it long."""
        mate, _ = self.best_pass(pl)
        if mate is not None and math.dist(pl.pos, mate.pos) <= 35.0:
            return self.pass_ball(pl, mate, throw=True)
        self.clear(pl)

    def take(self, pl, hands=False, quiet=False):
        before = self.poss
        super().take(pl, hands=hands, quiet=quiet)
        self.poss = pl.key[0]
        self.owned_since = self.t
        if before != pl.key[0] and not hands:
            # The ball changed hands in open play.
            won, lost = pl.key[0], 1 - pl.key[0]
            self.transition_until = self.t + self.engine["shapes"]["transition_s"]
            cp = self.teams[lost].profile.counterpress
            if self.rng.random() < cp.probability * self.effect(lost, "press", 1.0):
                self.counterpress[lost] = self.t + cp.duration_s
            self.counterpress[won] = -1.0
            reg = self.teams[won].profile.on_regain
            chance = (
                reg.channel_probability
                if reg
                else self.effect(won, "counter_probability", 0.0)
            )
            self.regain[won] = (self.t, self.rng.random() < chance)
            self.regain[lost] = None

    # ---- fouls ----------------------------------------------------------------------

    def tackle(self, pl):
        """A tackle from behind is often a foul: a free kick where it happened."""
        o = self.owner
        if o is not None:
            ux, uy = unit(o.vx, o.vy) if o.speed > 0.5 else (0.0, 0.0)
            behind = ux * (pl.x - o.x) + uy * (pl.y - o.y) < -0.5
            if behind and self.rng.random() < self.cfg["match"]["foul_from_behind"]:
                return self.foul(pl, o)
        super().tackle(pl)

    def foul(self, offender, victim):
        self.flush_carry()
        at = self.ball.pos
        self.emit(offender, "foul", "fail", at, at, None)
        self.counts["fouls"] += 1
        self.owner, self.in_hands = None, False
        self.dead = True
        self.set_restart("free_kick", victim.key[0], self.on_pitch(at))

    # ---- out of play and restarts ---------------------------------------------------

    def goal(self, gx, yc):
        p = self.pending
        side = p["player"].key[0] if p is not None else None
        before = self.counts["goals"]
        super().goal(gx, yc)
        if self.counts["goals"] > before:
            self.score[side] += 1
            self.set_restart(
                "kickoff", 1 - side, CENTRE, delay=self.cfg["match"]["celebration_s"]
            )

    def out(self, why):
        if self.pending is not None:
            self.resolve_pending(None)
        self.flush_carry()
        b = self.ball
        last = self.last_touch.key[0] if self.last_touch is not None else self.poss
        self.owner, self.in_hands = None, False
        self.dead = True
        if b.y < 0.0 or b.y > WIDTH:
            spot = (min(max(b.x, 1.0), LENGTH - 1.0), 0.0 if b.y < 0.0 else WIDTH)
            return self.set_restart("throw_in", 1 - last, spot)
        gx = LENGTH if b.x > LENGTH / 2 else 0.0
        defending = 1 if gx == LENGTH else 0  # the side whose goal line it is
        if last == defending:
            corner = (gx, 0.5 if b.y < GOAL_Y else WIDTH - 0.5)
            return self.set_restart("corner", 1 - defending, corner)
        six = (gx - 5.5 if gx == LENGTH else 5.5, GOAL_Y)
        return self.set_restart("goal_kick", defending, six)

    def set_restart(self, kind, side, spot, delay=None):
        c = self.cfg["match"]
        team = self.teams[side]
        if kind == "goal_kick":
            taker = self.keepers[side]
        elif kind == "kickoff":
            taker = self.by_key[(side, team.front_player)]
        else:
            taker = min(
                (p for p in self.players if p.key[0] == side and not p.keeper),
                key=lambda p: (math.dist(p.pos, spot), p.key),
            )
        self.restart = {
            "kind": kind,
            "side": side,
            "spot": spot,
            "taker": taker,
            "ready_at": self.t + (c["restart_delay_s"] if delay is None else delay),
            "deadline": self.t
            + (
                c["kickoff_wait_s"] + (delay or 0.0)
                if kind == "kickoff"
                else c["restart_max_s"]
            ),
            "spots": self.kickoff_spots(side) if kind == "kickoff" else None,
        }
        self.poss = side
        self.urgent()

    def restart_role(self, pl):
        """While play is stopped: the taker goes to the ball; the rest take up
        places (their shape around the ball, 9.15 m off it if they defend;
        their kick-off places for a kick-off)."""
        r = self.restart
        m = self.mind[pl.key]
        if (
            m.intent == "celebrate"
            and self.t < r["ready_at"] - self.cfg["match"]["walk_back_s"]
        ):
            return
        if pl is r["taker"]:
            m.intent, m.spot = "walk", r["spot"]
            m.cap = 5.5 if math.dist(pl.pos, r["spot"]) > 3.0 else 2.0
            return
        if r["spots"] is not None:
            spot = r["spots"][pl.key]
            m.intent, m.spot, m.cap = (
                "walk",
                spot,
                4.0 if math.dist(pl.pos, spot) > 8.0 else 1.9,
            )
            return
        if pl.keeper:
            m.intent = "keep"
            return
        spot = anchors(
            self.teams[pl.key[0]],
            r["spot"],
            "in_possession" if pl.key[0] == r["side"] else "out_of_possession",
            self.teams[pl.key[0]].profile.block_height,
            self.engine,
        )[pl.key[1]]
        if pl.key[0] != r["side"] and math.dist(spot, r["spot"]) < 9.5:
            ux, uy = unit(spot[0] - r["spot"][0], spot[1] - r["spot"][1])
            if ux == uy == 0.0:
                ux = -1.0 if pl.key[0] == 0 else 1.0
            spot = (r["spot"][0] + ux * 9.5, r["spot"][1] + uy * 9.5)
        spot = self.on_pitch(spot)
        m.intent, m.spot, m.cap = "walk", spot, self.pace(pl, spot)

    def step(self):
        if self.t >= self.next_mode_check:
            self.next_mode_check = self.t + 10.0
            mine = None
            for side in (0, 1):
                if (
                    self.own_x(side, self.ball.pos)
                    <= self.engine["game_state"]["defensive_third_x"]
                ):
                    mine = side
            if mine is not None:
                self.territory.append((self.t, mine))
            self.update_modes()
        if self.restart is not None:
            return self.restart_step()
        super().step()

    def restart_step(self):
        """One step of a stoppage: the ball is brought to its spot, everyone
        goes to his place, and when the taker is on the ball it is taken."""
        c = self.cfg
        r = self.restart
        for pl in self.players:
            m = self.mind[pl.key]
            if self.t >= m.next_think - 1e-9:
                m.next_think = self.t + c["game"]["think_s"]
                self.restart_role(pl)
        self.t = round(self.t + c["dt"], 6)
        self.prev_ball = self.ball.pos
        for pl in self.players:
            m = self.mind[pl.key]
            if m.intent == "keep":
                tgt, cap = self.keeper_spot(pl), 4.0
            elif m.intent == "celebrate":
                tgt, cap = m.spot, c["player"]["top_speed"] * 0.85
            else:
                tgt, cap = m.spot, m.cap
            pl.move(tgt, cap, c["dt"], c["player"])
            pl.face(self.ball.pos, c["dt"], c["player"])
        self.separate()
        referee.step(self.ref, self.ball.pos, c["dt"], c["player"], c["referee"])
        if (
            self.net_x is not None
            and self.t < r["ready_at"] - c["match"]["walk_back_s"]
        ):
            self.ball.step(c["dt"], c["ball"], c["substeps"])  # still in the net
            self.keep_in_net()
        else:
            self.net_x = None
            self.roll_ball(r["spot"])
        self.record()
        self.post()
        taker = r["taker"]
        there = math.dist(taker.pos, r["spot"]) <= 1.0 and self.ball_at(r["spot"])
        if r["spots"] is not None and self.t < r["deadline"]:
            # A kick-off: everyone in his own half, in his place, first.
            there = there and all(
                math.dist(p.pos, r["spots"][p.key]) <= 2.0 for p in self.players
            )
        if self.t >= r["ready_at"] and (
            there or self.t >= r["deadline"] and self.ball_at(r["spot"])
        ):
            if not there:  # he is late: he still has to reach it (no jumps)
                return
            self.take_restart(r)

    def roll_ball(self, spot):
        """A dead ball goes back to its spot: rolled by a ball boy (14 m/s)."""
        b = self.ball
        b.vx = b.vy = b.vh = 0.0
        b.h = max(0.0, b.h - 6.0 * self.cfg["dt"])
        d = math.dist(b.pos, spot)
        step = self.engine["motion"]["ball_return_ms"] * self.cfg["dt"]
        if d <= step:
            b.x, b.y = spot
        else:
            b.x += (spot[0] - b.x) / d * step
            b.y += (spot[1] - b.y) / d * step

    def ball_at(self, spot):
        return math.dist(self.ball.pos, spot) < 0.05 and self.ball.h == 0.0

    def take_restart(self, r):
        """Play on: the taker takes it."""
        kind, pl = r["kind"], r["taker"]
        self.restart = None
        self.dead = False
        self.net_x = None
        self.owner, self.in_hands = pl, False
        self.last_touch = pl
        self.poss = pl.key[0]
        for q in self.players:
            if self.mind[q.key].intent in ("walk", "celebrate"):
                self.mind[q.key].intent = "support"
        self.urgent()
        mate, _ = self.best_pass(pl)
        if kind == "corner":
            self.counts["corners"] += 1
            return self.cross(pl)
        if kind == "goal_kick":
            self.counts["goal_kicks"] += 1
        if kind == "throw_in":
            self.counts["throw_ins"] += 1
        if mate is None:
            mate = min(
                (q for q in self.mates(pl) if not q.keeper),
                key=lambda q: (math.dist(q.pos, pl.pos), q.key),
            )
        self.pass_ball(pl, mate, throw=kind == "throw_in")
        names = {
            "throw_in": "throw_in",
            "goal_kick": "goalkick",
            "free_kick": "freekick_short",
            "kickoff": "pass",
        }
        self.pending["kind"] = names[kind]
        if kind == "throw_in":
            self.pending["body"] = "other"

    def cross(self, pl):
        """A corner: the ball is crossed into the box, towards the
        penalty-spot area, for whoever gets there."""
        side = pl.key[0]
        gx = GOAL_X[side]
        tx = gx - 9.0 if gx == LENGTH else 9.0
        ty = GOAL_Y + self.rng.uniform(-6.0, 6.0)
        d = math.dist(self.ball.pos, (tx, ty))
        speed = 17.0
        T = d / speed
        lift = 0.5 * self.cfg["ball"]["gravity"] * T
        start = self.ball.pos
        target_mate = min(
            (q for q in self.mates(pl) if not q.keeper),
            key=lambda q: (math.dist(q.pos, (tx, ty)), q.key),
        )
        self.pending = self.strike_record(pl, "corner_crossed", start, (tx, ty), speed)
        self.pending["to"] = target_mate.key
        self.release(pl)
        self.ball.kick(
            speed,
            math.degrees(math.atan2(ty - start[1], tx - start[0])),
            lift=min(lift, 12.0),
        )
        self.kicked_at[pl.key] = self.t
        self.urgent()

    # ---- the target for "walk" (stoppages) and run-on play ---------------------------

    def target(self, pl):
        m = self.mind[pl.key]
        if m.intent == "walk":
            return m.spot, m.cap, self.cfg["player"], None
        return super().target(pl)


def simulate_physics_match(
    home, away, seed, weather="dry", kickoff=DEFAULT_KICKOFF, half_s=HALF_S
):
    """The whole match on the physics-first engine (ENGINE=physics)."""
    return FullMatch(
        home, away, seed, weather=weather, kickoff=kickoff, half_s=half_s
    ).run()
