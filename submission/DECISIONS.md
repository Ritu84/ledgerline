# Decisions

_The Architecture, Part 4 and policy-change sections were drafted with AI (Claude Code); see `AI_USAGE.md`. The replies to stakeholders are my own words._

## Architecture

**One rule: the model reads, code decides.**

What happens to a document, in order (`backend/ledgerline/pipeline.py`):

1. **E-invoice JSON is parsed in code.** No model call (`extraction.parse_einvoice`). That is about 10% of volume at zero cost.
2. **Bank account numbers are masked** before anything leaves (`extraction.mask_account_numbers`): every 9 to 18 digit run becomes `[ACCOUNT_1 ending 1234]`. The real value is put back in code after the reply.
3. **One model call extracts the fields** as text, exactly as printed. The reply must be a JSON object with the expected keys; a reply that cannot be parsed is retried once.
4. **Code normalizes** (`pipeline.normalize`, `parsing.py`): money to `Decimal`, dates day-first (month-first only for vendors in the US), units and HSN codes stripped. A value that cannot be parsed is left empty and reported; it is never guessed.
5. **Code runs every policy check** (`validation.run_checks`) against the vendor master and the paid-invoice history, and works out the required approvals.
6. **The result is stored with an audit entry.** Any failure on the way is stored as `processing_error` and goes to the review queue. No document is dropped.

**What the model does:** it copies fields from the document, and it sets one true/false flag, `addressed_to_software`. That flag can only add a review. Nothing in the model's reply can remove a review, choose a reason, set the approvals or approve anything.

**What code does:** everything that is a decision. GSTIN checksum, vendor matching by GSTIN, tax type by state, totals within ₹1.00, duplicates (normalized number, same supplier, same financial year, same organisation), bank details against the master, new vendor by invoice date, foreign currency, credit notes, suspicious content, approvals.

**Why:** the policy is a set of exact rules. Code applies exact rules the same way every time, can be tested against every dev label without a model (`tests/test_policy_on_dev_labels.py`), and cannot be talked out of a rule by text in an invoice. In my run of the starter, where the model decided, 7 of 13 documents that needed review were routed "ready" (`EVAL_REPORT.md`).

**Prompts and outputs:**

- The prompt holds only the instructions and the masked document. No vendor master, no policy text, no examples from the dev set.
- The document sits between `<document>` tags, and the system prompt says that everything inside is data to copy from, not instructions.
- The model is asked for strings as printed (`"1,41,600.00"`, `"05/04/2026"`), not for numbers or ISO dates. Parsing is done in code, where it can be tested.
- Output is one JSON object. Code fences around it are accepted; anything else is retried once, then becomes `processing_error`.

**Hostile documents:**

- Text addressed to software, and HTML or script markup, are flagged by code (`validation.check_suspicious_content`) as `suspicious_content`.
- If the document does talk the model into something, the worst outcome is a wrong field value. The checks then run on that value, and a person still approves.
- The UI shows all supplier text as plain text. The script in dev_013 is displayed, not run.
- Uploads are limited to 1 MB and must be text.

**What leaves Meridian's systems:** only the masked text of the one document being processed, to the LLM provider. Supplier name, GSTIN, IFSC, amounts and line items are in it. Bank account numbers are not. The vendor master, the paid history and the policy never leave. E-invoices do not leave at all.

**The API** (`backend/ledgerline/api.py`): every read and write is checked against the caller's organisation. Approve and reject run in one `BEGIN IMMEDIATE` transaction: one approval per person, two different people where the policy needs two, a note where the document was flagged, duplicates and credit notes cannot be approved, one payment per invoice (unique index), and every decision is written to the audit log.

**What this does not have:** real login (identity comes from a header), a job queue, automatic re-processing after an outage, and PO matching. These are listed in `FINDINGS.md` under "Found but not fixed".

## Part 4: what I went deep on, and why

**I chose A, evidence-linked review. One part of it is not built: per-field character offsets.**

Why A over B and C:

