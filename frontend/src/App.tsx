import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MicCapture } from "./audio/capture";
import { appendHistory, loadHistory, type CustomerHistoryItem } from "./customerHistory";
import Login from "./Login";
import History from "./History";
import {
  apiFetch,
  clearAuth,
  fetchMe,
  getUser,
  httpBase,
  wsUrl,
  type AuthUser,
} from "./auth";

type Portal = "gate" | "staff-login" | "customer-login" | "customer-kiosk" | "desk" | "history";

type LangOption = { code: string; label: string };

const CUSTOMER_LANGS: LangOption[] = [
  { code: "hi", label: "Hindi" },
  { code: "ta", label: "Tamil" },
  { code: "te", label: "Telugu" },
  { code: "kn", label: "Kannada" },
  { code: "ml", label: "Malayalam" },
  { code: "mr", label: "Marathi" },
  { code: "bn", label: "Bengali" },
  { code: "gu", label: "Gujarati" },
  { code: "pa", label: "Punjabi" },
  { code: "or", label: "Odia" },
  { code: "en", label: "English" },
];

const STAFF_LANGS: LangOption[] = [
  { code: "en", label: "English (staff)" },
  { code: "hi", label: "Hindi (staff)" },
];

const BCP47: Record<string, string> = {
  hi: "hi-IN",
  ta: "ta-IN",
  te: "te-IN",
  kn: "kn-IN",
  ml: "ml-IN",
  mr: "mr-IN",
  bn: "bn-IN",
  gu: "gu-IN",
  pa: "pa-IN",
  or: "or-IN",
  en: "en-IN",
};

type Transcript = {
  role: "customer" | "staff";
  source_lang: string;
  text_original: string;
  text_translated: string;
  glossary?: { term: string; definition: string }[];
  risk_flags?: { level?: string; reason?: string }[];
  confidence?: number;
  low_confidence?: boolean;
  normalized?: { normalized_snippets?: string[]; hints?: string[] };
};

type FormFields = Record<string, string | null | undefined>;

function redactPII(s: string): string {
  if (!s) return s;
  return s
    .replace(/\b\d{4}\s?\d{4}\s?\d{4}\b/g, "XXXX-XXXX-####")
    .replace(/\b[A-Z]{5}[0-9]{4}[A-Z]\b/gi, "XXXXX####X")
    .replace(/\b(?:\+91[\s-]?)?[6-9]\d{9}\b/g, "+91-XXXXXX####")
    .replace(/\b[\w.+-]+@[\w-]+\.[\w.-]+\b/gi, "***@***");
}

