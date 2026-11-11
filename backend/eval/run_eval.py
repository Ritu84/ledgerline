"""Evaluate the pipeline on the labelled dev set.  Usage (from backend/):

    python eval/run_eval.py                 # full pipeline, uses the configured LLM provider
    python eval/run_eval.py --policy-only   # no LLM: feed the labelled fields to the policy checks

Reports what matters for trust, not only field accuracy: whether each document was routed correctly
(per review code precision and recall), whether the approval count is right, and what it cost.
A document that fails is counted as wrong, never skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerline import db  # noqa: E402
from ledgerline.config import get_settings  # noqa: E402
from ledgerline.pipeline import _persist, normalize, process_document  # noqa: E402
from ledgerline.reference import load_reference  # noqa: E402
from ledgerline.validation import required_approvals, run_checks  # noqa: E402

TEXT_FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
               "bank_account", "ifsc", "po_number"]
MONEY_FIELDS = ["subtotal", "cgst", "sgst", "igst", "round_off", "total"]


def _norm(value) -> str:
    return "" if value is None else " ".join(str(value).split()).lower()


def load_rows() -> list[dict]:
    settings = get_settings()
    with open(settings.data_dir / "ground_truth" / "dev.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return sorted(rows, key=lambda r: r["document_id"])


def predict_policy_only(conn, ref, row: dict, raw_text: str) -> dict:
    """Routing from the labelled fields, so the policy code is tested apart from extraction."""
    inv, _ = normalize(row["expected"], None)
    reasons = run_checks(conn, ref, inv, raw_text)
    return _persist(conn, "meridian", row["document_id"], row["filename"], raw_text, inv, [], reasons,
                    required_approvals(inv), [])


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def evaluate(policy_only: bool = False, verbose: bool = True) -> dict:
    settings = get_settings()
    ref = load_reference()
    conn = db.connect(str(Path(tempfile.mkdtemp()) / "eval.db"))
    rows = load_rows()

    field_hits, field_total = Counter(), Counter()
    tp, fp, fn = Counter(), Counter(), Counter()
    routing_exact = review_flag_right = approvals_right = line_items_right = 0
    missed_review: list[str] = []
    wrong: list[str] = []
    costs, latencies, calls = [], [], 0

    for row in rows:
        expected = row["expected"]
        raw_text = (settings.data_dir / "invoices" / "dev" / row["filename"]).read_text(encoding="utf-8")
        if policy_only:
            got = predict_policy_only(conn, ref, row, raw_text)
        else:
            got = process_document(conn, ref, raw_text, row["document_id"], filename=row["filename"])

        for field in TEXT_FIELDS + MONEY_FIELDS:
            field_total[field] += 1
            field_hits[field] += _norm(got.get(field)) == _norm(expected.get(field))
        line_items_right += [
            {k: _norm(v) for k, v in item.items()} for item in got["line_items"]
        ] == [{k: _norm(v) for k, v in item.items()} for item in expected.get("line_items", [])]

        want, have = set(expected["review_reasons"]), set(got["review_reasons"])
        for code in want & have:
            tp[code] += 1
        for code in have - want:
            fp[code] += 1
        for code in want - have:
            fn[code] += 1
        routing_exact += want == have
        review_flag_right += got["needs_review"] == expected["needs_review"]
        approvals_right += got["required_approvals"] == expected["required_approvals"]
        if expected["needs_review"] and not got["needs_review"]:
            missed_review.append(row["document_id"])
        if want != have or got["required_approvals"] != expected["required_approvals"]:
            wrong.append(f"{row['document_id']}: expected {sorted(want)} x{expected['required_approvals']}, "
                         f"got {sorted(have)} x{got['required_approvals']}")

        costs.append(got["usage"]["cost_inr"])
        calls += got["usage"]["llm_calls"]
        if got["usage"]["llm_calls"]:
            latencies.append(got["usage"]["latency_ms"])

    n = len(rows)
    result = {
        "documents": n,
        "field_accuracy": sum(field_hits.values()) / max(1, sum(field_total.values())),
        "line_items_accuracy": line_items_right / n,
        "needs_review_accuracy": review_flag_right / n,
        "routing_exact_match": routing_exact / n,
        "required_approvals_accuracy": approvals_right / n,
        "missed_review": missed_review,
        "wrong": wrong,
        "cost_inr_total": sum(costs),
        "cost_inr_per_document": sum(costs) / n,
        "llm_calls": calls,
        "latency_ms_p50": percentile(latencies, 50),
        "latency_ms_p95": percentile(latencies, 95),
    }
    if not verbose:
        return result

    mode = "policy only (labelled fields, no LLM)" if policy_only else f"{settings.llm_provider} / {settings.llm_model}"
    print(f"Mode: {mode}\nDocuments: {n}\n")
    print(f"Field accuracy:       {sum(field_hits.values())}/{sum(field_total.values())} = {result['field_accuracy']:.1%}")
    for field in TEXT_FIELDS + MONEY_FIELDS:
        if field_hits[field] != field_total[field]:
            print(f"  {field:<16}{field_hits[field]}/{field_total[field]}")
    print(f"Line items exact:     {line_items_right}/{n}")
    print(f"needs_review correct: {review_flag_right}/{n}")
    print(f"Reasons exact match:  {routing_exact}/{n}")
    print(f"Approvals correct:    {approvals_right}/{n}")
    print(f"Missed reviews (should have been flagged, were not): {missed_review or 'none'}\n")
    print(f"{'review code':<24}{'precision':>10}{'recall':>8}{'tp':>4}{'fp':>4}{'fn':>4}")
    for code in sorted(set(tp) | set(fp) | set(fn)):
        precision = tp[code] / (tp[code] + fp[code]) if tp[code] + fp[code] else 0.0
        recall = tp[code] / (tp[code] + fn[code]) if tp[code] + fn[code] else 0.0
        print(f"{code:<24}{precision:>10.2f}{recall:>8.2f}{tp[code]:>4}{fp[code]:>4}{fn[code]:>4}")
    if wrong:
        print("\nRouting differences:")
        for line in wrong:
            print(f"  {line}")
    print(f"\nLLM calls: {calls}  cost: ₹{result['cost_inr_total']:.2f} total, "
          f"₹{result['cost_inr_per_document']:.4f} per document")
    print(f"Latency per document that used the LLM: p50 {result['latency_ms_p50']:.0f} ms, "
          f"p95 {result['latency_ms_p95']:.0f} ms")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-only", action="store_true", help="skip the LLM; check the policy code alone")
    args = parser.parse_args()
    evaluate(policy_only=args.policy_only)


if __name__ == "__main__":
    main()
