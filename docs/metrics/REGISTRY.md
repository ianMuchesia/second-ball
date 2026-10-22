# Metric registry

Generated from `core/metrics/registry.py` by `uv run python -m scripts.export_metrics_doc`. Do not edit by hand.

Every number carries `evidence_event_ids`; rates also carry `numerator`
and `denominator`. Thresholds: `core/metrics/config.yaml` (TUNABLE, owner: Ian).
Frame: SPADL (the acting team attacks towards x = 105).

## Per event

| Metric | Analyst | Casual fan | Unit | Windows | Definition | Formula |
|---|---|---|---|---|---|---|
| `pressure` | Pressure on the ball | How hard he is pressed | index 0-1 | latest event | Pressure on the player on the ball (0-1): nearby opponents, doubled in front or goal-side. | `core.metrics.positional.pressure` |
| `risk` | Risk of losing it here | How dangerous a mistake here would be | index 0-1 | latest event | How costly losing the ball here would be (0-1): high near his own goal, about 0 when his team has the upper hand in the final third. | `core.metrics.positional.risk` |
| `options` | Safe passing options | Free teammates to pass to | count | latest event | Teammates with a clear passing lane (no opponent within 2 m), not clearly offside. | `core.metrics.positional.options` |
| `facing_own_goal` | Facing own goal | Facing his own goal | flag | latest event | 1 if the player on the ball faces his own goal (120-240 degrees). | `core.metrics.positional.facing_own_goal` |
| `bad_situation` | Danger on the ball | In trouble on the ball | flag | latest event | 1 if risk >= 0.6, facing own goal, and pressure >= 0.5 or no safe option. | `core.metrics.positional.bad_situation` |
| `lines_broken` | Lines broken | Lines the pass cut through | count | latest event | Defending lines a pass crosses going forward (up to 3 lines from the freeze frame). | `core.metrics.positional.lines_broken` |
| `line_gap` | Back-midfield line gap | Space between their defence and midfield | metres | latest event | Metres between the defending team's back line and midfield line. | `core.metrics.positional.line_gap` |
| `overload` | Overload | Outnumbering them near the ball | danger 0-1 | latest event | Danger-weighted overload around the ball: attackers minus defenders >= 1 in a box 20 m ahead and 10 m behind in the ball's lane (numerator attackers, denominator defenders). | `core.metrics.positional.overload` |
| `xt_added` | xT added | Danger added by this move | xT | latest event | Expected threat added by this pass or carry. | `core.metrics.play.xt_added` |
| `pass_difficulty` | Pass difficulty | How hard that pass was | score 0-100 | latest event | Pass difficulty 0-100 (docs/metrics/pass_difficulty.md). | `core.metrics.play.pass_difficulty` |
| `ball_speed` | Ball speed | Ball speed | km/h | latest event | Ball speed of a pass or shot. | `core.metrics.play.ball_speed` |
| `name_tag` | Name-tag trigger | Show who it was | flag | latest event | 1 when a shot is at least 100 km/h or a pass at least 40 m: show the player's name. | `core.metrics.play.name_tag` |

## Per team

