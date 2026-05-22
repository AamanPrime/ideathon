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
  login as authLogin,
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
  const [liveMetrics, setLiveMetrics] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<string[]>([]);
  const [partialLine, setPartialLine] = useState("");
  const [serverPartial, setServerPartial] = useState("");

  const [staffText, setStaffText] = useState(
    "I will help you with account opening. May I verify your mobile number linked to your Aadhaar?"
  );
  const [staffTranslationPreview, setStaffTranslationPreview] = useState("");
  const [customerTextInput, setCustomerTextInput] = useState("");
  const [toasts, setToasts] = useState<{id: number; msg: string; type: "info" | "error" | "ok"}[]>([]);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [privacyRedact, setPrivacyRedact] = useState(false);
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

  // Auto-login on mount with the seeded admin so the user opens straight into
  // the chat. Falls back to the manual login screen only if even silent login
  // fails (e.g., backend offline or seed admin was deleted).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (authUser) {
        const me = await fetchMe();
        if (!me && !cancelled) {
          try {
            const u = await authLogin("admin@example.com", "ChangeMe!123");
            if (!cancelled) {
              setAuthUser(u);
              setPortal("desk");
            }
          } catch {
            if (!cancelled) {
              clearAuth();
              setAuthUser(null);
              setPortal("gate");
            }
          }
        }
        return;
      }
      try {
        const u = await authLogin("admin@example.com", "ChangeMe!123");
        if (!cancelled) {
          setAuthUser(u);
          setPortal("desk");
        }
      } catch {
        if (!cancelled) setPortal("gate");
      }
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
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

  const startSession = async () => {
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
        customer_lang: customerLang,
        staff_lang: staffLang,
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
    if (data.scenarios) setScenarios(data.scenarios as string[]);
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

  const injectScenario = (scenarioId: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "inject_scenario", scenario_id: scenarioId }));
  };

  // One-click guided demo: customer turn → staff reply → bilingual summary.
  const [guidedRunning, setGuidedRunning] = useState(false);
  const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
  const runGuidedDemo = async () => {
    if (guidedRunning) return;
    setGuidedRunning(true);
    try {
      if (!connected) {
        await startSession();
        await wait(900);
      }
      addToast("Step 1 — customer speaks (Gujarati)", "info");
      injectScenario("loan_enquiry_gu");
      await wait(2200);
      addToast("Step 2 — staff replies (translated + spoken)", "info");
      const reply = "I will help you with the loan enquiry. The indicative EMI for five lakh over 5 years is around ₹10,624.";
      setStaffText(reply);
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "staff_speak", text: reply, target_lang: "gu", gender: "female" }));
      }
      await wait(2800);
      addToast("Step 3 — generating bilingual summary", "info");
      await genSummary();
    } finally {
      setGuidedRunning(false);
    }
  };

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

  // ---------- WhatsApp-style chat view ----------
  const customerLangLabel = CUSTOMER_LANGS.find((l) => l.code === customerLang)?.label || customerLang;
  const staffLangLabel = STAFF_LANGS.find((l) => l.code === staffLang)?.label?.replace(/\s*\(staff\)$/i, "") || staffLang;
  const formHasAny = Object.values(form).some((v) => v);

  // Suggested staff replies from copilot (max 3).
  const suggested: string[] = [];
  for (const d of disambiguation) if (d.staff_prompt && suggested.length < 3) suggested.push(d.staff_prompt);
  for (const tp of talkingPoints) if (suggested.length < 3) suggested.push(tp);

  const [moreOpen, setMoreOpen] = useState(false);

  const sendStaffReply = () => {
    if (!staffText.trim()) return;
    staffSpeak();
    setStaffText("");
  };

  // Changing language while in a session — auto-restart with the new pair.
  const changeCustomerLang = async (next: string) => {
    setCustomerLang(next);
    if (sessionId) {
      addToast(`Switching customer language → ${next.toUpperCase()}…`, "info");
      await endSession();
      autoStartRef.current = false;
    }
  };
  const changeStaffLang = async (next: string) => {
    setStaffLang(next);
    if (sessionId) {
      await endSession();
      autoStartRef.current = false;
    }
  };

  return (
    <div className="chat-shell">
      {apiOffline && (
        <div className="banner-offline">Backend offline — start the FastAPI server on port 8000.</div>
      )}

      <header className="chat-header">
        <div className="chat-brand">
          <div className="brand-logo" aria-hidden>FD</div>
          <div className="brand-text">
            <strong>Frontline Desk</strong>
            <span>Multilingual voice assistant</span>
          </div>
        </div>

        <div className="chat-langs">
          <label className="lang-picker">
            <span>Customer</span>
            <select value={customerLang} onChange={(e) => void changeCustomerLang(e.target.value)}>
              {CUSTOMER_LANGS.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </label>
          <span className="lang-swap" aria-hidden>⇄</span>
          <label className="lang-picker">
            <span>Staff</span>
            <select value={staffLang} onChange={(e) => void changeStaffLang(e.target.value)}>
              {STAFF_LANGS.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="chat-header-actions">
          <button
            type="button"
            className="icon-btn"
            title="Copilot guidance"
            onClick={() => setMoreOpen(true)}
            aria-label="Copilot guidance"
          >
            <span className="icon-glyph">ⓘ</span>
            {typeof copilot?.intent === "string" && copilot.intent !== "generic" && <span className="icon-badge" />}
          </button>
          <ThemeToggle />
          <button type="button" className="icon-btn icon-btn-text" onClick={() => void staffSignOut()} title="Sign out">
            ⏻
          </button>
        </div>
      </header>

      {!!scenarios.length && (
        <div className="scenario-strip">
          <span className="strip-label">Try:</span>
          {scenarios.map((s) => {
            const pretty = s
              .replace(/_/g, " ")
              .replace(/\b(hi|ta|te|kn|ml|bn|mr|gu|pa|or|en)\b/i, (m) => m.toUpperCase());
            return (
              <button key={s} type="button" className="strip-chip" onClick={() => injectScenario(s)} disabled={!connected}>
                ▸ {pretty}
              </button>
            );
          })}
          <button
            type="button"
            className="strip-chip strip-chip-primary"
            onClick={() => void runGuidedDemo()}
            disabled={guidedRunning}
          >
            {guidedRunning ? "Running…" : "🎬 Guided demo"}
          </button>
        </div>
      )}

      <div className="chat-body">
        <main className="chat-main" ref={feedRef}>
          {lines.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty-icon">🎙</div>
              <h2>Tap the mic to start</h2>
              <p>
                The customer speaks <strong>{customerLangLabel}</strong>. You'll read it in <strong>{staffLangLabel}</strong>.
                Type or speak your reply — we translate it back and read it out for the customer.
              </p>
              {!!scenarios.length && (
                <p className="chat-empty-hint">
                  Or click a ▸ scenario chip above to try a sample conversation.
                </p>
              )}
            </div>
          )}

          {lines.map((l, i) => (
            <div key={i} className={`chat-row chat-row-${l.role}`}>
              <div className={`chat-bubble chat-bubble-${l.role}`}>
                <div className="chat-bubble-original">{displayText(l.text_original)}</div>
                {l.text_translated && l.text_translated !== l.text_original && (
                  <div className="chat-bubble-trans">{displayText(l.text_translated)}</div>
                )}
                <div className="chat-bubble-meta">
                  <span className="chat-bubble-lang">{l.source_lang.toUpperCase()}</span>
                  {l.role === "customer" && typeof l.confidence === "number" && (
                    <span className="chat-bubble-conf" title={`ASR confidence ${(l.confidence * 100).toFixed(0)}%`}>
                      {(l.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  {l.low_confidence && <span className="chat-bubble-warn">low confidence</span>}
                </div>
                {!!l.glossary?.length && (
                  <div className="chat-bubble-tags">
                    {l.glossary.slice(0, 4).map((g) => (
                      <span key={g.term} className="tag" title={g.definition}>{g.term}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {(partialLine || serverPartial) && listening && (
            <div className="chat-row chat-row-customer">
              <div className="chat-bubble chat-bubble-customer chat-bubble-partial">
                <span className="dot-typing"><i /><i /><i /></span>
                <span>{displayText(partialLine || serverPartial)}</span>
              </div>
            </div>
          )}
        </main>

        <aside className="chat-rail">
          <details className="rail-card" open={formHasAny}>
            <summary>
              <span>Customer details</span>
              {formHasAny && <span className="rail-meta">live</span>}
            </summary>
            <div className="rail-body">
              {!formHasAny && <p className="muted">Auto-fills as the customer shares details.</p>}
              {formHasAny && (
                <ul className="form-list">
                  {formRows.map(([k, label]) =>
                    form[k] ? (
                      <li key={k}>
                        <span className="form-list-label">{label}</span>
                        <span className="form-list-value">{displayText(String(form[k]))}</span>
                      </li>
                    ) : null
                  )}
                </ul>
              )}
            </div>
          </details>

          <details className="rail-card">
            <summary><span>Summary &amp; export</span></summary>
            <div className="rail-body">
              <div className="rail-actions">
                <button type="button" onClick={() => void genSummary()} disabled={summaryLoading || !sessionId}>
                  {summaryLoading ? "Generating…" : "📝 Generate summary"}
                </button>
                <button type="button" className="secondary" onClick={() => void exportPacket(true)} disabled={!sessionId}>
                  Export (redacted)
                </button>
              </div>
              {!!summary && (
                <div className="rail-summary">
                  <div className="block">
                    <h4>In {staffLangLabel}</h4>
                    <p>{displayText(String(summary.summary_staff_lang ?? ""))}</p>
                  </div>
                  <div className="block">
                    <h4>In {customerLangLabel}</h4>
                    <p>{displayText(String(summary.summary_customer_lang ?? ""))}</p>
                  </div>
                </div>
              )}
            </div>
          </details>

          <details className="rail-card">
            <summary>
              <span>Session</span>
              {liveMetrics && <span className="rail-meta">{String(liveMetrics.session_seconds)}s</span>}
            </summary>
            <div className="rail-body rail-session">
              <div className="kv-mini">
                <div>Customer</div><div>{customerLangLabel}</div>
                <div>Staff</div><div>{staffLangLabel}</div>
                {servingCustomerRef && (<><div>Ref</div><div className="mono">{servingCustomerRef}</div></>)}
                {liveMetrics && (<><div>Turns</div><div>{String(liveMetrics.total_turns)}</div></>)}
              </div>
              <div className="rail-actions">
                <button type="button" className="danger" onClick={() => void endSession()} disabled={!sessionId}>
                  End session
                </button>
              </div>
              <label className="rail-toggle">
                <input type="checkbox" checked={privacyRedact} onChange={(e) => setPrivacyRedact(e.target.checked)} />
                Redact PII on screen
              </label>
            </div>
          </details>
        </aside>
      </div>

      <footer className="chat-dock">
        <button
          type="button"
          className={`mic-fab ${listening ? "mic-fab-on" : ""}`}
          onClick={() => void toggleListen()}
          disabled={!connected}
          title={listening ? "Stop listening" : `Listen to customer (${customerLangLabel})`}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
            <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
            <line x1="12" y1="18" x2="12" y2="22" />
            <line x1="8" y1="22" x2="16" y2="22" />
          </svg>
          <span>{listening ? "Listening…" : `Listen (${customerLangLabel})`}</span>
        </button>

        <div className="dock-reply">
          {suggested.length > 0 && (
            <div className="dock-suggested">
              {suggested.map((s, i) => (
                <button key={i} type="button" className="dock-suggest-chip" onClick={() => setStaffText(s)} title="Use this reply">
                  {s.length > 80 ? s.slice(0, 80) + "…" : s}
                </button>
              ))}
            </div>
          )}
          <div className="dock-input-row">
            <textarea
              value={staffText}
              onChange={(e) => onStaffTextChange(e.target.value)}
              placeholder={`Type your reply in ${staffLangLabel}…`}
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  sendStaffReply();
                }
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
            <div className="dock-preview">
              <span className="dock-preview-label">In {customerLangLabel}:</span> {staffTranslationPreview}
            </div>
          )}
        </div>
      </footer>

      {moreOpen && (
        <div className="more-overlay" onClick={() => setMoreOpen(false)}>
          <aside className="more-drawer" onClick={(e) => e.stopPropagation()}>
            <header className="more-head">
              <h3>Copilot</h3>
              <button type="button" className="icon-btn" onClick={() => setMoreOpen(false)} aria-label="Close">✕</button>
            </header>
            <div className="more-body">
              {!copilot && <p className="muted">Once the customer speaks, intent, talking points and disclaimers appear here.</p>}
              {typeof copilot?.intent === "string" && copilot.intent !== "generic" && (
                <div className="block">
                  <h4>Detected intent</h4>
                  <p><strong className="intent-badge">{copilot.intent.replace(/_/g, " ")}</strong></p>
                </div>
              )}
              {lowConfFallback && <p className="hint">{lowConfFallback}</p>}
              {codeMix && <p className="hint">{codeMix}</p>}
              {!!talkingPoints.length && (
                <div className="block">
                  <h4>Talking points</h4>
                  <ul>{talkingPoints.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </div>
              )}
              {!!processGuide.length && (
                <div className="block">
                  <h4>Process guide</h4>
                  <ol>{processGuide.map((t, i) => <li key={i}>{t}</li>)}</ol>
                </div>
              )}
              {!!disclaimersStaff.length && (
                <div className="block">
                  <h4>Regulatory disclaimers</h4>
                  <ul>{disclaimersStaff.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </div>
              )}
              {!!agentGuidelines && (
                <div className="block">
                  <h4>Agent guidelines · {agentGuidelines.priority}</h4>
                  {!!agentGuidelines.auto_checklist?.length && (
                    <ol>{agentGuidelines.auto_checklist.map((x, i) => <li key={i}>{x}</li>)}</ol>
                  )}
                  <div className="dos-donts">
                    <div>
                      <strong className="ok-inline">Do</strong>
                      <ul>{(agentGuidelines.dos || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
                    </div>
                    <div>
                      <strong className="no-inline">Don't</strong>
                      <ul>{(agentGuidelines.donts || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      )}

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
