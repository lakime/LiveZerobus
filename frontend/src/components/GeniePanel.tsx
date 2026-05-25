import { useEffect, useState } from "react";

type GenieInfo =
  | { configured: false; reason: string }
  | { configured: true; space_id: string; url: string; url_alt: string };

// Local storage key for the user-configured override. If set, this wins
// over whatever the backend env var says — letting you re-point the
// embed without redeploying.
const LS_KEY = "livezerobus.genie.config";

type SavedConfig = { space_id: string; host: string };

function loadLocal(): SavedConfig | null {
  try {
    const v = localStorage.getItem(LS_KEY);
    return v ? JSON.parse(v) : null;
  } catch {
    return null;
  }
}

function saveLocal(cfg: SavedConfig | null) {
  if (cfg === null) localStorage.removeItem(LS_KEY);
  else localStorage.setItem(LS_KEY, JSON.stringify(cfg));
}

function buildUrl(host: string, space_id: string, alt = false): string {
  // Databricks serves Genie via two routes:
  //   /genie/rooms/{id}   → standard UI; X-Frame-Options DENY → iframe blocked
  //   /embed/genie/rooms/{id} → embed surface; CSP frame-ancestors *
  // Always use the /embed/ form unless the alt toggle is on (for fallback).
  const base = host.replace(/\/+$/, "");
  return alt
    ? `${base}/genie/rooms/${space_id}`
    : `${base}/embed/genie/rooms/${space_id}`;
}

export default function GeniePanel() {
  const [backendInfo, setBackendInfo] = useState<GenieInfo | null>(null);
  const [localCfg, setLocalCfg] = useState<SavedConfig | null>(loadLocal());
  const [useAlt, setUseAlt] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    fetch("/api/genie/info")
      .then((r) => r.json())
      .then(setBackendInfo)
      .catch((e) => setBackendInfo({ configured: false, reason: String(e) }));
  }, []);

  // Effective config: localStorage wins, otherwise backend env.
  const effective: SavedConfig | null =
    localCfg ??
    (backendInfo && backendInfo.configured
      ? { space_id: backendInfo.space_id, host: backendInfo.url.split("/genie/")[0] }
      : null);

  if (!backendInfo) return <div className="muted">Loading Genie status…</div>;

  if (editing || !effective) {
    return (
      <ConfigForm
        initial={effective}
        backendDefault={backendInfo.configured ? backendInfo.url.split("/genie/")[0] : ""}
        reason={!effective && !backendInfo.configured ? backendInfo.reason : null}
        usingLocal={!!localCfg}
        onSave={(cfg) => {
          saveLocal(cfg);
          setLocalCfg(cfg);
          setEditing(false);
        }}
        onClear={() => {
          saveLocal(null);
          setLocalCfg(null);
          setEditing(false);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const url = buildUrl(effective.host, effective.space_id, useAlt);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        className="muted small"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}
      >
        <span>
          Talk to your data via{" "}
          <a href={url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
            Databricks Genie
          </a>
          {" · space "}<code>{effective.space_id}</code>
          {localCfg && <span title="Using locally-saved override" className="badge ok" style={{ marginLeft: 6 }}>LOCAL</span>}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            className="btn"
            style={{ padding: "3px 10px", fontSize: 11 }}
            title="Toggle between the embed URL (iframeable) and the full-app URL (works in a new tab)"
            onClick={() => setUseAlt(!useAlt)}
          >
            {useAlt ? "Use /embed URL" : "Use full-app URL"}
          </button>
          <button
            className="btn"
            style={{ padding: "3px 10px", fontSize: 11 }}
            onClick={() => setEditing(true)}
          >
            ⚙ Configure
          </button>
        </div>
      </div>

      <iframe
        key={url}
        src={url}
        title="Databricks Genie"
        style={{
          width: "100%",
          height: "calc(100vh - 220px)",
          minHeight: 600,
          border: "1px solid var(--border)",
          borderRadius: 6,
          background: "#fff",
        }}
      />
    </div>
  );
}

function ConfigForm({
  initial,
  backendDefault,
  reason,
  usingLocal,
  onSave,
  onClear,
  onCancel,
}: {
  initial: SavedConfig | null;
  backendDefault: string;
  reason: string | null;
  usingLocal: boolean;
  onSave: (cfg: SavedConfig) => void;
  onClear: () => void;
  onCancel: () => void;
}) {
  const [spaceId, setSpaceId] = useState(initial?.space_id ?? "");
  const [host, setHost] = useState(initial?.host ?? backendDefault ?? "");
  const [err, setErr] = useState<string | null>(null);

  function trySave() {
    if (!spaceId.trim()) return setErr("space_id is required");
    if (!host.trim()) return setErr("host is required");
    let normalisedHost = host.trim();
    if (!/^https?:\/\//i.test(normalisedHost)) {
      normalisedHost = "https://" + normalisedHost;
    }
    // Allow user to paste a full URL — extract the id.
    let id = spaceId.trim();
    const m = id.match(/(?:rooms|spaces)\/([a-f0-9]+)/i);
    if (m) id = m[1];
    onSave({ space_id: id, host: normalisedHost.replace(/\/+$/, "") });
  }

  return (
    <div style={{ maxWidth: 720 }}>
      {reason && (
        <div style={{ marginBottom: 12 }}>
          <span className="badge warn">NOT CONFIGURED</span>{" "}
          <span className="muted small">backend: {reason}</span>
        </div>
      )}
      <p style={{ marginTop: 0 }}>
        Configure which Databricks Genie space appears in this tab. Your
        choice is saved in this browser only; nothing is sent to the
        backend. Clear it to fall back to whatever <code>GENIE_SPACE_ID</code>{" "}
        is set in <code>backend/app.yaml</code>.
      </p>

      <ol style={{ marginTop: 16, lineHeight: 1.7 }}>
        <li>Open a Genie space in Databricks (or create one).</li>
        <li>
          Copy the URL — looks like{" "}
          <code>https://adb-…databricks.net/genie/rooms/01f…</code>
        </li>
        <li>Paste it (or just the id) in the field below.</li>
      </ol>

      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, marginTop: 16, alignItems: "center" }}>
        <label htmlFor="genie-host">Workspace host</label>
        <input
          id="genie-host"
          className="input"
          placeholder="https://adb-5347428297913551.11.azuredatabricks.net"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          style={{ padding: "5px 8px", fontFamily: "monospace", fontSize: 12 }}
        />
        <label htmlFor="genie-id">Space id or URL</label>
        <input
          id="genie-id"
          className="input"
          placeholder="01f152bb72081127a45b965aebf87d6c (or full Genie URL)"
          value={spaceId}
          onChange={(e) => setSpaceId(e.target.value)}
          style={{ padding: "5px 8px", fontFamily: "monospace", fontSize: 12 }}
        />
      </div>

      {err && <p style={{ color: "var(--bad)", marginTop: 12 }}>{err}</p>}

      <div style={{ display: "flex", gap: 8, marginTop: 16, alignItems: "center" }}>
        <button className="btn primary" onClick={trySave}>Save</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
        {usingLocal && (
          <button
            className="btn"
            onClick={() => {
              if (confirm("Clear local override and use the backend default?")) onClear();
            }}
            title="Remove the locally-saved override"
          >
            Clear local override
          </button>
        )}
        <span className="muted small" style={{ marginLeft: "auto" }}>
          Stored in browser localStorage as <code>{LS_KEY}</code>
        </span>
      </div>
    </div>
  );
}
