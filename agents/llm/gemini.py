import threading
import time

from google import genai
from google.genai import types

from agents.llm.base import LLMResponse

# Gemini caps requests per minute, tokens per minute and requests per day, per
# project (https://ai.google.dev/gemini-api/docs/rate-limits; the numbers are
# in AI Studio). Going over returns 429 RESOURCE_EXHAUSTED. Two guards:
# - pacing: at most `rpm` requests a minute (token counts for the budget
#   precheck are local, so each model call is one request);
# - retry: the SDK retries 429/503 with backoff (it never retries by default).
RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=2.0, max_delay=30.0, http_status_codes=[429, 503]
)


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key,
        model,
        client=None,
        rpm=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        if not api_key and client is None:
            raise ValueError("GEMINI_API_KEY is not set")
        self.model = model
        self.client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(retry_options=RETRY)
        )
        self.gap_s = 60.0 / rpm if rpm else 0.0
        self.clock, self.sleep = clock, sleep
        self.next_at = 0.0
        self.lock = threading.Lock()

    def pace(self):
        """Wait so requests are at least 60/rpm seconds apart."""
        with self.lock:
            now = self.clock()
            if now < self.next_at:
                self.sleep(self.next_at - now)
                now = self.next_at
            self.next_at = now + self.gap_s

    def count_tokens(self, prompt, system):
        """Upper bound for the budget precheck, counted locally: one token per
        UTF-8 byte (real tokens are several bytes). Asking the API would cost a
        request against the per-minute cap and seconds of latency; the real
        count still comes back with the answer and is what gets charged."""
        return len(((system or "") + prompt).encode())

    def generate(self, prompt, system, max_output_tokens):
        self.pace()
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_output_tokens,
            ),
        )
        usage = response.usage_metadata
        return LLMResponse(
            text=response.text or "",
            model=self.model,
            input_tokens=usage.prompt_token_count or 0,
            # Thinking tokens are billed as output.
            output_tokens=(usage.candidates_token_count or 0)
            + (usage.thoughts_token_count or 0),
        )
