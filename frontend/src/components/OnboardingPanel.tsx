import { useEffect, useState } from "react";
import { api, type SupplierApplication } from "../api";

const STATUS_BADGE: Record<string, string> = {
  NEW: "badge wait", SCREENING: "badge wait",
  APPROVED: "badge buy", REJECTED: "badge review",
};

export default function OnboardingPanel({ tick }: { tick: number }) {
  const [apps, setApps] = useState<SupplierApplication[]>([]);
  const [form, setForm] = useState({
    supplier_name: "", contact_email: "", country: "",
    offered_skus: "", organic_cert: false, years_in_biz: 1,
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.applications().then(setApps).catch(() => setApps([]));
  }, [tick]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.submitApplication(form);
      setForm({
        supplier_name: "", contact_email: "", country: "",
        offered_skus: "", organic_cert: false, years_in_biz: 1,
      });
      const refreshed = await api.applications();
      setApps(refreshed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form className="onboarding-form" onSubmit={submit}>
        <input placeholder="Supplier name" value={form.supplier_name}
               onChange={e => setForm({ ...form, supplier_name: e.target.value })} required />
        <input placeholder="contact@example.com" type="email" value={form.contact_email}
               onChange={e => setForm({ ...form, contact_email: e.target.value })} required />
        <input placeholder="Country" value={form.country}
               onChange={e => setForm({ ...form, country: e.target.value })} required />
        <input placeholder="Offered SKUs (e.g. lettuce, herbs)" value={form.offered_skus}
               onChange={e => setForm({ ...form, offered_skus: e.target.value })} />
        <label>
          <input type="checkbox" checked={form.organic_cert}
                 onChange={e => setForm({ ...form, organic_cert: e.target.checked })} /> Organic
        </label>
        <input type="number" min={0} value={form.years_in_biz}
               onChange={e => setForm({ ...form, years_in_biz: +e.target.value })}
               placeholder="Years in biz" />
        <button className="btn" type="submit" disabled={busy}>Submit application</button>
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
