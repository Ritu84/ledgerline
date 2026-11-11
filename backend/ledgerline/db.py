"""SQLite persistence.

Money is stored as TEXT holding a two-decimal string ("23458.00"), never REAL, so no amount passes through
binary floating point (AP policy section 1).
"""
from __future__ import annotations

import json
import sqlite3

from .config import USD_TO_INR

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    filename TEXT,
    raw_text TEXT NOT NULL,
    document_type TEXT,
    supplier_name TEXT,
    supplier_gstin TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    currency TEXT,
    subtotal TEXT,
    cgst TEXT,
    sgst TEXT,
    igst TEXT,
    round_off TEXT,
    total TEXT,
    bank_account TEXT,
    ifsc TEXT,
    po_number TEXT,
    notes TEXT,
    line_items_json TEXT,
    warnings_json TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reasons_json TEXT,
    required_approvals INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'ready_for_approval',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    user_id TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount TEXT NOT NULL,
    currency TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER REFERENCES invoices(id),
    document_id TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    org_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- One person approving twice counts once; an invoice is paid at most once (AP policy section 4).
CREATE UNIQUE INDEX IF NOT EXISTS approvals_one_per_user ON approvals (invoice_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS payments_one_per_invoice ON payments (invoice_id);
CREATE INDEX IF NOT EXISTS invoices_by_org ON invoices (org_id);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def record_audit(conn: sqlite3.Connection, invoice_id: int, org_id: str, actor: str, action: str,
                 note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log (invoice_id, org_id, actor, action, note) VALUES (?, ?, ?, ?, ?)",
        (invoice_id, org_id, actor, action, note),
    )


def get_invoice(conn: sqlite3.Connection, invoice_id: int, org_id: str | None = None) -> dict | None:
    """One invoice with its approvals, payment, audit trail and LLM usage. org_id limits it to that tenant."""
    if org_id is None:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    for col in ("line_items_json", "warnings_json", "review_reasons_json"):
        inv[col.removesuffix("_json")] = json.loads(inv.pop(col) or "[]")
    inv["needs_review"] = bool(inv["needs_review"])
    inv["approvals"] = [dict(r) for r in conn.execute(
        "SELECT user_id, note, created_at FROM approvals WHERE invoice_id = ? ORDER BY id", (invoice_id,))]
    payment = conn.execute(
        "SELECT amount, currency, created_at FROM payments WHERE invoice_id = ?", (invoice_id,)).fetchone()
    inv["payment"] = dict(payment) if payment else None
    inv["audit_log"] = [dict(r) for r in conn.execute(
        "SELECT actor, action, note, created_at FROM audit_log WHERE invoice_id = ? ORDER BY id", (invoice_id,))]
    usage = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
        "COALESCE(SUM(latency_ms), 0) AS latency_ms FROM llm_calls WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    inv["usage"] = {
        "llm_calls": usage["calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_inr": round(usage["cost_usd"] * USD_TO_INR, 4),
        "latency_ms": usage["latency_ms"],
    }
    return inv
