"""Azure AI Foundry (Azure OpenAI in Foundry Models), v1 API.

    POST {endpoint}/openai/v1/chat/completions, header api-key, "model" = the
    deployment name; the v1 API needs no api-version (GA since August 2025:
    https://learn.microsoft.com/azure/ai-foundry/openai/api-version-lifecycle).
    The endpoint may be https://<resource>.openai.azure.com or
    https://<resource>.services.ai.azure.com, with or without /openai/v1.

Two deployments (DECISIONS.md, Phase 3a): gpt-5-mini for the Analyst
(reasoning effort low), gpt-4.1-mini for everything else. The agent making a
call is in CALL_ROLE (set by the pipeline per call), so `model` is the
deployment that call goes to and the budget prices that one. A deployment
must be named after its model (gpt-5-mini, gpt-4.1-mini): the budget prices
by name and blocks a name it has no price for, before any request.

No retries here: a failure becomes a ProviderError (retryable or not) and the
pipeline's own policy retries or falls back to a template.
"""

import httpx

from agents.llm.base import CALL_ROLE, RETRYABLE_STATUS, LLMResponse, ProviderError

REASONING_PREFIX = ("gpt-5", "o1", "o3", "o4")  # take reasoning_effort


def v1_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if not base.endswith("/openai/v1"):
        base += "/openai/v1"
    return base + "/chat/completions"


class FoundryProvider:
    name = "foundry"

    def __init__(
        self,
        endpoint,
        api_key,
        model,
        roles=None,
        client=None,
        timeout_s=30.0,
        reasoning_effort="low",
    ):
        """model: the default deployment; roles: {agent role: deployment},
        e.g. {"analyst": "gpt-5-mini"}."""
        missing = [
            n
            for n, v in (
                ("FOUNDRY_ENDPOINT", endpoint),
                ("FOUNDRY_API_KEY", api_key),
                ("FOUNDRY_MODEL", model),
            )
            if not v
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} not set")
        self.url = v1_url(endpoint)
        self.default = model
        self.roles = {k: v for k, v in (roles or {}).items() if v}
        self.reasoning_effort = reasoning_effort
        self.timeout_s = timeout_s
        self.client = client or httpx.Client(
            headers={"api-key": api_key}, timeout=timeout_s
        )

    @property
    def model(self) -> str:
        """The deployment the current call goes to (by the calling agent)."""
        return self.roles.get(CALL_ROLE.get(), self.default)

    def count_tokens(self, prompt, system):
        """Upper bound for the budget precheck: one token per UTF-8 byte (as
        for Gemini); the real count comes back with the answer and is charged."""
        return len(((system or "") + prompt).encode())

    def generate(self, prompt, system, max_output_tokens, timeout_s=None):
        deployment = self.model
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        # max_completion_tokens caps visible and reasoning tokens together:
        # exactly what the budget prechecked, never more.
        body = {
            "model": deployment,
            "messages": messages,
            "max_completion_tokens": max_output_tokens,
        }
        if deployment.startswith(REASONING_PREFIX) and self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        try:
            r = self.client.post(
                self.url, json=body, timeout=timeout_s or self.timeout_s
            )
        except httpx.TimeoutException as e:
            raise ProviderError(
                f"foundry {deployment}: timed out", retryable=True, status=408
            ) from e
        except httpx.TransportError as e:
            raise ProviderError(
                f"foundry {deployment} network: {type(e).__name__}", retryable=True
            ) from e
        if r.status_code >= 400:
            raise ProviderError(
                f"foundry {deployment} {r.status_code}: {error_message(r)}",
                retryable=r.status_code in RETRYABLE_STATUS,
                status=r.status_code,
            )
        try:
            data = r.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            usage = data["usage"]
            input_tokens = int(usage["prompt_tokens"])
            # Reasoning tokens are inside completion_tokens (billed as output).
            output_tokens = int(usage["completion_tokens"])
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderError(
                f"foundry {deployment}: malformed response", retryable=False
            ) from e
        why = choice.get("finish_reason")
        if why == "length" or not text.strip():
            # Cut off at the cap (a reasoning model may spend it thinking) or
            # nothing said: never a line. The tokens were billed, so they go
            # to the budget with the error.
            raise ProviderError(
                f"foundry {deployment}: "
                f"{'cut off' if text.strip() else 'empty answer'} "
                f"(finish_reason={why}; {output_tokens} of {max_output_tokens} "
                "tokens used)",
                retryable=False,
                usage=(input_tokens, output_tokens),
            )
        return LLMResponse(
            text=text,
            model=data.get("model") or deployment,  # the model that answered
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def error_message(r: httpx.Response) -> str:
    """The API's own error text (code and message), never the request."""
    try:
        err = r.json().get("error") or {}
        return f"{err.get('code', '')} {err.get('message', '')}".strip()[:300]
    except (ValueError, AttributeError):
        return r.reason_phrase or "error"
