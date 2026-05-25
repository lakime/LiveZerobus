import { useEffect, useState } from "react";

type GenieInfo =
  | { configured: false; reason: string }
  | { configured: true; space_id: string; url: string; url_alt: string };

export default function GeniePanel() {
  const [info, setInfo] = useState<GenieInfo | null>(null);
  const [useAlt, setUseAlt] = useState(false);

  useEffect(() => {
    fetch("/api/genie/info")
      .then((r) => r.json())
      .then(setInfo)
      .catch((e) => setInfo({ configured: false, reason: String(e) }));
  }, []);

  if (!info) {
    return <div className="muted">Loading Genie status…</div>;
  }

  if (!info.configured) {
    return <SetupInstructions reason={info.reason} />;
  }

  const url = useAlt ? info.url_alt : info.url;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="muted small" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>
          Talk to your data via{" "}
          <a href={url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
            Databricks Genie
          </a>
          {" · space "}<code>{info.space_id}</code>
        </span>
        <button
          className="btn"
          style={{ padding: "3px 10px", fontSize: 11 }}
          title="If the iframe is blank, try the alternate URL form"
          onClick={() => setUseAlt(!useAlt)}
        >
          {useAlt ? "Use /rooms URL" : "Use /spaces URL"}
        </button>
      </div>

      <iframe
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

function SetupInstructions({ reason }: { reason: string }) {
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <span className="badge warn">NOT CONFIGURED</span>
      </div>
      <p>To wire up the Genie chat:</p>
      <ol style={{ lineHeight: 1.7 }}>
        <li>
          In Databricks, open <strong>Genie</strong> from the left sidebar →{" "}
          <strong>+ New</strong>.
        </li>
        <li>
          Pick a name (e.g. <em>LiveZerobus — Talk to data</em>) and select the{" "}
          <code>6a1fb3b32b00f1cd</code> warehouse.
        </li>
        <li>
          Add tables from both catalogs:
          <ul>
            <li><code>livezerobus.procurement.gd_*</code> (procurement gold tables)</li>
            <li><code>sapsofts.procurement.*</code> (SAP BDC shared tables)</li>
          </ul>
        </li>
        <li>
          Save the space, then copy its <strong>Space ID</strong> from the URL
          (e.g. <code>/genie/rooms/<u>01f152bb...</u></code>).
        </li>
        <li>
          Set <code>GENIE_SPACE_ID</code> in <code>backend/app.yaml</code> (and{" "}
          <code>DATABRICKS_HOST</code> if not already set), then redeploy.
        </li>
      </ol>
      <p className="muted small">Reason backend reports: <code>{reason}</code></p>
    </div>
  );
}
