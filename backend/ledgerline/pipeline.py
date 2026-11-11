"""Process one document end to end: extract -> normalise -> check -> route -> persist.

Routing is decided here, by the deterministic checks in validation.py. Nothing the model says can make a
document skip review, and a document that can't be read is stored and routed as processing_error rather
than dropped.
"""
from __future__ import annotations

import json
import re
import sqlite3

from . import db
from .extraction import ExtractionError, extract
from .llm import LLMResponse
from .llm.pricing import cost_usd
from .models import Invoice, LineItem
from .parsing import ParseError, format_amount, format_quantity, parse_amount, parse_date, parse_decimal
from .reference import ReferenceData
from .validation import (REVIEW_CODES, check_suspicious_content, find_suspicious_content, required_approvals,
                         run_checks, vendor_prints_month_first)

ZERO = parse_amount("0")

# How suppliers print things, tidied in code so it doesn't depend on how the model copied them.
_QUANTITY_WITH_UNIT = re.compile(r"^\s*([\d,]*\.?\d+)\s*[A-Za-z][A-Za-z.]*\s*$")  # "500 kg", "10 PKT"
_HSN_SUFFIX = re.compile(r"\s*[|,;-]?\s*\(?\b(?:HSN|SAC)(?:\s*/\s*SAC)?\b[\s:.#-]*\d{4,8}\)?\s*$", re.IGNORECASE)
_SPACED_SEPARATOR = re.compile(r"\s*([/\-])\s*")  # "SIS / 26-27 / 0018" is the same number as "SIS/26-27/0018"


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize(data: dict, ref: ReferenceData | None = None) -> tuple[Invoice, list[str]]:
    """Typed invoice from the extracted strings, plus a note for every value that couldn't be parsed.

    A value we can't parse is left empty and reported, never guessed.
    """
    problems: list[str] = []

    def amount(field: str, value, default=None):
        try:
            parsed = parse_amount(value)
        except ParseError as exc:
            problems.append(f"{field}: {exc}")
            return default
        return default if parsed is None else parsed

    def quantity(field: str, value):
        if isinstance(value, str) and (m := _QUANTITY_WITH_UNIT.match(value)):
            value = m.group(1)
        try:
            return parse_decimal(value)
        except ParseError as exc:
            problems.append(f"{field}: {exc}")
            return None

    items = []
    for n, item in enumerate(data.get("line_items") or [], start=1):
        line_amount = amount(f"line {n} amount", item.get("amount"))
        if line_amount is None:
            problems.append(f"line {n} amount: missing")
            line_amount = ZERO
        items.append(LineItem(
            description=_HSN_SUFFIX.sub("", str(item.get("description") or "")).strip(),
            quantity=quantity(f"line {n} quantity", item.get("quantity")),
            unit_price=amount(f"line {n} unit price", item.get("unit_price")),
            amount=line_amount,
        ))

    supplier_name = _text(data.get("supplier_name"))
    if supplier_name:
        supplier_name = re.sub(r"\s+", " ", supplier_name)  # names spaced out on the page are the same name
    month_first = bool(ref) and vendor_prints_month_first(ref, supplier_name)
    try:
        invoice_date = parse_date(_text(data.get("invoice_date")), month_first=month_first)
    except ParseError as exc:
        problems.append(f"invoice_date: {exc}")
        invoice_date = None

    document_type = (_text(data.get("document_type")) or "invoice").lower()
    if document_type not in {"invoice", "credit_note"}:
        problems.append(f"document_type: unexpected value {document_type!r}")
        document_type = "invoice"

    gstin = _text(data.get("supplier_gstin"))
    ifsc = _text(data.get("ifsc"))
    invoice_number = _text(data.get("invoice_number"))
    inv = Invoice(
        document_type=document_type,
        supplier_name=supplier_name,
        supplier_gstin=gstin.upper() if gstin else None,
        invoice_number=_SPACED_SEPARATOR.sub(r"\1", invoice_number) if invoice_number else None,
        invoice_date=invoice_date,
        currency=(_text(data.get("currency")) or "INR").upper(),
        subtotal=amount("subtotal", data.get("subtotal")),
        cgst=amount("cgst", data.get("cgst"), ZERO),
        sgst=amount("sgst", data.get("sgst"), ZERO),
        igst=amount("igst", data.get("igst"), ZERO),
        round_off=amount("round_off", data.get("round_off"), ZERO),
        total=amount("total", data.get("total")),
        bank_account=re.sub(r"\D", "", str(data.get("bank_account") or "")) or None,  # contract: digits only
        ifsc=ifsc.upper() if ifsc else None,
        po_number=_text(data.get("po_number")),
        notes=_text(data.get("notes")),
        line_items=items,
    )
    for field in ("supplier_name", "invoice_number", "invoice_date", "total"):
        if getattr(inv, field) is None and not any(p.startswith(f"{field}:") for p in problems):
            problems.append(f"{field}: missing")
    return inv, problems