- The money is lost at the approve button. The ₹3.8 lakh bank-change fraud and Kavya's double payment were both failures of the review and approval step, not of extraction or cost.
- B (cheapest model, escalation, outage handling) matters, but cost stopped being the problem once the prompt was fixed: ₹0.094 per document against a ₹1.50 target. I would do B's outage handling next.
- About 390 documents a month need a person. If that person cannot see why a document was flagged, they re-key it, and the tool saves nothing.

What is built:

- **A queue** of documents that need attention, separate from those ready for approval.
- **Each review reason in plain language**, with the evidence under "What the checks found" (for example the bank account on the invoice against the one on file, or the earlier invoice it duplicates).
- **The original document** next to the extracted fields.
- **Approve and reject enforced on the server**, correct under double-clicks and retries: approving twice creates one payment; the same person cannot give both approvals; another organisation gets 404; duplicates and credit notes cannot be approved; a flagged document needs a note. Tests are in `backend/tests/test_api.py`.
- **An audit log** per document: who did what, and when.

What is not built:

- **Exact source of each field (character offsets and highlight).** The reviewer sees the document and the fields side by side but has to find the text by eye. This is the main gap against option A as written. My plan for it: find each extracted value in the original text in code (not by asking the model for offsets), highlight only when it is found exactly once, and say "not located" otherwise.
- **Speed for 150 invoices a day:** there are no keyboard shortcuts and no "next document" flow.
- **Automated frontend tests.** The UI was checked by hand and with a scripted browser run.

## Replies to stakeholders

### Anita Rao, CFO

For clean invoices below ₹10,000, all validation checks are completed before the invoice is marked "ready for approval"; the reviewer only needs to approve it. I have not removed the approval step because the current policy requires approval for every payment, and that decision should come from Sunil.

I don't think allowing AI to correct GSTINs automatically is safe. GSTIN identifies the vendor, and even a small incorrect change could identify the wrong supplier. Instead, I would show the reviewer a possible matching vendor when the GSTIN differs by one character, the corrected GSTIN is valid, and the bank details match.

During testing, when the model decided whether review was needed, it marked 7 out of 13 risky invoices as ready. This is why final decisions are now made in code.

### Farhan Sheikh, Head of AP

Whenever an invoice contains changed bank details, it is now sent for review, cannot be approved without a written note, and the system records who made the decision. The callback verification process is not implemented yet; I agree we should first define how it will work.

I have fixed the duplicate-payment issue: even if approval is sent repeatedly or by several people at once, only one payment is created.

Reviewers now see the reason for review in simple language, with supporting evidence and the original document. Highlighting the exact location of each extracted field is still pending, and I would prioritize it next.

The cheaper model extracted all 360 tested fields correctly. The problem was letting AI make the final decisions, which code now handles.

### Deepak Menon, CTO

The $165 bill was correct. The dashboard treated prices per thousand tokens as prices per million, so it showed costs 1,000 times too low, and unknown models counted as zero.

Previously, a long prompt was sent twice per document, around ₹5.85 per document on Opus. Now there is one shorter call with Gemini Flash-Lite, around ₹0.094 per document, and e-invoices need no model call.

p95 latency varied between 8.1 and 26.8 seconds across five runs, mainly from Gemini's free-tier response times, so I cannot guarantee the 10-second target yet. A hard 60-second timeout stops calls running indefinitely. I kept SQLite and a single provider.

Fine-tuning isn't required now: the model extracted all 360 fields correctly, and the failures were decisions, now handled by tested code.

### Priya Natarajan, Data Protection Officer

Yes, there was a serious privacy issue. The application was sending the complete document twice, along with the entire vendor master containing bank account numbers and IFSC codes.

Now only the text of the document being processed is sent. Before sending, the system masks 9-to-18-digit numbers, including bank account numbers, with placeholders such as `[ACCOUNT_1 ending 5678]`, and the actual values are restored within our application. The vendor master, payment history and policy rules are no longer sent, and e-invoices are processed locally.

Supplier names, GSTINs, IFSC codes, amounts, line items and addresses are still sent because extraction needs them. If any of these must also be restricted, I can extend the masking once you confirm the requirement.

### Sunil Joshi, Finance Controller

I have kept the existing AP policy unchanged. I found two cases the policy seems to miss: quantity × unit price not matching the printed line amount, and an invoice dated after the email that contains it. Both checks are behind feature flags that are disabled by default, so nothing changes unless you approve them.

