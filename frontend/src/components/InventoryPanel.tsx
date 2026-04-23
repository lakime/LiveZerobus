import { useEffect, useState } from "react";
import { api, type InventoryRow } from "../api";

export default function InventoryPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<InventoryRow[]>([]);

  useEffect(() => {
    api.inventory().then((r) =>
      setRows(r.filter(x => x.reorder_point != null && x.on_hand <= x.reorder_point)
               .sort((a, b) => a.on_hand - b.on_hand)
               .slice(0, 10))
    ).catch(() => {});
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No SKUs below reorder point.</p>;

  return (
    <table>
      <thead>
        <tr><th>SKU</th><th>DC</th><th>On hand</th><th>Reorder</th></tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={`${r.sku}-${r.dc_id}`}>
            <td>{r.sku}</td>
            <td>{r.dc_id}</td>
            <td className="neg">{r.on_hand}</td>
            <td className="muted">{r.reorder_point}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
