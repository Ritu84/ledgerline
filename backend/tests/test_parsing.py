from datetime import date
from decimal import Decimal

import pytest

from ledgerline.parsing import (ParseError, financial_year, format_amount, format_quantity,
                                normalize_invoice_number, parse_amount, parse_date)


def test_parse_amount_indian_grouping():
    assert parse_amount("1,23,456.00") == Decimal("123456.00")


def test_parse_amount_rupee_symbol():
    assert parse_amount("₹ 2,480.00") == Decimal("2480.00")


@pytest.mark.parametrize("text, expected", [
    ("Rs. 1,450.00", "1450.00"),
    ("INR 5,00,000/-", "500000.00"),
    ("₹1.2 lakh", "120000.00"),
    ("2.5 Crore", "25000000.00"),
    ("-0.40", "-0.40"),
    ("(40.00)", "-40.00"),
    ("$1,200.50", "1200.50"),
])
def test_parse_amount_formats_seen_on_indian_invoices(text, expected):
    assert parse_amount(text) == Decimal(expected)


def test_amounts_are_decimal_not_float():
    assert isinstance(parse_amount(1789.2), Decimal)
    assert parse_amount(1789.2) == Decimal("1789.20")
    assert parse_amount("0.1") + parse_amount("0.2") == Decimal("0.30")


def test_parse_amount_empty_is_none():
    assert parse_amount("") is None


def test_parse_amount_refuses_to_guess():
    with pytest.raises(ParseError):
        parse_amount("twelve thousand")


def test_format_amount_and_quantity():
    assert format_amount(Decimal("23458")) == "23458.00"
    assert format_quantity(Decimal("12.00")) == "12"
    assert format_quantity(Decimal("2.5")) == "2.5"


def test_parse_date_iso():
    assert parse_date("2026-04-25") == date(2026, 4, 25)


def test_parse_date_is_day_first_for_indian_vendors():
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_parse_date_is_month_first_for_us_vendors():
    assert parse_date("04/03/2026", month_first=True) == date(2026, 4, 3)


def test_parse_date_day_first_when_unambiguous():
    assert parse_date("25/04/2026") == date(2026, 4, 25)


@pytest.mark.parametrize("text", ["25-Apr-2026", "25 April 2026", "25.04.2026", "25th Apr 26", "April 25, 2026"])
def test_parse_date_other_printed_forms(text):
    assert parse_date(text) == date(2026, 4, 25)


def test_parse_date_refuses_impossible_or_unknown_dates():
    with pytest.raises(ParseError):
        parse_date("31/02/2026")
    with pytest.raises(ParseError):
        parse_date("sometime in April")


def test_financial_year_runs_april_to_march():
    assert financial_year(date(2026, 3, 31)) == "2025-26"
    assert financial_year(date(2026, 4, 1)) == "2026-27"


def test_normalize_invoice_number():
    assert normalize_invoice_number("sis / 26-27 / 0018") == "SIS26270018"
    assert normalize_invoice_number("INV#0042") != normalize_invoice_number("INV#42")
