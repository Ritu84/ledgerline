import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import {
  approveInvoice,
  getInvoice,
  listInvoices,
  rejectInvoice,
  uploadInvoice,
  USERS,
  type Invoice,
  type InvoiceSummary,
} from "./api";

const POLL_MS = 3000;

const REASON_TEXT: Record<string, string> = {
  processing_error: "The document could not be read reliably",
  credit_note: "Credit note: cannot be approved for payment",
  duplicate: "Duplicate of an invoice already paid or already in the queue",
  gstin_invalid: "Supplier GSTIN is missing or fails its checksum",
  vendor_unknown: "Supplier is not in the vendor master",
  vendor_new: "Supplier was onboarded less than 90 days before this invoice",
  bank_details_changed: "Bank details differ from the vendor master",
  tax_type_mismatch: "Wrong GST type for the supplier's state",
  totals_mismatch: "Lines, tax and round-off do not add up to the total",
  foreign_currency: "Foreign currency invoice",
  suspicious_content: "Contains text addressed to software, or markup",
  line_amount_mismatch: "A line's quantity × rate does not match its amount",
  invoice_date_in_future: "Invoice is dated after the email that sent it",
};

// Group the digits of a decimal string without ever turning it into a floating-point number.
function money(value: string | null | undefined, currency: string | null) {
  if (value === null || value === undefined || value === "") return "–";
  const negative = value.startsWith("-");
  const [whole, fraction = "00"] = value.replace("-", "").split(".");
  const indian = currency === "INR" || currency === null;
  let grouped: string;
  if (indian && whole.length > 3) {
    grouped = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + whole.slice(-3);
  } else {
    grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  const symbol = indian ? "₹" : currency === "USD" ? "$" : `${currency} `;
  return `${negative ? "-" : ""}${symbol}${grouped}.${fraction}`;
}

const label = (status: string) => status.replace(/_/g, " ");
const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

export default function App() {
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [user, setUser] = useState(USERS[0]);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setInvoices(await listInvoices());
    } catch (e) {
      setError(`Couldn't load the queue: ${errorText(e)}`);
    }
  }, []);

  // Keep the queue fresh. The timer is cleared on unmount, so only one ever runs.
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  async function open(id: number) {
    setNote("");
    setMessage("");
    setError("");
    try {
      setSelected(await getInvoice(id));
    } catch (e) {
      setError(`Couldn't open the document: ${errorText(e)}`);
    }
  }

  async function onUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError("");
    setMessage(`Processing ${file.name}…`);
    try {
      setSelected(await uploadInvoice(file));
      setNote("");
      setMessage(`Processed ${file.name}`);
      refresh();
    } catch (e) {
      setMessage("");
      setError(`Couldn't process ${file.name}: ${errorText(e)}`);
    }
  }

  async function decide(action: "approve" | "reject") {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (action === "approve") {
        const result = await approveInvoice(selected.id, user, note);
        setMessage(
          result.status === "approved"
            ? `Approved (${result.approvals} of ${result.required_approvals}). Payment instruction created.`
            : `Approval recorded (${result.approvals} of ${result.required_approvals}). Waiting for another approver.`,
        );
      } else {
        await rejectInvoice(selected.id, user, note);
        setMessage("Document rejected");
      }
      setNote("");
      setSelected(await getInvoice(selected.id));
      refresh();
    } catch (e) {
      // Nothing was recorded. Say so, and leave the note in place to try again.
      setError(`Not ${action === "approve" ? "approved" : "rejected"}: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const reasons = selected?.review_reasons ?? [];
  const decided = selected?.status === "approved" || selected?.status === "rejected";
  const alreadyApprovedByUser = selected?.approvals.some((a) => a.user_id === user) ?? false;
  let blocked = "";
  if (selected) {
    if (selected.document_type === "credit_note") blocked = "Credit notes cannot be approved for payment.";
    else if (reasons.includes("duplicate")) blocked = "Duplicates cannot be approved, only rejected.";
    else if (reasons.includes("processing_error")) blocked = "This document could not be read reliably, so it cannot be approved here.";
    else if (alreadyApprovedByUser && !decided) blocked = `${user} has already approved. A different person must give the next approval.`;
  }
  const noteNeededToApprove = selected?.needs_review ?? false;

  return (
    <div className="app">
      <header className="topbar">
        <h1>Ledgerline</h1>
        <span className="org">Meridian Precision Components</span>
        <label className="user">
          Signed in as{" "}
          <select value={user} onChange={(e) => setUser(e.target.value)}>
            {USERS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>
        <label className="upload">
          Upload document
          <input type="file" accept=".txt,.eml,.json" onChange={onUpload} />
        </label>
      </header>
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="message" role="status">
          {message}
        </p>
      )}

      <main className="layout">
        <section className="queue" aria-label="Documents">
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Invoice</th>
                <th className="num">Total</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} onClick={() => open(inv.id)} className={selected?.id === inv.id ? "active" : ""}>
                  <td>
                    {inv.supplier_name ?? "Unknown supplier"}
                    <small>{inv.document_id}</small>
                  </td>
                  <td>
                    {inv.invoice_number ?? "–"}
                    <small>{inv.invoice_date}</small>
                  </td>
                  <td className="num">{money(inv.total, inv.currency)}</td>
                  <td>
                    <span className={`badge ${inv.status}`}>{label(inv.status)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {invoices.length === 0 && <p className="empty">No documents yet. Upload one from data/invoices/dev.</p>}
        </section>

        <section className="detail" aria-label="Selected document">
          {selected ? (
            <>
              <h2>
                {selected.supplier_name ?? "Unknown supplier"}{" "}
                {selected.document_type === "credit_note" && <span className="badge needs_review">credit note</span>}
              </h2>
              <dl className="fields">
                <dt>GSTIN</dt>
                <dd>{selected.supplier_gstin ?? "–"}</dd>
                <dt>Invoice number</dt>
                <dd>{selected.invoice_number ?? "–"}</dd>
                <dt>Date</dt>
                <dd>{selected.invoice_date ?? "–"}</dd>
                <dt>PO</dt>
                <dd>{selected.po_number ?? "–"}</dd>
                <dt>Subtotal</dt>
                <dd>{money(selected.subtotal, selected.currency)}</dd>
                <dt>CGST</dt>
                <dd>{money(selected.cgst, selected.currency)}</dd>
                <dt>SGST</dt>
                <dd>{money(selected.sgst, selected.currency)}</dd>
                <dt>IGST</dt>
                <dd>{money(selected.igst, selected.currency)}</dd>
                <dt>Round-off</dt>
                <dd>{money(selected.round_off, selected.currency)}</dd>
                <dt>Total</dt>
                <dd className="total">{money(selected.total, selected.currency)}</dd>
                <dt>Bank</dt>
                <dd>
                  {selected.bank_account ?? "–"} {selected.ifsc}
                </dd>
              </dl>

              {reasons.length > 0 && (
                <div className="callout review">
                  <h3>Needs review</h3>
                  <ul>
                    {reasons.map((reason) => (
                      <li key={reason}>
                        {REASON_TEXT[reason] ?? reason} <code>{reason}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {selected.warnings.length > 0 && (
                <div className="callout warning">
                  <h3>What the checks found</h3>
                  <ul>
                    {selected.warnings.map((warning, i) => (
                      <li key={i}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
              {selected.notes && (
                <div className="callout">
                  <h3>Notes on the document</h3>
                  {/* Supplier text is untrusted: rendered as plain text, never as HTML. */}
                  <p className="supplier-note">{selected.notes}</p>
                </div>
              )}

              <h3>Line items</h3>
              <table className="lines">
                <thead>
                  <tr>
                    <th>Description</th>
                    <th className="num">Qty</th>
                    <th className="num">Rate</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.line_items.map((item, i) => (
                    <tr key={i}>
                      <td>{item.description}</td>
                      <td className="num">{item.quantity ?? "–"}</td>
                      <td className="num">{money(item.unit_price, selected.currency)}</td>
                      <td className="num">{money(item.amount, selected.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h3>Original document</h3>
              <pre className="document">{selected.raw_text}</pre>

              <div className="decision">
                <p className="hint">
                  Status: {label(selected.status)}. Approvals: {selected.approvals.length} of{" "}
                  {selected.required_approvals}
                  {selected.approvals.length > 0 && ` (${selected.approvals.map((a) => a.user_id).join(", ")})`}.
                  {selected.payment &&
                    ` Payment instruction created for ${money(selected.payment.amount, selected.payment.currency)}.`}
                </p>
                {!decided && (
                  <>
                    {blocked && <p className="hint blocked">{blocked}</p>}
                    <textarea
                      aria-label="Note for the audit log"
                      placeholder={
                        noteNeededToApprove
                          ? "Note for the audit log (required: this document needed review)"
                          : "Note for the audit log (required to reject)"
                      }
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <div className="actions">
                      <button
                        onClick={() => decide("approve")}
                        disabled={busy || blocked !== "" || (noteNeededToApprove && note.trim() === "")}
                      >
                        Approve
                      </button>
                      <button
                        className="secondary"
                        onClick={() => decide("reject")}
                        disabled={busy || note.trim() === ""}
                      >
                        Reject
                      </button>
                    </div>
                  </>
                )}
              </div>

              <h3>Audit log</h3>
              <ul className="audit">
                {selected.audit_log.map((entry, i) => (
                  <li key={i}>
                    <span className="when">{entry.created_at} UTC</span> <strong>{entry.actor}</strong>{" "}
                    {label(entry.action)}
                    {entry.note && entry.action !== "processed" && <>: {entry.note}</>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="empty">Choose a document from the queue to review it.</p>
          )}
        </section>
      </main>
    </div>
  );
}
