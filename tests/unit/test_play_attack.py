"""Stage 2 of the physics-first engine: the attack (engine/play/game.py).

A feeder plays the striker in against a centre-back, an outlet and a keeper;
after that nothing is scripted. These tests hold it to playing football, not
only to moving: outcomes come from play, players act after they win the ball,
nobody stands on it, the record tells the truth (a shot is stamped when it is
struck and written before the save or goal that follows; a goal is the ball
over the line; a save is the ball at the keeper's hands).
"""

import collections
import itertools
import math

import pytest

from engine.core import teleports
from engine.core.pitch import GOAL_HALF_WIDTH, GOAL_Y, LENGTH, own
from engine.league import load_league
from engine.play.game import Game, run_attack, seg_dist

SEEDS = range(1, 101)


@pytest.fixture(scope="module")
def league():
    return load_league()


@pytest.fixture(scope="module")
def attacks(league):
    return {
        s: run_attack(league["riverside_athletic"], league["harbour_town"], s)
        for s in SEEDS
    }


def test_every_kind_of_ending_comes_out_of_play(attacks):
    """Tackles, dribbles past a man, saves and goals all happen, and none of
    them is forced: the counts come from what the players did."""
    total = collections.Counter()
    for r in attacks.values():
        total.update({k: v for k, v in r.counts.items() if v})
    for kind in (
        "take_ons",
        "tackles_won",
        "lunges_missed",
        "goals",
        "saves_held",
        "saves_parried",
        "shots",
    ):
        assert total[kind] > 0, kind
    outcomes = collections.Counter(r.outcome for r in attacks.values())
    assert outcomes["goal"] > 0 and outcomes["defended_cleared"] > 0
    # Nothing is implausibly common: no ending takes most of the attacks, and
    # most shots do not go in (real football: about 1 in 10).
    assert max(outcomes.values()) < 60
    assert total["goals"] <= 0.3 * total["shots"]


def test_no_teleports_and_the_ball_is_always_real(attacks):
    for seed, r in attacks.items():
        assert teleports.find(r.tracks, {e.event_id: e for e in r.events}) == [], seed
        for s in r.tracks.samples:
            assert not any(math.isnan(v) for v in s.ball) and s.ball[2] >= 0.0


def test_events_are_in_order_on_the_clock_and_on_the_track(attacks):
    for seed, r in attacks.items():
        marks = [r.tracks.events[e.event_id] for e in r.events]
        assert marks == sorted(marks), seed
        clock = [e.minute * 60 + e.second for e in r.events]
        assert clock == sorted(clock), seed
        for e, k in zip(r.events, marks, strict=True):
            assert e.second == int(r.tracks.samples[k].t % 60), seed


def test_freeze_frames_are_the_track(attacks):
    for seed, r in attacks.items():
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for e in r.events:
            s = r.tracks.samples[r.tracks.events[e.event_id]]
            side = 0 if e.team_id == r.match.home_team else 1
            for p in e.freeze_frame:
                x, y = own(side, p.x, p.y)
                assert math.dist((x, y), s.players[slot[p.player_id]][:2]) <= 0.011, (
                    seed,
                    e.type,
                )


def test_a_shot_is_stamped_at_the_strike_and_written_before_its_result(attacks):
    """The shot sits on the sample where the ball is at the shooter's feet;
    its save (or the goal) comes after it, never before."""
    for seed, r in attacks.items():
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for i, e in enumerate(r.events):
            if e.type != "shot":
                continue
            k = r.tracks.events[e.event_id]
            s = r.tracks.samples[k]
            shooter = s.players[slot[e.player_id]]
            assert math.dist(shooter[:2], s.ball[:2]) <= 2.1, seed
            # The ball leaves him after this sample.
            nxt = r.tracks.samples[k + 1]
            assert math.dist(nxt.ball[:2], s.ball[:2]) > 1.0, seed
            if e.qualifiers.get("result") == "saved":
                save = r.events[i + 1]
                assert save.type == "keeper_save", seed
                assert r.tracks.events[save.event_id] > k, seed


def test_a_goal_is_the_ball_over_the_line_between_the_posts(attacks):
    seen = 0
    for seed, r in attacks.items():
        for e in r.events:
            if e.type != "shot" or e.outcome != "success":
                continue
            seen += 1
            k = r.tracks.events[e.event_id]
            after = r.tracks.samples[k : k + 40]
            crossed = [
                s
                for s in after
                if s.ball[0] > LENGTH
                and abs(s.ball[1] - GOAL_Y) < GOAL_HALF_WIDTH
                and s.ball[2] < 2.44
            ]
            assert crossed, seed
            # ...and the time it took is recorded with the shot.
            line = e.qualifiers["goal_line_s"]
            first = next(s for s in after if s.ball[0] > LENGTH)
            assert abs((first.t - r.tracks.samples[k].t) - line) <= 0.15, seed
    assert seen > 0


