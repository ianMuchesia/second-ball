# Pass difficulty (0-100)

How hard a pass was to play. Weights are Ian's (2026-10-22): pressure and
lines broken come first and "go hand in hand"; where on the pitch matters
(near the opponent's box everything is crowded); distance matters less,
because a long ball in space mostly depends on the passer's quality.

```
difficulty = 25 x passer_pressure
           + 25 x lines_broken_norm
           + 15 x zone
           + 15 x receiver_pressure
           + 15 x distance_norm
           +  5 x forwardness
```

Every part is 0-1, so the score is 0-100.

| Part | Meaning | How |
|---|---|---|
| passer_pressure | how hard the passer is pressed | `pressure` (docs/metrics/pressure_risk_options.md) |
| lines_broken_norm | defending lines the pass goes through | lines crossed / 3 (lines from the freeze frame) |
| zone | where the pass starts | own third 0, middle third 0.3, final third 0.7, opponent's box 1.0 |
| receiver_pressure | how crowded the target spot is | pressure at the end point (opponents near it; goal-side counts double) |
| distance_norm | length | min(1, length / 50 m) |
| forwardness | how much of it goes forward | forward metres / length |

All weights and cut-offs: `core/metrics/config.yaml` -> `pass_difficulty`
(TUNABLE, owner: Ian). The receiver's facing is not known from the feed, so
"in front" is not used for receiver pressure.
