"""Team shapes and freeze frames.

Each team has a shape table per (phase, ball_side) (see shapes.py). Anchors
are turned into metres around the ball, and each freeze frame moves players
part of the way from where they were towards their current anchor, plus
noise. All positions here are absolute (home attacks +x).
"""

import math
from dataclasses import dataclass, field

from engine.core.pitch import GOAL_Y, LENGTH, bearing, clamp, dist, on_pitch, own
from engine.core.shapes import (
    SIDE_Y,
    ball_side,
    generic_roles,
    override_table,
    table_for,
)
from engine.league import parse_shape


@dataclass
class TeamState:
    side: int  # 0 home, 1 away
    profile: object  # ClubProfile
    table: dict = field(
        default_factory=dict
    )  # (phase, ball_side) -> {role: (depth, y)}
    roles: dict = field(
        default_factory=dict
    )  # player index -> role, outfield on the pitch
    keeper: int = 0
    goals: int = 0
    reds: int = 0
    # Engine-internal match mode: normal | manage | protect | chase. Never emitted.
    mode: str = "normal"
    mode_since: float = 0.0
    calm_since: float | None = None
    overrides: dict = field(default_factory=dict)  # "protect" / "chase" -> table
    red_table: dict | None = None

    @classmethod
    def start(cls, side, profile):
        if profile.shapes:
            roles = {i: p.role for i, p in enumerate(profile.players) if i > 0}
        else:
            roles = dict(zip(range(1, 11), generic_roles(), strict=True))
        present = set(roles.values())
        overrides = {
            kind: override_table(profile, ov, present)
            for kind, ov in (
                ("protect", profile.shape_when_protecting_lead),
                ("chase", profile.shape_when_chasing),
            )
            if ov is not None
        }
        return cls(
            side=side,
            profile=profile,
            table=table_for(profile),
            roles=roles,
            overrides=overrides,
        )

    def shape(self, phase, side):
        """Anchors in use now: red-card shape, then mode shape, then the base table."""
        if self.red_table is not None:
            return self.red_table[(phase, side)]
        if (
            self.mode == "protect"
            and "protect" in self.overrides
            and phase != "in_possession"
        ):
            return self.overrides["protect"][(phase, side)]
        if (
            self.mode == "chase"
            and "chase" in self.overrides
            and phase == "in_possession"
        ):
            return self.overrides["chase"][(phase, side)]
        return self.table[(phase, side)]

    @property
    def on_pitch(self):
        return [self.keeper, *self.roles]

    def fullbacks(self):
        """{"left": player, "right": player} still on the pitch (team's own frame)."""
        if self.profile.shapes:
            by_role = {r: p for p, r in self.roles.items()}
            found = {"left": by_role.get("LB"), "right": by_role.get("RB")}
        else:
            back = parse_shape(self.profile.formation)[0]
            if back < 4:
                return {}
            by_role = {r: p for p, r in self.roles.items()}
            # generic lines are spread from low y (right) to high y (left)
            found = {"right": by_role.get("P1"), "left": by_role.get(f"P{back}")}
        return {side: p for side, p in found.items() if p is not None}

    @property
    def front_player(self):
        """Most advanced outfield player (kick-offs)."""
        depth = self.table[("out_of_possession", "centre")]
        return max(self.roles, key=lambda p: (depth[self.roles[p]][0], -p))

    def send_off(self, player):
        """Remove a player. The most advanced player drops into the gap they leave."""
        vacated = self.roles.pop(player)
        self.reds += 1
        depth = self.table[("out_of_possession", "centre")]
        donor = max(
            self.roles, key=lambda p: (depth[self.roles[p]][0], -p), default=None
        )
        if donor is not None and depth[self.roles[donor]][0] > depth[vacated][0]:
            self.roles[donor] = vacated
        ov = self.profile.shape_after_red_card
        if ov is not None and self.reds == 1:
            present = set(self.roles.values())
            order = [r for r in (ov.order or generic_roles()) if r in present]
            if len(order) == len(present) == 9:
                self.red_table = override_table(self.profile, ov, present)


def lines(phase, bx, block_height, push=0.0):
    """(keeper_x, back_x, front_x) in the team's frame for ball at bx.

    `push` moves the back line up with the ball (chasing: full-backs higher).
    """
    if phase == "in_possession":
        back = clamp(bx - 28 + push, 10, 62 + push)
        return clamp(bx - 45, 5, 22), back, max(back + 10, clamp(bx + 14, 28, 99))
    back = clamp(block_height + 0.3 * (bx - 52.5), 8, 60)
    back = min(back, max(6.0, bx - 3))
    keeper_x = clamp(2 + 0.12 * bx, 2, 14)
    if phase == "out_of_possession":
        return keeper_x, back, min(back + 24, 100)
    # transition: between the two
    ib, ifr = clamp(bx - 28, 10, 62), clamp(bx + 14, 28, 99)
    return keeper_x, (back + ib) / 2, (min(back + 24, 100) + ifr) / 2


