# Frontline Desk — Multilingual Gen-AI Banking Voice Assistant

Real-time multilingual voice loop for branch staff:

1. **Real multilingual voice loop** — Indic customer in → ASR → MT → staff sees own language → staff replies → MT → TTS plays back in customer's language. Powered by **Bhashini** ULCA pipelines.
2. **Banking-aware intelligence** — intent (loan / KYC / dispute / …), glossary, risk-phrase flags, SOP next-steps, regulatory disclaimers. Powered by **Groq** (or any OpenAI-compatible LLM).
3. **Smart form auto-fill** — extracts name, DOB, address, PAN, masked Aadhaar, phone, email from the live conversation as a CBS/CRM-style pre-fill.
4. **Trust & governance** — real JWT auth with roles, PII redacted before persistence, audit log table, optional redacted export.
5. **Bilingual interaction record** — every session generates a structured bilingual summary (purpose, points, products, follow-ups) stored in the DB for the audit file.

> **Stack:** FastAPI + Postgres/SQLite + React (Vite) + Bhashini + Groq.

---

## Quick start (zero-setup demo)

The default DB is a local **SQLite** file, the LLM provider can run in **mock** mode if you have no Groq key, and Bhashini falls back to `DEMO_MODE` demo strings if no keys.

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill in keys (or leave defaults for the demo)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On first launch, the backend:

- Creates the SQLite DB (`frontline_desk.db`)
- Seeds an **admin user** from `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (defaults: `admin@example.com` / `ChangeMe!123`)
- Prints the active LLM provider

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in with the seed admin. The form is pre-filled with the demo credentials.

---

## Environment variables (`backend/.env`)

| Variable                                                       | What it does                                                                                         |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                                 | `sqlite+aiosqlite:///./frontline_desk.db` (default) or `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET`                                                   | HMAC secret for signing JWTs (rotate in prod)                                                        |
| `JWT_ACCESS_TTL_MIN`                                           | Access-token lifetime (default 720 min)                                                              |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` / `SEED_ADMIN_NAME` | First admin created on empty DB                                                                      |
| `BHASHINI_USER_ID` / `BHASHINI_ULCA_API_KEY`                   | Bhashini ULCA credentials (ASR + MT + TTS). Without these, `DEMO_MODE` strings are used              |
| `LLM_PROVIDER`                                                 | `groq` (default), `openai`, or `mock`                                                                |
| `GROQ_API_KEY` / `GROQ_MODEL`                                  | Groq creds — model defaults to `llama-3.3-70b-versatile`                                             |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`                   | OpenAI-compatible alternative                                                                        |
| `DEMO_MODE`                                                    | Force demo transcripts even with Bhashini configured                                                 |
| `CORS_ORIGINS`                                                 | Comma-separated origins (Vite dev defaults work out of the box)                                      |

---

## Switching to Postgres

```bash
docker run --rm -d --name frontline-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=frontline_desk postgres:16

# in .env
DATABASE_URL=postgresql+asyncpg://postgres:devpass@localhost:5432/frontline_desk
```

Restart the backend — tables auto-create on startup. For schema migrations across releases use `alembic` (the `alembic` package is pre-installed; `alembic init` to scaffold).

---

## API surface

All endpoints below (except `/health`, `/auth/login`) require `Authorization: Bearer <jwt>`.

| Method   | Path                                      | Purpose                                             |
| -------- | ----------------------------------------- | --------------------------------------------------- |
| `GET`    | `/health`                                 | Provider/DB status                                  |
| `POST`   | `/auth/login`                             | Email + password → JWT + user object                |
| `GET`    | `/auth/me`                                | Current user                                        |
| `POST`   | `/auth/register` (admin)                  | Create staff users                                  |
| `POST`   | `/session`                                | Open a desk session (DB row + in-memory live state) |
| `GET`    | `/sessions`                               | List your sessions (admins see all)                 |
| `GET`    | `/sessions/{id}`                          | Full bilingual record + redacted turns              |
| `POST`   | `/summary`                                | Generate + persist bilingual summary                |
| `GET`    | `/session/{id}/metrics`                   | Live KPIs for the in-memory session                 |
| `GET`    | `/session/{id}/export?redact=true\|false` | JSON export packet                                  |
| `DELETE` | `/session/{id}`                           | Close session, mirror to DB                         |
| `WS`     | `/ws/desk/{session_id}?token=<jwt>`       | Realtime: audio chunks, partials, copilot, TTS      |

---

## Data model

- **`users`** — `id`, `email`, `password_hash` (bcrypt), `role` (`admin`/`staff`), `branch_code`, `preferred_lang`
- **`desk_sessions`** — owner, langs, customer_ref, JSON `metrics`, JSON `form_snapshot`, JSON `turns` (redacted), `status`
- **`interaction_records`** — bilingual summary (staff + customer language), full payload JSON, per session
- **`audit_events`** — every login, register, session open/close/export

PII redaction (`app.services.safety.redact_mapping`) runs **before** anything is written to `desk_sessions.turns`, so the database never stores a raw Aadhaar / PAN / phone / email.

---

## Architecture notes

- **Live state stays in RAM**, the DB is the audit-grade mirror. The WebSocket handler reads/writes the in-memory `DeskSession` for hot-path latency, and a `_persist_turn` helper appends a _redacted_ copy to the DB row asynchronously.
- **Bhashini ULCA**: `services/bhashini_client.py` resolves pipeline config + compute URLs per call. WAV 16 kHz is the default ASR format the React mic capture sends.
- **LLM is swappable** via `LLM_PROVIDER`. Both Groq and OpenAI expose an OpenAI-compatible chat completions endpoint, so one `AsyncOpenAI` client + a different `base_url` is all that's needed (`config.Settings.llm_effective`).
- **WebSocket auth**: token is sent as a `?token=` query param because browsers don't allow custom headers on WS handshakes.

---

## What changed from v0.2

- `+ /backend/app/db.py`, `+ /backend/app/models.py` — SQLAlchemy 2 async engine + ORM models
- `+ /backend/app/auth.py`, `+ /backend/app/routers/auth.py` — bcrypt + JWT + role guards + WS auth
- `~ /backend/app/main.py` — auth-guarded routes, DB-persistent sessions, redacted turn mirroring, `lifespan` seed-admin bootstrap
- `~ /backend/app/services/llm_bank.py` — provider-aware (`groq` / `openai` / `mock`)
- `+ /frontend/src/auth.ts`, `+ /frontend/src/Login.tsx`, `+ /frontend/src/History.tsx`
- `~ /frontend/src/App.tsx` — real login screen, JWT on all fetches + WS, history portal, sign-out wipes auth

---

## License

Released under the **MIT License**.

```
MIT License

Copyright (c) 2026 Frontline Desk contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Third-party services (Bhashini, Groq, OpenAI) retain their own terms of use; this license covers only the code in this repository.
