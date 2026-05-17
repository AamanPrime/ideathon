import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./auth";
import { ThemeToggle } from "./ThemeToggle";

type SessionItem = {
  id: string;
  customer_lang: string;
  staff_lang: string;
  customer_ref: string;
  status: string;
  last_intent: string | null;
  created_at: string | null;
  closed_at: string | null;
  metrics: Record<string, unknown>;
  turns?: Array<{ role: string; text_original: string; text_translated: string }>;
  form_snapshot?: Record<string, unknown>;
};

type RecordItem = {
  id: number;
  summary_staff_lang: string;
  summary_customer_lang: string;
  payload: Record<string, unknown>;
  created_at: string | null;
};

type Props = {
  onBack: () => void;
};

export default function History({ onBack }: Props) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ session: SessionItem; records: RecordItem[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch("/sessions");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSessions(d.sessions || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openSession = async (id: string) => {
    setSelected(id);
    setDetail(null);
    const r = await apiFetch(`/sessions/${id}`);
    if (r.ok) setDetail(await r.json());
  };

  return (
    <div className="shell shell-desk">
      <header className="topbar topbar-desk">
        <div className="brand">
          <strong>Session history</strong>
          <span>Bilingual interaction records · PII-redacted at rest</span>
        </div>
        <div className="row" style={{ gap: "0.5rem" }}>
          <button type="button" className="secondary btn-compact" onClick={onBack}>
            ← Back to console
          </button>
          <ThemeToggle />
        </div>
      </header>

      <div className="grid">
        <section className="panel">
          <h2>Past sessions</h2>
          {loading && <div className="small">Loading…</div>}
          {error && <div className="small risk-high">{error}</div>}
          {!loading && sessions.length === 0 && <div className="small">No sessions yet.</div>}
          <ul className="history-list">
            {sessions.map((s) => (
              <li key={s.id} style={{ cursor: "pointer" }} onClick={() => void openSession(s.id)}>
                <time>{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</time>
                <strong>
                  {s.customer_lang} → {s.staff_lang} · {s.status}
                  {s.last_intent ? ` · ${s.last_intent}` : ""}
                </strong>
                <span className="mono">{s.id.slice(0, 12)} {s.customer_ref ? `· ${s.customer_ref}` : ""}</span>
              </li>
            ))}
          </ul>
        </section>

        <aside>
          <section className="panel">
            <h2>Details</h2>
            {!selected && <div className="small">Select a session on the left.</div>}
            {selected && !detail && <div className="small">Loading session…</div>}
            {detail && (
              <>
                <div className="kv">
                  <div>ID</div>
                  <div className="mono">{detail.session.id}</div>
                  <div>Status</div>
                  <div className="mono">{detail.session.status}</div>
                  <div>Intent</div>
                  <div className="mono">{detail.session.last_intent || "—"}</div>
                  <div>Customer ref</div>
                  <div className="mono">{detail.session.customer_ref || "—"}</div>
                </div>
                <h3 style={{ marginTop: "0.85rem" }}>Bilingual records</h3>
                {detail.records.length === 0 && <div className="small">No summary generated.</div>}
                {detail.records.map((r) => (
                  <div key={r.id} className="bubble" style={{ marginBottom: "0.5rem" }}>
                    <div className="small">
                      <strong>Staff:</strong> {r.summary_staff_lang || "—"}
                    </div>
                    <div className="small">
                      <strong>Customer:</strong> {r.summary_customer_lang || "—"}
                    </div>
                  </div>
                ))}
                <h3 style={{ marginTop: "0.85rem" }}>Persisted turns (redacted)</h3>
                <div className="feed">
                  {(detail.session.turns as unknown as Array<{
                    role: string;
                    text_original: string;
                    text_translated: string;
                  }>) ?.map?.((t, i) => (
                    <div key={i} className={`bubble ${t.role}`}>
                      <div className="who">
                        <span className="mono">{t.role}</span>
                      </div>
                      <div className="small">
                        <strong>Original:</strong> {t.text_original}
                      </div>
                      <div className="small">
                        <strong>Translated:</strong> {t.text_translated}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
