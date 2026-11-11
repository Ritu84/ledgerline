import json, os, sys, tempfile
os.environ["LLM_PROVIDER"]="fake"; os.environ["DB_PATH"]=os.environ["LEDGERLINE_DB"]=tempfile.mkdtemp()+"/s.db"
from fastapi.testclient import TestClient
from ledgerline import api, db
from ledgerline.config import get_settings
print("db", get_settings().db_path.endswith("s.db"), "provider", get_settings().llm_provider)
c=TestClient(api.app)
up=lambda name: c.post("/api/invoices", files={"file":(name,b"any text","text/plain")}).json()
a=up("a.txt"); i=a["id"]
r1=c.post(f"/api/invoices/{i}/approve", json={"user_id":"asha"}).json()
r2=c.post(f"/api/invoices/{i}/approve", json={"user_id":"asha"}).json()
conn=db.connect(get_settings().db_path)
print("1 approve twice:", r1, r2, "payments:", [tuple(r) for r in conn.execute("select invoice_id, amount from payments where invoice_id=?",(i,))])
print("2 other org reads:", c.get(f"/api/invoices/{i}", headers={"X-Org-Id":"rival"}).status_code, "other org approves:", c.post(f"/api/invoices/{i}/approve", json={"user_id":"x"}, headers={"X-Org-Id":"rival"}).status_code)
b=up("b.txt"); j=b["id"]
conn.execute("update invoices set required_approvals=2 where id=?",(j,)); conn.commit()
print("3 same person twice on 2-approval invoice:", c.post(f"/api/invoices/{j}/approve", json={"user_id":"asha"}).json(), c.post(f"/api/invoices/{j}/approve", json={"user_id":"asha"}).json())
print("4 reject after approve:", c.post(f"/api/invoices/{i}/reject", json={"user_id":"asha"}).json(), "reject missing id 9999:", c.post("/api/invoices/9999/reject", json={"user_id":"asha"}).status_code)
k=up("c.txt")["id"]; conn.execute("update invoices set document_type='credit_note', needs_review=1, review_reasons_json='[\"credit_note\"]', status='needs_review' where id=?",(k,)); conn.commit()
print("5 credit note approve, no note:", c.post(f"/api/invoices/{k}/approve", json={"user_id":"asha"}).json(), [tuple(r) for r in conn.execute("select amount from payments where invoice_id=?",(k,))])
big=c.post("/api/invoices", files={"file":("big.txt",b"x"*5_000_000,"text/plain")}); print("6 5MB upload:", big.status_code)
print("7 stats:", c.get("/api/stats").json())
