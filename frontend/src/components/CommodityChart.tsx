import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer } from "recharts";
import { api, type CommodityRow } from "../api";

type Sample = { t: string } & Record<string, number | string>;

export default function CommodityChart({ tick }: { tick: number }) {
  const [series, setSeries] = useState<Sample[]>([]);
  const [latest, setLatest] = useState<CommodityRow[]>([]);

  useEffect(() => {
    api.commodity().then((rows) => {
      setLatest(rows);
      const t = new Date().toLocaleTimeString();
      setSeries((prev) => {
        const next = prev.slice(-59);
        const sample: Sample = { t };
        for (const r of rows) sample[r.input_key] = r.price_usd;
        next.push(sample);
        return next;
      });
    }).catch(() => {});
  }, [tick]);

  const inputs = latest.map(r => r.input_key);
  const colors: Record<string, string> = {
    coco_coir: "#5bc29e", peat: "#a07858", rockwool: "#c7b3a6",
    nutrient_pack: "#4ea1ff", kwh: "#f2b840",
  };

  return (
    <>
      <div style={{ display: "flex", gap: 18, marginBottom: 8, flexWrap: "wrap" }}>
        {latest.map(r => (
          <div key={r.input_key}>
            <div className="muted" style={{ fontSize: 11, textTransform: "uppercase" }}>
              {r.input_key}{r.unit ? ` · ${r.unit}` : ""}
            </div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>
              ${r.price_usd.toFixed(2)}{" "}
              <span className={(r.pct_24h ?? 0) >= 0 ? "pos" : "neg"} style={{ fontSize: 12 }}>
                {r.pct_24h != null ? `${(r.pct_24h * 100).toFixed(2)}%` : "—"}
              </span>
            </div>
          </div>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={series} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#263056" />
          <XAxis dataKey="t" stroke="#8a97b8" fontSize={11} tick={{ fill: "#8a97b8" }} />
          <YAxis stroke="#8a97b8" fontSize={11} tick={{ fill: "#8a97b8" }} />
          <Tooltip contentStyle={{ background: "#141a2f", border: "1px solid #263056" }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {inputs.map(c => (
            <Line key={c} dataKey={c} stroke={colors[c] ?? "#4ea1ff"} dot={false} strokeWidth={2} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}
