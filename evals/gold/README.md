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
