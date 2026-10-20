from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str
    model: str

    def count_tokens(self, prompt: str, system: str | None) -> int: ...

    def generate(
        self, prompt: str, system: str | None, max_output_tokens: int
    ) -> LLMResponse: ...
