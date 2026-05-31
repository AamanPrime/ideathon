# BharatVaani — Multilingual Gen-AI Banking Voice Assistant

**Team AlphaForge · PSBs Hackathon Series 2026 (IDEA 2.0 · Union Bank of India)**

A real-time, two-way voice assistant for bank frontline desks. The customer speaks
in **any of 11+ Indian languages**; the officer hears and reads it in English and
replies normally; the customer **hears the reply back in their own language** — all
in **under a second per turn**. Alongside translation, the system understands banking
intent, auto-fills KYC fields, masks PII, and writes a **bilingual, auditable record**
of every conversation.

> **Verified working** end-to-end on **Hindi** and **Gujarati** using
> **Google Gemini Live (native audio)** on **Vertex AI**.

---

## 1. The problem

India has 22 official languages and 120+ widely spoken ones, yet only ~10% of Indians
are comfortable in English. A bank officer at a branch frequently shares **no common
language** with the customer in front of them. With no interpreters available, this gap
causes:

- Slow service, KYC / data-entry errors, and mis-selling
- Exclusion of low-literacy, migrant, senior and regional-language customers
- Compliance risk against RBI's regional-language service expectations
- Staff having to be hired and posted **by language**

This affects **~200,000 bank branches** and **1.35 million+ banking correspondents**
across India.

---

## 2. What it does

1. **Real-time speech-to-speech translation** — Indic customer voice ⇄ English staff
   voice, bidirectional, turn-by-turn, < 1 s latency. Powered by **Gemini Live
   native-audio** (no brittle ASR→MT→TTS chain).
2. **Automatic language detection + memory** — no dropdowns; the customer just talks
   and is always answered in the same language they used.
3. **Banking-aware intelligence** — intent (account opening / loan / card dispute /
   remittance / locker), KYC form auto-fill, risk-phrase flags, SOP talking points.
   Powered by **Gemini 2.5 Flash**.
4. **Trust & governance** — JWT auth with roles, PII redaction (PAN / Aadhaar / phone /
   email) before persistence, audit-log table, redacted export.
5. **Bilingual interaction record** — every session generates a structured bilingual
   summary (purpose, key points, products, follow-ups, compliance notes) for the audit file.

> **Stack:** React + Vite + TypeScript · FastAPI (async) · SQLAlchemy 2 · SQLite/Postgres ·
> WebSockets · Google Gemini Live + Gemini 2.5 Flash on **Vertex AI** · JWT.

---

## 3. Architecture (overview)

```
Customer voice ─► Branch Desk (React + AudioWorklet, PCM16 @16kHz)
              ─► Real-Time Gateway (FastAPI · WebSocket · JWT · session store)
              ─► Gemini Live · Vertex AI (auto-detect · VAD · speech ⇄ speech)
   ◄── translated audio + live transcript stream back in < 1s (bidirectional) ──

   Each finished turn ─► Gemini 2.5 Flash (intent · KYC autofill · PII masking · summary)
                      ─► Secure datastore (bilingual records · audit log · RBAC)
```

The live audio loop lives in `backend/app/routers/live.py` (`/ws/live-translate`).
Live session state stays in RAM for hot-path latency; the DB is the audit-grade mirror,
and only **redacted** turns are persisted. See the Technical Architecture document for the
full labelled diagram and component breakdown.

---

## 4. How to run

### Prerequisites
- **Python 3.11+** (developed on 3.13) and **Node 18+**
- A **Google Cloud service-account JSON** with Vertex AI access (for the live audio
  path), or a `GEMINI_API_KEY` for the text-only fallback.

### 4.1 Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # FastAPI, SQLAlchemy, google-genai, etc.

# Credentials (NEVER commit these — both are gitignored):
#   place the GCP service-account JSON at backend/gcp_service_account.json
cp .env.example .env                      # then edit values (see table below)

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
On first launch the backend creates `frontline_desk.db` (SQLite), seeds an **admin user**
(`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`, defaults `admin@bank.local` / `ChangeMe!123`),
and prints the active AI provider.

### 4.2 Frontend
```bash
cd frontend
npm install
npm run dev        # serves on http://localhost:5173  (use localhost, not 127.0.0.1)
```
Open **http://localhost:5173**, sign in with the seed admin, choose languages, start the
live session, allow the microphone, and speak.

---

## 5. Dependencies

