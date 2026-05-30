import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MicCapture } from "./audio/capture";
import { appendHistory, loadHistory, type CustomerHistoryItem } from "./customerHistory";
import Login from "./Login";
import History from "./History";
import { ThemeToggle } from "./ThemeToggle";
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
  { code: "gu", label: "Gujarati" },
  { code: "hi", label: "Hindi" },
  { code: "ta", label: "Tamil" },
  { code: "te", label: "Telugu" },
  { code: "kn", label: "Kannada" },
  { code: "ml", label: "Malayalam" },
  { code: "mr", label: "Marathi" },
  { code: "bn", label: "Bengali" },
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
  const [servingCustomerRef] = useState("");

  const [customerLang, setCustomerLang] = useState("gu");
  const [staffLang, setStaffLang] = useState("en");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [listening, setListening] = useState(false);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);

  const [lines, setLines] = useState<Transcript[]>([]);
  const [form, setForm] = useState<FormFields>({});
  const [copilot, setCopilot] = useState<Record<string, unknown> | null>(null);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [, setSummaryMetrics] = useState<Record<string, unknown> | null>(null);
  const [, setLiveMetrics] = useState<Record<string, unknown> | null>(null);
  const [partialLine, setPartialLine] = useState("");
  const [serverPartial, setServerPartial] = useState("");

  const [staffText, setStaffText] = useState("");
  const [staffTranslationPreview, setStaffTranslationPreview] = useState("");
  const [customerTextInput, setCustomerTextInput] = useState("");
  const [toasts, setToasts] = useState<{id: number; msg: string; type: "info" | "error" | "ok"}[]>([]);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [privacyRedact] = useState(false);
  const [fontScale] = useState("1");
  const [highContrast] = useState(false);
  const [captionsMode] = useState(false);
  const [useBrowserPartial] = useState(true);
  const feedRef = useRef<HTMLDivElement>(null);
  const staffDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastIdRef = useRef(0);

  const wsRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechRef = useRef<SpeechRecognition | null>(null);

  const addToast = useCallback((msg: string, type: "info" | "error" | "ok" = "info") => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev.slice(-4), { id, msg, type }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  // Auto-scroll feed when new messages arrive
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [lines]);

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

  // Validate cached token on mount; if invalid, drop back to login.
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
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (show) {
        ws.send(JSON.stringify({ type: "customer_interim", text: show, is_final: Boolean(final) }));
      }
      // When ASR finalises a phrase, commit it as a real customer turn so the
      // backend runs translation + intent + form-prefill + copilot enrichment.
      if (final.trim()) {
        ws.send(JSON.stringify({ type: "customer_text", text: final.trim(), lang: customerLang }));
        setPartialLine("");
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

  const speakLocally = (text: string, lang: string) => {
    if (!("speechSynthesis" in window) || !text) return;
    const synth = window.speechSynthesis;
    const target = (BCP47[lang] || `${lang}-IN`).toLowerCase();
    const langPrefix = lang.toLowerCase();
    const doSpeak = () => {
      try {
        synth.cancel();
        const voices = synth.getVoices();
        let voice =
          voices.find((v) => v.lang.toLowerCase() === target) ||
          voices.find((v) => v.lang.toLowerCase().startsWith(langPrefix)) ||
          voices.find((v) => v.lang.toLowerCase().startsWith(target.slice(0, 2))) ||
          null;
        const cand = voices.filter((v) => v.lang.toLowerCase().startsWith(target.slice(0, 2)));
        const premium = cand.find((v) => /premium|enhanced|natural|neural/i.test(v.name));
        if (premium) voice = premium;
        const u = new SpeechSynthesisUtterance(text);
        u.lang = BCP47[lang] || `${lang}-IN`;
        u.rate = 0.92;
        u.pitch = 1.0;
        if (voice) u.voice = voice;
        synth.speak(u);
      } catch { /* noop */ }
    };
    if (synth.getVoices().length === 0) {
      const handler = () => {
        synth.removeEventListener("voiceschanged", handler);
        doSpeak();
      };
      synth.addEventListener("voiceschanged", handler);
      synth.getVoices();
      setTimeout(() => { if (synth.getVoices().length > 0) doSpeak(); }, 600);
    } else {
      doSpeak();
    }
  };

  // Warm up voices on first render so the first speak() doesn't get a silent list.
  useEffect(() => {
    if ("speechSynthesis" in window) window.speechSynthesis.getVoices();
  }, []);

  // Kept for the future "type customer text" affordance. Currently the new
  // chat UI captures customer text only via the mic (browser ASR finals).
  const sendCustomerText = () => {
    const text = customerTextInput.trim();
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      JSON.stringify({ type: "customer_text", text, lang: customerLang })
    );
    setCustomerTextInput("");
    addToast("Customer text sent for translation", "ok");
  };
  void sendCustomerText;

  // Staff typing → live translation preview
  const onStaffTextChange = (val: string) => {
    setStaffText(val);
    if (staffDebounceRef.current) clearTimeout(staffDebounceRef.current);
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    staffDebounceRef.current = setTimeout(() => {
      const t = val.trim();
      if (t.length < 4) return;
      wsRef.current?.send(JSON.stringify({ type: "staff_interim", text: t }));
    }, 400);
  };

  const startSession = async (override?: { cust?: string; staff?: string }) => {
    const cLang = override?.cust ?? customerLang;
    const sLang = override?.staff ?? staffLang;
    setSessionLoading(true);
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
        customer_lang: cLang,
        staff_lang: sLang,
        customer_ref: servingCustomerRef.trim(),
      }),
    });
    if (r.status === 401) {
      clearAuth();
      setAuthUser(null);
      setPortal("gate");
      setSessionLoading(false);
      return;
    }
    const data = await r.json();
    setSessionLoading(false);
    setSessionId(data.session_id);
    const ws = new WebSocket(wsUrl(`/ws/desk/${data.session_id}`));
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      addToast("Session connected", "ok");
    };
    ws.onclose = () => {
      setConnected(false);
      addToast("Session disconnected", "info");
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string);
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
      if (msg.type === "tts_audio") {
        void playWavBase64(msg.base64 as string);
        addToast("Playing TTS audio", "ok");
      }
      if (msg.type === "tts_fallback") {
        speakLocally(msg.text as string, msg.lang as string);
        addToast("Speaking in customer language (browser TTS)", "ok");
      }
      if (msg.type === "tts_error") {
        addToast(`TTS error: ${msg.message}`, "error");
      }
      if (msg.type === "staff_partial_translation") {
        setStaffTranslationPreview(msg.text_translated as string || "");
      }
      if (msg.type === "error") {
        addToast(`Error: ${msg.message}`, "error");
      }
      if (msg.type === "session_cleared") {
        setSessionId(null);
        setConnected(false);
        addToast("Session cleared", "info");
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

  // Change customer/staff language. A session is bound to its languages at
  // creation, so if one is live we transparently restart it with the new pair.
  const switchLang = async (which: "cust" | "staff", value: string) => {
    if (which === "cust") setCustomerLang(value);
    else setStaffLang(value);
    if (sessionId || connected) {
      await endSession();
      autoStartRef.current = true; // we restart manually below; don't double-fire the auto effect
      await startSession({
        cust: which === "cust" ? value : customerLang,
        staff: which === "staff" ? value : staffLang,
      });
    }
  };

  // Auto-start a session as soon as we're logged in, so the chat is ready.
  const autoStartRef = useRef(false);
  useEffect(() => {
    if (!authUser || sessionId || sessionLoading || autoStartRef.current) return;
    autoStartRef.current = true;
    void startSession().catch(() => { autoStartRef.current = false; });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authUser]);

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
    // When the browser Web Speech API is available (Chrome), it does live ASR
    // and emits `customer_text` finals — the real-time path. Streaming raw
    // audio chunks on top of that is redundant (the backend has no server-side
    // ASR), so we only fall back to MicCapture when Web Speech is unavailable.
    if (!getSpeechRecognition()) {
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
    }
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
    setSummaryLoading(true);
    addToast("Generating bilingual summary…", "info");
    try {
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
      addToast("Summary generated", "ok");
    } catch {
      addToast("Summary generation failed", "error");
    } finally {
      setSummaryLoading(false);
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


  const apiOffline = health?.status !== "ok";

  const talkingPoints = (copilot?.talking_points as string[] | undefined) || [];
  const processGuide = (copilot?.process_guide as string[] | undefined) || [];
  const disclaimersStaff = (copilot?.disclaimers_staff as string[] | undefined) || [];
  const disambiguation =
    (copilot?.disambiguation_options as { dimension?: string; choices?: string[]; staff_prompt?: string }[]) || [];

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

  // ---------- Dashboard state (must run on every render, before early returns) ----------
  // Customer-ID state (manual + auto-detected)
  const [currentCustomerId, setCurrentCustomerId] = useState<string>("");
  const [customerIdEditing, setCustomerIdEditing] = useState(false);
  const [customerIdDraft, setCustomerIdDraft] = useState("");
  const [autoDetectedCid, setAutoDetectedCid] = useState(false);

  // Auto-detect a CIF / Customer ID pattern in any conversation turn and
  // populate it once (don't override a manually-entered one).
  const CID_PATTERN = /\b(?:CIF|CID|CUST(?:OMER)?\s*ID)[-\s]?([A-Z0-9]{4,12})\b/i;
  useEffect(() => {
    if (currentCustomerId) return;
    for (const t of lines) {
      const combined = `${t.text_original} ${t.text_translated}`;
      const m = combined.match(CID_PATTERN);
      if (m) {
        const id = `CIF-${m[1].toUpperCase()}`.replace(/^CIF-CIF-/i, "CIF-");
        setCurrentCustomerId(id);
        setAutoDetectedCid(true);
        addToast(`Customer ID auto-detected: ${id}`, "ok");
        break;
      }
    }
  }, [lines, currentCustomerId, addToast]);

  // Session history for the sidebar
  type SessionRow = {
    id: string;
    customer_lang: string;
    staff_lang: string;
    customer_ref: string;
    status: string;
    last_intent: string | null;
    created_at: string | null;
  };
  const [sessionHistory, setSessionHistory] = useState<SessionRow[]>([]);
  const [historyFilter, setHistoryFilter] = useState("");
  const refreshHistory = useCallback(async () => {
    try {
      const r = await apiFetch("/sessions");
      if (!r.ok) return;
      const data = (await r.json()) as { sessions: SessionRow[] };
      setSessionHistory(data.sessions || []);
    } catch {
      /* noop */
    }
  }, []);
  useEffect(() => {
    if (!authUser) return;
    void refreshHistory();
    const id = window.setInterval(() => void refreshHistory(), 12000);
    return () => window.clearInterval(id);
  }, [authUser, refreshHistory]);
  useEffect(() => {
    if (!sessionId) void refreshHistory();
  }, [sessionId, summary, refreshHistory]);

  const filteredHistory = useMemo(() => {
    const f = historyFilter.trim().toLowerCase();
    if (!f) return sessionHistory.slice(0, 30);
    return sessionHistory
      .filter((s) =>
        (s.customer_ref || "").toLowerCase().includes(f) ||
        (s.last_intent || "").toLowerCase().includes(f) ||
        s.id.toLowerCase().includes(f)
      )
      .slice(0, 30);
  }, [sessionHistory, historyFilter]);

  const customerPriorVisits = useMemo(() => {
    if (!currentCustomerId) return [];
    const key = currentCustomerId.toLowerCase().replace(/^cif-/, "");
    return sessionHistory.filter(
      (s) => (s.customer_ref || "").toLowerCase().replace(/^cif-/, "").includes(key) && s.id !== sessionId
    );
  }, [sessionHistory, currentCustomerId, sessionId]);

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
        <ThemeToggle />
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
        <ThemeToggle />
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

  // ---------- Dashboard view ----------
  const customerLangLabel = CUSTOMER_LANGS.find((l) => l.code === customerLang)?.label || customerLang;
  const staffLangLabel = STAFF_LANGS.find((l) => l.code === staffLang)?.label?.replace(/\s*\(staff\)$/i, "") || staffLang;

  // Staff profile
  const staffName = authUser?.full_name || authUser?.email || "Staff";
  const staffInitials = staffName.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  const staffRole = authUser?.role || "staff";

  // Start a brand new session (resets state). Used by "+ New chat".
  const newChat = async () => {
    if (sessionId) await endSession();
    setCurrentCustomerId("");
    setCustomerIdDraft("");
    setCustomerIdEditing(false);
    setAutoDetectedCid(false);
    setLines([]);
    setForm({});
    setCopilot(null);
    setSummary(null);
    setSummaryMetrics(null);
    await startSession();
  };

  // Suggested staff replies from copilot (max 3, dedup)
  const suggested: string[] = [];
  for (const d of disambiguation) if (d.staff_prompt && !suggested.includes(d.staff_prompt) && suggested.length < 3) suggested.push(d.staff_prompt);
  for (const tp of talkingPoints) if (!suggested.includes(tp) && suggested.length < 3) suggested.push(tp);

  const sendStaffReply = () => {
    if (!staffText.trim()) return;
    staffSpeak();
    setStaffText("");
  };

  // Split turns by role for the two-pane layout
  const customerTurns = lines.filter((l) => l.role === "customer");
  const staffTurns = lines.filter((l) => l.role === "staff");

  // Compact summary (key points only)
  const products = ((summary?.products_discussed as string[] | undefined) || []);
  const actionItems = ((summary?.action_items as string[] | undefined) || []);
  const intentLabel = typeof copilot?.intent === "string" ? copilot.intent.replace(/_/g, " ") : "—";
  const intentConf = typeof copilot?.intent_confidence === "number" ? Math.round(copilot.intent_confidence * 100) : null;

  const saveCustomerId = () => {
    const trimmed = customerIdDraft.trim();
    if (!trimmed) return;
    const formatted = /^cif|cid/i.test(trimmed) ? trimmed.toUpperCase() : `CIF-${trimmed.toUpperCase()}`;
    setCurrentCustomerId(formatted);
    setAutoDetectedCid(false);
    setCustomerIdEditing(false);
    addToast(`Customer ID set: ${formatted}`, "ok");
  };

  return (
    <div className="dash">
      {apiOffline && (
        <div className="banner-offline">Backend offline — start the FastAPI server on port 8000.</div>
      )}

      {/* ----- SIDEBAR ----- */}
      <aside className="dash-sidebar">
        <div className="dash-sidebar-brand">
          <div className="brand-logo" aria-hidden>UB</div>
          <div>
            <strong>Union Bank</strong>
            <span>Branch Assistant</span>
          </div>
        </div>

        <button type="button" className="new-chat-btn" onClick={() => void newChat()}>
          <span className="plus">＋</span> New conversation
        </button>

        <div className="sidebar-search">
          <input
            value={historyFilter}
            onChange={(e) => setHistoryFilter(e.target.value)}
            placeholder="Search customer ID or intent…"
          />
        </div>

        <div className="sidebar-history">
          <div className="sidebar-section">Recent</div>
          {filteredHistory.length === 0 && (
            <div className="sidebar-empty">No prior conversations.</div>
          )}
          {filteredHistory.map((s) => {
            const isCurrent = s.id === sessionId;
            const ts = s.created_at ? new Date(s.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
            const label = s.customer_ref || "Walk-in";
            return (
              <button
                key={s.id}
                type="button"
                className={`history-item ${isCurrent ? "history-item-active" : ""}`}
                onClick={() => {
                  if (s.customer_ref && !currentCustomerId) {
                    setCurrentCustomerId(s.customer_ref);
                    addToast(`Loaded customer: ${s.customer_ref}`, "info");
                  }
                  setHistoryFilter("");
                }}
                title={s.id}
              >
                <div className="history-top">
                  <span className="history-id">{label}</span>
                  <span className="history-status">{s.status}</span>
                </div>
                <div className="history-bot">
                  <span>{s.last_intent ? s.last_intent.replace(/_/g, " ") : "—"}</span>
                  <span className="mono">{ts}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="sidebar-profile">
          <div className="profile-avatar">{staffInitials}</div>
          <div className="profile-meta">
            <strong>{staffName}</strong>
            <span>{staffRole === "admin" ? "Branch admin" : "Branch staff"}</span>
          </div>
          <ThemeToggle />
          <button type="button" className="profile-signout" onClick={() => void staffSignOut()} title="Sign out">⏻</button>
        </div>
      </aside>

      {/* ----- MAIN ----- */}
      <main className="dash-main">
        {/* Customer-info top bar */}
        <header className="dash-topbar">
          <div className="cust-info">
            {!currentCustomerId && !customerIdEditing && (
              <div className="cust-info-empty">
                <span className="cust-dot cust-dot-walkin" />
                <div>
                  <strong>Walk-in customer</strong>
                  <span>No customer ID yet — fine for new accounts. Add one later when asked.</span>
                </div>
                <button type="button" className="link-btn" onClick={() => { setCustomerIdEditing(true); setCustomerIdDraft(""); }}>
                  ＋ Add customer ID
                </button>
              </div>
            )}

            {customerIdEditing && (
              <div className="cust-info-edit">
                <input
                  autoFocus
                  value={customerIdDraft}
                  onChange={(e) => setCustomerIdDraft(e.target.value)}
                  placeholder="e.g. 102938 or CIF-102938"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveCustomerId();
                    if (e.key === "Escape") setCustomerIdEditing(false);
                  }}
                />
                <button type="button" onClick={saveCustomerId} disabled={!customerIdDraft.trim()}>Save</button>
                <button type="button" className="secondary" onClick={() => setCustomerIdEditing(false)}>Cancel</button>
              </div>
            )}

            {currentCustomerId && !customerIdEditing && (
              <div className="cust-info-known">
                <span className="cust-dot cust-dot-known" />
                <div className="cust-info-block">
                  <strong>
                    {currentCustomerId}
                    {autoDetectedCid && <span className="cust-auto-tag">✨ auto-detected</span>}
                  </strong>
                  <span>
                    {customerPriorVisits.length > 0
                      ? `${customerPriorVisits.length} prior visit${customerPriorVisits.length === 1 ? "" : "s"}`
                      : "No prior visits on file"}
                    {form.full_name && <> · <span className="mono">{displayText(String(form.full_name))}</span></>}
                  </span>
                </div>
                <button type="button" className="link-btn" onClick={() => { setCustomerIdEditing(true); setCustomerIdDraft(currentCustomerId.replace(/^CIF-/, "")); }}>
                  Edit
                </button>
              </div>
            )}
          </div>

          <div className="topbar-langs">
            <label>
              <span>Customer</span>
              <select
                value={customerLang}
                onChange={(e) => void switchLang("cust", e.target.value)}
                disabled={sessionLoading}
                title="Pick the customer's language (restarts the session)"
              >
                {CUSTOMER_LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
            </label>
            <span className="lang-swap" aria-hidden>⇄</span>
            <label>
              <span>Staff</span>
              <select
                value={staffLang}
                onChange={(e) => void switchLang("staff", e.target.value)}
                disabled={sessionLoading}
              >
                {STAFF_LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
            </label>
          </div>

          <div className="topbar-actions">
            {!sessionId && (
              <button type="button" onClick={() => void startSession()} disabled={sessionLoading}>
                {sessionLoading ? "Starting…" : "▶ Start session"}
              </button>
            )}
            {sessionId && (
              <button type="button" className="danger" onClick={() => void endSession()}>
                End session
              </button>
            )}
          </div>
        </header>

        {/* Two-pane conversation */}
        <div className="dash-convo">
          {/* LEFT: Customer pane */}
          <section className="convo-pane convo-pane-customer">
            <header className="convo-head">
              <h2>
                <span className="head-dot head-dot-customer" />
                Customer
              </h2>
              <span className="convo-lang">{customerLangLabel}</span>
            </header>

            <div className="convo-feed">
              {customerTurns.length === 0 && (
                <div className="convo-empty">
                  <div className="convo-empty-icon">🎙</div>
                  <p>Press the mic below to start. The customer's speech appears here in their language and is translated to your language in real time.</p>
                </div>
              )}
              {customerTurns.map((l, i) => (
                <article key={`c-${i}`} className="convo-turn convo-turn-customer">
                  <div className="convo-turn-original">{displayText(l.text_original)}</div>
                  {l.text_translated && l.text_translated !== l.text_original && (
                    <div className="convo-turn-trans">↳ {displayText(l.text_translated)}</div>
                  )}
                  <div className="convo-turn-meta">
                    <span>{l.source_lang.toUpperCase()}</span>
                    {typeof l.confidence === "number" && (
                      <span title={`ASR confidence ${(l.confidence * 100).toFixed(0)}%`}>
                        {(l.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    {l.low_confidence && <span className="warn">low conf</span>}
                  </div>
                </article>
              ))}
              {(partialLine || serverPartial) && listening && (
                <article className="convo-turn convo-turn-customer convo-turn-partial">
                  <span className="dot-typing"><i /><i /><i /></span>
                  <span>{displayText(partialLine || serverPartial)}</span>
                </article>
              )}
            </div>

            <div className="convo-input">
              <button
                type="button"
                className={`mic-fab ${listening ? "mic-fab-on" : ""}`}
                onClick={() => void toggleListen()}
                disabled={!connected}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
                  <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
                  <line x1="12" y1="18" x2="12" y2="22" />
                  <line x1="8" y1="22" x2="16" y2="22" />
                </svg>
                <span>{listening ? "Listening… tap to stop" : `Listen (${customerLangLabel})`}</span>
              </button>
            </div>
          </section>

          {/* RIGHT: Staff pane */}
          <section className="convo-pane convo-pane-staff">
            <header className="convo-head">
              <h2>
                <span className="head-dot head-dot-staff" />
                Staff
              </h2>
              <span className="convo-lang">{staffLangLabel}</span>
            </header>

            <div className="convo-feed">
              {staffTurns.length === 0 && (
                <div className="convo-empty">
                  <div className="convo-empty-icon">💬</div>
                  <p>Your replies appear here. Type below or pick a suggested reply — we translate to {customerLangLabel} and speak it out loud for the customer.</p>
                </div>
              )}
              {staffTurns.map((l, i) => (
                <article key={`s-${i}`} className="convo-turn convo-turn-staff">
                  <div className="convo-turn-original">{displayText(l.text_original)}</div>
                  {l.text_translated && l.text_translated !== l.text_original && (
                    <div className="convo-turn-trans">↳ in {customerLangLabel}: {displayText(l.text_translated)}</div>
                  )}
                  <div className="convo-turn-meta">
                    <span>{l.source_lang.toUpperCase()}</span>
                    <span>spoken</span>
                  </div>
                </article>
              ))}
            </div>

            <div className="convo-input">
              {(processGuide.length > 0 || disclaimersStaff.length > 0 || agentGuidelines) && (
                <details className="guidance-card">
                  <summary>
                    <span>Copilot guidance</span>
                    {agentGuidelines?.priority && <span className={`guidance-pri pri-${agentGuidelines.priority}`}>{agentGuidelines.priority}</span>}
                  </summary>
                  <div className="guidance-body">
                    {!!processGuide.length && (
                      <div className="guidance-block">
                        <h4>Process guide</h4>
                        <ol>{processGuide.slice(0, 4).map((t, i) => <li key={i}>{t}</li>)}</ol>
                      </div>
                    )}
                    {!!disclaimersStaff.length && (
                      <div className="guidance-block">
                        <h4>Regulatory disclaimers</h4>
                        <ul>{disclaimersStaff.slice(0, 3).map((t, i) => <li key={i}>{t}</li>)}</ul>
                      </div>
                    )}
                    {!!agentGuidelines && (
                      <div className="guidance-block guidance-dosdonts">
                        <div>
                          <strong className="ok-inline">Do</strong>
                          <ul>{(agentGuidelines.dos || []).slice(0, 3).map((x, i) => <li key={i}>{x}</li>)}</ul>
                        </div>
                        <div>
                          <strong className="no-inline">Don't</strong>
                          <ul>{(agentGuidelines.donts || []).slice(0, 3).map((x, i) => <li key={i}>{x}</li>)}</ul>
                        </div>
                      </div>
                    )}
                  </div>
                </details>
              )}
              {suggested.length > 0 && (
                <div className="suggested-wrap">
                  <div className="suggested-label">Suggested replies</div>
                  <div className="suggested-list">
                    {suggested.map((s, i) => (
                      <button key={i} type="button" className="suggest-chip" onClick={() => setStaffText(s)} title={s}>
                        {s.length > 90 ? s.slice(0, 90) + "…" : s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="staff-input-row">
                <textarea
                  value={staffText}
                  onChange={(e) => onStaffTextChange(e.target.value)}
                  placeholder={`Type your reply in ${staffLangLabel}…  (⌘/Ctrl + Enter to send)`}
                  rows={2}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendStaffReply(); }
                  }}
                />
                <button
                  type="button"
                  className="send-fab"
                  onClick={sendStaffReply}
                  disabled={!connected || !staffText.trim()}
                  title={`Translate & speak in ${customerLangLabel}`}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M22 2L11 13" />
                    <path d="M22 2l-7 20-4-9-9-4 20-7z" />
                  </svg>
                </button>
              </div>
              {staffTranslationPreview && (
                <div className="staff-preview">
                  <span>In {customerLangLabel}:</span> {staffTranslationPreview}
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Compact summary */}
        <section className="dash-summary">
          <header>
            <h3>Live summary</h3>
            <div className="summary-actions">
              <button type="button" className="secondary" onClick={() => void genSummary()} disabled={!sessionId || summaryLoading}>
                {summaryLoading ? "Generating…" : "📝 Generate full summary"}
              </button>
              <button type="button" className="secondary" onClick={() => void exportPacket(true)} disabled={!sessionId}>
                Export (redacted)
              </button>
            </div>
          </header>
          <div className="summary-grid">
            <div className="summary-card">
              <div className="summary-card-label">Intent</div>
              <div className="summary-card-value">
                {intentLabel}{intentConf !== null && <span className="muted"> · {intentConf}%</span>}
              </div>
            </div>
            <div className="summary-card">
              <div className="summary-card-label">Products discussed</div>
              <div className="summary-card-value">
                {products.length ? products.join(", ") : "—"}
              </div>
            </div>
            <div className="summary-card">
              <div className="summary-card-label">Customer details captured</div>
              <div className="summary-card-value">
                {formRows.filter(([k]) => form[k]).map(([k, label]) => (
                  <div key={k}><span className="muted">{label}:</span> <span className="mono">{displayText(String(form[k]))}</span></div>
                ))}
                {!formRows.some(([k]) => form[k]) && <span className="muted">None yet</span>}
              </div>
            </div>
            <div className="summary-card">
              <div className="summary-card-label">Action items</div>
              <div className="summary-card-value">
                {actionItems.length ? (
                  <ul>{actionItems.slice(0, 4).map((a, i) => <li key={i}>{a}</li>)}</ul>
                ) : (
                  <span className="muted">Click <em>Generate full summary</em> after the chat.</span>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      {toasts.length > 0 && (
        <div className="toast-stack">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`toast toast-${t.type}`}
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            >
              {t.msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
