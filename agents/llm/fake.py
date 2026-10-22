"""A fake model for tests and offline runs: free, instant, deterministic.

Default ("echo"): answers in the shape each role asks for, using only the
numbers in the prompt's VALUES block, so its lines pass the Verifier.
Error injection: the first `errors` Narrator answers are wrong on purpose
(`error` = "wrong_number", "invented_player" or "prediction"), to test the
Verifier, the retries and the fallback.
Failure injection: `failures` = {role: [mode, ...]}, consumed one per call of
that role ("analyst", "narrator", "localizer", "recap"): "timeout" (answers
after `slow_s`), "rate_limit" (429), "server_error" (503), "bad_request"
(400, not retryable), "malformed" (an unusable answer).
A `script` (list of strings, or a function of (prompt, system)) overrides it.
"""

import json
import re
import time

from agents.llm.base import LLMResponse, ProviderError

FAKE_MODEL = "fake-model"
VALUES = re.compile(r"VALUES:\s*(\{.*?\})\s*$", re.DOTALL | re.MULTILINE)
# Enough "translation" for the Localizer's English check to pass offline.
SWAHILI = {"the": "", "and": "na", "from": "kutoka", "to": "hadi", "with": "na"}
ROLES = ["analyst", "narrator", "localizer", "recap"]
FAILURES = {
    "rate_limit": (429, True),
    "server_error": (503, True),
    "bad_request": (400, False),
}
MALFORMED = "{not json"
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

    def __init__(
        self,
        script=None,
        errors: int = 0,
        error: str = "wrong_number",
        failures: dict[str, list[str]] | None = None,
        slow_s: float = 0.5,
    ):
        self.model = FAKE_MODEL
        self.script = script
        self.errors = errors
        self.error = error
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.slow_s = slow_s
        self.calls: list[tuple[str | None, str]] = []  # (system, prompt)

    def count_tokens(self, prompt, system):
        return len(((system or "") + prompt).split())

    def generate(self, prompt, system, max_output_tokens, timeout_s=None):
        role = next(
            (r for r in ROLES if f"ROLE: {r.upper()}" in (system or "")), "other"
        )
        mode = self.failures[role].pop(0) if self.failures.get(role) else None
        if mode == "timeout":
            if timeout_s is not None and self.slow_s > timeout_s:
                time.sleep(timeout_s)  # the request gives up, like an HTTP timeout
                raise ProviderError("fake timeout", retryable=True, status=408)
            time.sleep(self.slow_s)
        elif mode in FAILURES:
            status, retryable = FAILURES[mode]
            raise ProviderError(f"fake {status}", retryable=retryable, status=status)
        self.calls.append((system, prompt))
        text = MALFORMED if mode == "malformed" else self.answer(prompt, system or "")
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
        if "ROLE: RECAP" in system:
            return f"That is how it stands: {v.get('score', 'level')}."
        if "ROLE: LOCALIZER" in system:
            words = prompt.split("TEXT:", 1)[-1].split()
            return "[sw] " + " ".join(SWAHILI.get(w.lower(), w) for w in words)
        line = self.echo_line(v)
        narrated = sum(1 for s, _ in self.calls if s and "ROLE: NARRATOR" in s)
        if narrated <= self.errors:
            return ERRORS[self.error](line)
        return line

    @staticmethod
    def echo_line(v: dict) -> str:
        if "changes" in v:  # casual: words, not numbers
            parts = [f"{name.lower()} {word}" for name, word in v["changes"].items()]
        else:
            numbers = v.get("numbers", {})
            parts = [
                f"{name.replace('_', ' ')} {value}" for name, value in numbers.items()
            ]
        team = v.get("team") or "The match"
        zone = v.get("facts", {}).get("exploited_zone")
        how = f" A counter {zone}." if zone else ""
        return (
            f"{team}, {v.get('minute', 0)}': "
            + (", ".join(parts[:2]) or v.get("kind", ""))
            + "."
            + how
        )
