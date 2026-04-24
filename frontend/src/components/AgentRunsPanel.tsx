import { useEffect, useState } from "react";
import { api, type AgentRun } from "../api";

export default function AgentRunsPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<AgentRun[]>([]);

  useEffect(() => {
    api.runs(25).then(setRows).catch(() => setRows([]));
  }, [tick]);

  if (rows.length === 0) return <p className="muted">No agent runs yet.</p>;

  return (
    <table>
      <thead>
        <tr>
          <th>Started</th><th>Agent</th>
          <th>Input</th><th>Output</th>
          <th>Tokens</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.run_id}>
            <td className="muted small">{new Date(r.started_ts).toLocaleTimeString()}</td>
            <td>{r.agent_name}</td>
            <td className="muted small truncate">{r.input_ref}</td>
            <td className="muted small truncate">{r.output_ref}</td>
            <td className="muted small">
              {(r.prompt_tokens ?? 0) + (r.output_tokens ?? 0)}
            </td>
            <td>
              <span className={r.status === "OK" ? "badge buy" : "badge review"}>
                {r.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
