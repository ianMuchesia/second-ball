"""Leave-one-out: narrating a moment, the Narrator never sees the example
written for that moment; a 3-gram backstop rejects near-copies of any
example; and every caught draft of a real run is saved as a gold item."""

import asyncio
import json

from agents.live.record import fake_llm
from agents.narrator import examples
from agents.pipeline.facts import task_for
from agents.pipeline.verifier import copied
from agents.pipeline.workflow import narrate
from evals.gold.caught import caught, kind_of, save
from tests.unit.test_narration_report import demo

MATCH = "m-riverside_athletic-harbour_town-1"
IANS_34 = "Lightning from Harbour! One pass behind Riverside's left-back"


def test_the_example_for_the_moment_being_narrated_is_left_out():
    every = examples("casual")
    held = examples("casual", (MATCH, "goal", 34))
    assert len(held) == len(every) - 1
    assert not any(x.startswith(IANS_34) for x in held)
    assert any(x.startswith(IANS_34) for x in every)


def test_the_narrator_prompt_for_34_has_no_34_example():
    data = demo()
    goal = next(m for m in data.moments if m.kind == "goal" and m.clock.minute == 34)
    llm = fake_llm()
    asyncio.run(narrate(llm, task_for(data, goal, "casual", [])))
    systems = [s for s, _ in llm.provider.calls if "ROLE: NARRATOR" in (s or "")]
    assert systems and all(IANS_34 not in s for s in systems)
    assert all("STYLE EXAMPLES ONLY" in s for s in systems)  # others still there


def test_copy_backstop_counts_shared_phrases_not_shared_words():
    ex = examples("casual")
    near = "Lightning from Harbour! One pass behind Riverside's left-back on the break, and Harbour lead 1-0!"
    assert copied(near, ex)
    # Sharing a few words ("Harbour lead") is fine.
    assert not copied("Harbour lead 1-0 after a quick break down the left.", ex)


def test_caught_drafts_are_labelled_by_error_kind():
    assert kind_of("'drop' but the number goes from 0.71 to 0.8: say it rose") == (
        "wrong_direction"
    )
    assert (
        kind_of("the control numbers are Riverside's, not Harbour's") == "wrong_owner"
    )
    assert kind_of("'Patient' is not a team or a player on the team sheet") == (
        "unknown_name"
    )


def test_a_real_runs_caught_drafts_are_saved(tmp_path):
    b = tmp_path / "demo"
    b.mkdir()
    (b / "meta.json").write_text(
        json.dumps(
            {
                "model": "gemini-x",
                "recorded_at": "2026-10-23T18:28:37",
                "match_id": MATCH,
            }
        )
    )
    (b / "overlays.jsonl").write_text(
        json.dumps({"overlay_id": "m-mo048-analyst", "t_in": {"match": {"minute": 63}}})
    )
    v = {
        "passed": False,
        "text": "Harbour's control rises.",
        "reasons": ["x's, not y's"],
    }
    ok = {"passed": True, "text": "fine", "reasons": []}
    n = {
        "overlay_id": "m-mo048-analyst",
        "kind": "red_card_impact",
        "persona": "analyst",
        "verdicts": [v, ok],
    }
    (b / "narrations.jsonl").write_text(json.dumps(n))
    (row,) = caught(b)
    assert (row["minute"], row["errors"], row["human_label"]) == (
        63,
        ["wrong_owner"],
        None,
    )
    out = save(b, tmp_path / "gold")
    assert json.loads(out.read_text()) == [row]
