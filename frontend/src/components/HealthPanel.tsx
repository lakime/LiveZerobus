import { useEffect, useState } from "react";
import { api, type HealthLayer, type HealthLayerStatus, type HealthStatus, type HealthTable } from "../api";

const POLL_MS = 15_000;

const LAYER_LABELS: Record<string, { title: string; sub: string }> = {
  bronze:   { title: "Bronze",   sub: "Simulators → Zerobus → Delta" },
  gold:     { title: "Gold",     sub: "Lakeflow MVs (Bronze→Silver→Gold)" },
  lakebase: { title: "Lakebase", sub: "Postgres synced tables (read path)" },
  sap_bdc:  { title: "SAP BDC",  sub: "External Delta Sharing catalog" },
};

const STATUS_COLOR: Record<HealthLayerStatus, { bg: string; fg: string; label: string }> = {
  fresh:    { bg: "rgba(33,192,122,0.15)",  fg: "#21c07a", label: "FRESH" },
  stale:    { bg: "rgba(242,184,64,0.15)",  fg: "#f2b840", label: "STALE" },
  error:    { bg: "rgba(255,90,90,0.18)",   fg: "#ff5a5a", label: "ERROR" },
  no_data:  { bg: "rgba(138,151,184,0.15)", fg: "#8a97b8", label: "NO DATA" },
  disabled: { bg: "rgba(138,151,184,0.15)", fg: "#8a97b8", label: "DISABLED" },
  unknown:  { bg: "rgba(138,151,184,0.15)", fg: "#8a97b8", label: "UNKNOWN" },
};

function StatusBadge({ status }: { status: HealthLayerStatus }) {
  const c = STATUS_COLOR[status] ?? STATUS_COLOR.unknown;
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 10,
      background: c.bg, color: c.fg, letterSpacing: "0.5px",
    }}>● {c.label}</span>
  );
}

function fmtAge(min: number | null): string {
  if (min == null) return "—";
  if (min < 1) return `${(min * 60).toFixed(0)}s ago`;
  if (min < 60) return `${min.toFixed(1)} min ago`;
  if (min < 24 * 60) return `${(min / 60).toFixed(1)} h ago`;
  return `${(min / 1440).toFixed(1)} d ago`;
}

function fmtCount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

function TableRow({ t }: { t: HealthTable }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1.6fr 0.9fr 1.1fr 0.7fr",
      gap: 8, padding: "6px 0", fontSize: 12,
      borderBottom: "1px dashed #1d2544",
    }}>
      <span style={{ fontFamily: "var(--mono, ui-monospace, monospace)", color: "#cdd5ec" }}>
        {t.table}
      </span>
      <span style={{ color: "var(--muted)", textAlign: "right" }}>{fmtCount(t.count)}</span>
      <span style={{ color: "var(--muted)" }}>{fmtAge(t.age_min)}</span>
      <span style={{ textAlign: "right" }}><StatusBadge status={t.status} /></span>
      {t.error && (
        <span style={{
          gridColumn: "1 / -1", fontSize: 11, color: "#ff8888", marginTop: 2,
        }}>↳ {t.error}</span>
      )}
    </div>
  );
}

function LayerCard({ layer }: { layer: HealthLayer }) {
  const meta = LAYER_LABELS[layer.name] ?? { title: layer.name, sub: "" };
  const showTables = layer.tables.length > 0;
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 14 }}>{meta.title}</h3>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>{meta.sub}</div>
        </div>
        <StatusBadge status={layer.status} />
      </div>

      {layer.error && (
        <div style={{
          marginTop: 10, fontSize: 11, color: "#ff8888",
          background: "rgba(255,90,90,0.08)",
          border: "1px solid rgba(255,90,90,0.25)",
          padding: "6px 8px", borderRadius: 6,
        }}>{layer.error}</div>
      )}

      {layer.name === "sap_bdc" && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
          {layer.status === "disabled"
            ? "SAP_BDC_WAREHOUSE_ID not set — SAP BDC features are off."
            : `${layer.table_count ?? 0} tables visible in catalog`}
        </div>
      )}

      {showTables && (
        <>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1.6fr 0.9fr 1.1fr 0.7fr",
            gap: 8, marginTop: 12, paddingBottom: 4,
            fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.5,
            borderBottom: "1px solid var(--border)",
          }}>
            <span>Table</span>
            <span style={{ textAlign: "right" }}>Rows</span>
            <span>Last event</span>
            <span style={{ textAlign: "right" }}>Status</span>
          </div>
          {layer.tables.map(t => <TableRow key={t.table} t={t} />)}
        </>
      )}
    </div>
  );
}

