import { useEffect, useState } from "react";
import { api, type BudgetState } from "../api";

const fmtMoney = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function BudgetPanel({ tick }: { tick: number }) {
  const [state, setState] = useState<BudgetState | null>(null);
  const [amount, setAmount] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [sign, setSign] = useState<"+" | "-">("+");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [localTick, setLocalTick] = useState(0);

  useEffect(() => {
    api.budget().then(setState).catch(() => setState(null));
  }, [tick, localTick]);

  async function submit() {
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setFeedback("Enter a positive number");
      return;
    }
    setBusy(true);
    setFeedback(null);
    try {
      const delta = sign === "+" ? value : -value;
      const res = await api.addBudgetEntry({ delta_usd: delta, note: note || undefined });
      setFeedback(`Saved · new balance ${fmtMoney.format(res.balance_usd)}`);
      setAmount("");
      setNote("");
      setLocalTick(t => t + 1);
    } catch (e: unknown) {
      setFeedback(`Failed: ${(e as Error)?.message ?? "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

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

      <div style={{ display: "flex", gap: 6, alignItems: "center", margin: "8px 0 12px", flexWrap: "wrap" }}>
        <select
          value={sign}
          onChange={e => setSign(e.target.value as "+" | "-")}
          disabled={busy}
          style={{ padding: "6px 8px" }}
        >
          <option value="+">Top-up (+)</option>
          <option value="-">Write-off (−)</option>
        </select>
        <input
          type="number"
          placeholder="Amount USD"
          value={amount}
          onChange={e => setAmount(e.target.value)}
          disabled={busy}
          style={{ padding: "6px 8px", width: 120 }}
        />
        <input
          type="text"
          placeholder="Note (optional)"
          value={note}
          onChange={e => setNote(e.target.value)}
          disabled={busy}
          style={{ padding: "6px 8px", flex: 1, minWidth: 160 }}
        />
        <button className="btn" onClick={submit} disabled={busy || !amount}>
          {busy ? "Saving…" : "Add entry"}
        </button>
        {feedback && <span className="muted small">{feedback}</span>}
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