def _line_items_json(inv: Invoice) -> str:
    return json.dumps([
        {"description": item.description, "quantity": format_quantity(item.quantity),
         "unit_price": format_amount(item.unit_price), "amount": format_amount(item.amount)}
        for item in inv.line_items
    ], ensure_ascii=False)


def _persist(conn: sqlite3.Connection, org_id: str, document_id: str, filename: str | None, raw_text: str,
             inv: Invoice | None, details: list[str], reasons: list[str], approvals: int,
             responses: list[LLMResponse]) -> dict:
    needs_review = bool(reasons)
    status = "needs_review" if needs_review else "ready_for_approval"
    if inv is None:
        columns = (None,) * 14 + ("[]",)
        document_type, currency = "invoice", None
    else:
        document_type, currency = inv.document_type, inv.currency
        columns = (
            inv.supplier_name, inv.supplier_gstin, inv.invoice_number,
            inv.invoice_date.isoformat() if inv.invoice_date else None,
            format_amount(inv.subtotal), format_amount(inv.cgst), format_amount(inv.sgst),
            format_amount(inv.igst), format_amount(inv.round_off), format_amount(inv.total),
            inv.bank_account, inv.ifsc, inv.po_number, inv.notes, _line_items_json(inv),
        )
    with conn:
        cur = conn.execute(
            """INSERT INTO invoices (org_id, document_id, filename, raw_text, document_type, currency,
                   supplier_name, supplier_gstin, invoice_number, invoice_date, subtotal, cgst, sgst, igst,
                   round_off, total, bank_account, ifsc, po_number, notes, line_items_json, warnings_json,
                   needs_review, review_reasons_json, required_approvals, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (org_id, document_id, filename, raw_text, document_type, currency, *columns,
             json.dumps(details, ensure_ascii=False), int(needs_review), json.dumps(reasons), approvals, status),
        )
        invoice_id = cur.lastrowid
        for r in responses:
            conn.execute(
                "INSERT INTO llm_calls (invoice_id, document_id, model, input_tokens, output_tokens, cost_usd, "
                "latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (invoice_id, document_id, r.model, r.input_tokens, r.output_tokens,
                 cost_usd(r.model, r.input_tokens, r.output_tokens), r.latency_ms),
            )
        db.record_audit(conn, invoice_id, org_id, "system", "processed",
                        json.dumps({"review_reasons": reasons, "required_approvals": approvals}))
    return db.get_invoice(conn, invoice_id)


def process_document(
    conn: sqlite3.Connection,
    ref: ReferenceData,
    raw_text: str,
    document_id: str,
    org_id: str = "meridian",
    filename: str | None = None,
) -> dict:
    """Never raises for a bad document: it is stored with processing_error so a person looks at it."""
    responses: list[LLMResponse] = []
    try:
        data, responses = extract(raw_text)
        inv, problems = normalize(data, ref)
        reasons = run_checks(conn, ref, inv, raw_text, org_id,
                             model_flagged_suspicious=data.get("addressed_to_software") is True)
        if data.get("more_than_one_invoice") is True:
            problems.append("the file: it holds more than one invoice; split it and upload each one")
        details = [f"Could not read {p}" for p in problems]
        if problems:
            reasons = sorted(set(reasons) | {"processing_error"}, key=REVIEW_CODES.index)
        snippets = find_suspicious_content(raw_text, ref.vendor_names)
        details += [f"Text addressed to software or markup: “{s}”" for s in snippets[:5]]
        if "suspicious_content" in reasons and not snippets:
            details.append("The reading model reported text addressed to software or AI; read the document in full")
        return _persist(conn, org_id, document_id, filename, raw_text, inv, details, reasons,
                        required_approvals(inv), responses)
    except Exception as exc:  # noqa: BLE001 - a batch must never lose a document
        if isinstance(exc, ExtractionError):
            responses = exc.responses
        reasons = ["processing_error"] + check_suspicious_content(raw_text, known_names=ref.vendor_names)
        details = [f"Processing failed: {type(exc).__name__}: {exc}"]
        return _persist(conn, org_id, document_id, filename, raw_text, None, details, reasons, 1, responses)
