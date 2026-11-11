# My first hour

_Written after the work, not in the first hour; it records what I understood at the start._

## What I think is going on

On 9 November, between 11:18 and 11:27 IST, I shared the challenge link and started by understanding what needed to be built. Going through the repository with the help of AI, I understood that Ledgerline is already a working invoice application about to go live. My task was not to build something new, but to fix the issues that could make vendor payments unsafe, and document the changes.

## The risks I suspect, most serious first

The AI's review of the code showed these issues:

1. **Invoice approval:** the LLM decided whether an invoice needed review, while the validation checks only produced warnings.
2. **Duplicate payments:** approving twice could create two payments, and duplicates and credit notes could be approved.
3. **Sensitive data:** vendor bank account numbers were sent to the LLM provider.
4. **Incorrect validations:** GSTIN checksum, state codes, duplicate detection, totals, and missing policy rules.
5. **Unreliable metrics:** the 94% accuracy had leaked examples and skipped failed documents, and the cost dashboard was 1,000 times too low.

## My plan for the time I have

Fix what can directly affect payments and data first: approvals and duplicate payments, then sensitive data and validation logic, each with a regression test. Then compare against the original app and write the documents. Because time was limited, I used AI for code exploration, implementation and testing, and checked the results by asking questions and asking for more tests.

## What I would ask Meridian

1. How do approvers log in today?
2. Should invoices that pass every check be paid automatically, or should every payment need an approval?
3. Where can we get trusted vendor phone numbers to verify bank-account changes?