def test_a_save_is_the_ball_at_the_keepers_hands(attacks):
    seen = 0
    for seed, r in attacks.items():
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for e in r.events:
            if e.type != "keeper_save":
                continue
            seen += 1
            k = r.tracks.events[e.event_id]
            prev, s = r.tracks.samples[k - 1], r.tracks.samples[k]
            keeper = s.players[slot[e.player_id]]
            # The ball passed within his reach on the way in (he is diving).
            near = min(
                seg_dist(keeper[:2], prev.ball[:2], s.ball[:2]),
                math.dist(keeper[:2], s.ball[:2]),
            )
            assert near <= 1.6, (seed, near)
    assert seen > 0


def test_the_same_seed_gives_the_same_attack(league):
    def dump(r):
        return (
            [e.model_dump_json() for e in r.events],
            [(s.t, s.ball, s.players) for s in r.tracks.samples],
            r.outcome,
        )

    a = run_attack(league["riverside_athletic"], league["harbour_town"], 11)
    b = run_attack(league["riverside_athletic"], league["harbour_town"], 11)
    c = run_attack(league["riverside_athletic"], league["harbour_town"], 12)
    assert dump(a) == dump(b)
    assert dump(a) != dump(c)


def watch(league, seed, on_step):
    g = Game(league["riverside_athletic"], league["harbour_town"], seed)
    orig = g.step

    def step():
        before = g.owner
        orig()
        on_step(g, before)

    g.step = step
    g.run()


@pytest.mark.parametrize("seed", range(1, 41))
def test_nobody_stands_on_the_ball_with_a_man_near(league, seed):
    idle = [0.0]

    def check(g, before):
        o = g.owner
        if o is None or g.in_hands or g.end_at is not None or o is not before:
            idle[0] = 0.0
            return
        near = min(math.dist(o.pos, q.pos) for q in g.opponents(o) if not q.keeper)
        idle[0] = idle[0] + g.cfg["dt"] if (o.speed < 1.0 and near < 5.0) else 0.0
        assert idle[0] <= 1.5, (seed, g.t)

    watch(league, seed, check)


@pytest.mark.parametrize("seed", range(1, 41))
def test_a_player_who_wins_the_ball_does_something_with_it(league, seed):
    """Within 2.5 s he carries it 3 m or plays it (a keeper: distributes
    within 4 s). Shielding under a man on him for longer is allowed."""
    st = {}

    def check(g, before):
        o = g.owner
        if g.end_at is not None:
            return
        if o is not before:
            st.clear()
            if o is not None:
                st.update(o=o, t=g.t, at=o.pos, hands=g.in_hands)
            return
        if o is None or not st:
            return
        if math.dist(o.pos, st["at"]) >= 3.0:
            st.clear()
            return
        near = min(math.dist(o.pos, q.pos) for q in g.opponents(o) if not q.keeper)
        limit = 4.0 if st["hands"] else 2.5
        if near > 2.5 and g.t > 2.5:
            assert g.t - st["t"] <= limit, (seed, g.t)

    watch(league, seed, check)


@pytest.mark.parametrize("seed", range(1, 41))
def test_a_clear_chance_is_taken(league, seed):
    """A Riverside player inside 18 m, central, with no outfield body in the
    way, shoots within 2.5 s."""
    clear = [0.0]

    def check(g, before):
        o = g.owner
        if o is None or o.key[0] != 0 or g.end_at is not None or o is not before:
            clear[0] = 0.0
            return
        goal = (LENGTH, GOAL_Y)
        lane = all(
            seg_dist(q.pos, o.pos, goal) > 1.5 for q in g.opponents(o) if not q.keeper
        )
        if math.dist(o.pos, goal) <= 18.0 and lane and abs(o.y - GOAL_Y) < 12.0:
            clear[0] += g.cfg["dt"]
            assert clear[0] <= 2.5, (seed, g.t)
        else:
            clear[0] = 0.0

    watch(league, seed, check)


@pytest.mark.parametrize("seed", range(1, 41))
def test_no_zig_zag_in_open_space(league, seed):
    """With nobody within 4 m, his chosen heading does not swing one way,
    back, and back again (each over 20 degrees) inside 3 s."""
    st = {"h": None, "turns": [], "since": 0.0, "o": None}

    def check(g, before):
        o = g.owner
        if o is not st["o"]:
            st.update(o=o, h=None, turns=[], since=g.t)
        if o is None or g.in_hands or g.end_at is not None:
            return
        m = g.mind[o.key]
        near = min(math.dist(o.pos, q.pos) for q in g.opponents(o) if not q.keeper)
        if near <= 4.0 or m.intent != "carry" or g.t - st["since"] <= 1.0:
            st["h"] = None
            return
        if st["h"] is not None:
            turn = (m.heading - st["h"] + 540.0) % 360.0 - 180.0
            if abs(turn) > 20.0:
                st["turns"].append((g.t, turn > 0))
                recent = [x for x in st["turns"] if g.t - x[0] <= 3.0]
                flips = sum(1 for a, b in itertools.pairwise(recent) if a[1] != b[1])
                assert flips < 2, (seed, g.t)
        st["h"] = m.heading

    watch(league, seed, check)


