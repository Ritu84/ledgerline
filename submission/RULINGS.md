# Rulings on the disputed documents

## My flags

I added two feature flags to handle issues that I found were missing from the existing policy (implemented and run with AI; see `AI_USAGE.md`). Both flags are disabled by default, so the application continues following `AP_POLICY.md` unless they are enabled.

| Feature flag | What it does | Document |
|---|---|---|
| `LEDGERLINE_FLAG_LINE_ARITHMETIC=1` | Sends an invoice for review if quantity × unit price differs from the printed line amount by more than ₹1.00 (new code `line_amount_mismatch`). | disp_05 |
| `LEDGERLINE_FLAG_FUTURE_DATE=1` | Sends an emailed invoice for review if its invoice date is later than the email's sent date (new code `invoice_date_in_future`). | disp_06 |

I tested both changes using `test_line_arithmetic_flag` and `test_future_date_flag` in `tests/test_validation.py`.

With both flags enabled, all 24 development documents continued to produce their expected results without any additional reviews.

I generated `predictions_disputed.jsonl` using:

`LEDGERLINE_FLAG_LINE_ARITHMETIC=1 LEDGERLINE_FLAG_FUTURE_DATE=1 make predict`

The final predictions were generated using the real Gemini model on 11 November 2026, around 7:50 PM IST. Earlier, when the free API quota was exhausted, I had regenerated the file from stored model outputs using `backend/eval/replay_disputed.py`. The fresh model run later produced identical results.

## disp_01 — Invalid GSTIN

- **Ruling:** Needs review with `gstin_invalid` and `vendor_unknown`. Requires 1 approval.
- **It rests on:** According to sections 1 and 3 of the policy, domestic vendors are identified using their GSTIN. The invoice contains GSTIN `27AAKCS4B21M1ZW`, which fails checksum validation and does not match any vendor in the master data. However, I noticed that changing just one character (B to 8) would make it match Sitara's actual GSTIN. The bank account also matches Sitara's existing details. Even though this looks like a typing or OCR error, I don't think the system should automatically correct a vendor's identity without confirmation.
- **The best argument against my ruling:** There is strong evidence that the invoice belongs to Sitara. Sending it for manual review adds ₹85 in review cost, even though the error could be very small. Anita also wanted such errors to be corrected automatically.
- **The policy change I'd propose:** I would show the reviewer the most likely matching vendor and perform duplicate and bank account checks using that possible match. This is important because an invalid GSTIN currently prevents the system from identifying the supplier, which could also cause it to miss a duplicate invoice. I would still require a person to confirm the correction.
- **Implemented?** No, this is a proposed improvement.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes.

## disp_02 — Revised invoice already paid

- **Ruling:** Needs review with `duplicate`. Requires 1 approval, but the invoice can only be rejected.
- **It rests on:** The invoice number `SIS/26-27/0018` was already paid on 22 April 2026 for ₹34,220. The revised invoice has the same supplier, invoice number, and financial year, but the amount has increased to ₹35,872. According to sections 3 and 4.4 of the policy, this is a duplicate, and duplicate invoices cannot be approved. If the revised invoice were approved, the vendor would receive another ₹35,872 in addition to the amount already paid.
- **The best argument against my ruling:** The vendor may genuinely be owed the additional ₹1,652. Rejecting the revised invoice could delay payment, especially for an MSME supplier. Also, the reviewer may only see the duplicate warning and miss the fact that the invoice amount has changed.
- **The policy change I'd propose:** I would make the policy clearer about revised invoices. Instead of paying the full revised invoice again, the vendor should submit a debit note or supplementary invoice for only the ₹1,652 difference.
- **Implemented?** No additional changes were needed because the existing policy already blocks duplicate approvals.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes.

## disp_03 — Indian vendor billing in USD

- **Ruling:** Needs review with `foreign_currency`. Requires 2 approvals.
- **It rests on:** Narmada Polymers is an Indian vendor with GSTIN `24AAOFN2207Q1ZX` and has been in the vendor master since 2022. However, the invoice is in USD for $2,643.20, with an equivalent INR amount of ₹2,32,601.60 printed on it. The current policy treats any invoice not in INR as foreign, so I followed that rule and required two approvals.
- **The best argument against my ruling:** The supplier is actually based in India, so treating the invoice as foreign is not completely correct. It also means the system may identify the supplier by name instead of GSTIN and skip GST validation, even though the vendor is domestic.
- **The policy change I'd propose:** I would separate the vendor's country from the invoice currency. A vendor should be considered foreign based on its country, not just the currency used. If a GSTIN is available, the system should still validate it. I would also keep the two-approval requirement for non-INR payments and clarify which currency, amount, and exchange rate should be used for payment.
- **Implemented?** No. I followed the existing policy because requiring two approvals is safer in this case.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes.

