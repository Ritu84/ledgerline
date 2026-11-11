"""Write predictions_disputed.jsonl from stored model readings, with the current policy code and flags.

Used on 11 Nov 2026 when the free Gemini quota was used up: the model readings come from the live-app
run of 00:13 IST (same extraction code); everything after the model (normalisation, checks, flags,
approvals) runs fresh. With quota, `LEDGERLINE_FLAG_LINE_ARITHMETIC=1 LEDGERLINE_FLAG_FUTURE_DATE=1
make predict` produces the same file from scratch.

Usage: python eval/replay_disputed.py <ledgerline.db with the disp_* rows> <output.jsonl>
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from ledgerline import db, extraction, pipeline
from ledgerline.cli import to_contract
from ledgerline.config import get_settings
from ledgerline.reference import load_reference

FIELDS = ["document_type", "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "currency",
          "subtotal", "cgst", "sgst", "igst", "round_off", "total", "bank_account", "ifsc", "po_number", "notes"]


def main(source_db: str, output: str) -> None:
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    stored = {r["document_id"]: r for r in src.execute(
        "SELECT * FROM invoices WHERE document_id LIKE 'disp_%' AND org_id = 'meridian' ORDER BY id")}
    usage = {d: [dict(u) for u in src.execute("SELECT * FROM llm_calls WHERE invoice_id = ?", (r["id"],))]
             for d, r in stored.items()}
    folder = get_settings().data_dir / "invoices" / "disputed"
    conn = db.connect(str(Path(tempfile.mkdtemp()) / "replay.db"))
    ref = load_reference()
    lines = []
    for path in sorted(folder.iterdir(), key=lambda p: p.stem):
        row = stored[path.stem]
        reading = {f: row[f] for f in FIELDS}
        reading["line_items"] = json.loads(row["line_items_json"])
        reading["addressed_to_software"] = False  # not stored; the code checks still run on the raw text
        responses = [extraction.LLMResponse("", u["model"], u["input_tokens"], u["output_tokens"], u["latency_ms"])
                     for u in usage[path.stem]]
        pipeline.extract = lambda _text, r=reading, resp=responses: (r, resp)
        raw_text = path.read_bytes().decode("utf-8-sig", errors="replace")
        lines.append(to_contract(pipeline.process_document(conn, ref, raw_text, path.stem, filename=path.name)))
    with open(output, "w", encoding="utf-8") as out:
        for line in lines:
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
    for line in lines:
        print(line["document_id"], line["needs_review"], line["review_reasons"], line["required_approvals"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
