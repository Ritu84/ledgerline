# How I worked with AI

_This file was drafted by the AI tool from the session log, at my request. Facts are taken from the log; `L123` means line 123 of the log, shown in the exported transcripts in `ai-logs/`._

## Tools and models

- **Claude Code (desktop app).** Model: Claude Fable 5 (`claude-fable-5-2`) until 10 Nov 22:19 IST, then Claude Opus 5.5 (`claude-opus-5-5`) after I switched models (L2267). It did almost all of the hands-on work: reading the starter, writing the code changes and the tests, running the evals, driving a browser to check the UI, and drafting `FINDINGS.md`, `EVAL_REPORT.md`, this file, and the Architecture, Part 4 and policy-change sections of `DECISIONS.md`.
- **Gemini `gemini-3.5-flash-lite`** (Google, OpenAI-compatible endpoint) is the model inside the pipeline that reads the documents.
- **The four parts meant to be in my own words** (`FIRST_HOUR.md`, `RULINGS.md`, `REFLECTION.md`, and the stakeholder replies): I wrote these myself after reading AI drafts; AI only edited them for length and headings.

## How I set up context

- I did not write a context file (no `CLAUDE.md` in this repository). The AI was pointed at the repository and read `README.md`, `docs/AP_POLICY.md`, `docs/PRODUCT_BRIEF.md`, `docs/STAKEHOLDER_THREAD.md`, `docs/HANDOVER.md`, `docs/OUTPUT_CONTRACT.md` and the code itself.
- No planning mode. I gave a standing instruction to work end to end, make its own decisions, and test everything itself, and said I would check at the end.
- The API key was kept in a git-ignored `.env`; the AI was told not to print it or put it in any file or command line.
- How I started: I pasted the challenge's GitHub link and asked what needs to be built (L2), then asked for an exact explanation and for more detail (L53, L95), and later what already exists in the codebase (L214). The AI tried to create the GitHub repository and was blocked by the app's permission check, so I ran that command myself (L130–L138).

## My workflow

- **Split:** the AI read, built, tested and measured. I asked questions to understand the domain (how invoices and payments work, what Ledgerline checks against), set the direction, and made the calls that the challenge says are mine.
- **How the output was checked:**
  - Unit tests (`make test`), including one that checks the policy rules against all 24 dev labels with no model.
  - The eval on the real model (`make eval`).
  - The untouched starter run on the same model, to have a real comparison instead of claims from reading code (`backend/eval/starter_baseline/`).
  - A scripted browser run through the UI (upload, queue, approve, reject, double approve).
- **What I checked myself:** mostly by asking. I asked again and again whether everything had been tested (L1033, L1541, L2294, L3179), asked for explanations of the domain and of each check (L1838, L2250, L2269), and pushed for edge-case testing (L2522), which is what exposed most of the bugs. The log shows no code that I read or ran by hand apart from creating the repository.

## Where the AI was wrong

1. **Its end-to-end check reported failures that were not failures.** It compared supplier names exactly against the answer key, so names printed in capitals (for example `SITARA INDUSTRIAL SUPPLIES PVT. LTD.`) were reported as failures. It then checked that the official scorer ignores letter case, so the score was unaffected.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, L1604–L1745.

2. **It fixed the starter and wrote up its faults before ever running the starter on a real model.** For most of the work, the findings came from reading code. When the starter was finally run on Gemini, the first result was 0 of 24 documents processed, for a reason that was not in the list at all (the model wraps JSON in a code fence and the starter cannot parse it). The measured numbers in `FINDINGS.md` and `EVAL_REPORT.md` exist only because that run was done late. The order should have been: run the starter first.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, first starter run L1984; findings written from it L2124.

3. **It reported latency from a single run as if it settled the question.** The first eval gave p95 = 8.2 s, under the 10 s target (L1550), and the summaries carried that figure forward without saying one run proves nothing. Later runs gave 12.5 s and 13.8 s. `EVAL_REPORT.md` now reports all four runs and does not claim the target.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, L1550 and L1617; corrected at L2184 and L2746.

4. **It described Part 4 option A as done when one required part was missing.** Option A asks for the exact source of every field (character offsets). The AI built the queue, the reasons and the server-side approval rules, and only noticed at write-up time that offsets were never built. `DECISIONS.md` says so plainly.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, L2199.

5. **It said "no issues" after a happy-path test.** After running the dev documents and the main approval rules through the app, it reported that everything worked. When I asked it to test every edge case, it found nine more bugs in its own code (see `FINDINGS.md`, "Found in my own pipeline during edge-case testing"), including an all-digit invoice number stored as a masked placeholder and the same person counting as two approvers when typed in capitals.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, "no issues" at L2518; edge-case testing from L2522.

6. **It set a "120 second timeout" and assumed that capped each call.** It does not: it limits each step separately. When the provider misbehaved, one eval run hung for 9 hours before anyone noticed. While investigating, it first blamed the provider, then found the real cause on the machine (IPv6 tried first and never connecting). That run also used up the day's free-tier quota and left `predictions_disputed.jsonl` with three `processing_error` lines. Its first fix forced IPv4, which would have broken the app on an IPv6-only network; that was removed. With no quota left, `predictions_disputed.jsonl` was first rebuilt from the real Gemini results stored during the live-app test at 00:13 IST on 11 Nov; after the quota reset, a fresh `make predict` produced an identical file.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, L2881–L3130.

7. **A waiting loop that could never end.** To wait for a background run it used `pgrep -f <script name>`, which matched its own shell, so it waited on itself until the loop was killed by hand. No effect on results; it cost time.
   - Transcript: `ai-logs/01_main_session_2026-11-09_to_11.md`, L2035–L2065.

**The ones I went along with at first:** all of them. I did not catch any of these mistakes myself; each was found by the AI later, usually after I asked it to test more. The clearest case is number 5: when it said everything worked (L2518), I accepted that, and only my next request to test every edge case (L2522) uncovered the bugs.

Also to be honest about: the regression tests were written together with the fixes. Each was not separately run against the untouched starter to see it fail first.

## What I deliberately didn't delegate, and why

Less than I should have, and I say so plainly. The AI wrote the code, the tests and the technical documents. What stayed with me: the decision to take this approach, the requests to test further, creating the repository, keeping my API key out of the repository, and the four parts meant to be mine (see "Tools and models").

## Time

About 4½ hours of active session time, from 9 Nov 11:18 IST to 11 Nov 2026, counting any gap over 15 minutes as a break (estimated from the log timestamps): about 45 minutes on 9 Nov understanding the task, about 2½ hours on 10 Nov building, testing and writing, and about 1¼ hours on 11 Nov on edge cases, the provider outage and the documents. Time spent reading outside the session is not counted.

## Transcripts

There was one Claude Code session for the whole project (a fork I started on 10 Nov at L1827 was never used).

- `ai-logs/00_first_hour_2026-11-09.md`: the first stretch, 9 Nov 11:18–11:27 IST (L0–L94).
- `ai-logs/01_main_session_2026-11-09_to_11.md`: everything after it.
- `ai-logs/full_session_redacted.jsonl.gz`: the complete raw log.

Only the Gemini API key is redacted, shown as `[REDACTED_GEMINI_API_KEY]`; I had pasted it into the chat once (L1111). In the two readable files, tool output longer than 4,000 characters is shortened, and the raw log keeps it in full. Nothing else is cut or edited. The export was taken on 11 Nov 2026 at 19:06 IST, so the last few minutes of the session are not in it.
- `FIRST_HOUR.md` was not written in the first hour, before the AI work started; it says so at the top.