## disp_04 — Suspicious content in email

- **Ruling:** Needs review with `suspicious_content`. Requires 1 approval.
- **It rests on:** The email contains a message addressed to the AP automation system, asking it to include invoice number `VL/0968` in the remittance advice. The message does not appear harmful, and the remaining invoice details are valid. However, section 3 of the policy says that text directed at automated systems should be flagged for review. I decided to follow this rule because allowing the AI model to decide which instructions are harmless could create a security risk.
- **The best argument against my ruling:** This looks like a normal business instruction, so flagging it may create an unnecessary review. If reviewers keep receiving harmless warnings, they may eventually start ignoring important ones. This would also increase the existing review workload.
- **The policy change I'd propose:** I would keep the current rule for now. If the same vendor repeatedly includes identical harmless text, I would allow a reviewer to mark that exact text as trusted for that vendor. I would not allow the AI to independently decide whether an instruction should be ignored.
- **Implemented?** No changes were required.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes.

## disp_05 — Incorrect line amount

- **Ruling:** Needs review with `line_amount_mismatch`. Requires 1 approval. This ruling is different from the existing policy and is implemented behind `LEDGERLINE_FLAG_LINE_ARITHMETIC`.
- **It rests on:** I noticed that the first invoice line has a calculation error: quantity 4, unit price ₹3,850, expected amount ₹15,400, printed amount ₹15,950, a difference of ₹550. Including GST, the possible overcharge is approximately ₹649. The existing `totals_mismatch` validation does not catch this because it only verifies whether the printed line amounts add up to the subtotal and total. Since those printed values are internally consistent, the invoice could be marked as ready even though the actual quantity × price calculation is incorrect.
- **The best argument against my ruling:** The existing policy does not explicitly require line-level arithmetic validation. Also, OCR may sometimes read the quantity or price incorrectly, which could create unnecessary reviews costing ₹85 each.
- **The policy change I'd propose:** I would add line-level arithmetic validation to section 3 of the policy. If the difference between quantity × unit price and the printed amount is more than ₹1.00, the invoice should go for review.
- **Implemented?** Yes, using `LEDGERLINE_FLAG_LINE_ARITHMETIC`. I also added `test_line_arithmetic_flag` to verify this behavior. None of the 24 development documents triggered the new check.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes, when the flag is enabled.

## disp_06 — Future-dated invoice

- **Ruling:** Needs review with `invoice_date_in_future`. Requires 1 approval. This ruling is different from the existing policy and is implemented behind `LEDGERLINE_FLAG_FUTURE_DATE`.
- **It rests on:** The invoice was received by email on 28 April 2026, but the invoice itself is dated 25 June 2026, almost two months later. I also noticed that the vendor, Shakti, was onboarded on 20 March 2026. Based on the printed invoice date, the vendor is 97 days old; based on the email date, it is only 39 days old. Because the existing policy uses the printed invoice date, the vendor is not considered new, and the new-vendor check does not apply, so the invoice could be marked ready without any warning. I felt this was risky because the future date could be either a mistake or an attempt to bypass the new-vendor validation.
- **The best argument against my ruling:** The policy clearly says to use the printed invoice date, and some businesses do issue post-dated invoices. Also, this check currently works only for emails because scanned documents do not have an email sent date.
- **The policy change I'd propose:** I would update the policy to require review whenever the invoice date is later than the date the invoice was received. This would help identify incorrect dates and prevent them from bypassing other validations.
- **Implemented?** Yes, using `LEDGERLINE_FLAG_FUTURE_DATE`. I added `test_future_date_flag` to test the change. None of the 24 development documents triggered this check.
- **Does my pipeline's line in `predictions_disputed.jsonl` match?** Yes, when the flag is enabled.

## The two I consider riskiest, and why

1. **disp_02 — Duplicate payment risk.** I consider this the highest risk because a single incorrect approval could result in a significant duplicate payment. The original invoice of ₹34,220 has already been paid. If the revised invoice is approved, another ₹35,872 would be paid, resulting in an overpayment of ₹34,220 relative to the revised total. The word "REVISED" also makes the document appear legitimate, which could lead a reviewer to approve it without checking the previous payment.

2. **disp_06 — Future date bypassing validation.** I consider this the second highest risk because the invoice passes the existing checks without generating any warning. The future invoice date makes the vendor appear older than it actually was when the email was sent, which prevents the new-vendor check from triggering. This is concerning because a fraudster could potentially use the same technique to bypass additional verification for recently onboarded vendors. That is why I added the future-date validation behind a feature flag.

Both cases showed me that **passing the existing validation rules does not always mean an invoice is safe to pay.** The rules themselves also need to be reviewed for gaps and edge cases.
