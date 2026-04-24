import { useEffect, useState } from "react";
import { api, type BudgetState } from "../api";

const fmtMoney = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function BudgetPanel({ tick }: { tick: number }) {
  const [state, setState] = useState<BudgetState | null>(null);

  useEffect(() => {
    api.budget().then(setState).catch(() => setState(null));
  }, [tick]);

  if (!state) return <p className="muted">No budget yet.</p>;

  return (
    <div>
      <div className="budget-top">
        <div>
          <div className="muted small">Period</div>
          <div className="value">{state.period_ym}</div>
        </div>
        <div>
          <div className="muted small">Remaining (SEED)</div>
          <div className="value">
            {state.balance_usd != null ? fmtMoney.format(state.balance_usd) : "—"}
          </div>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>When</th><th>Δ</th><th>Balance</th><th>PO</th><th>Note</th></tr>
        </thead>
        <tbody>
          {state.entries.map(e => (
            <tr key={e.ledger_id}>
              <td className="muted small">{new Date(e.entry_ts).toLocaleTimeString()}</td>
              <td className={e.delta_usd < 0 ? "neg" : "pos"}>
                {fmtMoney.format(e.delta_usd)}
              </td>
              <td>{fmtMoney.format(e.balance_usd)}</td>
              <td className="muted small">{e.po_id ?? ""}</td>
              <td className="muted small truncate">{e.note ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
