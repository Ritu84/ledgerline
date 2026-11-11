# Evaluation report

_Drafted with AI (Claude Code) from runs on my machine; see `AI_USAGE.md`._

## Setup

- **Provider and model:** Google Gemini `gemini-3.5-flash-lite`, through the OpenAI-compatible endpoint (`LLM_PROVIDER=openai_compat`). The same model was used for the starter and for my pipeline.
- **Prices used:** $0.30 per million input tokens, $2.50 per million output tokens, ₹88 per dollar.
- **Date:** 10 Nov 2026. Starter runs in the afternoon, my final run at about 22:00 IST. The provider was returning `503 Service Unavailable` on some calls that day.
- **Documents:** the 24 dev documents in `data/documents/dev/`, scored against `data/ground_truth/dev.jsonl`.
- **Mine:** `make eval` (or `cd backend && .venv/bin/python eval/run_eval.py`).
- **Starter:** a clean clone of the starter at commit `4be14a8`, then
  `PYTHONPATH=<starter>/backend python backend/eval/starter_baseline/run_starter.py` and
  `python backend/eval/starter_baseline/score_starter.py backend/eval/starter_baseline <file-stem>`.
  The raw outputs are saved next to the scripts: `as_delivered.jsonl`, `fences_stripped.jsonl`, `fences_stripped_no_examples.jsonl`.

Each starter configuration was run once. Mine was run five times (10 and 11 Nov 2026); the accuracy numbers were identical every time, latency was not. The last run was on 11 Nov at about 19:50 IST, on the final code. On 11 Nov I also ran 24 hand-made edge-case documents and 25 API checks (parallel approvals, other organisations, bad input) against the running app; the bugs this found are listed in `FINDINGS.md`.

## What the "94%" actually measured

The handover says 94.2% field accuracy. I could not reproduce that figure on its original model (`claude-opus-5-5`; I did not have a key for it). On my model the starter gives these numbers:

| Starter run | Documents processed | Starter's own metric | Same fields, failures counted |
|---|---|---|---|
| As delivered | 0 of 24 | no number (nothing to score) | 0 / 288 = 0% |
| Reply fences stripped by the harness, examples as delivered | 24 of 24 | 286 / 288 = **99.3%** | 99.3% |
| Fences stripped, leaked examples removed | 18 of 24 | 213 / 216 = **98.6%** | 213 / 288 = **74.0%** |

What that metric is:

1. **It contains its own answers.** The prompt's three examples are dev_001, dev_002 and dev_003 together with their expected output, and the eval then scores those same three. With the examples in, they score 36/36. With the examples out, all three crash (0/36).
2. **It skips failures.** A document that raises an exception is left out of the denominator. That is the difference between 98.6% and 74.0%. Leaving the three example documents out completely, the fair number is 213 / 252 = 84.5%.
3. **It scores 12 header fields only**, compared as floats. It does not score `needs_review`, the review reasons, the approvals, the bank details or the line items.
4. **So it says nothing about the thing AP cares about.** The 99.3% run sent 7 of the 13 documents that needed review straight to "ready".

