# Cost

What a model call costs, how a run is capped, and what real runs cost. Every
figure below comes from the budget ledger (`core/budget.py`) of a real run,
not an estimate, unless it says so.

## Models and prices

USD per 1M tokens (`agents/llm/prices.py`). Reasoning tokens are billed as
output.

| Model | Used for | Input | Output | Source |
|---|---|---|---|---|
| gpt-5-mini (Azure Foundry, Global Standard, South Africa North) | Analyst (reasoning effort low) | 0.25 | 2.00 | Azure retail prices API, read 2026-10-25 |
| gpt-4.1-mini (Azure Foundry, Global Standard, South Africa North) | Narrator, Localizer, recaps | 0.40 | 1.60 | Azure retail prices API, read 2026-10-25 |
| gemini-3.5-flash-lite (Google AI Studio) | development | 0.30 | 2.50 | ai.google.dev pricing, 2026-10-19 (paid price used even on the free tier) |

KES figures use 130 KES per USD (rate dated 2026-09-29, `KES_RATE`).

## How spending is capped

- **Per run, hard:** `MAX_RUN_USD` (0.50 in `.env.example`) and
  `MAX_RUN_TOKENS` (500,000). A real provider is refused without
  `MAX_RUN_USD`.
- **Before each call:** the worst case (input at one token per byte, plus the
  call's full output cap) must fit what is left, or the call is blocked with no
  request sent, and the kill switch stops every later call in the run. Billing
  can never pass what was prechecked.
- **Output caps per call:** Analyst 1,500 tokens (gpt-5-mini thinks inside
  this cap; at 400 it ran out before answering on 9 of 12 moments), every
  other agent 400.
- **Failed calls:** tokens billed on an answer cut off at the cap are charged
  to the budget; a call that failed with nothing billed is not.
- **Nothing by accident:** without `--provider` every command uses the free fake
  model; a real run asks first and shows a request estimate from a free dry
  run.
- **Judge mode costs nothing:** the screen plays a recorded bundle, zero model
  calls.

## Real runs (the demo match, English + Kiswahili)

| Run (date) | Model(s) | Calls | Cost | Per aired line | Wall time |
|---|---|---|---|---|---|
| `runs/demo`, 2026-10-25 | gemini-3.5-flash-lite | 80 | $0.0263 (KES 3.42) | $0.0009 | 8.0 min (paced to the free tier's 10 requests/min) |
| `runs/demo-foundry`, 2026-10-25 | gpt-5-mini + gpt-4.1-mini, Analyst cap 400 | 72 | $0.0317 (KES 4.13) | $0.0011 | 2.3 min |
| `runs/demo-foundry-2`, 2026-10-25 | gpt-5-mini + gpt-4.1-mini, Analyst cap 1,500 | 70 | $0.0322 (KES 4.19) | $0.0012 | 2.4 min |
| Foundry smoke test (one call per deployment) | both | 2 | $0.000086 | - | seconds |

Per aired line = cost / the run's 28 narrated lines (`meta.json`: AI lines +
template lines).

Where `runs/demo-foundry-2`'s $0.0322 went:

| Agent | Model | Calls | Tokens in / out | Cost |
|---|---|---|---|---|
| Analyst | gpt-5-mini | 12 | 8,750 / 5,123 | $0.0124 |
| Narrator | gpt-4.1-mini | 25 | 27,171 / 916 | $0.0123 |
| Localizer (Kiswahili) | gpt-4.1-mini | 29 | 4,900 / 1,857 | $0.0049 |
| Recaps | gpt-4.1-mini | 4 | 5,206 / 288 | $0.0025 |

The Analyst's reasoning is most of its output: 5,123 output tokens for 12
short JSON insights.

Earlier eval runs: the narration repeat-run eval (2026-10-22, Gemini, 207
calls) cost $0.0471 ([EVAL.md](EVAL.md)).

## Not measured yet

- **Hosting.** Defined (`infra/main.bicep`: Azure Container Apps, one
  replica of 0.5 vCPU / 1 GiB while judges may visit, a Basic container
  registry, Log Analytics) with a monthly budget of 20 (billing currency) on
  the resource group that emails at 50% and 80% spent and 100% forecast. Not
  deployed yet, so its real cost is not measured; it makes no model calls.
- **Rate limits.** Each Foundry deployment allows 50 requests and 50K tokens a
  minute. `runs/demo-foundry-2` averaged about 29 requests and 20K input
  tokens a minute across both deployments (70 calls in 2.4 min) with no
  throttling; peaks within a minute and a live (real-time) run are not
  measured.
