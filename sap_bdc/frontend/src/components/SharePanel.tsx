import { useEffect, useState } from "react";
import { api, SapTable, ServiceInfo } from "../api";

export default function SharePanel() {
  const [info, setInfo] = useState<ServiceInfo | null>(null);
  const [tables, setTables] = useState<SapTable[]>([]);
  const [regenerating, setRegenerating] = useState(false);
  const [lastRegen, setLastRegen] = useState<string | null>(null);

  useEffect(() => {
    api.info().then(setInfo).catch(() => null);
    api.tables().then(setTables).catch(() => null);
  }, []);

  async function handleRegenerate() {
    setRegenerating(true);
    try {
      const r = await api.regenerate();
      setLastRegen(`Regenerated ${r.tables.length} tables`);
      const fresh = await api.tables();
      setTables(fresh);
    } catch {
      setLastRegen("Regeneration failed");
    } finally {
      setRegenerating(false);
    }
  }

  const ready = tables.filter((t) => t.available);

  return (
    <div>
      {info && (
        <div className="share-info">
          <div className="info-row">
            <div className="info-label">Share name</div>
            <div className="info-value">{info.share}</div>
          </div>
          <div className="info-row">
            <div className="info-label">Schema</div>
            <div className="info-value">{info.schema}</div>
          </div>
          <div className="info-row" style={{ gridColumn: "1 / -1" }}>
            <div className="info-label">Delta Sharing endpoint</div>
            <div className="info-value" style={{ wordBreak: "break-all" }}>{info.endpoint}</div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Shared tables ({ready.length})</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {lastRegen && <span className="muted small">{lastRegen}</span>}
          <button className="btn" onClick={handleRegenerate} disabled={regenerating}>
            {regenerating ? "Regenerating…" : "↺ Regenerate Data"}
          </button>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Table</th>
            <th>Module</th>
            <th>Description</th>
            <th style={{ textAlign: "right" }}>Rows</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {tables.map((t) => (
            <tr key={t.name}>
              <td style={{ fontFamily: "monospace", color: "var(--accent)" }}>{t.name}</td>
              <td className="muted">{t.module}</td>
              <td className="muted" style={{ maxWidth: 360 }}>{t.description}</td>
              <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                {t.available ? t.row_count.toLocaleString() : "—"}
              </td>
              <td>
                <span className={`badge ${t.available ? "ok" : "warn"}`}>
                  {t.available ? "SHARED" : "PENDING"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
