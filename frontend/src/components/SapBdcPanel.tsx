import { useEffect, useState } from "react";
import { api, SapBdcPoLine, SapBdcVendor } from "../api";

type Sub = "overview" | "vendors" | "purchase-orders";

export default function SapBdcPanel() {
  const [sub, setSub] = useState<Sub>("overview");
  const [info, setInfo] = useState<{
    connected: boolean;
    catalog: string;
    schema: string;
    reason?: string;
    table_count?: number;
    tables?: string[];
  } | null>(null);

  useEffect(() => {
    api.sapBdcInfo().then(setInfo).catch(() => null);
  }, []);

  if (!info) return <div className="muted">Loading SAP BDC status…</div>;

  if (!info.connected) {
    return (
      <div>
        <div style={{ marginBottom: 12 }}>
          <span className="badge warn">DISCONNECTED</span>
        </div>
        <p style={{ marginTop: 0 }}>
          The SAP BDC catalog isn't reachable from this workspace.
        </p>
        <p className="small muted">
          Configure <code>SAP_BDC_WAREHOUSE_ID</code> on the backend and ensure
          the catalog <code>{info.catalog}.{info.schema}</code> exists in Unity Catalog.
          {info.reason && <> Reason: <code>{info.reason}</code></>}
        </p>
        <p className="small muted">
          To create the catalog, upload the <code>profile.json</code> from the
          external SAP BDC service via{" "}
          <strong>Catalog → Add data → Add a provider</strong>, then{" "}
          <strong>Create catalog from share</strong>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <span className="badge ok">CONNECTED</span>{" "}
        <span className="muted small">
          via Delta Sharing · {info.table_count} tables in{" "}
          <code>{info.catalog}.{info.schema}</code>
        </span>
      </div>

      <div className="tabs" style={{ marginBottom: 12 }}>
        {(["overview", "vendors", "purchase-orders"] as Sub[]).map((id) => (
          <button
            key={id}
            className={`tab ${sub === id ? "on" : ""}`}
            onClick={() => setSub(id)}
          >
            {id === "overview" ? "Overview" : id === "vendors" ? "Vendors (LFA1)" : "Purchase Orders (EKKO+EKPO)"}
          </button>
        ))}
      </div>

      {sub === "overview" && <Overview tables={info.tables || []} />}
      {sub === "vendors" && <Vendors />}
      {sub === "purchase-orders" && <PurchaseOrders />}
    </div>
  );
}

function Overview({ tables }: { tables: string[] }) {
  return (
    <div>
      <p style={{ marginTop: 0 }}>
        Zero-copy view of an external SAP Business Data Cloud tenant.
        Tables ship to this workspace via Delta Sharing — no ETL, no replication.
      </p>
      <h3>Tables in share</h3>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
          gap: 6,
        }}
      >
        {tables.map((t) => (
          <div
            key={t}
            className="badge ok"
            style={{ padding: "4px 8px", textAlign: "center", fontFamily: "monospace" }}
          >
            {t.toUpperCase()}
          </div>
        ))}
      </div>
    </div>
  );
}

function Vendors() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<SapBdcVendor[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setRows(await api.sapBdcVendors(q, 200));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="search-bar">
        <input
          placeholder="Search by name, country, city, LIFNR…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <button className="btn" onClick={load} disabled={loading}>
          {loading ? "…" : "Search"}
        </button>
        <span className="muted small">{rows.length} rows</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>LIFNR</th>
            <th>Name</th>
            <th>Country</th>
            <th>City</th>
            <th>Street</th>
            <th>Phone</th>
            <th>Acct group</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.LIFNR}>
              <td style={{ fontFamily: "monospace" }}>{r.LIFNR}</td>
              <td>{r.NAME1}</td>
              <td>{r.LAND1}</td>
              <td>{r.ORT01}</td>
              <td className="muted">{r.STRAS}</td>
              <td className="muted">{r.TELF1}</td>
              <td className="muted">{r.KTOKK}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PurchaseOrders() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<SapBdcPoLine[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setRows(await api.sapBdcPurchaseOrders(q, 200));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="search-bar">
        <input
          placeholder="Search by PO #, vendor, material…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
        />
        <button className="btn" onClick={load} disabled={loading}>
          {loading ? "…" : "Search"}
        </button>
        <span className="muted small">{rows.length} lines</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>PO #</th>
            <th>Item</th>
            <th>Type</th>
            <th>Vendor</th>
            <th>Material</th>
            <th>Plant</th>
            <th style={{ textAlign: "right" }}>Qty</th>
            <th>UoM</th>
            <th style={{ textAlign: "right" }}>Net price</th>
            <th>Curr</th>
            <th style={{ textAlign: "right" }}>Net value</th>
            <th>PO date</th>
            <th>Delivery</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.po_number}-${r.item}-${i}`}>
              <td style={{ fontFamily: "monospace" }}>{r.po_number}</td>
              <td style={{ fontFamily: "monospace" }}>{r.item}</td>
              <td className="muted">{r.po_type}</td>
              <td title={`LIFNR: ${r.vendor_id}`}>
                {r.vendor_name || r.vendor_id}{" "}
                {r.vendor_country && <span className="muted small">({r.vendor_country})</span>}
              </td>
              <td style={{ fontFamily: "monospace" }}>{r.material}</td>
              <td className="muted">{r.plant}</td>
              <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                {r.quantity?.toLocaleString()}
              </td>
              <td className="muted">{r.uom}</td>
              <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                {r.net_price?.toFixed(2)}
              </td>
              <td className="muted">{r.currency}</td>
              <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                {r.net_value?.toFixed(2)}
              </td>
              <td className="muted">{r.po_date}</td>
              <td className="muted">{r.delivery_date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
