import { useEffect, useState } from "react";
import { api, ServiceInfo } from "../api";

export default function ProfilePanel() {
  const [info, setInfo] = useState<ServiceInfo | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.info().then(setInfo).catch(() => null);
  }, []);

  function copyEndpoint() {
    if (!info) return;
    navigator.clipboard.writeText(info.endpoint).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <button className="btn primary" onClick={api.downloadProfile}>
          ↓ Download profile.json
        </button>
        <button className="btn" onClick={copyEndpoint}>
          {copied ? "✓ Copied!" : "Copy endpoint URL"}
        </button>
      </div>

      {info && (
        <div className="info-row" style={{ marginBottom: 20 }}>
          <div className="info-label">Delta Sharing endpoint</div>
          <div className="code-block">{info.endpoint}</div>
        </div>
      )}

      <h3>How to connect from Databricks Unity Catalog</h3>

      <ol className="connect-steps">
        <li>
          <div className="step-num">1</div>
          <div className="step-body">
            <div className="step-title">Download the profile file</div>
            <div className="step-desc">
              Click "Download profile.json" above. This file contains the endpoint URL and bearer
              token needed to authenticate as a Delta Sharing recipient.
            </div>
          </div>
        </li>
        <li>
          <div className="step-num">2</div>
          <div className="step-body">
            <div className="step-title">Open Databricks Unity Catalog</div>
            <div className="step-desc">
              In your Databricks workspace navigate to{" "}
              <strong>Catalog → Delta Sharing → Shared with me → Add provider</strong>.
            </div>
          </div>
        </li>
        <li>
          <div className="step-num">3</div>
          <div className="step-body">
            <div className="step-title">Upload the profile file</div>
            <div className="step-desc">
              Select "Upload a Delta Sharing profile file" and upload the{" "}
              <code>sap-bdc-profile.json</code> file you downloaded. Databricks will verify
              connectivity to the endpoint automatically.
            </div>
          </div>
        </li>
        <li>
          <div className="step-num">4</div>
          <div className="step-body">
            <div className="step-title">Create a catalog from the share</div>
            <div className="step-desc">
              Once the provider is registered, click <strong>Create catalog</strong> on the{" "}
              <code>sap-procurement</code> share. All 15 SAP tables will appear under the new
              catalog without any data being copied.
            </div>
            <div className="code-block">USE CATALOG sap_bdc;<br />SELECT * FROM procurement.EKKO LIMIT 10;</div>
          </div>
        </li>
        <li>
          <div className="step-num">5</div>
          <div className="step-body">
            <div className="step-title">Query zero-copy — no ETL needed</div>
            <div className="step-desc">
              Databricks reads Parquet files directly from this service. No data is duplicated.
              The tables refresh automatically when you click "Regenerate Data" in the Share tab.
            </div>
          </div>
        </li>
      </ol>
    </div>
  );
}
