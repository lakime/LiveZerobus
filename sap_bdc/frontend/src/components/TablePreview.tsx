import { useEffect, useState } from "react";
import { api, TableData } from "../api";

type Props = { table: string | null };

const PAGE = 50;

export default function TablePreview({ table }: Props) {
  const [data, setData] = useState<TableData | null>(null);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOffset(0);
    setSearch("");
    setData(null);
  }, [table]);

  useEffect(() => {
    if (!table) return;
    setLoading(true);
    api.tableRows(table, offset, PAGE, search)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [table, offset, search]);

  if (!table) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 300 }}>
        <p className="muted">Select a table from the Tables tab to preview its data.</p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>{table}</h2>
        {data && <span className="muted small">{data.total.toLocaleString()} rows</span>}
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Search across all columns…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setOffset(0); }}
        />
        {loading && <span className="muted small">Loading…</span>}
      </div>

      {data && data.rows.length > 0 ? (
        <>
          <div className="preview-wrap">
            <table>
              <thead>
                <tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} title={cell}>{cell || <span className="muted">—</span>}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              className="btn"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              ← Prev
            </button>
            <span>
              {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total.toLocaleString()}
            </span>
            <button
              className="btn"
              disabled={offset + PAGE >= data.total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Next →
            </button>
          </div>
        </>
      ) : data ? (
        <p className="muted small">No rows match your search.</p>
      ) : null}
    </div>
  );
}