**Backend (Python):** `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `aiosqlite`,
`pydantic-settings`, `pyjwt` / `python-jose`, `passlib[bcrypt]`, **`google-genai`**
(Vertex AI + Gemini Live), `python-multipart`, `websockets`. Full list in
`backend/requirements.txt`.

**Frontend (Node):** `react`, `react-dom`, `vite`, `typescript`. Uses the browser
**Web Audio / AudioWorklet** and **WebSocket** APIs (no extra audio libs). Full list in
`frontend/package.json`.

**Cloud:** Google **Vertex AI** with the Gemini Live API enabled on the project.

### Environment variables (`backend/.env`)
| Variable | What it does |
| --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./frontline_desk.db` (default) or a Postgres async URL |
| `JWT_SECRET` | HMAC secret for signing JWTs (rotate in prod) |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` / `SEED_ADMIN_NAME` | First admin created on empty DB |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the GCP service-account JSON (default `gcp_service_account.json`) |
| `GEMINI_PROJECT_ID` | GCP project ID for Vertex AI |
| `VERTEX_LOCATION` | Vertex region (default `us-central1`) |
| `GEMINI_MODEL` | Live model (default `gemini-live-2.5-flash-native-audio`) |
| `GEMINI_API_KEY` | Optional key for the OpenAI-compatible text fallback |
| `CORS_ORIGINS` | Comma-separated origins (Vite dev defaults work out of the box) |

---

## 6. Sample data

- **Seed admin user** is created automatically on first run — `admin@bank.local` /
  `ChangeMe!123`. Use it to sign in immediately; no data import needed.
- **Synthetic audio for testing the live loop** — generate sample utterances and stream
  them through the WebSocket (no microphone needed):
  ```bash
  # Hindi (macOS voice) and Gujarati (gTTS), converted to 16 kHz PCM
  say -v Lekha -o /tmp/hindi.aiff "मुझे एक बचत खाता खोलना है"
  ffmpeg -y -i /tmp/hindi.aiff -ar 16000 -ac 1 -f s16le /tmp/hindi.pcm
  python -c "from gtts import gTTS; gTTS('મારે બચત ખાતું ખોલવું છે', lang='gu').save('/tmp/guj.mp3')"
  ffmpeg -y -i /tmp/guj.mp3 -ar 16000 -ac 1 -f s16le /tmp/guj.pcm
  ```
- **Integration test scripts** (in `backend/`) stream that audio at the live endpoint and
  print the transcript + translation + whether translated audio came back:
  - `test_live_ws.py` — single Hindi → English turn
  - `test_live_twoturn.py` — Hindi → English **then** English → Hindi (multi-turn, bidirectional)
  - `test_live_gujarati.py` — Gujarati ⇄ English
  ```bash
  python test_live_twoturn.py     # backend must be running on :8000
  ```

---

## 7. Known limitations

- **Languages verified end-to-end:** Hindi and Gujarati. The model supports many more
  (target 22+), but only these two are fully validated in our tests.
- **Cloud dependency:** the live audio path requires **Vertex AI Gemini Live to be
  enabled** on the GCP project and network access to Google. There is no offline mode yet.
- **On-prem / local LLM (Ollama) deployment** for strict data residency is **designed but
  not yet implemented** — current builds run on Vertex AI (India-region capable).
- **Speaker attribution is heuristic:** the customer-vs-staff direction is inferred from
  the transcript's script (Indic vs Latin). This is clean for a regional-language customer
  + English-speaking officer, but ambiguous if both speak the same script.
- **Microphone + modern browser required;** the frontend serves on `localhost` (use
  `localhost:5173`, not `127.0.0.1`). Audio autoplay needs a user gesture.
- **Latency / reliability** depend on the branch's internet link; a text fallback exists
  but is less seamless than the native-audio loop.
- **Cost at national scale** is non-trivial; production would use language-pack tiers and
  autoscaling to control unit cost.
- **Not yet integrated** with a real Core Banking System / CRM — KYC autofill is a
  pre-fill surface, not a write-back to CBS.

---

## 8. API surface

All endpoints (except `/health`, `/auth/login`) require `Authorization: Bearer <jwt>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Provider / DB status |
| `POST` | `/auth/login` | Email + password → JWT + user |
| `GET` | `/auth/me` | Current user |
| `POST` | `/auth/register` (admin) | Create staff users |
| `POST` | `/session` | Open a desk session |
| `GET` | `/sessions` · `/sessions/{id}` | List / fetch sessions (bilingual record) |
| `POST` | `/summary` | Generate + persist bilingual summary |
| `GET` | `/session/{id}/metrics` · `/export` | KPIs / JSON export |
| `WS` | `/ws/live-translate?source_lang=&target_lang=&session_id=` | **Live Gemini speech-to-speech translation** |
| `WS` | `/ws/desk/{session_id}?token=<jwt>` | Turn-based desk channel (copilot, summaries) |

---

## 9. Data model

- **`users`** — `email`, bcrypt `password_hash`, `role` (admin/staff), `branch_code`, `preferred_lang`
- **`desk_sessions`** — owner, langs, customer_ref, JSON `metrics` / `form_snapshot` / `turns` (redacted), `status`
- **`interaction_records`** — bilingual summary + full payload JSON, per session
- **`audit_events`** — login, register, session open/close/export

PII redaction runs **before** anything is written to `desk_sessions.turns`, so the DB
never stores a raw Aadhaar / PAN / phone / email.

---

## 10. License

Released under the **MIT License**. Third-party services (Google Gemini / Vertex AI)
retain their own terms; this license covers only the code in this repository.
