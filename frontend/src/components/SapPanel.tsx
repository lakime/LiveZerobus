import { useEffect, useState } from "react";
import { api, type SapPoLine, type SapInvoiceMatch } from "../api";

const PO_STATUS_BADGE: Record<string, string> = {
  OPEN: "badge wait",
  PARTIALLY_RECEIVED: "badge review",
  FULLY_RECEIVED: "badge buy",
  CANCELLED: "badge",
};

const MATCH_BADGE: Record<string, string> = {
  MATCHED: "badge buy",
  VARIANCE: "badge neg",
  PENDING_GR: "badge wait",
  NO_PO: "badge review",
};

function fmt(v: number | null | undefined, decimals = 2) {
  return v != null ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : "—";
}

function fmtTs(ts: string | null | undefined) {
  return ts ? new Date(ts).toLocaleString() : "—";
}

export default function SapPanel({ tick }: { tick: number }) {
  const [poLines, setPoLines] = useState<SapPoLine[]>([]);
  const [invoices, setInvoices] = useState<SapInvoiceMatch[]>([]);
  const [poFilter, setPoFilter] = useState("");
  const [invFilter, setInvFilter] = useState("");

  useEffect(() => {
    api.sapPoLines().then(setPoLines).catch(() => setPoLines([]));
    api.sapInvoiceMatching().then(setInvoices).catch(() => setInvoices([]));
  }, [tick]);

  const filteredPo = poFilter
    ? poLines.filter((r) => r.po_status === poFilter)
    : poLines;

  const filteredInv = invFilter
    ? invoices.filter((r) => r.match_status === invFilter)
    : invoices;

  return (
    <div>
      <section style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Open PO lines</h3>
          <select
            value={poFilter}
            onChange={(e) => setPoFilter(e.target.value)}
            style={{ fontSize: "0.85rem" }}
          >
            <option value="">All statuses</option>
            <option value="OPEN">OPEN</option>
            <option value="PARTIALLY_RECEIVED">PARTIALLY_RECEIVED</option>
            <option value="FULLY_RECEIVED">FULLY_RECEIVED</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <span className="muted small">{filteredPo.length} row(s)</span>
        </div>

        {filteredPo.length === 0 ? (
          <p className="muted">No PO lines yet — start the SAP simulator to generate data.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>PO / Item</th>
                <th>Supplier</th>
                <th>SKU</th>
                <th>Qty (g)</th>
                <th>Net value $</th>
                <th>Outstanding (g)</th>
                <th>Delivery</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredPo.map((r) => (
                <tr key={`${r.po_number}-${r.po_item}`}>
                  <td className="mono small">{r.po_number}/{r.po_item}</td>
                  <td>{r.supplier_name ?? r.supplier_id ?? "—"}{r.supplier_tier ? <span className="muted small"> [{r.supplier_tier}]</span> : null}</td>
                  <td>{r.sku ?? "—"}</td>
                  <td className="num">{fmt(r.quantity_g, 0)}</td>
                  <td className="num">${fmt(r.net_value_usd)}</td>
                  <td className="num">{fmt(r.qty_outstanding_g, 0)}</td>
                  <td className="muted small">{fmtTs(r.delivery_date_ts)}</td>
                  <td>
                    <span className={PO_STATUS_BADGE[r.po_status ?? ""] ?? "badge"}>
                      {r.po_status ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>3-way invoice match</h3>
          <select
            value={invFilter}
            onChange={(e) => setInvFilter(e.target.value)}
            style={{ fontSize: "0.85rem" }}
          >
            <option value="">All statuses</option>
            <option value="MATCHED">MATCHED</option>
            <option value="VARIANCE">VARIANCE</option>
            <option value="PENDING_GR">PENDING_GR</option>
            <option value="NO_PO">NO_PO</option>
          </select>
          <span className="muted small">{filteredInv.length} row(s)</span>
        </div>

        {filteredInv.length === 0 ? (
          <p className="muted">No SAP invoices yet — wait for the simulator to complete a P2P cycle (PO → GR → Invoice).</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Invoice doc</th>
                <th>PO / Item</th>
                <th>Supplier</th>
                <th>SKU</th>
                <th>Invoice $</th>
                <th>PO value $</th>
                <th>Variance $</th>
                <th>GR qty (g)</th>
                <th>Match</th>
              </tr>
            </thead>
            <tbody>
              {filteredInv.map((r) => (
                <tr key={r.invoice_doc_number}>
                  <td className="mono small">{r.invoice_doc_number}</td>
                  <td className="mono small">{r.po_number ?? "—"}/{r.po_item ?? "—"}</td>
                  <td>{r.supplier_id ?? "—"}</td>
                  <td>{r.sku ?? "—"}</td>
                  <td className="num">${fmt(r.net_amount_usd)}</td>
                  <td className="num">{r.po_net_value_usd != null ? `$${fmt(r.po_net_value_usd)}` : "—"}</td>
                  <td className={`num ${(r.variance_usd ?? 0) > 0 ? "neg" : "pos"}`}>
                    {r.variance_usd != null ? `$${fmt(r.variance_usd)}` : "—"}
                  </td>
                  <td className="num">{fmt(r.gr_qty_g, 0)}</td>
                  <td>
                    <span className={MATCH_BADGE[r.match_status ?? ""] ?? "badge review"}>
                      {r.match_status ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
