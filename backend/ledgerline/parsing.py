"""Turn the strings the model copies off the page into Python values.

Money is always Decimal (AP policy section 1: never binary floating point).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")

_LAKH = Decimal("100000")
_CRORE = Decimal("10000000")
_CURRENCY_TOKENS = re.compile(r"(₹|\bRs\.?|\bINR\b|\bUSD\b|\bUS\$|\$|/-)", re.IGNORECASE)


class ParseError(ValueError):
    """A value the document printed that we can't turn into a number or date with confidence."""


def money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_decimal(value) -> Decimal | None:
    """'₹ 1,23,456.00' -> Decimal('123456.00'); 'Rs. 1.2 lakh' -> Decimal('120000'); '(40.00)' -> -40.

    Raises ParseError rather than guessing when the text isn't a number.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ParseError(f"not an amount: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))  # repr keeps 1789.2 as 1789.2, not 1789.19999...
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if text == "" or text in {"-", "–", "—"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = _CURRENCY_TOKENS.sub("", text).replace(",", "").replace(" ", "").strip()
    multiplier = Decimal(1)
    lowered = text.lower()
    for word, factor in (("crore", _CRORE), ("cr", _CRORE), ("lakhs", _LAKH), ("lakh", _LAKH), ("lac", _LAKH)):
        if lowered.endswith(word):
            multiplier, text = factor, text[: -len(word)]
            break
    if text.startswith("+"):
        text = text[1:]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    try:
        number = Decimal(text) * multiplier
    except InvalidOperation as exc:
        raise ParseError(f"not an amount: {value!r}") from exc
    return -number if negative else number


def parse_amount(value) -> Decimal | None:
    """Like parse_decimal, rounded to two places."""
    number = parse_decimal(value)
    return None if number is None else money(number)


def format_amount(value: Decimal | None) -> str | None:
    return None if value is None else f"{money(value):.2f}"


def format_quantity(value: Decimal | None) -> str | None:
    """'12' rather than '12.00' for whole quantities; keep decimals when they matter."""
    if value is None:
        return None
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_WORDY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-/.]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})$")
_WORDY_US = re.compile(r"^([A-Za-z]{3,9})[\s\-/.]*(\d{1,2})(?:st|nd|rd|th)?[\s,\-/.]*(\d{2,4})$")


def _year(text: str) -> int:
    year = int(text)
    return year + 2000 if year < 100 else year


def parse_date(value, month_first: bool = False) -> date | None:
    """Parse a printed date.

    Indian vendors print day first; vendors in the US print month first (AP policy section 1). We never
    let a library guess: an unrecognised format raises ParseError so the document goes to review.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if m := _ISO.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := _NUMERIC.match(text):
            first, second, year = int(m[1]), int(m[2]), _year(m[3])
            day, month = (second, first) if month_first else (first, second)
            return date(year, month, day)
        if m := _WORDY.match(text):
            return date(_year(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))
        if m := _WORDY_US.match(text):
            return date(_year(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))
    except (ValueError, KeyError) as exc:
        raise ParseError(f"not a date: {value!r}") from exc
    raise ParseError(f"unrecognised date format: {value!r}")


def financial_year(day: date) -> str:
    """2026-04-03 -> '2026-27'; 2026-03-31 -> '2025-26' (AP policy section 1)."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def normalize_invoice_number(number: str | None) -> str:
    """'SIS / 26-27 / 0018' -> 'SIS26270018'. Leading zeros are significant."""
    return re.sub(r"[\s/\-#.]", "", number or "").upper()


def normalize_name(name: str | None) -> str:
    """Case-insensitive, ignoring spaces and punctuation (the foreign supplier key)."""
    return re.sub(r"[^0-9a-z]", "", (name or "").lower())
