import { useEffect, useState } from "react";
import { api, SapTable } from "../api";

type Props = { onSelect: (name: string) => void };

export default function TableBrowser({ onSelect }: Props) {
  const [tables, setTables] = useState<SapTable[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.tables()
      .then(setTables)
      .catch(() => setTables([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="muted small">Loading tables…</p>;

  const ready = tables.filter((t) => t.available);
  const total = tables.reduce((s, t) => s + t.row_count, 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
        <p className="muted small" style={{ margin: 0 }}>
          {ready.length} tables · {total.toLocaleString()} total rows
        </p>
      </div>
      <div className="table-grid">
        {tables.map((t) => (
          <div
            key={t.name}
            className="table-card"
            onClick={() => t.available && onSelect(t.name)}
            style={{ opacity: t.available ? 1 : 0.45, cursor: t.available ? "pointer" : "default" }}
          >
            <div className="tc-top">
              <span className="table-name">{t.name}</span>
              <span className="table-module">{t.module}</span>
            </div>
            <div className="table-desc">{t.description}</div>
            <div className="table-rows">
              <span>{t.available ? t.row_count.toLocaleString() : "—"}</span>
              {" "}rows
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
