import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledgerline import db
from ledgerline.api import app
from ledgerline.llm.fake import FakeClient

KAVYA = {"user_id": "kavya", "note": "ok"}


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("LEDGERLINE_DB", str(tmp_path / "api.db"))
    return TestClient(app)


def upload(client, name="dev_001.txt", **headers):
    response = client.post("/api/invoices", files={"file": (name, b"some invoice text", "text/plain")},
                           headers=headers)
    assert response.status_code == 200
    return response.json()


def upload_changed(client, monkeypatch, canned, **changes):
    canned.update(changes)
    llm = FakeClient([json.dumps(canned)])
    monkeypatch.setattr("ledgerline.extraction.get_client", lambda: llm)
    return upload(client)


def payments(tmp_path):
    conn = db.connect(str(tmp_path / "api.db"))
    try:
        return [dict(r) for r in conn.execute("SELECT invoice_id, amount FROM payments")]
    finally:
        conn.close()


def test_upload_list_get_approve(client):
    invoice_id = upload(client)["id"]

    listed = client.get("/api/invoices").json()
    assert [row["id"] for row in listed] == [invoice_id]

    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["invoice_number"] == "SIS/26-27/0042"

    approved = client.post(f"/api/invoices/{invoice_id}/approve", json=KAVYA)
    assert approved.json()["status"] == "approved"


def test_stats_counts_processed_documents(client):
    upload(client, "a.txt")
    assert client.get("/api/stats").json()["invoices_processed"] == 1


def test_approving_twice_creates_one_payment(client, tmp_path):
    invoice_id = upload(client)["id"]
    for _ in range(3):
        response = client.post(f"/api/invoices/{invoice_id}/approve", json=KAVYA)
        assert response.status_code == 200
        assert response.json()["approvals"] == 1
    assert payments(tmp_path) == [{"invoice_id": invoice_id, "amount": "23458.00"}]


def test_high_value_invoice_needs_two_different_people(client, tmp_path, monkeypatch, canned):
    invoice = upload_changed(client, monkeypatch, canned, subtotal="5,00,000.00", cgst="0.00", sgst="0.00",
                             round_off="0.00", total="5,00,000.00",
                             line_items=[{"description": "Press", "quantity": "1", "unit_price": "5,00,000.00",
                                          "amount": "5,00,000.00"}])
    assert invoice["required_approvals"] == 2
    url = f"/api/invoices/{invoice['id']}/approve"

    assert client.post(url, json=KAVYA).json()["status"] == "ready_for_approval"
    again = client.post(url, json=KAVYA).json()  # the same person again counts once
    assert (again["approvals"], again["status"]) == (1, "ready_for_approval")
    shouted = client.post(url, json={"user_id": " KAVYA ", "note": ""}).json()  # so does the same name in capitals
    assert (shouted["approvals"], shouted["status"]) == (1, "ready_for_approval")
    assert payments(tmp_path) == []

    done = client.post(url, json={"user_id": "arjun", "note": ""}).json()
    assert (done["approvals"], done["status"]) == (2, "approved")
    assert len(payments(tmp_path)) == 1


def test_duplicate_cannot_be_approved_but_can_be_rejected(client, tmp_path):
    upload(client)
    duplicate = upload(client)
    assert duplicate["review_reasons"] == ["duplicate"]
    approve = client.post(f"/api/invoices/{duplicate['id']}/approve", json=KAVYA)
    assert approve.status_code == 409
    assert payments(tmp_path) == []
    reject = client.post(f"/api/invoices/{duplicate['id']}/reject", json={"user_id": "kavya", "note": "paid already"})
    assert reject.json()["status"] == "rejected"


def test_credit_note_cannot_be_approved(client, monkeypatch, canned):
    credit = upload_changed(client, monkeypatch, canned, document_type="credit_note")
    assert credit["required_approvals"] == 0
    assert client.post(f"/api/invoices/{credit['id']}/approve", json=KAVYA).status_code == 409