export default function HealthPanel({ tick }: { tick: number }) {
  const [status, setStatus] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Trigger state
  const [triggerBusy, setTriggerBusy] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  async function load(force = false) {
    setLoading(true);
    try {
      if (force) await api.healthRefresh().catch(() => undefined);
      const s = await api.healthStatus();
      setStatus(s);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const id = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(id);
  }, []);
  useEffect(() => { if (tick > 0) load(false); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [tick]);

  async function triggerPipeline() {
    setTriggerBusy(true);
    setTriggerMsg(null);
    try {
      const r = await api.healthTriggerPipeline();
      if (r.already_running) {
        setTriggerMsg("Pipeline already RUNNING — letting it finish.");
      } else if (r.triggered) {
        setTriggerMsg(`Triggered Lakeflow pipeline (update ${r.update_id?.slice(0, 8)}). Cold-start can take 7–10 min.`);
      } else {
        setTriggerMsg("Trigger request returned no update.");
      }
      // Refresh status soon after — pipeline state will flip.
      setTimeout(() => load(true), 2_000);
    } catch (e: unknown) {
      setTriggerMsg(`Trigger failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTriggerBusy(false);
    }
  }

  const gold = status?.layers.find(l => l.name === "gold");
  const goldStale = gold && gold.status !== "fresh";
  const layerByName = (n: string) => status?.layers.find(l => l.name === n);

  const summaryLine = status
    ? `Generated ${new Date(status.generated_at).toLocaleTimeString()} · pipeline ${status.pipeline_id.slice(0, 8)}`
    : (loading ? "Loading…" : "—");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header card: summary + controls */}
      <div className="card" style={{
        padding: 16, display: "flex", flexDirection: "column", gap: 12,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16 }}>Demo-day health</h2>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>{summaryLine}</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" onClick={() => load(true)} disabled={loading}>
              {loading ? "Checking…" : "↻ Re-check"}
            </button>
            <button
              className="btn"
              onClick={triggerPipeline}
              disabled={triggerBusy}
              style={{
                background: goldStale ? "#f2b840" : undefined,
                color: goldStale ? "#0a0e1f" : undefined,
                fontWeight: goldStale ? 700 : undefined,
              }}
              title={goldStale ? "Gold is stale — recommended" : "Force a pipeline run"}
            >
              {triggerBusy ? "Triggering…" : "▶ Trigger Lakeflow pipeline"}
            </button>
          </div>
        </div>

        {/* Quick chips */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {["bronze", "gold", "lakebase", "sap_bdc"].map(name => {
            const l = layerByName(name);
            if (!l) return null;
            const meta = LAYER_LABELS[name];
            return (
              <div key={name} style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px", border: "1px solid var(--border)", borderRadius: 18,
                background: "rgba(255,255,255,0.02)",
              }}>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{meta.title}</span>
                <StatusBadge status={l.status} />
              </div>
            );
          })}
        </div>

        {triggerMsg && (
          <div style={{
            fontSize: 12, padding: "8px 10px", borderRadius: 6,
            background: triggerMsg.startsWith("Trigger failed")
              ? "rgba(255,90,90,0.10)" : "rgba(33,192,122,0.10)",
            color: triggerMsg.startsWith("Trigger failed") ? "#ff8888" : "#21c07a",
            border: `1px solid ${triggerMsg.startsWith("Trigger failed") ? "rgba(255,90,90,0.25)" : "rgba(33,192,122,0.25)"}`,
          }}>{triggerMsg}</div>
        )}

        {error && (
          <div style={{
            fontSize: 12, padding: "8px 10px", borderRadius: 6,
            background: "rgba(255,90,90,0.10)", color: "#ff8888",
            border: "1px solid rgba(255,90,90,0.25)",
          }}>{error}</div>
        )}
      </div>

      {/* Per-layer detail */}
      {status && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: 14,
        }}>
          {status.layers.map(l => <LayerCard key={l.name} layer={l} />)}
        </div>
      )}

      {/* Footer reference */}
      <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.5 }}>
        For destructive recovery (resetting stuck Lakebase synced tables — DROP &amp;
        recreate), run <code>python scripts/reset_synced_tables.py &lt;table…&gt;</code> on
        the operator workstation. This panel only exposes read checks + pipeline trigger.
      </div>
    </div>
  );
}
