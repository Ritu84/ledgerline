"""HTTP API used by the reviewer UI.  Run: uvicorn ledgerline.api:app --reload"""
from __future__ import annotations

import os
import sqlite3
from pathlib import PurePath

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .config import USD_TO_INR, get_settings
from .pipeline import process_document
from .reference import load_reference

MAX_UPLOAD_BYTES = 1_000_000
InvoiceId = Annotated[int, Path(ge=1, le=2**63 - 1)]  # SQLite's integer range; larger ids are a 422, not a 500
DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

app = FastAPI(title="Ledgerline API", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("LEDGERLINE_CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Org-Id"],
)


def get_conn():
    conn = db.connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_org(x_org_id: str = Header(default="meridian")) -> str:
    return x_org_id


class DecisionRequest(BaseModel):
    user_id: str
    note: str = ""


def _load(conn: sqlite3.Connection, invoice_id: int, org_id: str) -> dict:
    """The invoice if it belongs to this org. Another org's invoice looks the same as a missing one."""
    invoice = db.get_invoice(conn, invoice_id, org_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _decision(body: DecisionRequest) -> tuple[str, str]:
    # One person, one identity: "Kavya.Iyer" and "kavya.iyer" must not count as two approvers.
    user_id, note = body.user_id.strip().lower(), body.note.strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    return user_id, note


def _state(conn: sqlite3.Connection, invoice_id: int, org_id: str) -> dict:
    invoice = db.get_invoice(conn, invoice_id, org_id)
    return {"id": invoice_id, "approvals": len(invoice["approvals"]),
            "required_approvals": invoice["required_approvals"], "status": invoice["status"],
            "payment": invoice["payment"]}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/invoices")
async def upload_invoice(file: UploadFile, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Document is larger than 1 MB")
    try:
        raw_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Document must be UTF-8 text (.txt, .eml or .json)")
    filename = PurePath(file.filename or "upload").name
    document_id = filename.rsplit(".", 1)[0] or "upload"
    return process_document(conn, load_reference(), raw_text, document_id, org_id=org_id, filename=filename)


@app.get("/api/invoices")
def list_invoices(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT id, document_id, document_type, supplier_name, invoice_number, invoice_date, currency, total, "
        "status, needs_review, required_approvals FROM invoices WHERE org_id = ? ORDER BY id DESC",
        (org_id,),
    ).fetchall()
    return [dict(r) | {"needs_review": bool(r["needs_review"])} for r in rows]


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: InvoiceId, org_id: str = Depends(get_org), conn=Depends(get_conn)):
    return _load(conn, invoice_id, org_id)


@app.post("/api/invoices/{invoice_id}/approve")
def approve_invoice(invoice_id: InvoiceId, body: DecisionRequest, org_id: str = Depends(get_org),
                    conn=Depends(get_conn)):
    """Record one person's approval (AP policy section 4). Safe to retry: a repeat changes nothing."""
    user_id, note = _decision(body)
    conn.execute("BEGIN IMMEDIATE")  # one writer at a time, so two requests can't both create a payment
    try:
        invoice = _load(conn, invoice_id, org_id)
        reasons = invoice["review_reasons"]
        if any(a["user_id"] == user_id for a in invoice["approvals"]):
            conn.rollback()
            return _state(conn, invoice_id, org_id)
        if invoice["document_type"] == "credit_note":
            raise HTTPException(status_code=409, detail="Credit notes cannot be approved for payment")
        if "duplicate" in reasons:
            raise HTTPException(status_code=409, detail="Duplicate invoices cannot be approved, only rejected")
        if "processing_error" in reasons or invoice["total"] is None:
            raise HTTPException(status_code=409,
                                detail="This document could not be read reliably, so it cannot be paid from here")
        if invoice["status"] in {"approved", "rejected"}:
            raise HTTPException(status_code=409, detail=f"Invoice is already {invoice['status']}")
        if invoice["needs_review"] and not note:
            raise HTTPException(status_code=422, detail="A note is required to approve a document that needed review")

        conn.execute("INSERT INTO approvals (invoice_id, user_id, note) VALUES (?, ?, ?)", (invoice_id, user_id, note))
        db.record_audit(conn, invoice_id, org_id, user_id, "approved", note)
        approvals = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM approvals WHERE invoice_id = ?", (invoice_id,)).fetchone()[0]
        if approvals >= max(1, invoice["required_approvals"]):
            conn.execute("UPDATE invoices SET status = 'approved' WHERE id = ?", (invoice_id,))
            conn.execute("INSERT OR IGNORE INTO payments (invoice_id, amount, currency) VALUES (?, ?, ?)",
                         (invoice_id, invoice["total"], invoice["currency"]))
            db.record_audit(conn, invoice_id, org_id, "system", "payment_created",
                            f"{invoice['currency']} {invoice['total']}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return _state(conn, invoice_id, org_id)


@app.post("/api/invoices/{invoice_id}/reject")
def reject_invoice(invoice_id: InvoiceId, body: DecisionRequest, org_id: str = Depends(get_org),
                   conn=Depends(get_conn)):
    user_id, note = _decision(body)
    conn.execute("BEGIN IMMEDIATE")
    try:
        invoice = _load(conn, invoice_id, org_id)
        if invoice["status"] == "approved":
            raise HTTPException(status_code=409, detail="Invoice is already approved and a payment exists")
        if invoice["status"] != "rejected":
            if not note:
                raise HTTPException(status_code=422, detail="A note is required to reject a document")
            conn.execute("UPDATE invoices SET status = 'rejected' WHERE id = ?", (invoice_id,))
            db.record_audit(conn, invoice_id, org_id, user_id, "rejected", note)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return _state(conn, invoice_id, org_id)


@app.get("/api/stats")
def stats(org_id: str = Depends(get_org), conn=Depends(get_conn)):
    """Feeds the cost dashboard."""
    invoices = conn.execute("SELECT COUNT(*) FROM invoices WHERE org_id = ?", (org_id,)).fetchone()[0]
    row = conn.execute(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(c.cost_usd), 0) AS cost_usd "
        "FROM llm_calls c JOIN invoices i ON i.id = c.invoice_id WHERE i.org_id = ?",
        (org_id,),
    ).fetchone()
    total_inr = row["cost_usd"] * USD_TO_INR
    return {
        "invoices_processed": invoices,
        "llm_calls": row["calls"],
        "llm_cost_inr": round(total_inr, 2),
        "avg_llm_cost_per_invoice_inr": round(total_inr / invoices, 4) if invoices else 0.0,
    }
