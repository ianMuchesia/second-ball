from google import genai
from google.genai import types

from agents.llm.base import LLMResponse


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key, model, client=None):
        if not api_key and client is None:
            raise ValueError("GEMINI_API_KEY is not set")
        self.model = model
        self.client = client or genai.Client(api_key=api_key)

    def count_tokens(self, prompt, system):
        contents = [system, prompt] if system else prompt
        return self.client.models.count_tokens(
            model=self.model, contents=contents
        ).total_tokens

    def generate(self, prompt, system, max_output_tokens):
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
