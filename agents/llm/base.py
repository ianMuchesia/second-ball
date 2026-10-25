from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

# The agent making the current model call ("analyst", "narrator", ...), set
# by the pipeline per call; a provider may route it to its own deployment.
CALL_ROLE: ContextVar[str | None] = ContextVar("call_role", default=None)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ProviderError(Exception):
    """A model call failed. retryable: worth trying again after a pause (rate
    limit, server error, network); not: a bad request, an auth error.
    exhausted: the quota is gone for a long time (e.g. the free tier's daily
    cap): stop calling the model for this run."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status: int | None = None,
        exhausted: bool = False,
        usage: tuple[int, int] | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.exhausted = exhausted
        # (input, output) tokens the provider billed although the call failed
        # (e.g. an answer cut off at the cap): charged all the same.
        self.usage = usage


RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class Provider(Protocol):
    name: str
    model: str

    def count_tokens(self, prompt: str, system: str | None) -> int: ...

    def generate(
        self, prompt: str, system: str | None, max_output_tokens: int
    ) -> LLMResponse: ...
