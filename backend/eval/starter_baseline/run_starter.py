"""Starter over the dev set, with every model reply recorded.
variant: asis | noleak  (examples removed);  add "+fence" to strip ``` fences before the starter parses the reply."""
import json, os, sys, time, tempfile, re
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(os.environ.get("LEDGERLINE_ENV", ".env"))
variant, out = sys.argv[1], sys.argv[2]
from ledgerline import db, extraction
from ledgerline.config import get_settings
from ledgerline.pipeline import process_document
from ledgerline.reference import load_reference
if "noleak" in variant:
    extraction._few_shot_examples = lambda limit=3: "(none)"
fence = "+fence" in variant
real = extraction.get_client()
LOG = []
class Wrap:
    def complete(self, system, prompt, max_tokens=2000):
        r = real.complete(system, prompt, max_tokens)
        LOG.append({"in": r.input_tokens, "out": r.output_tokens, "ms": r.latency_ms, "head": r.text[:40],
                    "fenced": r.text.lstrip().startswith("```"), "prompt_chars": len(prompt)})
        if fence:
            m = re.search(r"```(?:json)?\s*(.*?)\s*```", r.text, re.S)
            if m: r.text = m.group(1)
        return r
extraction.get_client = lambda: Wrap()
s = get_settings(); ref = load_reference()
conn = db.connect(str(Path(tempfile.mkdtemp()) / "starter.db"))
rows = [json.loads(l) for l in open(s.data_dir / "ground_truth" / "dev.jsonl", encoding="utf-8")]
with open(out, "w") as f:
    for row in rows:
        text = (s.data_dir / "invoices" / "dev" / row["filename"]).read_text(encoding="utf-8")
        rec = {"document_id": row["document_id"], "transport_retries": 0}
        for attempt in range(4):
            LOG.clear(); t = time.time(); rec.pop("error", None)
            try:
                rec["got"] = process_document(conn, ref, text, row["document_id"]); break
            except Exception as exc:
                rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
                if "HTTPStatusError" in rec["error"] or "Timeout" in rec["error"]:
                    rec["transport_retries"] += 1; time.sleep(5); continue
                break
        rec["seconds"] = round(time.time() - t, 2); rec["calls"] = list(LOG)
        f.write(json.dumps(rec, default=str) + "\n"); f.flush()
        print(row["document_id"], "ERR " + rec["error"][:80] if "error" in rec else "ok", rec["seconds"], flush=True)
