# USD per 1M tokens, paid Standard tier, text, prompts <= 200k tokens.
# Paid prices are used even on the free tier so MAX_RUN_USD means something.
# Source: https://ai.google.dev/gemini-api/docs/pricing (last updated 2026-10-19).
PRICES_DATE = "2026-10-19"

PRICES = {
    "gemini-3.5-flash-lite": {"input_per_m": 0.30, "output_per_m": 2.50},
    # Listed at half price until 2026-12-31; the full price is used here.
    "gemini-3.8-flash": {"input_per_m": 1.50, "output_per_m": 7.50},
    "gemini-2.5-flash": {"input_per_m": 0.30, "output_per_m": 2.50},
}
