// API typings + client for the seed-procurement backend.

export type InventoryRow = {
  sku: string;
  room_id: string;
  on_hand_g: number;
  last_event_ts: string;
  reorder_point_g: number | null;
  target_stock_g: number | null;
};

export type SupplierRow = {
  sku: string;
  supplier_id: string;
  supplier_name: string | null;
  pack_size_g: number | null;
  unit_price_usd: number;
  usd_per_gram: number | null;
  lead_time_days: number;
  min_qty: number;
  organic: boolean | null;
  score: number;
  rank: number;
  quote_ts: string;
};

export type CommodityRow = {
  input_key: string;
  price_usd: number;
  unit: string | null;
  event_ts: string;
  pct_1h: number | null;
  pct_24h: number | null;
};

export type DemandHourRow = {
  sku: string;
  hour_ts: string;
  trays: number;
  grams_req: number;
};

export type RecommendationRow = {
  recommendation_id: string;
  created_ts: string;
  sku: string;
  room_id: string;
  reorder_grams: number;
  recommended_supplier_id: string;
  recommended_supplier_name: string | null;
  pack_size_g: number | null;
  packs: number | null;
  unit_price_usd: number;
  total_cost_usd: number;
  expected_lead_days: number;
  ml_score: number;
  input_pct_24h: number | null;
  decision: "BUY_NOW" | "WAIT" | "REVIEW";
  rationale: string | null;
};

export type Summary = {
  skus_below_reorder: number;
  buy_now_last_5m: number;
  spend_pending_1h_usd: number;
  last_market_tick: string | null;
  po_drafts_open: number;
  inbound_unprocessed: number;
};

export type EmailThread = {
  thread_id: string;
  last_ts: string;
  supplier_id: string;
  supplier_email: string;
  sku: string | null;
  subject: string;
  intent: string | null;
  side: "OUT" | "IN";
};

export type EmailRow = {
  email_id: string;
  thread_id: string;
  ts: string;
  supplier_id: string | null;
  supplier_email: string | null;
  subject: string | null;
  body_md: string | null;
  sku: string | null;
  intent: string | null;
  sent_by: string | null;
  status: string | null;
  side: "OUT" | "IN";
};

export type PoDraft = {
  po_id: string;
  created_ts: string;
  thread_id: string | null;
  sku: string | null;
  supplier_id: string | null;
  packs: number | null;
  pack_size_g: number | null;
  total_grams: number | null;
  unit_price_usd: number | null;
  total_cost_usd: number | null;
  needed_by: string | null;
  status: string | null;
  rationale: string | null;
};

export type BudgetState = {
  period_ym: string;
  balance_usd: number | null;
  last_entry_ts: string | null;
  entries: {
    ledger_id: string;
    entry_ts: string;
    period_ym: string;
    category: string;
    delta_usd: number;
    balance_usd: number;
    po_id: string | null;
    note: string | null;
  }[];
};

export type SupplierApplication = {
  application_id: string;
  submitted_ts: string;
  supplier_name: string | null;
  contact_email: string | null;
  country: string | null;
  offered_skus: string | null;
  organic_cert: boolean | null;
  years_in_biz: number | null;
  status: string | null;
  score: number | null;
  agent_notes: string | null;
};

export type InvoiceReconciliation = {
  reconciliation_id: string;
  received_ts: string;
  po_id: string | null;
  supplier_id: string | null;
  invoiced_amount_usd: number | null;
  expected_amount_usd: number | null;
  variance_usd: number | null;
  variance_pct: number | null;
  status: string | null;
  agent_notes: string | null;
};

export type AgentRun = {
  run_id: string;
  started_ts: string;
  finished_ts: string | null;
  agent_name: string | null;
  input_ref: string | null;
  output_ref: string | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  status: string | null;
  error_msg: string | null;
};

