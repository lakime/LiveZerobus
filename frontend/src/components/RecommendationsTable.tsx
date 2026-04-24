import { useEffect, useState } from "react";
import { api, type RecommendationRow } from "../api";

export default function RecommendationsTable({ tick }: { tick: number }) {
  const [rows, setRows] = useState<RecommendationRow[]>([]);

  useEffect(() => {
    api.recommendations(25).then(setRows).catch(() => {});
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No recommendations yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>When</th><th>Seed SKU</th><th>Room</th>
          <th>Reorder</th><th>Packs</th>
          <th>Supplier</th><th>Pack $</th><th>Total $</th>
          <th>Lead</th><th>ML</th><th>Input 24h</th><th>Decision</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.recommendation_id}>
            <td className="muted">{new Date(r.created_ts).toLocaleTimeString()}</td>
            <td>{r.sku}</td>
            <td>{r.room_id}</td>
            <td>{r.reorder_grams.toFixed(0)} g</td>
            <td>{r.packs ?? "—"}</td>
            <td>{r.recommended_supplier_name ?? r.recommended_supplier_id}</td>
            <td>${r.unit_price_usd.toFixed(2)}</td>
            <td>${r.total_cost_usd.toLocaleString()}</td>
            <td>{r.expected_lead_days}d</td>
            <td className="pos">{r.ml_score.toFixed(2)}</td>
            <td className={(r.input_pct_24h ?? 0) >= 0 ? "pos" : "neg"}>
              {r.input_pct_24h != null ? `${(r.input_pct_24h * 100).toFixed(2)}%` : "—"}
            </td>
            <td>
              <span className={
                r.decision === "BUY_NOW" ? "badge buy" :
                r.decision === "WAIT" ? "badge wait" : "badge review"
              }>{r.decision}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
