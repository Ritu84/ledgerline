"""The policy code, run over the labelled dev documents with their labelled fields (no LLM).

This separates "did we apply the policy correctly" from "did the model read the page correctly".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from run_eval import evaluate  # noqa: E402

from ledgerline.llm.pricing import cost_usd  # noqa: E402


def test_policy_checks_agree_with_every_dev_label():
    result = evaluate(policy_only=True, verbose=False)
    assert result["wrong"] == []
    assert result["missed_review"] == []
    assert result["routing_exact_match"] == 1.0
    assert result["required_approvals_accuracy"] == 1.0


def test_prices_are_per_million_tokens():
    # Opus 5.5: $4 per million input tokens, $20 per million output tokens.
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == 4.0
    assert cost_usd("claude-opus-5-5", 0, 1_000_000) == 20.0
