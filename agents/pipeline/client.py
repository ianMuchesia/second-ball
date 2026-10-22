"""Agent Framework chat client over OUR adapter (agents/llm), so every model
call an agent makes still goes through core/budget.py (the kill switch)."""

import asyncio

from agent_framework import BaseChatClient, ChatResponse, Message

from agents.llm import LLMClient

DEFAULT_MAX_OUTPUT = 400


class AdapterChatClient(BaseChatClient):
    OTEL_PROVIDER_NAME = "second-ball-adapter"

    def __init__(self, llm: LLMClient, **kwargs):
        super().__init__(**kwargs)
        self.llm = llm

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            raise NotImplementedError("the pipeline does not stream")
        options = dict(options or {})
        prompt = "\n\n".join(m.text for m in messages if m.role != "system" and m.text)
        system = "\n\n".join(
            [
                options.get("instructions") or "",
                *(m.text for m in messages if m.role == "system"),
            ]
        ).strip()
        response = await asyncio.to_thread(
            self.llm.complete,
            prompt,
            max_output_tokens=options.get("max_tokens") or DEFAULT_MAX_OUTPUT,
            system=system or None,
        )
        return ChatResponse(
            messages=[Message(role="assistant", contents=[response.text])],
            model=response.model,
        )
