import json,sys,statistics
S=sys.argv[1]
truth={}
for l in open(sys.argv[1] + "/../../../data/ground_truth/dev.jsonl"):
    r=json.loads(l); truth[r["document_id"]]=r["expected"]
FIELDS=["document_type","supplier_name","supplier_gstin","invoice_number","invoice_date","currency","subtotal","cgst","sgst","igst","total","po_number"]
def n(v):
    if v is None: return ""
    try: return f"{float(v):.2f}"
    except (TypeError,ValueError): return str(v).strip().lower()
def pct(vals,p):
    o=sorted(vals); return o[min(len(o)-1,round(p/100*(len(o)-1)))] if o else 0
for v in sys.argv[2:]:
    rows=[json.loads(l) for l in open(f"{S}/{v}.jsonl")]
    print("=====",v,"docs",len(rows))
    ok=[r for r in rows if "got" in r]; bad=[r for r in rows if "got" not in r]
    print("failed:",[(r["document_id"],r["error"][:60]) for r in bad])
    def score(ids):
        c=t=0; wrong=[]
        for r in rows:
            if r["document_id"] not in ids: continue
            e=truth[r["document_id"]]
            for f in FIELDS:
                t+=1
                if "got" in r and n(r["got"].get(f))==n(e.get(f)): c+=1
                else: wrong.append((r["document_id"],f,(r.get("got") or {}).get(f),e.get(f)))
        return c,t,wrong
    okids={r["document_id"] for r in ok}; allids=set(truth)
    c,t,w=score(okids); print(f"starter metric (failures skipped): {c}/{t} = {c/t:.1%}" if t else "none ok")
    c,t,w=score(allids); print(f"all 24, failures counted: {c}/{t} = {c/t:.1%}")
    ex=allids-{"dev_001","dev_002","dev_003"}
    c2,t2,w2=score(ex); print(f"without the 3 example docs, failures counted: {c2}/{t2} = {c2/t2:.1%}")
    c3,t3,_=score({"dev_001","dev_002","dev_003"}); print(f"the 3 example docs only: {c3}/{t3}")
    for x in w: 
        if x[2] is not None or x[0] in okids: print("   wrong",x)
    need=[d for d,e in truth.items() if e["needs_review"]]
    missed=[];extra=[];reason_ok=0;appr_ok=0
    for r in rows:
        e=truth[r["document_id"]]; g=r.get("got")
        if g is None:
            if e["needs_review"]: missed.append(r["document_id"]+"(dropped)")
            continue
        nr=bool(g.get("needs_review"))
        if e["needs_review"] and not nr: missed.append(r["document_id"])
        if nr and not e["needs_review"]: extra.append(r["document_id"])
        rs=g.get("review_reasons") or []
        if sorted(rs)==sorted(e["review_reasons"]): reason_ok+=1
        else: print("   reasons",r["document_id"],"got",rs,"want",e["review_reasons"])
        if g.get("required_approvals")==e["required_approvals"]: appr_ok+=1
        else: print("   approvals",r["document_id"],"got",g.get("required_approvals"),"want",e["required_approvals"],g.get("total"),g.get("currency"),g.get("document_type"))
    print(f"need review {len(need)}; missed {len(missed)}: {missed}; unnecessary {len(extra)}: {extra}; reasons exact {reason_ok}/24; approvals {appr_ok}/24")
    calls=[c for r in rows for c in r["calls"]]
    if calls and "in" in calls[0]:
        tin=sum(c["in"] for c in calls); tout=sum(c["out"] for c in calls)
        usd=tin*0.30/1e6+tout*2.50/1e6
        print(f"calls {len(calls)} in {tin} out {tout} usd {usd:.4f} inr {usd*88:.2f} per doc inr {usd*88/24:.3f}; fenced {sum(c['fenced'] for c in calls)}; prompt chars avg {statistics.mean(c['prompt_chars'] for c in calls):.0f}")
        # opus pricing 5/25 per M as delivered default
        lat=[sum(c["ms"] for c in r["calls"]) for r in rows if r["calls"]]
        print("latency per doc ms p50",pct(lat,50),"p95",pct(lat,95),"max",max(lat))
        print("transport retries",sum(r.get("transport_retries",0) for r in rows))
