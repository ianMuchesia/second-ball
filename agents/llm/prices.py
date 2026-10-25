# USD per 1M tokens, paid Standard tier, text, prompts <= 200k tokens.
# Paid prices are used even on the free tier so MAX_RUN_USD means something.
# Source: https://ai.google.dev/gemini-api/docs/pricing (last updated 2026-10-19).
PRICES_DATE = "2026-10-19"

PRICES = {
    "gemini-3.5-flash-lite": {"input_per_m": 0.30, "output_per_m": 2.50},
    # Listed at half price until 2026-12-31; the full price is used here.
    "gemini-3.8-flash": {"input_per_m": 1.50, "output_per_m": 7.50},
    "gemini-2.5-flash": {"input_per_m": 0.30, "output_per_m": 2.50},
    # Azure AI Foundry, Global Standard, South Africa North (Azure retail
    # prices API, prices.azure.com, read 2026-10-25): "GPT 5 Mini Inpt/outpt
    # Glbl" and "gpt 4.1 mini Inp/Outp glbl". Not priority processing.
    "gpt-5-mini": {"input_per_m": 0.25, "output_per_m": 2.00},
    "gpt-4.1-mini": {"input_per_m": 0.40, "output_per_m": 1.60},
    # The fake provider (tests, offline): free, but still goes through the budget.
    "fake-model": {"input_per_m": 0.0, "output_per_m": 0.0},
}