def test_reviewed_document_needs_a_note_to_approve(client, monkeypatch, canned):
    flagged = upload_changed(client, monkeypatch, canned, total="99,999.00")
    url = f"/api/invoices/{flagged['id']}/approve"
    assert client.post(url, json={"user_id": "kavya", "note": "  "}).status_code == 422
    assert client.post(url, json={"user_id": "kavya", "note": "checked with vendor"}).json()["status"] == "approved"


def test_rejected_invoice_cannot_then_be_approved(client, tmp_path):
    invoice_id = upload(client)["id"]
    assert client.post(f"/api/invoices/{invoice_id}/reject", json={"user_id": "kavya", "note": "wrong PO"}).status_code == 200
    assert client.post(f"/api/invoices/{invoice_id}/approve", json=KAVYA).status_code == 409
    assert payments(tmp_path) == []


def test_approved_invoice_cannot_be_rejected(client):
    invoice_id = upload(client)["id"]
    client.post(f"/api/invoices/{invoice_id}/approve", json=KAVYA)
    assert client.post(f"/api/invoices/{invoice_id}/reject", json={"user_id": "arjun", "note": "no"}).status_code == 409
    assert client.get(f"/api/invoices/{invoice_id}").json()["status"] == "approved"


def test_unknown_invoice_is_404_for_every_action(client):
    assert client.get("/api/invoices/999").status_code == 404
    assert client.post("/api/invoices/999/approve", json=KAVYA).status_code == 404
    assert client.post("/api/invoices/999/reject", json=KAVYA).status_code == 404


def test_another_org_cannot_see_or_decide_an_invoice(client, tmp_path):
    invoice_id = upload(client)["id"]
    other = {"X-Org-Id": "someone-else"}
    assert client.get(f"/api/invoices/{invoice_id}", headers=other).status_code == 404
    assert client.get("/api/invoices", headers=other).json() == []
    assert client.post(f"/api/invoices/{invoice_id}/approve", json=KAVYA, headers=other).status_code == 404
    assert client.post(f"/api/invoices/{invoice_id}/reject", json=KAVYA, headers=other).status_code == 404
    assert payments(tmp_path) == []
    assert client.get(f"/api/invoices/{invoice_id}").json()["status"] == "ready_for_approval"


def test_decisions_are_written_to_the_audit_log(client):
    invoice_id = upload(client)["id"]
    client.post(f"/api/invoices/{invoice_id}/approve", json={"user_id": "kavya", "note": "matches PO"})
    log = client.get(f"/api/invoices/{invoice_id}").json()["audit_log"]
    assert [(e["actor"], e["action"]) for e in log] == [
        ("system", "processed"), ("kavya", "approved"), ("system", "payment_created")]
    assert log[1]["note"] == "matches PO"
    assert log[1]["created_at"]


def test_upload_that_is_not_text_is_refused(client):
    response = client.post("/api/invoices", files={"file": ("x.txt", b"\xff\xfe\x00bad", "text/plain")})
    assert response.status_code == 400


def test_cors_does_not_allow_any_origin(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_an_id_too_large_for_the_database_is_refused_not_a_crash(client):
    huge = 10**20
    assert client.get(f"/api/invoices/{huge}").status_code == 422
    assert client.post(f"/api/invoices/{huge}/approve", json=KAVYA).status_code == 422


def test_einvoice_saved_with_a_byte_order_mark_is_parsed_without_the_model(client, fake_llm):
    einvoice = (Path(__file__).resolve().parents[2] / "data/invoices/dev/dev_006.json").read_bytes()
    response = client.post("/api/invoices", files={"file": ("e.json", b"\xef\xbb\xbf" + einvoice, "application/json")})
    assert response.status_code == 200
    assert response.json()["invoice_number"] == "KT/2026/118"
    assert fake_llm.calls == []
