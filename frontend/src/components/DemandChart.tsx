import { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";
import { api, type DemandHourRow } from "../api";

export default function DemandChart({ tick }: { tick: number }) {
  const [rows, setRows] = useState<DemandHourRow[]>([]);

  useEffect(() => {
    api.demand(24).then(setRows).catch(() => {});
  }, [tick]);

  const data = useMemo(() => {
    const byHour = new Map<string, number>();
    for (const r of rows) {
      const k = new Date(r.hour_ts).toLocaleTimeString([], { hour: "2-digit" });
      byHour.set(k, (byHour.get(k) ?? 0) + r.trays);
    }
    return Array.from(byHour, ([hour, trays]) => ({ hour, trays }));
  }, [rows]);

  if (data.length === 0) return <p className="muted">Waiting for planting data…</p>;

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#263056" />
        <XAxis dataKey="hour" stroke="#8a97b8" fontSize={11} tick={{ fill: "#8a97b8" }} />
        <YAxis stroke="#8a97b8" fontSize={11} tick={{ fill: "#8a97b8" }} />
        <Tooltip contentStyle={{ background: "#141a2f", border: "1px solid #263056" }} />
        <Bar dataKey="trays" fill="#5bc29e" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
