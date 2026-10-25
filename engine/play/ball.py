"""The ball as a physical object: position, velocity, height.

On the ground it slows by rolling resistance plus air drag; in the air it
falls under gravity with quadratic drag and bounces. Nothing tells it where
to stop: it stops where the physics says. All positions are absolute metres
(105 x 68, home attacks +x).
"""

import math
from dataclasses import dataclass


@dataclass
class Ball:
    x: float
    y: float
    h: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vh: float = 0.0

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def ground_speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def moving(self):
        return self.h > 0.0 or self.vh != 0.0 or self.ground_speed > 0.0

    def copy(self):
        return Ball(self.x, self.y, self.h, self.vx, self.vy, self.vh)

    def kick(self, speed, angle_deg, lift=0.0):
        """Strike it: `speed` m/s along the ground at `angle_deg`, `lift` m/s up."""
        a = math.radians(angle_deg)
        self.vx, self.vy, self.vh = speed * math.cos(a), speed * math.sin(a), lift

    def step(self, dt, p, substeps=5):
        """Advance `dt` seconds under the parameters `p` (play.yaml ball)."""
        h = dt / substeps
        for _ in range(substeps):
            self._sub(h, p)

    def _sub(self, dt, p):
        airborne = self.h > 0.0 or self.vh > 0.0
        speed = math.sqrt(self.vx**2 + self.vy**2 + (self.vh**2 if airborne else 0))
        drag = p["drag_k"] * speed  # a = -k |v| v
        self.vx -= drag * self.vx * dt
        self.vy -= drag * self.vy * dt
        if airborne:
            self.vh -= (p["gravity"] + drag * self.vh) * dt
            self.h += self.vh * dt
            if self.h <= 0.0:
                self.h = 0.0
                bounce = -self.vh * p["restitution"]
                self.vh = bounce if bounce > 0.5 else 0.0
                self.vx *= p["bounce_keep"]
                self.vy *= p["bounce_keep"]
        else:
            g = math.hypot(self.vx, self.vy)
            if g > 0.0:
                slow = min(g, p["roll_decel"] * dt)
                self.vx -= self.vx / g * slow
                self.vy -= self.vy / g * slow
        self.x += self.vx * dt
        self.y += self.vy * dt
        if not airborne and math.hypot(self.vx, self.vy) < p["rest_speed"]:
            self.vx = self.vy = 0.0


def predict(ball, p, horizon, step, substeps=5):
    """Where the ball will be: [(seconds ahead, x, y, h)], every `step`,
    until it stops or `horizon` is reached (it never mutates `ball`)."""
    b = ball.copy()
    out = [(0.0, b.x, b.y, b.h)]
    t = 0.0
    while t < horizon - 1e-9:
        b.step(step, p, substeps)
        t += step
        out.append((round(t, 6), b.x, b.y, b.h))
        if not b.moving:
            break
    return out