| Metric | Analyst | Casual fan | Unit | Windows | Definition | Formula |
|---|---|---|---|---|---|---|
| `possession_time` | Possession (time) | Time on the ball | share 0-1 | whole match, last 5 min, last 10 min, last 15 min | Share of in-play time the team had the ball. | `core.metrics.basic.possession_time` |
| `possession_passes` | Possession (passes) | Share of the passing | share 0-1 | whole match, last 5 min, last 10 min, last 15 min | Share of all passes (throw-ins excluded) made by the team. | `core.metrics.basic.possession_passes` |
| `passes_per_possession` | Passes per possession | How long they keep it | passes | whole match, last 5 min, last 10 min, last 15 min | Team passes divided by the possessions the team owned. | `core.metrics.basic.passes_per_possession` |
| `shots` | Shots | Shots | count | whole match, last 5 min, last 10 min, last 15 min | Shots taken, including free kicks and penalties. | `core.metrics.basic.shots` |
| `xg` | xG | Quality of chances | goals | whole match, last 5 min, last 10 min, last 15 min | Sum of the feed's xG over the team's shots. | `core.metrics.basic.xg` |
| `ppda` | PPDA | How hard they're pressing | passes per action | whole match, last 5 min, last 10 min, last 15 min | Opponent open-play passes in its own 60% of the pitch divided by the team's tackles, interceptions and fouls there. Lower = more pressing. | `core.metrics.basic.ppda` |
| `field_tilt` | Field tilt | Who is camped in whose half | share 0-1 | whole match, last 5 min, last 10 min, last 15 min | Share of all final-third touches (each team in its own attacking third) made by the team. | `core.metrics.basic.field_tilt` |
| `xt_share` | xT share | Who is creating danger | share 0-1 | whole match, last 10 min | Share of all expected threat (xT) added by successful passes and carries that the team added. | `core.metrics.chaos.xt_share` |
| `control_index` | Control index | Who is in control | index 0-1 | last 10 min | Mean of possession (time), field tilt and xT share over the last 10 minutes: how much the team is running the match. | `core.metrics.chaos.control_index` |
| `final_third_pressures` | Final-third pressures / min | Pressing high up the pitch | per minute | whole match, last 5 min, last 10 min, last 15 min | Opponent touches in their own third made under pressure, per minute. | `core.metrics.play.final_third_pressures` |
| `high_turnovers` | High turnovers | Balls won high up | count | whole match, last 5 min, last 10 min, last 15 min | Balls won in open play within 40 m of the opponent's goal. | `core.metrics.play.high_turnovers` |
| `counterpress_regains` | Counter-press regains (5 s) | Winning it straight back | share 0-1 | whole match, last 5 min, last 10 min, last 15 min | Share of balls lost in open play won back within 5 seconds. | `core.metrics.play.counterpress_regains` |
| `actions_per_minute` | Actions / min in possession | Tempo on the ball | per minute | whole match, last 5 min, last 10 min, last 15 min | On-ball actions per minute of the team's own possession. | `core.metrics.play.actions_per_minute` |
| `xt_added_total` | xT added | Danger created by passing and carrying | xT | whole match, last 5 min, last 10 min, last 15 min | Net expected threat added by the team's successful passes and carries (numerator xT, denominator moves). | `core.metrics.play.team_xt_added` |
| `big_chances` | Big chances | Big chances | count | whole match, last 5 min, last 10 min, last 15 min | Shots with xG of at least 0.3. | `core.metrics.play.big_chances` |
| `pass_distance` | Average pass length | How far they pass | metres | whole match, last 5 min, last 10 min, last 15 min | Average pass length. | `core.metrics.play.pass_distance` |
| `pass_accuracy` | Pass accuracy | Passes that found a teammate | share 0-1 | whole match, last 5 min, last 10 min, last 15 min | Completed passes divided by passes. | `core.metrics.play.pass_accuracy` |
| `lines_broken_per_pass` | Lines broken per pass | Passing through the lines | lines per pass | whole match, last 5 min, last 10 min, last 15 min | Defending lines crossed per completed pass. | `core.metrics.play.lines_broken_per_pass` |
| `pass_difficulty_mean` | Average pass difficulty | How hard their passes are | score 0-100 | whole match, last 5 min, last 10 min, last 15 min | Average difficulty (0-100) of the team's passes. | `core.metrics.play.mean_pass_difficulty` |
| `fastest_shot` | Fastest shot | Hardest shot | km/h | whole match, last 5 min, last 10 min, last 15 min | Fastest shot. | `core.metrics.play.fastest_shot` |
| `name_tags` | Name-tag moments | Standout strikes and passes | count | whole match, last 5 min, last 10 min, last 15 min | Fast shots (100+ km/h) and long passes (40+ m). | `core.metrics.play.name_tags` |
| `bad_situations` | Dangerous moments on the ball | Times caught in trouble | count | whole match, last 5 min, last 10 min, last 15 min | Times the team's player on the ball met the bad_situation rule (Ian's spec). | `core.metrics.positional.bad_situations` |
| `pressure_on_ball` | Average pressure on the ball | How much they are being pressed | index 0-1 | whole match, last 5 min, last 10 min, last 15 min | Average pressure on the team's player on the ball (0-1). | `core.metrics.positional.mean_pressure_on_ball` |
| `defensive_line_gap` | Back-midfield gap (defending) | Space between their defence and midfield | metres | whole match, last 5 min, last 10 min, last 15 min | Average metres between the team's back line and midfield line while defending. | `core.metrics.positional.team_line_gap` |
| `overloads` | Overloads | Outnumbering them | danger | whole match, last 5 min, last 10 min, last 15 min | Danger-weighted overloads the team created on the ball. | `core.metrics.positional.overloads` |
| `upper_hand` | Upper hand | Who is on top | level 0-2 | last 5 min, last 10 min, last 15 min, last 20 min, last 30 min | 0 none, 1 upper hand (10+ final-third touches, 2+ shots, constant pressure), 2 strong (also xG 0.5+). | `core.metrics.positional.upper_hand` |
| `upper_hand_checkpoint` | Upper hand (10-min checkpoint) | Who was on top in that spell | level 0-2 | whole match | Upper hand in the last completed fixed 10-minute block (0-10, 10-20, ...). | `core.metrics.positional.upper_hand_checkpoint` |

