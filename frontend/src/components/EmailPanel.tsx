import { useEffect, useState } from "react";
import { api, type EmailRow, type EmailThread } from "../api";

export default function EmailPanel({ tick }: { tick: number }) {
  const [threads, setThreads] = useState<EmailThread[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<EmailRow[]>([]);

  useEffect(() => {
    api.emailThreads(25).then(setThreads).catch(() => {});
  }, [tick]);

  useEffect(() => {
    if (!sel) return;
    api.emailThread(sel).then(setMsgs).catch(() => setMsgs([]));
  }, [sel, tick]);

  async function reply(thread: string) {
    const r = await api.simulateReply(thread).catch(() => null);
    if (!r?.email_id) return;
    const next = await api.emailThread(thread);
    setMsgs(next);
  }

  return (
    <div className="email-layout">
      <aside className="email-list">
        <h3>Supplier threads</h3>
        {threads.length === 0 && <p className="muted">No negotiations yet.</p>}
        {threads.map(t => (
          <button
            key={t.thread_id}
            className={`thread ${sel === t.thread_id ? "on" : ""}`}
            onClick={() => setSel(t.thread_id)}
          >
            <div className="thread-top">
              <span className="sku">{t.sku ?? "—"}</span>
              <span className="muted small">
                {new Date(t.last_ts).toLocaleTimeString()}
              </span>
            </div>
            <div className="thread-mid">{t.supplier_email}</div>
            <div className="muted small truncate">{t.subject}</div>
            <div className="muted small">
              last: {t.side}/{t.intent ?? "—"}
            </div>
          </button>
        ))}
      </aside>
      <section className="email-body">
        {!sel && <p className="muted">Select a thread to view the conversation.</p>}
        {sel && (
          <>
            <div className="email-actions">
              <button className="btn" onClick={() => reply(sel)}>Simulate supplier reply</button>
            </div>
            {msgs.map(m => (
              <article key={m.email_id} className={`email ${m.side === "OUT" ? "out" : "in"}`}>
                <header>
                  <span className="side">{m.side === "OUT" ? "You →" : "← Supplier"}</span>
                  <span>{m.subject}</span>
                  <span className="muted small">{new Date(m.ts).toLocaleString()}</span>
                  {m.intent && <span className="pill">{m.intent}</span>}
                </header>
                <pre className="body">{m.body_md}</pre>
              </article>
            ))}
          </>
        )}
      </section>
    </div>
  );
}
