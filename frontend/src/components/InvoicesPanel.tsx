import { useEffect, useState } from "react";
import { api, type InvoiceReconciliation } from "../api";

const BADGE: Record<string, string> = {
  NEW: "badge wait", OK: "badge buy",
  REVIEW: "badge wait", DISPUTE: "badge review", PAID: "badge buy",
};

export default function InvoicesPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<InvoiceReconciliation[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.invoices().then(setRows).catch(() => setRows([]));
  }, [tick]);

  async function generate() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.simulateInvoice();
      if (r.error) {
        setMsg(r.error);
      } else {
        setMsg(
          `Generated invoice ${r.reconciliation_id} for ${r.po_id} ` +
          `($${r.invoiced_amount_usd?.toFixed(2)} vs expected ` +
          `$${r.expected_amount_usd?.toFixed(2)}). Run agent cycle to reconcile.`
        );
        const refreshed = await api.invoices();
        setRows(refreshed);
      }
    } catch (e: any) {
      setMsg(`Error: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="invoice-actions" style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center" }}>
        <button className="btn" onClick={generate} disabled={busy}>
          {busy ? "Generating…" : "Generate sample invoice"}
        </button>
        {msg && <span className="muted small">{msg}</span>}
      </div>

      {rows.length === 0 ? (
        <p className="muted">
          No invoices yet — click "Generate sample invoice" (you need an APPROVED
          PO first) or run the agent cycle.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Received</th><th>PO</th><th>Supplier</th>
              <th>Invoiced $</th><th>Expected $</th><th>Variance</th>
              <th>Status</th><th>Agent notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.reconciliation_id}>
                <td className="muted small">{new Date(r.received_ts).toLocaleTimeString()}</td>
                <td>{r.po_id}</td>
                <td>{r.supplier_id}</td>
                <td>${r.invoiced_amount_usd?.toFixed(2)}</td>
                <td>{r.expected_amount_usd != null ? `$${r.expected_amount_usd.toFixed(2)}` : "—"}</td>
                <td className={(r.variance_usd ?? 0) < 0 ? "pos" : "neg"}>
                  {r.variance_pct != null ? `${r.variance_pct.toFixed(2)}%` : "—"}
                </td>
                <td><span className={BADGE[r.status ?? ""] ?? "badge review"}>{r.status}</span></td>
                <td className="muted small truncate">{r.agent_notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
