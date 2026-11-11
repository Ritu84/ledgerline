export const ORG_ID = "meridian";
export const USERS = ["kavya.iyer", "arjun.mehta", "neha.kulkarni"];

// Amounts arrive as two-decimal strings ("23458.00") and are never converted to floating point.
export type InvoiceSummary = {
  id: number;
  document_id: string;
  document_type: string | null;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  total: string | null;
  status: string;
  needs_review: boolean;
  required_approvals: number;
};

export type LineItem = {
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
};

export type Approval = { user_id: string; note: string | null; created_at: string };
export type AuditEntry = { actor: string; action: string; note: string | null; created_at: string };

export type Invoice = InvoiceSummary & {
  raw_text: string;
  supplier_gstin: string | null;
  subtotal: string | null;
  cgst: string | null;
  sgst: string | null;
  igst: string | null;
  round_off: string | null;
  bank_account: string | null;
  ifsc: string | null;
  po_number: string | null;
  notes: string | null;
  line_items: LineItem[];
  warnings: string[];
  review_reasons: string[];
  approvals: Approval[];
  payment: { amount: string; currency: string | null; created_at: string } | null;
  audit_log: AuditEntry[];
};

export type DecisionResult = {
  id: number;
  status: string;
  approvals: number;
  required_approvals: number;
};

const orgHeaders = { "X-Org-Id": ORG_ID };

// Every call goes through here so a failed request is an error the UI shows, never a silent success.
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...orgHeaders, ...init.headers } });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON: keep the status code
    }
    throw new Error(detail);
  }
  return response.json();
}

export const listInvoices = () => request<InvoiceSummary[]>("/api/invoices");
export const getInvoice = (id: number) => request<Invoice>(`/api/invoices/${id}`);

export function uploadInvoice(file: File): Promise<Invoice> {
  const body = new FormData();
  body.append("file", file);
  return request<Invoice>("/api/invoices", { method: "POST", body });
}

function decide(id: number, action: "approve" | "reject", user: string, note: string): Promise<DecisionResult> {
  return request<DecisionResult>(`/api/invoices/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: user, note }),
  });
}

export const approveInvoice = (id: number, user: string, note: string) => decide(id, "approve", user, note);
export const rejectInvoice = (id: number, user: string, note: string) => decide(id, "reject", user, note);
