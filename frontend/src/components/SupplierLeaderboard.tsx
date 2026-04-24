import { useEffect, useState } from "react";
import { api, type SupplierRow } from "../api";

const fmtPack = (p: number | null) => (p != null ? `${p.toFixed(0)}g` : "—");

export default function SupplierLeaderboard({ tick }: { tick: number }) {
  const [rows, setRows] = useState<SupplierRow[]>([]);

  useEffect(() => {
    api.leaderboard(3).then(setRows).catch(() => {});
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No seed quotes yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Seed SKU</th><th>#</th><th>Supplier</th>
          <th>Pack</th><th>Price</th><th>$/g</th>
          <th>Lead</th><th>Organic</th><th>ML</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={`${r.sku}-${r.supplier_id}`}>
            <td>{r.sku}</td>
            <td>#{r.rank}</td>
            <td>{r.supplier_name ?? r.supplier_id}</td>
            <td className="muted">{fmtPack(r.pack_size_g)}</td>
            <td>${r.unit_price_usd.toFixed(2)}</td>
            <td className="muted">{r.usd_per_gram != null ? `$${r.usd_per_gram.toFixed(3)}` : "—"}</td>
            <td>{r.lead_time_days}d</td>
            <td>{r.organic ? "✓" : ""}</td>
            <td className="pos">{r.score.toFixed(3)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
