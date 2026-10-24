# Gold eval items: real mistakes from real runs

- `caught/` — every draft the Verifier sent back in a real-model recording,
  saved by the recorder (`evals/gold/caught.py`): the text, the reasons, the
  moment and the kind of error. `human_label` is for a person to say whether
  the Verifier was right (the name check also flags ordinary words that start
  a sentence, e.g. "Meanwhile").
- `missed.json` — lines that aired wrong because no check existed yet, each
  with the fix that now catches it.
- `agents/narrator/examples.yaml` — Ian's lines; the first gold items.

These feed Phase 6: each item is run through the current Verifier.

## What the Verifier checks, with real mistakes it met

Every row is from a real Gemini run of the demo match.

| Error | Real example | Check |
|---|---|---|
| Wrong number | "0.61 goals" read as 61 goals | `wrong_numbers`, `wrong_counts` |
| Wrong owner | Riverside's control credited to Harbour | `wrong_owner` |
| Wrong direction | "drop control from 0.71 to 0.80" (it rose) | `wrong_direction` |
| Wrong relation | "a counter creates 2 counter goals" (Harbour's second goal on the counter) | `unphrased_counts` |
| Wrong score format | "zero to one", "Harbour lead 0-1", "one-nil" | `number_style`, `score_repeated` |
| Invented fact | "one quick break" (no such count) | `wrong_counts` |
| Unknown name | "Patient" as if a player (a false alarm: an ordinary word) | `unknown_names` |
| Wrong time | a 73' line shown at 63' | the screen: `aired_t` (not the Verifier) |

Claims shown in the evidence drawer go through the same checks, as made and
again as served.
