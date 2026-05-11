import { useState } from "react";
import TableBrowser from "./components/TableBrowser";
import TablePreview from "./components/TablePreview";
import SharePanel from "./components/SharePanel";
import ProfilePanel from "./components/ProfilePanel";

type Tab = "tables" | "preview" | "share" | "connect";

export default function App() {
  const [tab, setTab] = useState<Tab>("tables");
  const [selectedTable, setSelectedTable] = useState<string | null>(null);

  function selectTable(name: string) {
    setSelectedTable(name);
    setTab("preview");
  }

  function T({ id, label }: { id: Tab; label: string }) {
    return (
      <button className={`tab${tab === id ? " on" : ""}`} onClick={() => setTab(id)}>
        {label}
      </button>
    );
  }

  return (
    <div className="app">
      <header>
        <div className="header-left">
          <span className="sap-badge">SAP BDC</span>
          <div>
            <h1>SAP Business Data Cloud</h1>
            <div className="subtitle">Mock Delta Sharing provider · 15 procurement tables</div>
          </div>
        </div>
        <span className="live">● Live</span>
      </header>

      <nav className="tabs">
        <T id="tables" label="Tables" />
        <T id="preview" label={selectedTable ? `Preview · ${selectedTable}` : "Preview"} />
        <T id="share" label="Share" />
        <T id="connect" label="Connect to Databricks" />
      </nav>

      <div className="card">
        {tab === "tables" && <TableBrowser onSelect={selectTable} />}
        {tab === "preview" && <TablePreview table={selectedTable} />}
        {tab === "share" && <SharePanel />}
        {tab === "connect" && <ProfilePanel />}
      </div>

      <footer>SAP BDC Mock · Delta Sharing Protocol v1 · GreenHarvest Demo Tenant</footer>
    </div>
  );
}
