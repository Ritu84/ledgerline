import json

from ledgerline import cli
from ledgerline.config import get_settings
from ledgerline.llm.fake import FakeClient


def run(tmp_path, input_dir):
    output = tmp_path / "predictions.jsonl"
    cli.main(["predict", "--input", str(input_dir), "--reference", str(get_settings().data_dir / "reference"),
              "--output", str(output)])
    return [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]


def test_every_document_gets_a_line_even_when_the_model_fails(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("b_002.txt", "a_001.txt", "c_003.eml"):
        (docs / name).write_text("INVOICE", encoding="utf-8")
    (docs / "ignore.pdf").write_text("x", encoding="utf-8")
    client = FakeClient(["garbage", "more garbage"])  # a_001 fails twice; the rest get the canned reply
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: client)

    lines = run(tmp_path, docs)

    assert [line["document_id"] for line in lines] == ["a_001", "b_002", "c_003"]
    assert lines[0]["needs_review"] is True
    assert lines[0]["review_reasons"] == ["processing_error"]
    assert lines[1]["review_reasons"] == []
    assert lines[2]["review_reasons"] == ["duplicate"]  # same invoice as b_002, later in the batch


def test_output_matches_the_contract(tmp_path, fake_llm):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "dev_001.txt").write_text("INVOICE", encoding="utf-8")
    line = run(tmp_path, docs)[0]
    assert line["total"] == "23458.00" and line["round_off"] == "-0.40" and line["igst"] == "0.00"
    assert line["invoice_date"] == "2026-04-25"
    assert line["line_items"][0] == {"description": "SS Hex Bolt M10x40 (Box/100)", "quantity": "12",
                                     "unit_price": "1450.00", "amount": "17400.00"}
    assert line["required_approvals"] == 1
    assert set(line["usage"]) == {"llm_calls", "input_tokens", "output_tokens", "cost_inr", "latency_ms"}
