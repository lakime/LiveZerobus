import { useEffect, useState } from "react";
import { api, type InvoiceReconciliation } from "../api";

const BADGE: Record<string, string> = {
  NEW: "badge wait", OK: "badge buy",
  REVIEW: "badge wait", DISPUTE: "badge review", PAID: "badge buy",
};

export default function InvoicesPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<InvoiceReconciliation[]>([]);

  useEffect(() => {
    api.invoices().then(setRows).catch(() => setRows([]));
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No invoices to reconcile.</p>;

  return (
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
  );
}