# ---- decisions Ian's review asked for (attack 56) ------------------------------


def test_no_endless_duel(attacks):
    """A contest moves on: control of the ball changes team at most 4 times
    in any 10 s (a poke that nobody controls is not a change)."""
    for seed, r in attacks.items():
        ch = r.changes
        for t0 in ch:
            assert sum(1 for t in ch if t0 <= t < t0 + 10.0) <= 4, seed


@pytest.mark.parametrize("seed", range(1, 41))
def test_a_beaten_defender_does_not_keep_diving_in(league, seed):
    """No defender misses (or is ridden by) the same carrier 3 times in 6 s."""
    misses = collections.defaultdict(list)

    def check(g, before):
        for pl in g.players:
            m = g.mind[pl.key]
            if (
                m.stun_until > g.t
                and m.stun_until - g.t > g.cfg["defend"]["stun_s"] - 0.11
            ):
                o = g.owner
                if o is not None:
                    key = (pl.key, o.key)
                    misses[key] = [t for t in misses[key] if g.t - t <= 6.0] + [g.t]
                    assert len(misses[key]) < 3, (seed, g.t)

    watch(league, seed, check)


@pytest.mark.parametrize("seed", range(1, 41))
def test_the_keeper_is_not_caught_off_his_line(league, seed):
    """When the keeper is well off his line (beyond his 1-on-1 distance), an
    attacker never wins the ball there: he only comes for balls he gets."""

    def check(g, before):
        k = g.keeper
        far = math.dist(k.pos, (LENGTH, GOAL_Y)) > g.cfg["keeper"]["max_1v1_m"] + 1.5
        if (
            far
            and g.owner is not None
            and g.owner is not before
            and g.owner.key[0] == 0
        ):
            raise AssertionError(
                (seed, g.t, "attacker won the ball with the keeper out")
            )

    watch(league, seed, check)


@pytest.mark.parametrize("seed", range(1, 41))
def test_an_open_goal_is_shot_at(league, seed):
    """Keeper beaten (off the line to goal by 2.5 m, or behind the ball), a
    Riverside player within 25 m with no body in the lane shoots within 1 s."""
    open_for = [0.0]

    def check(g, before):
        o = g.owner
        if o is None or o.key[0] != 0 or g.end_at is not None or o is not before:
            open_for[0] = 0.0
            return
        goal = (LENGTH, GOAL_Y)
        k = g.keeper
        beaten = seg_dist(k.pos, o.pos, goal) > 2.5 or math.dist(
            k.pos, goal
        ) > math.dist(o.pos, goal)
        lane = all(
            seg_dist(q.pos, o.pos, goal) > 1.2 for q in g.opponents(o) if not q.keeper
        )
        if beaten and lane and math.dist(o.pos, goal) <= 25.0:
            open_for[0] += g.cfg["dt"]
            assert open_for[0] <= 1.0, (seed, g.t)
        else:
            open_for[0] = 0.0

    watch(league, seed, check)


def test_the_screen_gets_the_goal_line_time(league, tmp_path, monkeypatch):
    """The API hands the screen how long after the strike the ball crossed
    the line, so the score changes then (not at the strike)."""
    from engine.play.__main__ import write_run
    from stream.api import get_events

    r = run_attack(league["riverside_athletic"], league["harbour_town"], 76)
    assert r.outcome == "goal"
    write_run(r, tmp_path / "attack-76", "attack-76")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    goals = [
        e
        for e in get_events("attack-76")
        if e["type"] == "shot" and e["outcome"] == "success"
    ]
    assert goals and 0.1 <= goals[0]["goal_line_s"] <= 2.0


def test_the_referee_runs_with_play_and_never_jumps(attacks):
    """He is in the track (his own slot), moves under a man's limits, and
    stays out of the way of play most of the time."""
    from engine.play.referee import SLOT

    near = []
    for seed, r in attacks.items():
        k = r.tracks.slots.index(SLOT)
        s = r.tracks.samples
        for a, b in itertools.pairwise(s):
            assert math.dist(a.players[k][:2], b.players[k][:2]) / 0.1 <= 7.0 + 1e-6, (
                seed
            )
        near += [math.dist(x.players[k][:2], x.ball[:2]) for x in s]
    near.sort()
    assert near[len(near) // 2] >= 12.0  # usually well clear of the ball
