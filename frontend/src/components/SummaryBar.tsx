import type { Summary } from "../api";

const fmt = new Intl.NumberFormat("en-US");
const fmtMoney = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export default function SummaryBar({ summary }: { summary: Summary | null }) {
  return (
    <div className="summary">
      <Kpi label="SKUs below reorder" value={summary ? fmt.format(summary.skus_below_reorder) : "—"} />
      <Kpi label="BUY_NOW (last 5m)"   value={summary ? fmt.format(summary.buy_now_last_5m) : "—"} />
      <Kpi label="Pending spend / 1h"  value={summary ? fmtMoney.format(summary.spend_pending_1h_usd) : "—"} />
      <Kpi label="Last market tick"
           value={summary?.last_market_tick ? new Date(summary.last_market_tick).toLocaleTimeString() : "—"} />
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
