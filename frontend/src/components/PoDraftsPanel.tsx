import { useEffect, useState } from "react";
import { api, type PoDraft } from "../api";

const BADGE: Record<string, string> = {
  DRAFT: "badge wait", APPROVED: "badge buy", REJECTED: "badge review",
  SENT: "badge buy", RECEIVED: "badge buy",
};

export default function PoDraftsPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<PoDraft[]>([]);

  useEffect(() => {
    api.poDrafts().then(setRows).catch(() => setRows([]));
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No PO drafts yet — run a cycle.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Created</th><th>PO</th><th>SKU</th><th>Supplier</th>
          <th>Packs</th><th>Total g</th><th>Unit $</th><th>Total $</th>
          <th>Needed by</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.po_id}>
            <td className="muted">{new Date(r.created_ts).toLocaleTimeString()}</td>
            <td>{r.po_id}</td>
            <td>{r.sku}</td>
            <td>{r.supplier_id}</td>
            <td>{r.packs}</td>
            <td>{r.total_grams?.toFixed(0)}</td>
            <td>${r.unit_price_usd?.toFixed(2)}</td>
            <td>${r.total_cost_usd?.toLocaleString()}</td>
            <td>{r.needed_by ?? "—"}</td>
            <td>
              <span className={BADGE[r.status ?? ""] ?? "badge review"}>
                {r.status ?? "?"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
