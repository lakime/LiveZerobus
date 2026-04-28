import { useEffect, useState } from "react";
import { api, type Summary } from "./api";
import SummaryBar from "./components/SummaryBar";
import InventoryPanel from "./components/InventoryPanel";
import SupplierLeaderboard from "./components/SupplierLeaderboard";
import CommodityChart from "./components/CommodityChart";
import DemandChart from "./components/DemandChart";
import RecommendationsTable from "./components/RecommendationsTable";
import EmailPanel from "./components/EmailPanel";
import PoDraftsPanel from "./components/PoDraftsPanel";
import BudgetPanel from "./components/BudgetPanel";
import OnboardingPanel from "./components/OnboardingPanel";
import InvoicesPanel from "./components/InvoicesPanel";
import AgentRunsPanel from "./components/AgentRunsPanel";
import SapPanel from "./components/SapPanel";

const REFRESH_MS = 3000;

type Tab = "dashboard" | "emails" | "po" | "onboarding" | "invoices" | "runs" | "sap";

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tick, setTick] = useState(0);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, [tick]);

  async function runCycle() {
    setBusy(true);
    try { await api.runCycle(); }
    catch { /* ignore — the dashboard will reveal failures */ }
    finally {
      setBusy(false);
      setTick(t => t + 1);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>LiveZerobus — Vertical-Farm Seed Procurement</h1>
        <div className="header-right">
          <button className="btn" onClick={runCycle} disabled={busy}>
            {busy ? "Running agents…" : "Run agent cycle"}
          </button>
          <span className="live">● LIVE · {new Date().toLocaleTimeString()}</span>
        </div>
      </header>

      <SummaryBar summary={summary} />

      <nav className="tabs">
        <Tab id="dashboard"  on={tab} onSet={setTab}>Dashboard</Tab>
        <Tab id="emails"     on={tab} onSet={setTab}>Emails</Tab>
        <Tab id="po"         on={tab} onSet={setTab}>POs &amp; Budget</Tab>
        <Tab id="onboarding" on={tab} onSet={setTab}>Supplier onboarding</Tab>
        <Tab id="invoices"   on={tab} onSet={setTab}>Invoices</Tab>
        <Tab id="runs"       on={tab} onSet={setTab}>Agent runs</Tab>
        <Tab id="sap"        on={tab} onSet={setTab}>SAP P2P</Tab>
      </nav>

      {tab === "dashboard" && (
        <section className="grid">
          <div className="card span-2">
            <h2>Grow-input prices</h2>
            <CommodityChart tick={tick} />
          </div>
          <div className="card">
            <h2>Seeds below reorder point</h2>
            <InventoryPanel tick={tick} />
          </div>
          <div className="card">
            <h2>Planting (last 24h · trays)</h2>
            <DemandChart tick={tick} />
          </div>
          <div className="card span-2">
            <h2>Supplier leaderboard — ML-ranked</h2>
            <SupplierLeaderboard tick={tick} />
          </div>
          <div className="card span-3">
            <h2>Procurement recommendations</h2>
            <RecommendationsTable tick={tick} />
          </div>
        </section>
      )}

      {tab === "emails" && (
        <section className="card tall">
          <h2>Negotiation mailbox</h2>
          <EmailPanel tick={tick} />
        </section>
      )}

      {tab === "po" && (
        <section className="grid">
          <div className="card span-2">
            <h2>PO drafts</h2>
            <PoDraftsPanel tick={tick} />
          </div>
          <div className="card">
            <h2>Budget ledger</h2>
            <BudgetPanel tick={tick} />
          </div>
        </section>
      )}

      {tab === "onboarding" && (
        <section className="card">
          <h2>Supplier onboarding</h2>
          <OnboardingPanel tick={tick} />
        </section>
      )}

      {tab === "invoices" && (
        <section className="card">
          <h2>Invoice reconciliation</h2>
          <InvoicesPanel tick={tick} />
        </section>
      )}

      {tab === "runs" && (
        <section className="card">
          <h2>Agent run log</h2>
          <AgentRunsPanel tick={tick} />
        </section>
      )}

      {tab === "sap" && (
        <section className="card tall">
          <h2>SAP Procure-to-Pay</h2>
          <SapPanel tick={tick} />
        </section>
      )}

      <footer>
        Zerobus → Delta (Lakeflow SDP) → Lakebase · Foundation Model API for agents ·
        refresh every {REFRESH_MS / 1000}s
      </footer>
    </div>
  );
}

function Tab({
  id, on, onSet, children,
}: {
  id: Tab; on: Tab; onSet: (t: Tab) => void; children: React.ReactNode;
}) {
  return (
    <button
      className={`tab ${id === on ? "on" : ""}`}
      onClick={() => onSet(id)}
    >
      {children}
    </button>
  );
}