function getSpeechRecognition(): (new () => SpeechRecognition) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognition;
    webkitSpeechRecognition?: new () => SpeechRecognition;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export default function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(() => getUser());
  const [portal, setPortal] = useState<Portal>(() => (getUser() ? "desk" : "gate"));
  const [customerIdInput, setCustomerIdInput] = useState("");
  const [fingerprintScanning, setFingerprintScanning] = useState(false);
  const [kioskCustomerId, setKioskCustomerId] = useState("");
  const [kioskHistory, setKioskHistory] = useState<CustomerHistoryItem[]>([]);
  const [servingCustomerRef, setServingCustomerRef] = useState("");

  const [customerLang, setCustomerLang] = useState("hi");
  const [staffLang, setStaffLang] = useState("en");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [listening, setListening] = useState(false);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);

  const [lines, setLines] = useState<Transcript[]>([]);
  const [form, setForm] = useState<FormFields>({});
  const [copilot, setCopilot] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [summaryMetrics, setSummaryMetrics] = useState<Record<string, unknown> | null>(null);
  const [liveMetrics, setLiveMetrics] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [partialLine, setPartialLine] = useState("");
  const [serverPartial, setServerPartial] = useState("");

  const [staffText, setStaffText] = useState(
    "I will help you with account opening. May I verify your mobile number linked to your Aadhaar?"
  );

  const [privacyRedact, setPrivacyRedact] = useState(false);
  const [fontScale, setFontScale] = useState("1");
  const [highContrast, setHighContrast] = useState(false);
  const [captionsMode, setCaptionsMode] = useState(false);
  const [useBrowserPartial, setUseBrowserPartial] = useState(true);

  const wsRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechRef = useRef<SpeechRecognition | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      const r = await fetch(`${httpBase()}/health`);
      setHealth(await r.json());
    } catch {
      setHealth({ status: "offline" });
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const id = window.setInterval(() => void refreshHealth(), 15000);
    return () => window.clearInterval(id);
  }, [refreshHealth]);

  // Validate cached token on mount; if invalid, fall back to login.
  useEffect(() => {
    if (!authUser) return;
    (async () => {
      const me = await fetchMe();
      if (!me) {
        clearAuth();
        setAuthUser(null);
        setPortal("gate");
      }
    })().catch(() => undefined);
  }, [authUser]);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-scale", fontScale);
  }, [fontScale]);

  useEffect(() => {
    document.documentElement.classList.toggle("a11y-hc", highContrast);
  }, [highContrast]);

  useEffect(() => {
    document.documentElement.classList.toggle("a11y-captions", captionsMode);
  }, [captionsMode]);

  const stopPlayback = () => {
    try {
      currentAudioRef.current?.pause();
      currentAudioRef.current = null;
    } catch {
      /* noop */
    }
  };

  useEffect(() => {
    if (!listening || !connected || !useBrowserPartial) {
      speechRef.current?.stop();
      speechRef.current = null;
      setPartialLine("");
      return;
    }
    const Ctor = getSpeechRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    speechRef.current = rec;
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = BCP47[customerLang] || `${customerLang}-IN`;
    rec.onresult = (ev: SpeechRecognitionEvent) => {
      let interim = "";
      let final = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        const t = r[0]?.transcript || "";
        if (r.isFinal) final += t;
        else interim += t;
      }
      const show = final || interim;
      setPartialLine(show);
      if (show && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "customer_interim",
            text: show,
            is_final: Boolean(final),
          })
        );
      }
    };
    rec.onerror = () => undefined;
    try {
      rec.start();
    } catch {
      /* noop */
    }
    return () => {
      try {
        rec.stop();
      } catch {
        /* noop */
      }
    };
  }, [listening, connected, customerLang, useBrowserPartial]);

  useEffect(() => {
    if (!sessionId || !connected) {
      setLiveMetrics(null);
      return;
    }
    const tick = async () => {
      try {
        const r = await apiFetch(`/session/${sessionId}/metrics`);
        const d = await r.json();
        if (!d.error) setLiveMetrics(d.metrics as Record<string, unknown>);
      } catch {
        /* noop */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 4000);
    return () => window.clearInterval(id);
  }, [sessionId, connected]);

  const displayText = (s: string) => (privacyRedact ? redactPII(s) : s);

  const playWavBase64 = async (b64: string) => {
    stopPlayback();
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudioRef.current = audio;
    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (currentAudioRef.current === audio) currentAudioRef.current = null;
    };
    await audio.play();
  };

  const startSession = async () => {
    setLines([]);
    setForm({});
    setCopilot(null);
    setSummary(null);
    setSummaryMetrics(null);
    setPartialLine("");
    setServerPartial("");
    const r = await apiFetch(`/session`, {
      method: "POST",
      body: JSON.stringify({
        customer_lang: customerLang,
        staff_lang: staffLang,
        customer_ref: servingCustomerRef.trim(),
      }),
    });
    if (r.status === 401) {
      clearAuth();
      setAuthUser(null);
      setPortal("gate");
      return;
    }
    const data = await r.json();
    if (data.scenarios) setScenarios(data.scenarios as string[]);
    setSessionId(data.session_id);
    const ws = new WebSocket(wsUrl(`/ws/desk/${data.session_id}`));
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string);
      if (msg.type === "ready" && msg.scenarios) setScenarios(msg.scenarios as string[]);
      if (msg.type === "transcript") {
        setLines((prev) => [
          ...prev,
          {
            role: msg.role,
            source_lang: msg.source_lang,
            text_original: msg.text_original,
            text_translated: msg.text_translated,
            glossary: msg.glossary,
            risk_flags: msg.risk_flags,
            confidence: msg.confidence,
            low_confidence: msg.low_confidence,
            normalized: msg.normalized,
          },
        ]);
      }
      if (msg.type === "partial_transcript") {
        setServerPartial(msg.text as string);
      }
      if (msg.type === "copilot") setCopilot(msg);
      if (msg.type === "form_prefill") setForm(msg.fields || {});
      if (msg.type === "tts_audio") void playWavBase64(msg.base64 as string);
      if (msg.type === "session_cleared") {
        setSessionId(null);
        setConnected(false);
      }
    };
  };

  const endSession = async () => {
    stopPlayback();
    try {
      wsRef.current?.send(JSON.stringify({ type: "end_session" }));
    } catch {
      /* noop */
    }
    wsRef.current?.close();
    wsRef.current = null;
    if (sessionId) {
      await apiFetch(`/session/${sessionId}`, { method: "DELETE" }).catch(() => undefined);
    }
    setSessionId(null);
    setConnected(false);
    setListening(false);
    await micRef.current?.stop();
    micRef.current = null;
  };

  const toggleListen = async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    if (listening) {
      stopPlayback();
      await micRef.current?.stop();
      micRef.current = null;
      setListening(false);
      setPartialLine("");
      return;
    }
    stopPlayback();
    const ws = wsRef.current;
    const cap = new MicCapture((b64) => {
      ws.send(
        JSON.stringify({
          type: "customer_audio_wav",
          base64: b64,
          format: "wav",
          sample_rate: 16000,
        })
      );
    }, 2400);
    micRef.current = cap;
    await cap.start();
    setListening(true);
  };

  const staffSpeak = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      JSON.stringify({
        type: "staff_speak",
        text: staffText,
        target_lang: customerLang,
        gender: "female",
      })
    );
  };

  const genSummary = async () => {
    if (!sessionId) return;
    const r = await apiFetch(`/summary`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await r.json();
    const summ = (data.summary || data) as Record<string, unknown>;
    setSummary(summ);
    setSummaryMetrics((data.metrics || null) as Record<string, unknown> | null);
    const ref = servingCustomerRef.trim().toUpperCase();
    if (ref) {
      const line = String(summ.summary_staff_lang ?? summ.summary_customer_lang ?? "Session summary").slice(0, 240);
      appendHistory(ref, { title: "Branch voice-desk session", detail: line });
    }
  };

  const exportPacket = async (redact: boolean) => {
    if (!sessionId) return;
    const r = await apiFetch(`/session/${sessionId}/export?redact=${redact ? "true" : "false"}`);
    const data = await r.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `desk-session-${sessionId.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const injectScenario = (scenarioId: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "inject_scenario", scenario_id: scenarioId }));
  };

  const bhashiniOk = Boolean(health?.bhashini_configured);
  const llmOk = Boolean(health?.llm_configured);
  const apiOffline = health?.status !== "ok";

  const talkingPoints = (copilot?.talking_points as string[] | undefined) || [];
  const processGuide = (copilot?.process_guide as string[] | undefined) || [];
  const disclaimersStaff = (copilot?.disclaimers_staff as string[] | undefined) || [];
  const disambiguation =
    (copilot?.disambiguation_options as { dimension?: string; choices?: string[]; staff_prompt?: string }[]) || [];
  const lowConfFallback = copilot?.low_confidence_fallback as string | undefined;
  const codeMix = copilot?.code_mixing_note as string | undefined;

  const formRows = useMemo(
    () =>
      [
        ["full_name", "Full name"],
        ["date_of_birth", "DOB"],
        ["address", "Address"],
        ["pan", "PAN"],
        ["aadhaar", "Aadhaar (masked)"],
        ["phone", "Phone"],
        ["email", "Email"],
      ] as const,
    []
  );

  const quotes = (summary?.attributed_quotes as { role?: string; excerpt?: string }[] | undefined) || [];

  const agentGuidelines = copilot?.agent_guidelines as
    | {
        task_label?: string;
        priority?: string;
        auto_checklist?: string[];
        dos?: string[];
        donts?: string[];
        escalate_when?: string[];
      }
    | undefined;

  const completeFingerprint = () => {
    const base = customerIdInput.trim() || `FP-${Date.now().toString(36).toUpperCase()}`;
    setFingerprintScanning(true);
    window.setTimeout(() => {
      setFingerprintScanning(false);
      const id = base.toUpperCase();
      setKioskCustomerId(id);
      setKioskHistory(loadHistory(id));
      setPortal("customer-kiosk");
    }, 2000);
  };

  const staffSignOut = async () => {
    await endSession();
    clearAuth();
    setAuthUser(null);
    setPortal("gate");
  };

  if (portal === "gate" || !authUser) {
    return (
      <Login
        onSuccess={(u) => {
          setAuthUser(u);
          setPortal("desk");
        }}
      />
    );
  }

  if (portal === "history") {
    return <History onBack={() => setPortal("desk")} />;
  }

  if (portal === "customer-login") {
    return (
      <div className="gate-root">
        <div className="gate-aurora" />
        <div className="gate-form glass-panel customer-login-panel">
          <button type="button" className="link-back" onClick={() => setPortal("gate")}>
            ← Back
          </button>
          <h2>Customer kiosk</h2>
          <p className="small">Enter customer ID, or use fingerprint (simulated). History is stored only in this browser.</p>
          <label className="field">
            Customer ID
            <input
              value={customerIdInput}
              onChange={(e) => setCustomerIdInput(e.target.value)}
              placeholder="e.g. CIF-102938"
            />
          </label>
          <div className={`fp-scanner ${fingerprintScanning ? "fp-scanner--active" : ""}`} aria-hidden>
            <div className="fp-ring" />
            <div className="fp-ring fp-ring--delay" />
            <span className="fp-label">{fingerprintScanning ? "Verifying…" : "Touch sensor"}</span>
          </div>
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <button type="button" disabled={fingerprintScanning} onClick={() => completeFingerprint()}>
              {customerIdInput.trim() ? "Continue with ID + fingerprint" : "Fingerprint only (demo)"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (portal === "customer-kiosk") {
    return (
      <div className="gate-root">
        <div className="gate-aurora" />
        <div className="gate-form glass-panel kiosk-panel">
          <h2>Welcome</h2>
          <p className="mono accent-mono">{kioskCustomerId}</p>
          <h3 className="kiosk-sub">Recent service requests</h3>
          <ul className="history-list">
            {kioskHistory.map((h) => (
              <li key={h.id}>
                <time>{new Date(h.at).toLocaleString()}</time>
                <strong>{h.title}</strong>
                <span>{h.detail}</span>
              </li>
            ))}
          </ul>
          <button type="button" className="secondary" onClick={() => setPortal("gate")}>
            Exit kiosk
          </button>
        </div>
      </div>
    );
  }

  const staffDisplay = authUser?.full_name || authUser?.email || "Staff";

  return (
    <div className="shell shell-desk">
      {apiOffline && (
        <div className="banner-offline">
          API unreachable or degraded — start the FastAPI backend on port 8000. Demo audio may still run with{" "}
          <span className="mono">DEMO_MODE</span>.
        </div>
      )}

      <header className="topbar topbar-desk">
        <div className="brand">
          <strong>Frontline Desk</strong>
          <span>Multilingual voice · Bhashini · session-only memory</span>
        </div>
        <div className="row topbar-actions">
          <span className="staff-chip">
            <span className="staff-dot" />
            {staffDisplay}
          </span>
          <label className="field field-inline">
            Customer ref
            <input
              className="input-compact"
              value={servingCustomerRef}
              onChange={(e) => setServingCustomerRef(e.target.value)}
              placeholder="CIF / optional"
            />
          </label>
          <span className={`pill ${health?.status === "ok" ? "ok" : "warn"}`}>
            API {String(health?.status ?? "…")}
          </span>
          <span className={`pill ${bhashiniOk ? "ok" : "warn"}`}>Bhashini {bhashiniOk ? "ready" : "demo"}</span>
          <span className={`pill ${llmOk ? "ok" : "warn"}`}>LLM {llmOk ? "ready" : "optional"}</span>
          <button type="button" className="secondary btn-compact" onClick={() => setPortal("history")}>
            History
          </button>
          <button type="button" className="secondary btn-compact" onClick={() => void staffSignOut()}>
            Sign out
          </button>
        </div>
      </header>

      <div className="panel" style={{ marginTop: "0.75rem" }}>
        <h2>Accessibility & privacy</h2>
        <div className="row">
          <label className="field">
            Text size
            <select value={fontScale} onChange={(e) => setFontScale(e.target.value)}>
              <option value="1">Standard</option>
              <option value="1.12">Large</option>
              <option value="1.24">Extra large</option>
            </select>
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={highContrast} onChange={(e) => setHighContrast(e.target.checked)} />
            High contrast
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={captionsMode} onChange={(e) => setCaptionsMode(e.target.checked)} />
            Captions / larger feed
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input type="checkbox" checked={privacyRedact} onChange={(e) => setPrivacyRedact(e.target.checked)} />
            Redact PII in UI
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={useBrowserPartial}
              onChange={(e) => setUseBrowserPartial(e.target.checked)}
              disabled={!getSpeechRecognition()}
            />
            Browser partial ASR {getSpeechRecognition() ? "" : "(unsupported)"}
          </label>
        </div>
      </div>

      <div className="grid">
        <section className="panel">
          <h2>Live console</h2>
          <div className="row" style={{ marginBottom: "0.75rem" }}>
            <label className="field">
              Customer speaks
              <select value={customerLang} onChange={(e) => setCustomerLang(e.target.value)} disabled={connected}>
                {CUSTOMER_LANGS.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label} ({l.code})
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Staff UI language
              <select value={staffLang} onChange={(e) => setStaffLang(e.target.value)} disabled={connected}>
                {STAFF_LANGS.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
            {!!scenarios.length && (
              <div className="field">
                <span>Demo inject</span>
                <div className="row" style={{ marginTop: "0.25rem" }}>
                  {scenarios.map((s) => (
                    <button key={s} type="button" className="secondary" disabled={!connected} onClick={() => injectScenario(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!connected ? (
              <button type="button" onClick={() => void startSession()}>
                Start secure session
              </button>
            ) : (
              <>
                <button type="button" className={listening ? "danger" : ""} onClick={() => void toggleListen()}>
                  {listening ? "Stop listening" : "Listen to customer"}
                </button>
                <button type="button" className="secondary" onClick={() => void genSummary()}>
                  Bilingual summary
                </button>
                <button type="button" className="secondary" onClick={() => void exportPacket(false)}>
                  Export JSON
                </button>
                <button type="button" className="secondary" onClick={() => void exportPacket(true)}>
                  Export redacted
                </button>
                <button type="button" className="danger" onClick={() => void endSession()}>
                  End & wipe session
                </button>
              </>
            )}
          </div>

          {(partialLine || serverPartial) && listening && (
            <div className="partial-box">
              <strong>Live partial</strong> (browser / server):{" "}
              <span className="mono">{displayText(partialLine || serverPartial)}</span>
            </div>
          )}

          <div className="split-console">
            <div>
              <div className="small" style={{ marginBottom: "0.35rem" }}>
                <strong>Customer stream</strong>
              </div>
              <div className="feed">
                {lines.filter((l) => l.role === "customer").length === 0 && (
                  <div className="small">Customer utterances (with confidence & INR/date hints).</div>
                )}
                {lines
                  .map((l, i) => ({ l, i }))
                  .filter(({ l }) => l.role === "customer")
                  .map(({ l, i }) => (
                    <div key={i} className="bubble customer">
                      <div className="who">
                        <span className="mono">Customer</span>
                        <span className="mono">{l.source_lang}</span>
                      </div>
                      {typeof l.confidence === "number" && (
                        <div className="confidence-bar" title={`ASR confidence ~ ${l.confidence}`}>
                          <i style={{ width: `${Math.round(l.confidence * 100)}%` }} />
                        </div>
                      )}
                      {l.low_confidence && <div className="small risk-med">Low confidence — consider repeating.</div>}
                      <div className="small" style={{ marginBottom: "0.35rem" }}>
                        <strong>Original:</strong> {displayText(l.text_original)}
                      </div>
                      <div className="small">
                        <strong>Staff view:</strong> {displayText(l.text_translated)}
                      </div>
                      {!!l.normalized?.hints?.length && (
                        <div className="small" style={{ marginTop: "0.35rem" }}>
                          <strong>Normalized hints:</strong> {l.normalized.hints.join(" · ")}
                        </div>
                      )}
                      {!!l.normalized?.normalized_snippets?.length && (
                        <div className="small">{l.normalized.normalized_snippets.join(" · ")}</div>
                      )}
                      {!!l.glossary?.length && (
                        <div style={{ marginTop: "0.5rem" }}>
                          {l.glossary.map((g) => (
                            <span key={g.term} className="tag" title={g.definition}>
                              {g.term}
                            </span>
                          ))}
                        </div>
                      )}
                      {!!l.risk_flags?.length && (
                        <div style={{ marginTop: "0.5rem" }}>
                          {l.risk_flags.map((r, j) => (
                            <span
                              key={j}
                              className={`tag ${
                                r.level === "high" ? "risk-high" : r.level === "medium" ? "risk-med" : "risk-low"
                              }`}
                            >
                              {r.reason}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            </div>
            <div>
              <div className="small" style={{ marginBottom: "0.35rem" }}>
                <strong>Staff stream</strong>
              </div>
              <div className="feed">
                {lines.filter((l) => l.role === "staff").length === 0 && (
                  <div className="small">Staff replies & translations.</div>
                )}
                {lines
                  .map((l, i) => ({ l, i }))
                  .filter(({ l }) => l.role === "staff")
                  .map(({ l, i }) => (
                    <div key={i} className="bubble staff">
                      <div className="who">
                        <span className="mono">Staff</span>
                        <span className="mono">{l.source_lang}</span>
                      </div>
                      <div className="small" style={{ marginBottom: "0.35rem" }}>
                        <strong>Original:</strong> {displayText(l.text_original)}
                      </div>
                      <div className="small">
                        <strong>Customer language:</strong> {displayText(l.text_translated)}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>

          <div style={{ marginTop: "0.85rem" }}>
            <h2 style={{ marginTop: 0 }}>Staff → customer (translate + TTS, barge-in on re-listen)</h2>
            <textarea value={staffText} onChange={(e) => setStaffText(e.target.value)} />
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <button type="button" onClick={staffSpeak} disabled={!connected}>
                Speak in customer language
              </button>
              <span className="small">Starting listening stops TTS playback (barge-in).</span>
            </div>
          </div>
        </section>

        <aside>
          {liveMetrics && (
            <section className="panel">
              <h2>Session KPIs</h2>
              <div className="kv">
                <div>Duration</div>
                <div className="mono">{String(liveMetrics.session_seconds)} s</div>
                <div>Turns</div>
                <div className="mono">{String(liveMetrics.total_turns)}</div>
                <div>Low-conf segments</div>
                <div className="mono">{String(liveMetrics.low_confidence_segments)}</div>
                <div>Bhashini errors</div>
                <div className="mono">{String(liveMetrics.bhashini_errors)}</div>
                <div>TTS playouts</div>
                <div className="mono">{String(liveMetrics.tts_playouts)}</div>
                <div>Handling index</div>
                <div className="mono">{String(liveMetrics.approx_handling_index)} turns/min</div>
              </div>
            </section>
          )}

          <section className="panel" style={{ marginTop: "1rem" }}>
            <h2>Copilot</h2>
            <div className="small" style={{ marginBottom: "0.65rem" }}>
              Intent, disambiguation, disclaimers, and SOP hints. LLM fills richer cards when configured.
            </div>
            {codeMix && (
              <div className="small" style={{ marginBottom: "0.5rem" }}>
                <strong>Code-mix:</strong> {codeMix}
              </div>
            )}
            {lowConfFallback && (
              <div className="small" style={{ marginBottom: "0.5rem" }}>
                <strong>Fallback:</strong> {lowConfFallback}
              </div>
            )}
            <div className="kv">
              <div>Intent</div>
              <div className="mono">{String(copilot?.intent ?? "—")}</div>
              <div>Confidence</div>
              <div className="mono">{String(copilot?.intent_confidence ?? "—")}</div>
            </div>
            {!!disambiguation.length && (
              <div style={{ marginTop: "0.65rem" }}>
                <div className="small" style={{ marginBottom: "0.35rem" }}>
                  <strong>Disambiguation</strong>
                </div>
                {disambiguation.map((d, i) => (
                  <div key={i} className="small" style={{ marginBottom: "0.5rem" }}>
                    <div>{d.dimension}</div>
                    <div className="row">
                      {(d.choices || []).map((c) => (
                        <span key={c} className="tag">
                          {c}
                        </span>
                      ))}
                    </div>
                    {d.staff_prompt && (
                      <button type="button" className="secondary" onClick={() => setStaffText(d.staff_prompt || "")}>
                        Use prompt
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!!disclaimersStaff.length && (
              <div style={{ marginTop: "0.65rem" }}>
                <div className="small" style={{ marginBottom: "0.35rem" }}>
                  <strong>Regulatory disclaimers (staff)</strong>
                </div>
                <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {disclaimersStaff.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!talkingPoints.length && (
              <div style={{ marginTop: "0.65rem" }}>
                <div className="small" style={{ marginBottom: "0.35rem" }}>
                  <strong>Talking points</strong>
                </div>
                <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {talkingPoints.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!processGuide.length && (
              <div style={{ marginTop: "0.65rem" }}>
                <div className="small" style={{ marginBottom: "0.35rem" }}>
                  <strong>Process guide (staff lang)</strong>
                </div>
                <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                  {processGuide.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!agentGuidelines && (
              <div className="agent-guidelines" style={{ marginTop: "0.85rem" }}>
                <div className="agent-guidelines-head">
                  <strong>Agent auto-guidelines</strong>
                  <span className={`tag tag-priority tag-${agentGuidelines.priority || "low"}`}>
                    {agentGuidelines.task_label} · {agentGuidelines.priority}
                  </span>
                </div>
                <div className="small" style={{ marginTop: "0.5rem" }}>
                  <strong>Checklist</strong>
                  <ol className="guideline-ol">
                    {(agentGuidelines.auto_checklist || []).map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ol>
                </div>
                <div className="guideline-split">
                  <div className="small">
                    <strong className="ok-inline">Do</strong>
                    <ul>
                      {(agentGuidelines.dos || []).map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="small">
                    <strong className="no-inline">Don&apos;t</strong>
                    <ul>
                      {(agentGuidelines.donts || []).map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                {!!agentGuidelines.escalate_when?.length && (
                  <div className="small escalate-box">
                    <strong>Escalate when</strong>
                    <ul>
                      {agentGuidelines.escalate_when.map((x, i) => (
                        <li key={i}>{x}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel" style={{ marginTop: "1rem" }}>
            <h2>Smart form (CBS / CRM pre-fill)</h2>
            <div className="small" style={{ marginBottom: "0.65rem" }}>
              Regex + banking LLM merge. Session-local only.
            </div>
            <div className="kv">
              {formRows.map(([k, label]) => (
                <div key={k} style={{ display: "contents" }}>
                  <div>{label}</div>
                  <div className="mono">{displayText(String(form[k] ?? "—"))}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel" style={{ marginTop: "1rem" }}>
            <h2>Bilingual summary + quotes</h2>
            {!summary && <div className="small">Generate after dialogue. Includes KPI commentary when LLM is on.</div>}
            {!!summaryMetrics && (
              <div className="small" style={{ marginBottom: "0.5rem" }}>
                At summary time: {String(summaryMetrics.session_seconds)}s · {String(summaryMetrics.total_turns)} turns ·{" "}
                {String(summaryMetrics.low_confidence_segments)} low-conf.
              </div>
            )}
            {!!summary && (
              <div className="small">
                <div style={{ marginBottom: "0.5rem" }}>
                  <strong>Staff</strong>: {displayText(String(summary.summary_staff_lang ?? ""))}
                </div>
                <div style={{ marginBottom: "0.5rem" }}>
                  <strong>Customer</strong>: {displayText(String(summary.summary_customer_lang ?? ""))}
                </div>
                {!!(summary.session_kpis_comment as string) && (
                  <div style={{ marginBottom: "0.5rem" }}>
                    <strong>KPI note:</strong> {String(summary.session_kpis_comment)}
                  </div>
                )}
                {!!quotes.length && (
                  <div style={{ marginBottom: "0.5rem" }}>
                    <strong>Attributed quotes</strong>
                    <ul>
                      {quotes.map((q, i) => (
                        <li key={i}>
                          <span className="mono">{q.role}</span>: {displayText(String(q.excerpt ?? ""))}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {!!(summary as { compliance_notes?: string[] }).compliance_notes?.length && (
                  <div>
                    <strong>Compliance</strong>
                    <ul>
                      {(summary as { compliance_notes: string[] }).compliance_notes.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
