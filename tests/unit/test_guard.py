"""Nothing spends real requests by accident: the fake model is the default,
a real one prints an estimate and asks, and a fake re-record never replaces a
real-model bundle."""

import json

import pytest

from agents.live.record import fake_llm
from agents.live.record import main as record_main
from agents.llm import LLMClient
from agents.llm.fake import FakeProvider
from agents.llm.guard import confirm, dry_run_requests
from tests.unit.test_llm_adapter import budget


def real_llm() -> LLMClient:
    provider = FakeProvider()
    provider.name, provider.model = "gemini", "gemini-3.5-flash-lite"
    return LLMClient(provider, budget(0.5))


def test_the_fake_model_never_asks():
    said = []
    confirm(fake_llm(), "About 50 requests", ask=pytest.fail, out=said.append)
    assert said == []


def test_a_real_model_says_what_it_will_spend_and_asks():
    said = []
    confirm(
        real_llm(),
        "About 53 requests",
        ask=lambda _: "y",
        out=said.append,
        interactive=True,
    )
    assert "gemini-3.5-flash-lite" in said[0] and "About 53 requests" in said[0]
    assert "$0.5" in said[0]


def test_no_means_nothing_is_spent():
    with pytest.raises(SystemExit, match="no requests spent"):
        confirm(
            real_llm(),
            "About 53 requests",
            ask=lambda _: "",
            out=print,
            interactive=True,
        )


def test_without_a_terminal_a_real_run_needs_yes():
    with pytest.raises(SystemExit, match="--yes"):
        confirm(real_llm(), "x", out=print, interactive=False)
    confirm(real_llm(), "x", yes=True, out=print, interactive=False)


def test_the_estimate_is_counted_on_the_free_model():
    def job(llm):
        llm.complete("hi", max_output_tokens=10)
        llm.complete("again", max_output_tokens=10)

    assert dry_run_requests(job) == 2


def test_a_fake_rerecord_never_replaces_a_real_bundle(tmp_path):
    out = tmp_path / "demo"
    out.mkdir()
    (out / "meta.json").write_text(json.dumps({"model": "gemini-3.5-flash-lite"}))
    with pytest.raises(SystemExit, match="recorded with gemini"):
        record_main(["--out", str(out)])
    assert json.loads((out / "meta.json").read_text())["model"].startswith("gemini")
