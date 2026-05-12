import { useEffect, useState } from "react";
import { api, SapTable, ServiceInfo, SharingEntry } from "../api";

export default function SharePanel() {
  const [info, setInfo] = useState<ServiceInfo | null>(null);
  const [tables, setTables] = useState<SapTable[]>([]);
  const [sharing, setSharing] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function loadAll() {
    const [i, t, s] = await Promise.all([
      api.info().catch(() => null),
      api.tables().catch(() => [] as SapTable[]),
      api.sharingStatus().catch(() => null),
    ]);
    setInfo(i);
    setTables(t);
    if (s) {
      const m: Record<string, boolean> = {};
      for (const e of s.tables) m[e.name] = e.enabled;
      setSharing(m);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function toggle(name: string, enabled: boolean) {
    setBusy(true);
    try {
      const r: SharingEntry = await api.setSharing(name, enabled);
      setSharing((s) => ({ ...s, [r.name]: r.enabled }));
      setMsg(`${r.name}: ${r.enabled ? "shared" : "not shared"}`);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function bulk(enable: boolean) {
    setBusy(true);
    try {
      const r = enable ? await api.enableAll() : await api.disableAll();
      const m: Record<string, boolean> = {};
      for (const n of Object.keys(sharing)) m[n] = false;
      for (const n of r.enabled) m[n] = true;
      setSharing(m);
      setMsg(enable ? `Shared all ${r.enabled.length} tables` : "Disabled all tables");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleRegenerate() {
    setRegenerating(true);
    try {
      await api.regenerate();
      await loadAll();
      setMsg("Data regenerated");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setRegenerating(false);
    }
  }

  const sharedCount = Object.values(sharing).filter(Boolean).length;
  const totalReady = tables.filter((t) => t.available).length;

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
          <div className="info-row">
            <div className="info-label">Endpoint</div>
            <div className="info-value" style={{ wordBreak: "break-all" }}>{info.endpoint}</div>
          </div>
          <div className="info-row">
            <div className="info-label">Sharing</div>
            <div className="info-value">
              {sharedCount} / {totalReady} tables shared
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Per-table sharing controls</h3>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {msg && <span className="muted small">{msg}</span>}
          <button className="btn" onClick={() => bulk(true)} disabled={busy}>Enable all</button>
          <button className="btn" onClick={() => bulk(false)} disabled={busy}>Disable all</button>
          <button className="btn" onClick={handleRegenerate} disabled={regenerating || busy}>
            {regenerating ? "Regenerating…" : "↺ Regenerate Data"}
          </button>
        </div>
      </div>

      <p className="muted small" style={{ marginTop: 0 }}>
        Tables disabled here are <strong>invisible to Databricks UC</strong> but
        still browsable in the Tables / Preview tabs above. Default state for
        a fresh deployment is all disabled — enable each table you want
        published to consumers.
      </p>

      <table>
        <thead>
          <tr>
            <th style={{ width: 60 }}>Share</th>
            <th>Table</th>
            <th>Module</th>
            <th>Description</th>
            <th style={{ textAlign: "right" }}>Rows</th>
          </tr>
        </thead>
        <tbody>
          {tables.map((t) => {
            const enabled = !!sharing[t.name];
            return (
              <tr key={t.name}>
                <td>
                  <label style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: t.available ? "pointer" : "not-allowed" }}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={!t.available || busy}
                      onChange={(e) => toggle(t.name, e.target.checked)}
                    />
                    <span className={`badge ${enabled ? "ok" : "warn"}`}>
                      {enabled ? "ON" : "OFF"}
                    </span>
                  </label>
                </td>
                <td style={{ fontFamily: "monospace", color: "var(--sap-blue-dark)", fontWeight: 700 }}>
                  {t.name}
                </td>
                <td className="muted">{t.module}</td>
                <td className="muted" style={{ maxWidth: 360 }}>{t.description}</td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                  {t.available ? t.row_count.toLocaleString() : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
