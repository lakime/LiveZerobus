import { useEffect, useState } from "react";
import { api, type SupplierRow } from "../api";

export default function SupplierLeaderboard({ tick }: { tick: number }) {
  const [rows, setRows] = useState<SupplierRow[]>([]);

  useEffect(() => {
    api.leaderboard(3).then(setRows).catch(() => {});
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No quotes yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>SKU</th><th>Rank</th><th>Supplier</th>
          <th>Price</th><th>Lead</th><th>Min qty</th><th>ML score</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={`${r.sku}-${r.supplier_id}`}>
            <td>{r.sku}</td>
            <td>#{r.rank}</td>
            <td>{r.supplier_name ?? r.supplier_id}</td>
            <td>${r.unit_price_usd.toFixed(2)}</td>
            <td>{r.lead_time_days}d</td>
            <td className="muted">{r.min_qty}</td>
            <td className="pos">{r.score.toFixed(3)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