def anchors(team, ball, phase, block_height, cfg, push=0.0):
    """{player: (x, y)} absolute anchors for one team in one phase."""
    bx, by = own(team.side, *ball)
    side = ball_side(by, cfg)
    shape = team.shape(phase, side)
    keeper_x, back, front = lines(phase, bx, block_height, push)
    pull = cfg["shapes"]["ball_pull"] * (by - SIDE_Y[side])

    # Attacking runs: deep in the opponent's half, every line but the back one
    # moves part of the way up to the front line (midfielders join the attack).
    runs = 0.0
    if phase == "in_possession":
        r = cfg["shapes"]["attack_runs"]
        ramp = clamp((bx - r["from_x"]) / (r["full_x"] - r["from_x"]), 0.0, 1.0)
        # Shapes that already attack with many forwards push fewer players up.
        forwards = sum(
            1 for d, _ in team.table[("in_possession", "centre")].values() if d >= 0.85
        )
        need = clamp(
            (r["forwards_wanted"] - forwards) / (r["forwards_wanted"] - 2), 0.0, 1.0
        )
        runs = r["share"] * ramp * need

    spots = {team.keeper: (keeper_x, GOAL_Y + 0.15 * (by - GOAL_Y))}
    for player, role in team.roles.items():
        depth, y = shape[role]
        if depth > 0:
            depth += (1.0 - depth) * runs
        spots[player] = (back + depth * (front - back), y + pull)
    return {pl: on_pitch(*own(team.side, x, y)) for pl, (x, y) in spots.items()}


@dataclass
class Frame:
    """One moment: absolute positions and facing for everyone on the pitch."""

    positions: dict  # (side, player) -> (x, y)
    facing: dict  # (side, player) -> degrees, absolute frame
    shape_positions: dict = field(default_factory=dict)  # before carrier/presser moved

    def nearest(self, side, point, exclude=(), outfield_only=False, keeper=None):
        best, best_d = None, math.inf
        for (s, pl), pos in self.positions.items():
            if s != side or (s, pl) in exclude or (outfield_only and pl == keeper):
                continue
            d = dist(pos, point)
            if d < best_d:
                best, best_d = pl, d
        return best, best_d


def build_frame(
    rng,
    cfg,
    teams,
    attack,
    carrier,
    ball,
    presser_dist,
    facing_back,
    blocks,
    phases,
    previous=None,
    pushes=None,
):
    """Freeze frame with the carrier on the ball and the closest defender at presser_dist.

    Players move `shapes.follow` of the way from `previous` towards their anchor.
    """
    noise = cfg["frame_noise_m"]
    follow = cfg["shapes"]["follow"]
    positions = {}
    for team in teams:
        push = (pushes or {}).get(team.side, 0.0)
        spots = anchors(team, ball, phases[team.side], blocks[team.side], cfg, push)
        for pl, (x, y) in spots.items():
            tx, ty = x + rng.gauss(0, noise), y + rng.gauss(0, noise)
            prev = previous.get((team.side, pl)) if previous else None
            if prev is not None:
                tx, ty = (
                    prev[0] + follow * (tx - prev[0]),
                    prev[1] + follow * (ty - prev[1]),
                )
            positions[(team.side, pl)] = on_pitch(tx, ty)
    shape_positions = dict(positions)
    positions[(attack, carrier)] = ball

    defence = 1 - attack
    keeper = teams[defence].keeper
    presser, _ = Frame(positions, {}).nearest(
        defence, ball, outfield_only=True, keeper=keeper
    )
    if presser is not None:
        # Goal-side = towards the defending team's goal = +x in the carrier's frame.
        if rng.random() < cfg["pressing"]["goal_side_share"]:
            angle = math.radians(rng.uniform(-50, 50))
        else:
            angle = math.radians(rng.uniform(0, 360))
        cx, cy = own(attack, *ball)
        px, py = (
            cx + presser_dist * math.cos(angle),
            cy + presser_dist * math.sin(angle),
        )
        positions[(defence, presser)] = on_pitch(*own(attack, px, py))

    facing = {}
    for key, pos in positions.items():
        if key == (attack, carrier):
            own_deg = rng.gauss(180, 25) if facing_back else rng.gauss(0, 50)
            facing[key] = (own_deg if attack == 0 else own_deg + 180) % 360
        else:
            facing[key] = (bearing(pos, ball) + rng.gauss(0, 20)) % 360
    return Frame(positions, facing, shape_positions)


def keeper_spot(side):
    return own(side, 5.5, GOAL_Y)


def centre_spot():
    return (LENGTH / 2, GOAL_Y)
