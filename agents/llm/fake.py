"""A fake model for tests and offline runs: free, instant, deterministic.

Default ("echo"): answers in the shape each role asks for, using only the
numbers in the prompt's VALUES block, so its lines pass the Verifier.
Error injection: the first `errors` Narrator answers are wrong on purpose
(`error` = "wrong_number", "invented_player" or "prediction"), to test the
Verifier, the retries and the fallback.
A `script` (list of strings, or a function of (prompt, system)) overrides it.
"""

import json
import re

from agents.llm.base import LLMResponse

FAKE_MODEL = "fake-model"
VALUES = re.compile(r"VALUES:\s*(\{.*?\})\s*$", re.DOTALL | re.MULTILINE)
ERRORS = {
    "wrong_number": lambda line: re.sub(r"\d+(\.\d+)?", "97", line, count=1),
    "invented_player": lambda line: f"Okafor makes it happen. {line}",
    "prediction": lambda line: f"{line} They will win this.",
}


def values_from(prompt: str) -> dict:
    found = VALUES.search(prompt)
    return json.loads(found.group(1)) if found else {}


class FakeProvider:
    name = "fake"

    def __init__(self, script=None, errors: int = 0, error: str = "wrong_number"):
        self.model = FAKE_MODEL
        self.script = script
        self.errors = errors
        self.error = error
        self.calls: list[tuple[str | None, str]] = []  # (system, prompt)

    def count_tokens(self, prompt, system):
        return len(((system or "") + prompt).split())

    def generate(self, prompt, system, max_output_tokens):
        self.calls.append((system, prompt))
        text = self.answer(prompt, system or "")
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=self.count_tokens(prompt, system),
            output_tokens=len(text.split()),
        )

    def answer(self, prompt: str, system: str) -> str:
        if callable(self.script):
            return self.script(prompt, system)
        if self.script is not None:
            return self.script[(len(self.calls) - 1) % len(self.script)]
        v = values_from(prompt)
        if "ROLE: ANALYST" in system:
            return json.dumps(
                {
                    "claim": f"{v.get('team', 'The team')}: {v.get('kind', 'moment')}.",
                    "mechanism": "See the numbers before and after.",
                }
            )
        if "ROLE: LOCALIZER" in system:
            return "[sw] " + prompt.split("TEXT:", 1)[-1].strip()
        line = self.echo_line(v)
        narrated = sum(1 for s, _ in self.calls if s and "ROLE: NARRATOR" in s)
        if narrated <= self.errors:
            return ERRORS[self.error](line)
        return line

    @staticmethod
    def echo_line(v: dict) -> str:
        numbers = v.get("numbers", {})
        parts = [f"{name.replace('_', ' ')} {value}" for name, value in numbers.items()]
        team = v.get("team") or "The match"
        return (
            f"{team}, {v.get('minute', 0)}': "
            + (", ".join(parts[:2]) or v.get("kind", ""))
            + "."
        )
