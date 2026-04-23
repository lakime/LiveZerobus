import { useEffect, useState } from "react";
import { api, type Summary } from "./api";
import SummaryBar from "./components/SummaryBar";
import InventoryPanel from "./components/InventoryPanel";
import SupplierLeaderboard from "./components/SupplierLeaderboard";
import CommodityChart from "./components/CommodityChart";
import DemandChart from "./components/DemandChart";
import RecommendationsTable from "./components/RecommendationsTable";

const REFRESH_MS = 3000;

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, [tick]);

  return (
    <div className="app">
      <header>
        <h1>LiveZerobus — Auto Procurement</h1>
        <span className="live">● LIVE · {new Date().toLocaleTimeString()}</span>
      </header>

      <SummaryBar summary={summary} />

      <section className="grid">
        <div className="card span-2">
          <h2>Commodity prices</h2>
          <CommodityChart tick={tick} />
        </div>
        <div className="card">
          <h2>Inventory (below reorder point)</h2>
          <InventoryPanel tick={tick} />
        </div>
        <div className="card">
          <h2>Demand (last 24h)</h2>
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

      <footer>
        Zerobus → Delta (Lakeflow Spark Declarative Pipelines) → Lakebase · refresh every {REFRESH_MS / 1000}s
      </footer>
    </div>
  );
}
