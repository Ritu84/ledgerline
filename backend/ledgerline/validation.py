"""Deterministic AP policy checks (AP_POLICY.md section 3).

These decide routing. The LLM only reads documents; code applies the policy, so a document cannot talk
its way past a check and the result is the same every time.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal
from email.utils import parsedate_to_datetime

from .flags import flag_enabled
from .models import Invoice
from .parsing import ParseError, financial_year, normalize_invoice_number, normalize_name, parse_date
from .reference import ReferenceData

GSTIN_PATTERN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOTALS_TOLERANCE = Decimal("1.00")
NEW_VENDOR_DAYS = 90
HIGH_VALUE_THRESHOLD = Decimal("500000.00")

# Every code the policy defines, in the order we report them.
REVIEW_CODES = [
    "processing_error", "credit_note", "duplicate", "gstin_invalid", "vendor_unknown", "vendor_new",
    "bank_details_changed", "tax_type_mismatch", "totals_mismatch", "foreign_currency", "suspicious_content",
    # Only behind flags (RULINGS.md): departures from the written policy.
    "line_amount_mismatch", "invoice_date_in_future",
]


def gstin_checksum(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = GSTIN_ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str | None) -> bool:
    """Validate a GSTIN's format and check digit (AP policy Appendix A)."""
    if not gstin:
        return False
    gstin = gstin.strip().upper()
    if GSTIN_PATTERN.fullmatch(gstin) is None:
        return False
    return gstin_checksum(gstin[:14]) == gstin[14]


def supplier_key(inv: Invoice) -> str:
    """GSTIN for domestic documents, normalised legal name for foreign ones (AP policy section 1)."""
    if inv.is_domestic:
        return (inv.supplier_gstin or "").strip().upper()
    return normalize_name(inv.supplier_name)


def find_vendor(ref: ReferenceData, inv: Invoice) -> dict | None:
    """A domestic supplier is identified by GSTIN alone; the printed name is not proof of identity."""
    key = supplier_key(inv)
    if not key:
        return None
    for vendor in ref.vendors:
        if inv.is_domestic:
            if (vendor.get("gstin") or "").strip().upper() == key:
                return vendor
        elif normalize_name(vendor.get("legal_name")) == key:
            return vendor
    return None


def vendor_prints_month_first(ref: ReferenceData, supplier_name: str | None) -> bool:
    """US vendors print MM/DD/YYYY. Used before the full invoice exists, so it matches on name."""
    wanted = normalize_name(supplier_name)
    return any(
        normalize_name(v.get("legal_name")) == wanted and (v.get("country") or "").upper() == "US"
        for v in ref.vendors
    ) if wanted else False


def check_credit_note(inv: Invoice) -> list[str]:
    return ["credit_note"] if inv.document_type == "credit_note" else []


def check_gstin(inv: Invoice) -> list[str]:
    if inv.is_domestic and not is_valid_gstin(inv.supplier_gstin):
        return ["gstin_invalid"]
    return []


def check_vendor(vendor: dict | None) -> list[str]:
    return [] if vendor else ["vendor_unknown"]


def check_vendor_new(inv: Invoice, vendor: dict | None) -> list[str]:
    if not vendor or not vendor.get("onboarded_on") or inv.invoice_date is None:
        return []
    onboarded = date.fromisoformat(vendor["onboarded_on"])
    return ["vendor_new"] if (inv.invoice_date - onboarded).days < NEW_VENDOR_DAYS else []


def check_bank_details(inv: Invoice, vendor: dict | None) -> list[str]:
    """Account digits-only, IFSC case-insensitive. Not raised for unknown vendors or no bank details."""
    if not vendor:
        return []
    doc_account = re.sub(r"\D", "", inv.bank_account or "")
    doc_ifsc = (inv.ifsc or "").strip().upper()
    if not doc_account and not doc_ifsc:
        return []
    file_account = re.sub(r"\D", "", vendor.get("bank_account") or "")
    file_ifsc = (vendor.get("ifsc") or "").strip().upper()
    if doc_account and doc_account != file_account:
        return ["bank_details_changed"]
    if doc_ifsc and doc_ifsc != file_ifsc:
        return ["bank_details_changed"]
    return []


