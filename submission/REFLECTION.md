# Reflection

## Three things I didn't know when I started, and how I learned each one

1. **How an invoice becomes a payment.** Initially, I wasn't completely clear about the full process of how an invoice gets converted into a payment. During the session, I asked AI to explain the workflow in simple terms. I understood that an invoice first goes through validation checks, then approval, and finally a payment instruction is created. I also learned that credit notes are different from regular invoices because they reduce the amount owed to a vendor rather than creating a new payment.

2. **What Ledgerline uses to validate invoices.** At first, I wasn't sure what data Ledgerline was using to validate invoices. I explored this by asking AI about the different validation checks and the data required for each one. I learned that Ledgerline mainly uses the vendor master to verify supplier details and bank accounts, payment history to identify duplicate invoices, and Meridian's GSTIN to determine the correct GST treatment. I also asked what logic was written for each check, to understand how they were implemented and where they could fail.

3. **What p50 and p95 mean.** I wasn't familiar with p50 and p95 when I first saw them in the evaluation report. I asked AI to explain these metrics and understood that p50 represents the median response time, while p95 represents the time within which 95% of requests are completed. I also learned why p95 matters when measuring application performance. In our evaluation runs, p95 was below the 10-second target in some cases but exceeded it in others, which showed that the performance was not consistently meeting the requirement.

## The decision I'm least sure of

The decision I'm least confident about is letting AI handle most of the implementation end to end and reviewing everything only at the end.

I made this decision mainly because of the limited time available and wanted to complete as much of the challenge as possible. This approach helped me implement the fixes and tests quickly, but I also realized that relying too much on AI without checking its work regularly can create problems.

For example, the starter application was tested with the actual model only near the end. AI initially reported that there were no issues, but later edge-case testing revealed eleven bugs. One model call also got stuck for around nine hours.

I also let AI write the first drafts of the parts that were supposed to reflect my own understanding and decisions: the rulings, the first-hour note, this reflection and the stakeholder replies. I have rewritten them in my own words, but I should have written them myself from the start.

Looking back, I think I should have reviewed the implementation after each major change instead of waiting until the end.

The biggest concern for me is whether I can confidently explain every important code change and decision without depending on AI. If I cannot explain why something was implemented in a particular way, that would mean I relied on AI more than I should have.

## With one more week

1. **Write my own notes from the start:** write the rulings, first-hour note, reflection and replies myself from the beginning, so they clearly represent my understanding and decisions.
2. **Improve field traceability:** I would add the exact source location and character offsets for every extracted field in the review screen. This would help Farhan's reviewers verify the information without having to search through the entire invoice manually.
3. **Implement proper authentication:** Currently, user identity is taken from a request header. I would replace this with a proper login and authentication system because invoice approval permissions depend on knowing who the user actually is.
4. **Add bank-change verification records:** I would implement a proper callback verification process for vendor bank account changes and store the verification details. This is especially important because a similar issue had already resulted in a loss of ₹3.8 lakh.
5. **Run more extensive evaluations:** I would test the system using a few hundred real invoices over multiple days to measure accuracy, missed issues, and response times. The current evaluation of 24 documents across five runs is too small to confidently say that the system will consistently meet its targets.

Overall, this challenge helped me understand that using AI can speed up development significantly, but it is still important to validate its output, understand the decisions being made, and take responsibility for the final implementation.