export type SapPoLine = {
  po_number: string;
  po_item: number;
  event_type: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  supplier_tier: string | null;
  sku: string | null;
  quantity_g: number | null;
  unit_price_usd: number | null;
  net_value_usd: number | null;
  delivery_date_ts: string | null;
  qty_received_g: number | null;
  qty_outstanding_g: number | null;
  po_status: "OPEN" | "PARTIALLY_RECEIVED" | "FULLY_RECEIVED" | "CANCELLED" | null;
  event_ts: string | null;
};

export type SapInvoiceMatch = {
  invoice_doc_number: string;
  po_number: string | null;
  po_item: number | null;
  supplier_id: string | null;
  sku: string | null;
  net_amount_usd: number | null;
  po_net_value_usd: number | null;
  gr_qty_g: number | null;
  variance_usd: number | null;
  status: string | null;
  match_status: "MATCHED" | "VARIANCE" | "PENDING_GR" | "NO_PO" | null;
  event_ts: string | null;
};

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function postJSON<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  summary: () => getJSON<Summary>("/api/summary"),
  inventory: () => getJSON<InventoryRow[]>("/api/inventory"),
  leaderboard: (top = 3) => getJSON<SupplierRow[]>(`/api/suppliers/leaderboard?top=${top}`),
  commodity: () => getJSON<CommodityRow[]>("/api/commodity/latest"),
  demand: (hours = 24) => getJSON<DemandHourRow[]>(`/api/demand/hourly?hours=${hours}`),
  recommendations: (limit = 25) =>
    getJSON<RecommendationRow[]>(`/api/recommendations?limit=${limit}`),

  // Agent endpoints
  emailThreads: (limit = 25) => getJSON<EmailThread[]>(`/api/agents/email/threads?limit=${limit}`),
  emailThread: (threadId: string) =>
    getJSON<EmailRow[]>(`/api/agents/email/thread/${encodeURIComponent(threadId)}`),
  poDrafts: (status?: string) =>
    getJSON<PoDraft[]>(`/api/agents/po_drafts${status ? `?status=${status}` : ""}`),
  budget: () => getJSON<BudgetState>("/api/agents/budget"),
  applications: (status?: string) =>
    getJSON<SupplierApplication[]>(
      `/api/agents/applications${status ? `?status=${status}` : ""}`,
    ),
  submitApplication: (body: {
    supplier_name: string;
    contact_email: string;
    country: string;
    offered_skus?: string;
    organic_cert?: boolean;
    years_in_biz?: number;
  }) => postJSON<{ application_id: string; status: string }>("/api/agents/applications", body),
  invoices: (status?: string) =>
    getJSON<InvoiceReconciliation[]>(
      `/api/agents/invoices${status ? `?status=${status}` : ""}`,
    ),
  runs: (limit = 25) => getJSON<AgentRun[]>(`/api/agents/runs?limit=${limit}`),
  sapPoLines: (status?: string, limit = 100) =>
    getJSON<SapPoLine[]>(`/api/sap/po-lines?limit=${limit}${status ? `&status=${status}` : ""}`),
  sapInvoiceMatching: (matchStatus?: string, limit = 100) =>
    getJSON<SapInvoiceMatch[]>(
      `/api/sap/invoice-matching?limit=${limit}${matchStatus ? `&match_status=${matchStatus}` : ""}`,
    ),
  runCycle: () => postJSON<Record<string, unknown>>("/api/agents/cycle"),
  simulateReply: (threadId: string) =>
    postJSON<{ email_id?: string; intent?: string; error?: string }>(
      `/api/agents/negotiator/simulate-reply?thread_id=${encodeURIComponent(threadId)}`,
    ),
  simulateInvoice: (poId?: string) =>
    postJSON<{
      reconciliation_id?: string;
      po_id?: string;
      invoiced_amount_usd?: number;
      expected_amount_usd?: number;
      simulated_variance_pct?: number;
      error?: string;
    }>(
      `/api/agents/invoices/simulate${poId ? `?po_id=${encodeURIComponent(poId)}` : ""}`,
    ),
};
