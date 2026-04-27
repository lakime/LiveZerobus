import { useEffect, useState } from "react";
import { api, type SupplierApplication } from "../api";

const STATUS_BADGE: Record<string, string> = {
  NEW: "badge wait", SCREENING: "badge wait",
  APPROVED: "badge buy", REJECTED: "badge review",
};

// Major seed-producing / exporting countries. ISO 3166-1 alpha-2 code as
// the value (matches dim_supplier.country), human label for display.
const COUNTRIES: { code: string; name: string }[] = [
  { code: "NL", name: "Netherlands" },
  { code: "US", name: "United States" },
  { code: "FR", name: "France" },
  { code: "DE", name: "Germany" },
  { code: "IT", name: "Italy" },
  { code: "ES", name: "Spain" },
  { code: "IL", name: "Israel" },
  { code: "JP", name: "Japan" },
  { code: "CN", name: "China" },
  { code: "IN", name: "India" },
  { code: "CA", name: "Canada" },
  { code: "GB", name: "United Kingdom" },
  { code: "BE", name: "Belgium" },
  { code: "DK", name: "Denmark" },
  { code: "CH", name: "Switzerland" },
  { code: "AU", name: "Australia" },
  { code: "NZ", name: "New Zealand" },
  { code: "OTHER", name: "Other" },
];

// Crop types available in dim_sku — aligned with the 8 categories the
// scoring model and SKU_INPUT_MAP know about.
const CROP_TYPES = [
  "lettuce", "basil", "kale", "arugula",
  "spinach", "microgreens", "herb", "asian-green",
];

const EMPTY_FORM = {
  supplier_name: "",
  contact_email: "",
  country: "",
  offered_skus: new Set<string>(),
  organic_cert: false,
  years_in_biz: 1,
};

export default function OnboardingPanel({ tick }: { tick: number }) {
  const [apps, setApps] = useState<SupplierApplication[]>([]);
  const [form, setForm] = useState<typeof EMPTY_FORM>({
    ...EMPTY_FORM,
    offered_skus: new Set<string>(),
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.applications().then(setApps).catch(() => setApps([]));
  }, [tick]);

  function toggleSku(sku: string) {
    setForm(prev => {
      const next = new Set(prev.offered_skus);
      if (next.has(sku)) next.delete(sku);
      else next.add(sku);
      return { ...prev, offered_skus: next };
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      // Backend expects offered_skus as a comma-separated string —
      // join the multi-select set on the wire to keep the API unchanged.
      await api.submitApplication({
        supplier_name: form.supplier_name,
        contact_email: form.contact_email,
        country: form.country,
        offered_skus: Array.from(form.offered_skus).join(", "),
        organic_cert: form.organic_cert,
        years_in_biz: form.years_in_biz,
      });
      setForm({ ...EMPTY_FORM, offered_skus: new Set<string>() });
      const refreshed = await api.applications();
      setApps(refreshed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form className="onboarding-form" onSubmit={submit}>
        <input
          placeholder="Supplier name"
          value={form.supplier_name}
          onChange={e => setForm({ ...form, supplier_name: e.target.value })}
          required
        />
        <input
          placeholder="contact@example.com"
          type="email"
          value={form.contact_email}
          onChange={e => setForm({ ...form, contact_email: e.target.value })}
          required
        />
        <select
          value={form.country}
          onChange={e => setForm({ ...form, country: e.target.value })}
          required
        >
          <option value="" disabled>Country…</option>
          {COUNTRIES.map(c => (
            <option key={c.code} value={c.code}>{c.name}</option>
          ))}
        </select>

        <div className="sku-multi" style={{ gridColumn: "1 / -1" }}>
          <span className="muted small" style={{ marginRight: 8 }}>
            Offered crop types:
          </span>
          {CROP_TYPES.map(sku => (
            <label key={sku} className={`chip ${form.offered_skus.has(sku) ? "on" : ""}`}>
              <input
                type="checkbox"
                checked={form.offered_skus.has(sku)}
                onChange={() => toggleSku(sku)}
                style={{ display: "none" }}
              />
              {sku}
            </label>
          ))}
        </div>

        <label>
          <input
            type="checkbox"
            checked={form.organic_cert}
            onChange={e => setForm({ ...form, organic_cert: e.target.checked })}
          /> Organic certified
        </label>

        <select
          value={form.years_in_biz}
          onChange={e => setForm({ ...form, years_in_biz: +e.target.value })}
        >
          <option value={1}>&lt; 2 years</option>
          <option value={3}>2 – 5 years</option>
          <option value={7}>5 – 10 years</option>
          <option value={15}>10 – 25 years</option>
          <option value={30}>25+ years</option>
        </select>

        <button className="btn" type="submit" disabled={busy}>
          Submit application
        </button>
      </form>

      {apps.length === 0 ? (
        <p className="muted">No applications yet — submit one above.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Submitted</th><th>Supplier</th><th>Email</th>
              <th>Country</th><th>Offered</th><th>Organic</th>
              <th>Years</th><th>Score</th><th>Status</th><th>Agent notes</th>
            </tr>
          </thead>
          <tbody>
            {apps.map(a => (
              <tr key={a.application_id}>
                <td className="muted small">{new Date(a.submitted_ts).toLocaleString()}</td>
                <td>{a.supplier_name}</td>
                <td className="muted small">{a.contact_email}</td>
                <td>{a.country}</td>
                <td className="muted small truncate">{a.offered_skus}</td>
                <td>{a.organic_cert ? "✓" : ""}</td>
                <td>{a.years_in_biz}</td>
                <td className="pos">{a.score != null ? a.score.toFixed(2) : "—"}</td>
                <td>
                  <span className={STATUS_BADGE[a.status ?? ""] ?? "badge review"}>
                    {a.status}
                  </span>
                </td>
                <td className="muted small truncate">{a.agent_notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
