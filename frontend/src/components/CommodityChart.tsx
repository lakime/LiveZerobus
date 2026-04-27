import { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api, type CommodityRow } from "../api";

type Sample = { t: string } & Record<string, number | string>;

const COLORS: Record<string, string> = {
  coco_coir: "#5bc29e",
  peat: "#a07858",
  rockwool: "#c7b3a6",
  nutrient_pack: "#4ea1ff",
  kwh: "#f2b840",
};

export default function CommodityChart({ tick }: { tick: number }) {
  // raw absolute-price samples — used by KPI cards and as the source for the
  // percent-change normalization below.
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

  // Normalize each series to % change vs the first observed sample. Without
  // this, nutrient_pack (~$22) and kwh (~$0.24) share a Y axis and the cheap
  // commodities collapse onto the zero line — so the chart looks flat even
  // when individual prices move several percent.
  const normalized = useMemo(() => {
    if (series.length === 0) return [] as Sample[];
    const baseline: Record<string, number> = {};
    for (const sample of series) {
      for (const [k, v] of Object.entries(sample)) {
        if (k === "t" || baseline[k] !== undefined) continue;
        if (typeof v === "number" && v !== 0) baseline[k] = v;
      }
    }
    return series.map((sample) => {
      const out: Sample = { t: sample.t as string };
      for (const [k, v] of Object.entries(sample)) {
        if (k === "t") continue;
        if (typeof v === "number" && baseline[k]) {
          out[k] = ((v - baseline[k]) / baseline[k]) * 100;
        }
      }
      return out;
    });
  }, [series]);

  const fmtPct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

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

      <div className="muted small" style={{ marginBottom: 4 }}>
        % change since session start — absolute prices shown above
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={normalized} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#263056" />
          <XAxis dataKey="t" stroke="#8a97b8" fontSize={11} tick={{ fill: "#8a97b8" }} />
          <YAxis
            stroke="#8a97b8"
            fontSize={11}
            tick={{ fill: "#8a97b8" }}
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
            domain={["auto", "auto"]}
          />
          <ReferenceLine y={0} stroke="#3b4670" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{ background: "#141a2f", border: "1px solid #263056" }}
            formatter={(value: number, name: string) => [fmtPct(value), name]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {inputs.map(c => (
            <Line
              key={c}
              dataKey={c}
              stroke={COLORS[c] ?? "#4ea1ff"}
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}
