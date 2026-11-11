"""Feature flags for departures from AP_POLICY.md (README Part 2).

Every flag is off by default and switched on with LEDGERLINE_FLAG_<NAME>=1. The policy text stays the
default behaviour; a flag is how a ruling that departs from it ships without quietly changing it.
"""
from __future__ import annotations

import os

# name -> one-line description. Register a flag here before using it so `enabled_flags()` can list it.
KNOWN_FLAGS: dict[str, str] = {
    "LINE_ARITHMETIC": "review a line whose quantity x unit price differs from its amount by more than Rs 1.00 "
                       "(new code line_amount_mismatch; ruling disp_05)",
    "FUTURE_DATE": "review an emailed invoice dated after the email was sent "
                   "(new code invoice_date_in_future; ruling disp_06)",
}


def flag_enabled(name: str) -> bool:
    return os.getenv(f"LEDGERLINE_FLAG_{name.upper()}", "").strip().lower() in {"1", "true", "yes", "on"}


def enabled_flags() -> list[str]:
    return sorted(name for name in KNOWN_FLAGS if flag_enabled(name))