def check_tax_type(inv: Invoice, buyer_state_code: str) -> list[str]:
    if not inv.is_domestic or not inv.supplier_gstin or not inv.supplier_gstin[:2].isdigit():
        return []
    intra_state = inv.supplier_gstin[:2] == buyer_state_code
    if intra_state and inv.igst > 0:
        return ["tax_type_mismatch"]
    if not intra_state and (inv.cgst > 0 or inv.sgst > 0):
        return ["tax_type_mismatch"]
    return []


def check_totals(inv: Invoice) -> list[str]:
    if inv.total is None:
        return []
    if inv.line_items:
        base = sum((item.amount for item in inv.line_items), Decimal("0"))
    elif inv.subtotal is not None:
        base = inv.subtotal
    else:
        return []
    computed = base + inv.cgst + inv.sgst + inv.igst + inv.round_off
    return [] if abs(computed - inv.total) <= TOTALS_TOLERANCE else ["totals_mismatch"]


def check_line_arithmetic(inv: Invoice) -> list[str]:
    """Flag LINE_ARITHMETIC: quantity x unit price must match each line amount within the totals tolerance."""
    for item in inv.line_items:
        if item.quantity is None or item.unit_price is None:
            continue
        if abs(item.quantity * item.unit_price - item.amount) > TOTALS_TOLERANCE:
            return ["line_amount_mismatch"]
    return []


_EMAIL_DATE = re.compile(r"^Date:\s*(.+)$", re.MULTILINE)


def email_sent_on(raw_text: str) -> date | None:
    """The date in an email's own Date header (in the sender's time zone), or None for other documents."""
    head = re.split(r"\r?\n\r?\n", raw_text, maxsplit=1)[0] if raw_text.lstrip().startswith(("From:", "Received:", "Return-Path:")) else ""
    m = _EMAIL_DATE.search(head)
    if not m:
        return None
    try:
        return parsedate_to_datetime(m.group(1).strip()).date()
    except (TypeError, ValueError):
        return None


def check_future_date(inv: Invoice, raw_text: str) -> list[str]:
    """Flag FUTURE_DATE: an invoice cannot be dated after the email that carried it was sent."""
    sent = email_sent_on(raw_text)
    if sent is None or inv.invoice_date is None:
        return []
    return ["invoice_date_in_future"] if inv.invoice_date > sent else []


def check_foreign_currency(inv: Invoice) -> list[str]:
    return [] if inv.is_domestic else ["foreign_currency"]


def _same_invoice(key: str, number: str, fy: str | None, other_key: str, other_number: str,
                  other_date: date | None) -> bool:
    if not key or key != other_key or number != other_number:
        return False
    if fy is None or other_date is None:
        return True  # can't tell the years apart: treat as the same invoice and let a human look
    return financial_year(other_date) == fy


def check_duplicate(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, org_id: str = "meridian",
                    exclude_id: int | None = None) -> list[str]:
    """Same supplier key, normalised number and FY, in payment history or earlier in this batch."""
    if inv.document_type != "invoice":
        return []
    key = supplier_key(inv)
    number = normalize_invoice_number(inv.invoice_number)
    if not key or not number:
        return []
    fy = financial_year(inv.invoice_date) if inv.invoice_date else None

    for paid in ref.paid_invoices:
        paid_key = (paid.get("supplier_gstin") or "").strip().upper() if inv.is_domestic \
            else normalize_name(paid.get("supplier_name"))
        try:
            paid_date = parse_date(paid.get("invoice_date"))
        except ParseError:
            paid_date = None
        if _same_invoice(key, number, fy, paid_key, normalize_invoice_number(paid.get("invoice_number")),
                         paid_date):
            return ["duplicate"]

    rows = conn.execute(
        "SELECT id, supplier_gstin, supplier_name, invoice_number, invoice_date, currency FROM invoices "
        "WHERE org_id = ? AND document_type = 'invoice' AND (? IS NULL OR id != ?)",
        (org_id, exclude_id, exclude_id),
    ).fetchall()
    for row in rows:
        domestic = (row["currency"] or "INR") == "INR"
        if domestic != inv.is_domestic:
            continue
        row_key = (row["supplier_gstin"] or "").strip().upper() if domestic else normalize_name(row["supplier_name"])
        row_date = date.fromisoformat(row["invoice_date"]) if row["invoice_date"] else None
        if _same_invoice(key, number, fy, row_key, normalize_invoice_number(row["invoice_number"]), row_date):
            return ["duplicate"]
    return []


