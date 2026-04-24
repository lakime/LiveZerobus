import { useEffect, useState } from "react";
import { api, type InventoryRow } from "../api";

const fmt = (n: number) => `${n.toFixed(0)} g`;

export default function InventoryPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<InventoryRow[]>([]);

  useEffect(() => {
    api.inventory().then((r) =>
      setRows(r.filter(x => x.reorder_point_g != null && x.on_hand_g <= (x.reorder_point_g as number))
               .sort((a, b) => a.on_hand_g - b.on_hand_g)
               .slice(0, 10))
    ).catch(() => {});
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No seed lots below reorder point.</p>;

  return (
    <table>
      <thead>
        <tr><th>Seed SKU</th><th>Room</th><th>On hand</th><th>Reorder @</th></tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={`${r.sku}-${r.room_id}`}>
            <td>{r.sku}</td>
            <td>{r.room_id}</td>
            <td className="neg">{fmt(r.on_hand_g)}</td>
            <td className="muted">{r.reorder_point_g != null ? fmt(r.reorder_point_g) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