On review volume: across 24 labelled documents, the application sent all 13 that required review to the queue, with no additional reviews. Documents that cannot be read are no longer skipped; they go to review so they don't disappear unnoticed.

I agree we should not add the vendor phone field until there is a proper bank-change callback workflow. I have proposed that workflow rather than implementing an incomplete process.

### Ravi Kulkarni, contractor

I understand why the rules are in the prompt: Finance needs to change them quickly. But in testing, the model marked 7 of 13 invoices that needed review as ready, including changed bank accounts and duplicates. In 5 cases it identified the correct issue but still decided review wasn't required. Even when the model understands the policy, it does not always apply it consistently.

So I separated extraction from validation. The model still reads invoices across different formats and layouts, where it performs well; the policy checks and review decisions are now deterministic code with regression tests.

As a next step, I would move configurable values, such as the ₹5 lakh threshold and the 90-day vendor rule, into a settings file Finance can update without a developer.

## Policy changes I propose

_These follow from the disputed documents and `RULINGS.md`. None is applied by default: the pipeline follows the policy as written. Proposals 3 and 4 are built behind flags (`LEDGERLINE_FLAG_LINE_ARITHMETIC`, `LEDGERLINE_FLAG_FUTURE_DATE`) so Finance can switch them on once agreed._

1. **Revised and supplementary invoices (disp_02).**
   - Change: say what happens when a supplier re-issues an invoice under a number that is already paid. Proposal: it stays a duplicate and cannot be approved; the supplier sends a separate debit note or supplementary invoice for the difference only.
   - Why: the "revised" Sitara invoice is for ₹35,872 and ₹34,220 is already paid. Only ₹1,652 is owed.
   - Cost or risk: the supplier waits for the difference until the new document arrives; for an MSME vendor the 45-day clock matters.

2. **Define "foreign" by the vendor, not the currency (disp_03).**
   - Change: a supplier with an Indian GSTIN is domestic even when it bills in USD: identify it by GSTIN and run the tax check. Keep two approvals for any non-INR payment.
   - Why: today an Indian vendor billing in dollars is identified by name only, which is the weaker check.
   - Cost or risk: needs a rule for which amount is paid (USD or the INR equivalent) and at what rate.

3. **Check quantity × rate against each line amount (disp_05).**
   - Change: a new review reason when a line does not multiply out, with the same ₹1.00 tolerance.
   - Why: the policy only adds up the printed line amounts, so a line overcharged by ₹550 passes as "ready".
   - Cost or risk: more reviews at ₹85 each, some caused by misread quantities on scans rather than by the supplier.

4. **Invoice dated after it was received (disp_06).**
   - Change: review any invoice whose printed date is later than the date it arrived.
   - Why: the new-vendor rule counts 90 days from the printed date, so a future date switches that check off (Shakti Castings: 39 days since onboarding by the email date, 97 by the printed date).
   - Cost or risk: only possible where an arrival date exists (emails today); genuine post-dated invoices would be reviewed.

5. **A GSTIN that is one misread character from a known vendor (disp_01).**
   - Change: keep the review, but let the reviewer see the likely vendor, and run the duplicate and bank checks against that vendor.
   - Why: with a garbled GSTIN the duplicate check has no supplier to match on, so a real duplicate could pass as merely "unknown vendor".
   - Cost or risk: a wrong suggestion could mislead a reviewer; it must never be applied without a person.

6. **A call-back workflow for bank changes (Farhan's request, Sunil's condition).**
   - Change: when `bank_details_changed` fires, the reviewer phones the vendor on a number already on file, from before the change request, never on a number in the same email. They record who they spoke to and when. Approval stays blocked until that record exists. Only then add a phone field to the vendor master, filled from existing contracts or purchase orders.
   - Why: Meridian lost ₹3.8 lakh to one fake bank-change email. Today a bank change only needs a note, and a note can say anything.
   - Cost or risk: a few minutes per bank change (two in the 24 dev documents), plus a one-off job to collect phone numbers. Vendors without a number on file wait until one is confirmed.