As delivered, the starter processed nothing on this model because the model wraps its JSON in a ``` fence and the starter parses the raw reply with no retry. That is a model difference, but the starter offers this provider as a supported option.

## What I chose to measure, and why

- **Missed reviews** (needed review, predicted ready). This comes first. Kavya: "I can live with extra reviews. I can't live with a missed one." A missed review can pay a fraudster; an extra one costs ₹85.
- **Unnecessary reviews.** Each one is ₹85 of someone's time, and too many teach people to ignore flags.
- **Precision and recall per review code.** A total can hide one code that never fires.
- **Exact match of the reason list, and of required approvals.** The approval count is a control on the biggest payments.
- **Field accuracy over all fields** (15 per document, including bank account and IFSC), with money compared as exact decimals, and **line items** as a whole.
- **Failed documents count as wrong** everywhere.
- **Cost per document in ₹** from recorded token counts, and **latency p50 and p95** per document, against the targets of ₹1.50 and 10 seconds.

## Starter versus mine, on the same model

Starter column: the run with reply fences stripped and the examples as delivered. This is the most favourable version of the starter that runs at all.

| Metric | Starter | Mine |
|---|---|---|
| Documents processed as delivered | 0 of 24 | 24 of 24 |
| Missed reviews (needed review, predicted ready) | **7 of 13** | **0 of 13** |
| Unnecessary reviews | 1 of 11 | 0 of 11 |
| Review reasons exactly right | 18 of 24 | 24 of 24 |
| Required approvals right | 21 of 24 | 24 of 24 |
| Field accuracy (starter's 12 fields) | 286 / 288 (99.3%) | 288 / 288 |
| Field accuracy (all 15 fields) | not measured | 360 / 360 |
| Line items right | not measured | 24 of 24 |
| LLM calls for 24 documents | 48 | 21 (3 e-invoices need none) |
| Tokens per document (input + output) | 12,818 + 758 | about one eighth of that |
| Cost per document (₹) | 0.505 (its dashboard showed 0.00) | 0.094 |
| Cost per document at the starter's default model, Opus 5.5 (₹) | about 5.85 | not applicable |
| Latency p50 and p95 (seconds) | 16.1 and 39.5 | five runs: 6.4 / 8.2, 2.6 / 12.5, 4.2 / 8.1, 2.8 / 13.8, 17.3 / 26.8 |

Notes on the table:

- The starter's latency was measured while two starter runs were going at the same time, so it is somewhat inflated. It still makes two calls per document with a prompt about eight times longer.
- With the leaked examples removed the starter gets worse on most rows: 6 documents dropped, 3 missed reviews (one of them the dropped foreign-currency invoice), 4 unnecessary reviews, reasons right on 10 of 24, approvals right on 16 of 24.
- My pipeline's per-code precision and recall are 1.00 for every code that appears in the dev set.

## Labels I disagree with

None. After reading the policy closely, I agree with all 24 dev labels as written, and `tests/test_policy_on_dev_labels.py` checks that my rules reproduce every one of them without a model.

Two observations, neither a disagreement:

- The labels follow the policy literally. Where I think the policy itself has a gap (line arithmetic, future-dated invoices, revised invoices, foreign defined by currency), the place for that is the disputed set and "Policy changes I propose" in `DECISIONS.md`, not the dev labels.
- Supplier names: my output keeps the form printed on the document (sometimes all capitals). The scorer ignores case. If it did not, a few `supplier_name` fields would count as wrong.

## Failure analysis

On the dev set my pipeline has no remaining errors, so this section lists the starter's errors by cause, and then where I expect mine to fail.

**The starter's errors, by cause**

| What happened | Documents | Cause |
|---|---|---|
| Needed review, routed ready | dev_004, 005, 007, 008, 013, 015, 019 | Design: the model's `requires_review` decides. In 5 of the 7 the model listed a reason and still said false. |
| Duplicate not caught | dev_015, dev_019 | Rules: raw text comparison of names and numbers; and the warning that did fire (dev_019) is not used. |
| Wrong approvals | dev_007, 014, 017 | Rules: `>` instead of `≥` ₹5,00,000; no rule for foreign currency or credit notes. |
| Crash on `500 kg`, `$50.00` | dev_003, 014, 016, 022 | Normalization: `parse_amount`. |
| Crash on a list of line items | dev_001, 002 | Model output shape not handled. |
| Every reply unparseable | all 24 | Extraction: no handling of fenced JSON, no retry. |
| Date 2026-08-04 for 04/08... read month-first | dev_004 (no-examples run) | Normalization: date guessing. |
| `SIS / 26-27 / 0018` | dev_015 | Normalization: spaces around separators. |

**Where I expect my pipeline to fail** (not seen on the dev set)

- **Latency.** Over five runs, p95 was 8.2, 12.5, 8.1, 13.8 and 26.8 seconds: under the target twice, over it three times. The last run (11 Nov evening, final code) was the slowest, with p50 17.3 s. I checked the cause: connecting to Google took 0.3 s, but Gemini itself took 6 to 15 seconds to answer even a five-token request and sometimes returned 503. In that evening's prediction run, 2 of 24 documents hit the 60-second cap and became `processing_error`; a rerun minutes later processed all 24. So on the free tier, latency is set by the provider, not by the pipeline. Meeting p95 under 10 s reliably would need a paid tier or a second provider to fall back to.
- **Model misreads on real OCR.** The dev OCR text is fairly clean. A misread digit in a total will usually be caught by the totals check, and a misread GSTIN by the checksum, but a misread invoice number would pass and could hide a duplicate.
- **Masking.** Any 9 to 18 digit run is hidden from the model. A long numeric invoice number would be masked and put back in code; this works in the tests but I have no real example.
- **Suspicious-content rules** are a list of patterns plus one model flag. Wording I did not think of will pass. It can only add a review, never remove one.
- **Layouts not in the dev set:** several invoices in one file, handwritten or very poor scans, languages other than English, TDS or other deductions, more than one tax rate.

## How much to trust these numbers

Not very far beyond "the design is right and the starter is unsafe".

- **24 documents.** 0 missed out of 13 is consistent with a true miss rate anywhere up to about 20%. It is evidence, not proof.
- **I tuned on this set.** My rules and prompt were written while looking at these 24 documents, so 100% here is the ceiling, not the expectation. The disputed and hidden sets are the honest test.
- **Single runs.** The starter numbers are one run each; model output varies between runs, and the 7 of 13 could be 5 or 9 on another day. The direction would not change, because the cause is in the design.
- **Latency varies** with the provider (see above: three of five runs over target). I would not claim the 10-second target is met until it is measured over a few hundred documents on different days.
- **The dev set is not the real mix.** 13 of 24 need review here against about 13% in production; production is 70% OCR. Real cost per document will differ a little with document length; at ₹0.094 there is a wide margin under ₹1.50.
- **The starter was measured on my model, not its own.** The 0 of 24 as delivered is specific to a model that fences its JSON. The missed reviews are not: they come from letting the model decide.

## My recommendation

**Yes with conditions: run every invoice through Ledgerline next month, but as a first reader, with a person still approving every payment.** Not the starter; this version.

Why yes: every payment still needs a human approval, the server now enforces who can approve what, and a document that cannot be read lands in the queue instead of disappearing. A wrong extraction costs one review (₹85). The expensive mistakes (duplicate, changed bank account, credit note) are decided by code that is tested against the policy.

Conditions:

1. **Real login** before go-live. Today identity comes from a header (see `FINDINGS.md`, "Found but not fixed").
2. **Two weeks in parallel** with the current manual process on live documents. Compare every "ready" document against what AP decided by hand.
3. **A sampled check afterwards:** each week a person re-checks a sample of "ready" documents, enough to see a 1% miss rate.
4. **Bank changes stay blocked** until the call-back is recorded by a person.
5. **Watch p95 latency and the `processing_error` count** daily in the first month.

What would change my mind:

- **To "no":** one missed duplicate, bank change or credit note in the parallel run that traces to a rule (not to a new kind of document); or more than about 2% of documents ending as `processing_error`.
- **To "yes, with fewer conditions":** 500 or more live documents with no missed review and an unnecessary-review rate under about 5%.
