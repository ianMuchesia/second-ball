"""Team shapes and freeze frames.

Players stand on formation anchors (lines back to front, spread across the
width), shifted towards the ball and by phase (with or without the ball), plus
noise. All positions here are absolute (home attacks +x).
"""

import math
from dataclasses import dataclass, field

from engine.core.pitch import GOAL_Y, LENGTH, WIDTH, bearing, clamp, dist, on_pitch, own
from engine.league import parse_shape


@dataclass
class TeamState:
    side: int  # 0 home, 1 away
    profile: object  # ClubProfile
    on_pitch: list = field(default_factory=list)  # player indices, goalkeeper first
    shape_out: list = field(default_factory=list)
    shape_in: list = field(default_factory=list)
    goals: int = 0
    reds: int = 0

    @classmethod
    def start(cls, side, profile):
        return cls(
            side=side,
            profile=profile,
            on_pitch=list(range(11)),
            shape_out=parse_shape(profile.formation),
            shape_in=parse_shape(profile.in_possession_shape),
        )

    @property
    def keeper(self):
        return self.on_pitch[0]

    def send_off(self, player):
        """Remove a player; the shape loses one from its most advanced line."""
        self.on_pitch.remove(player)
        self.reds += 1
        for shape in (self.shape_out, self.shape_in):
            shape[-1] -= 1
            if shape[-1] == 0:
                shape.pop()


def _line_ys(n, span, centre):
    if n == 1:
        return [centre]
    return [centre - span / 2 + span * i / (n - 1) for i in range(n)]


def anchors(team, ball, in_possession, block_height):
    """{player: (x, y)} absolute anchors for one team."""
    p = team.profile
    bx, by = own(team.side, *ball)
    shape = team.shape_in if in_possession else team.shape_out

    if in_possession:
        keeper_x = clamp(bx - 45, 5, 22)
        back = clamp(bx - 28, 10, 62)
        front = clamp(bx + 14, 28, 99)
        span = 26 + 40 * p.width
        pull = 0.3
    else:
        keeper_x = clamp(2 + 0.12 * bx, 2, 14)
        back = clamp(block_height + 0.3 * (bx - 52.5), 8, 60)
        back = min(back, max(6.0, bx - 3))
        front = min(back + 24, 100)
        span = 22 + 18 * p.width
        pull = 0.45

    centre = GOAL_Y + pull * (by - GOAL_Y)
    spots = {team.keeper: (keeper_x, GOAL_Y + 0.15 * (by - GOAL_Y))}
    outfield = iter(team.on_pitch[1:])
    for i, n in enumerate(shape):
        x = back if len(shape) == 1 else back + (front - back) * i / (len(shape) - 1)
        for y in _line_ys(n, min(span, WIDTH - 4), centre):
            spots[next(outfield)] = (x, y)

    return {pl: on_pitch(*own(team.side, x, y)) for pl, (x, y) in spots.items()}


@dataclass
class Frame:
    """One moment: absolute positions and facing for everyone on the pitch."""

    positions: dict  # (side, player) -> (x, y)
    facing: dict  # (side, player) -> degrees, absolute frame

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
    rng, cfg, teams, attack, carrier, ball, presser_dist, facing_back, blocks
):
    """Freeze frame with the carrier on the ball and the closest defender at presser_dist."""
    noise = cfg["frame_noise_m"]
    positions = {}
    for team in teams:
        spots = anchors(team, ball, team.side == attack, blocks[team.side])
        for pl, (x, y) in spots.items():
            positions[(team.side, pl)] = on_pitch(
                x + rng.gauss(0, noise), y + rng.gauss(0, noise)
            )
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
    return Frame(positions, facing)


def keeper_spot(side):
    return own(side, 5.5, GOAL_Y)


def centre_spot():
    return (LENGTH / 2, GOAL_Y)