## Per match

| Metric | Analyst | Casual fan | Unit | Windows | Definition | Formula |
|---|---|---|---|---|---|---|
| `possession_changes_per_min` | Possession changes / min | (analyst only) | per minute | whole match, last 5 min, last 10 min, last 15 min | Times the ball changes team, per minute. | `core.metrics.basic.possession_changes_per_min` |
| `two_way_threat` | Two-way threat (min xG) | Both teams creating chances | goals | last 10 min | The smaller of the two teams' xG in the window. | `core.metrics.chaos.two_way_threat` |
| `threat_switches` | Threat switches | How often the danger switches ends | count | last 10 min | Times the team creating threat (a shot, or the ball reaching high xT) changes sides. | `core.metrics.chaos.threat_switches` |
| `transition_speed` | Transition speed (regain to shot/box) | How fast they attack after winning it | seconds | last 10 min | Median seconds from winning the ball in open play to a shot or getting it into the box. | `core.metrics.chaos.transition_speed` |
| `openness_index` | Openness index | How end-to-end it is | index 0-1 | last 10 min | Mean of two-way threat, threat switches and transition speed, each scaled 0-1: how end-to-end the match is. | `core.metrics.chaos.openness_index` |
| `openness_vs_expected` | Openness vs expected | More or less open than usual for this fixture | index difference | last 10 min | Openness minus the usual openness of fixtures with the same pre-match strength gap (0 = as usual). | `core.metrics.chaos.openness_vs_expected` |
| `short_possessions` | Short possessions (<3 passes) | (analyst only) | share 0-1 | whole match, last 10 min | Share of possessions with fewer than 3 passes. | `core.metrics.chaos.short_possessions` |
| `loose_balls` | Loose balls / min | (analyst only) | per minute | whole match, last 10 min | Times the ball got away from a player (bad touches), per minute. | `core.metrics.chaos.loose_balls` |
| `seconds_between_actions` | Seconds between actions | Pace of the game | seconds | whole match, last 5 min, last 10 min, last 15 min | Median in-play seconds between consecutive events. | `core.metrics.play.seconds_between_actions` |
| `momentum` | Momentum (xT, home - away) | Who is on top right now | xT | whole match | Exponentially weighted xT added, home minus away (half-life 3 minutes); above 0 the home team is on top. | `core.metrics.play.momentum` |
