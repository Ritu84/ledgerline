"""Token pricing for the cost dashboard and the llm_calls table."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# USD per million tokens: (input, output). From the providers' pricing pages.
# Opus 5.5 is $4 in / $20 out per million tokens. The earlier table held per-thousand values under a
# per-million label, which made every reported cost 1000x too low.
USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-3.5-flash-lite": (0.30, 2.50),  # paid tier; output price includes thinking tokens
    "fake": (0.0, 0.0),
}
_warned: set[str] = set()


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in USD_PER_MTOK and model not in _warned:
        _warned.add(model)
        log.warning("No price for model %r: its cost is recorded as 0. Add it to USD_PER_MTOK.", model)
    input_price, output_price = USD_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