# Text addressed to software or AI, or markup that would run in a browser (AP policy section 3).
_MARKUP = re.compile(
    r"<\s*/?\s*(script|img|iframe|svg|object|embed|form|input|a\s|style|link|meta|body|html|div|span)\b"
    r"|\bon(error|load|click|mouseover)\s*=|javascript\s*:",
    re.IGNORECASE,
)
_ADDRESSED_TO_MACHINES = re.compile(
    r"\b(automated|automation|ai assistants?|ai systems?|ai agents?|language models?|llms?|chatgpt|"
    r"gpt|claude|copilot|bots?)\b"
    r"|ignore (all |any )?(previous|prior|above) instructions"
    r"|\b(requires_review|review_reasons|needs_review)\b"
    r"|\b(skip|bypass|disable) (the |all |any )?(checks?|review|validation|approval)"
    r"|\b(ignore|disregard|forget) (all |any |the )?(previous|prior|above|earlier|other) (instructions|rules)"
    r"|\b(new|updated|revised|system) instructions\b"
    r"|\b(invoice processing|payment|payables?|AP|approval) (system|software|tool)s?\b"
    r"|<\s*/?\s*(document|system|instructions?)\s*>",
    re.IGNORECASE,
)
_AI = re.compile(r"\bAI\b")  # case-sensitive: the word "AI", not "ai" in "Mumbai" or "e-mail"


def _blank_known_names(raw_text: str, known_names) -> str:
    """Hide approved vendors' own names, so 'Western Automation Pvt. Ltd.' is not text addressed to software.

    Same length, so the snippets shown to reviewers still come from the original text.
    """
    for name in known_names:
        words = re.findall(r"[0-9A-Za-z]+", name or "")
        if not words:
            continue
        pattern = re.compile(r"\b" + r"[\s.,&'-]*".join(map(re.escape, words)) + r"\b", re.IGNORECASE)
        raw_text = pattern.sub(lambda m: " " * len(m.group(0)), raw_text)
    return raw_text


def find_suspicious_content(raw_text: str, known_names=()) -> list[str]:
    """Short snippets explaining why a document looks like it is talking to software, for reviewers."""
    scanned = _blank_known_names(raw_text, known_names)
    spans = sorted(
        (max(0, m.start() - 40), min(len(raw_text), m.end() + 40))
        for pattern in (_MARKUP, _ADDRESSED_TO_MACHINES, _AI) for m in pattern.finditer(scanned)
    )
    merged: list[tuple[int, int]] = []
    for start, end in spans:  # two patterns often hit the same sentence; show it once
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return [raw_text[start:end].replace("\n", " ").strip() for start, end in merged]


def check_suspicious_content(raw_text: str, model_flagged: bool = False, known_names=()) -> list[str]:
    return ["suspicious_content"] if (model_flagged or find_suspicious_content(raw_text, known_names)) else []


def required_approvals(inv: Invoice) -> int:
    """AP policy section 4.1."""
    if inv.document_type == "credit_note":
        return 0
    if not inv.is_domestic:
        return 2
    if inv.total is not None and inv.total >= HIGH_VALUE_THRESHOLD:
        return 2
    return 1


def run_checks(conn: sqlite3.Connection, ref: ReferenceData, inv: Invoice, raw_text: str = "",
               org_id: str = "meridian", model_flagged_suspicious: bool = False) -> list[str]:
    """Every review reason that applies, deduplicated, in REVIEW_CODES order."""
    vendor = find_vendor(ref, inv)
    buyer_state = str(ref.buyer.get("state_code") or (ref.buyer.get("gstin") or "")[:2])
    reasons = (
        check_credit_note(inv)
        + check_duplicate(conn, ref, inv, org_id)
        + check_gstin(inv)
        + check_vendor(vendor)
        + check_vendor_new(inv, vendor)
        + check_bank_details(inv, vendor)
        + check_tax_type(inv, buyer_state)
        + check_totals(inv)
        + check_foreign_currency(inv)
        + check_suspicious_content(raw_text, model_flagged_suspicious, ref.vendor_names)
        + (check_line_arithmetic(inv) if flag_enabled("LINE_ARITHMETIC") else [])
        + (check_future_date(inv, raw_text) if flag_enabled("FUTURE_DATE") else [])
    )
    return sorted(set(reasons), key=REVIEW_CODES.index)
