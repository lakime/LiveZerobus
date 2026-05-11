import { useState, useEffect } from "react";
import TableBrowser from "./components/TableBrowser";
import TablePreview from "./components/TablePreview";
import SharePanel from "./components/SharePanel";
import ProfilePanel from "./components/ProfilePanel";

type Tab = "tables" | "preview" | "share" | "connect";

const TCODE: Record<Tab, string> = {
  tables: "/SAP/BDC/DATA01",
  preview: "/SAP/BDC/SE16N",
  share: "/SAP/BDC/SHARE",
  connect: "/SAP/BDC/CONNECT",
};

const TAB_TITLE: Record<Tab, string> = {
  tables: "Table Browser",
  preview: "Data Browser (SE16N-style)",
  share: "Delta Share Configuration",
  connect: "Databricks Connection",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("tables");
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

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

  const timestr = now.toTimeString().slice(0, 8);
  const datestr = now.toISOString().slice(0, 10);

  return (
    <>
      {/* ── SAP Title Bar ───────────────────────────────── */}
      <div className="sap-titlebar">
        <div className="left">
          <span className="sap-logo">SAP</span>
          <span>Business Data Cloud — Procurement Tenant</span>
          <span className="system-id">[BDC/100]</span>
        </div>
        <div className="right">User: PUZAR  |  Client: 100  |  System: BDC</div>
      </div>

      {/* ── Transaction toolbar ─────────────────────────── */}
      <div className="sap-toolbar">
        <span className="tcode">{TCODE[tab]}</span>
        <div className="toolbar-sep" />
        <button className="toolbar-btn" title="Back (F3)">◀ Back</button>
        <button className="toolbar-btn" title="Save (Ctrl+S)">💾 Save</button>
        <button className="toolbar-btn" title="Refresh (F5)" onClick={() => window.location.reload()}>↻ Refresh</button>
        <div className="toolbar-sep" />
        <button className="toolbar-btn" title="Help (F1)">? Help</button>
      </div>

      {/* ── Main content ────────────────────────────────── */}
      <div className="sap-main">
        <nav className="tabs">
          <T id="tables" label="Tables" />
          <T id="preview" label={selectedTable ? `Preview · ${selectedTable}` : "Data Preview"} />
          <T id="share" label="Delta Share" />
          <T id="connect" label="Databricks Connection" />
        </nav>

        <div className="card">
          <div className="panel-title">{TAB_TITLE[tab]}</div>
          {tab === "tables" && <TableBrowser onSelect={selectTable} />}
          {tab === "preview" && <TablePreview table={selectedTable} />}
          {tab === "share" && <SharePanel />}
          {tab === "connect" && <ProfilePanel />}
        </div>
      </div>

      {/* ── Function key bar ────────────────────────────── */}
      <div className="fkey-bar">
        <span className="fkey"><b>F1</b> Help</span>
        <span className="fkey"><b>F3</b> Back</span>
        <span className="fkey"><b>F4</b> Search</span>
        <span className="fkey"><b>F5</b> Refresh</span>
        <span className="fkey"><b>F7</b> Page Up</span>
        <span className="fkey"><b>F8</b> Page Down</span>
      </div>

      {/* ── SAP Status Bar ──────────────────────────────── */}
      <div className="sap-statusbar">
        <div className="sb-left">
          <div className="sb-cell"><span className="lbl">SY-DATUM:</span><span className="val">{datestr}</span></div>
          <div className="sb-cell"><span className="lbl">SY-UZEIT:</span><span className="val">{timestr}</span></div>
          <div className="sb-cell"><span className="lbl">SY-MANDT:</span><span className="val">100</span></div>
          <div className="sb-cell"><span className="lbl">SY-LANGU:</span><span className="val">EN</span></div>
        </div>
        <div className="right">● Connected to BDC tenant</div>
      </div>
    </>
  );
}
