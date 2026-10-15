<div align="center">

# 🛡️ ContractSentinel

### AI Contract-Risk Analyzer — a local-first LangGraph agent that finds, scores, and rewrites risky clauses

*Upload a contract → every risky clause found, scored, and redlined — with an evidence trail, a branded PDF, and delivery to your own Drive & inbox. Run it **fully offline** on local models, or **deploy it to the cloud** — same pipeline, swappable providers.*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)

[![Ollama](https://img.shields.io/badge/Local-Qwen3%20%2B%20BGE--M3-000000?logo=ollama&logoColor=white)](https://ollama.com/)
[![Groq](https://img.shields.io/badge/Cloud-Groq%20gpt--oss--120b-F55036?logo=groq&logoColor=white)](https://groq.com/)
[![Turso](https://img.shields.io/badge/Data-Turso%20libSQL-4FF8D2?logo=turso&logoColor=black)](https://turso.tech/)
[![Deploy](https://img.shields.io/badge/Deploy-Render%20%2B%20Vercel-5A67D8?logo=render&logoColor=white)](https://render.com/)

[![Tests](https://img.shields.io/badge/tests-1231%20backend%20%C2%B7%20264%20frontend-2EA36F)](#-testing)
[![Features](https://img.shields.io/badge/spec--driven-66%20features-0E9C92)](#-development-methodology)
[![Status](https://img.shields.io/badge/status-feature%20complete%20%C2%B7%20deployed-2EA36F)](#-project-status)
[![Privacy](https://img.shields.io/badge/privacy-local--first-0E9C92)](#-local-first-by-design)

</div>

---

## 📌 Overview

**ContractSentinel** is an autonomous, AI-powered system that reads a legal contract and tells you **where the risk is**. A user uploads a **PDF or DOCX**; a fixed **7-node [LangGraph](https://langchain-ai.github.io/langgraph/) pipeline** splits it into clauses, retrieves supporting legal evidence for each one, validates which clauses are *genuinely* worth flagging, scores each **Low / Medium / High** with a written rationale, drafts a **safer rewrite** for the risky ones, and compiles a **branded PDF report** — delivered to the user's own **Google Drive** and **emailed** to them.

It behaves like a real multi-tenant SaaS — landing page, authentication, per-user data isolation, per-user Drive, live progress streaming, a metrics dashboard and report history — built spec-first with a strict review gate.

**Two ways to run the exact same pipeline, chosen by a clean provider seam:**

| Mode | Generation | Embeddings | Data | Privacy |
|------|-----------|-----------|------|---------|
| 🏠 **Local-first** *(default)* | Qwen3:8b via **Ollama** | BGE-M3 via **Ollama** | **SQLite** | 💯 Contract text **never leaves the machine** |
| ☁️ **Cloud deployment** | **Groq** `gpt-oss-120b` | **Cloudflare** `bge-m3` | **Turso** (libSQL) | Hosted demo on Render + Vercel |

> The architecture, nodes, prompts, and tests are **identical** across both modes — only the provider adapters change. That seam is what lets a privacy-first local tool also ship as a live hosted demo without a rewrite.

---

## 📊 At a Glance

<div align="center">

| 🧠 Pipeline | 📚 Knowledge Base | 🧪 Tests | 🔒 Security | 📐 Process |
|:-:|:-:|:-:|:-:|:-:|
| **7 nodes · 2 edges** fixed LangGraph | **1,400+** real clauses · **39** types (CUAD + Bonterms) | **1,231** backend · **264** frontend | **8** hardening layers | **66** spec-reviewed features |

</div>

---

## 📖 Table of Contents

- [Highlights](#-highlights)
- [Local-First by Design](#-local-first-by-design)
- [Architecture — the 7-Node Graph](#-architecture--the-7-node-graph)
- [The 7-Node Pipeline](#-the-7-node-pipeline)
- [Request Lifecycle](#-request-lifecycle)
- [Deployment Architecture](#-deployment-architecture)
- [Model Provider Seam](#-model-provider-seam)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [Running the App](#-running-the-app)
- [Testing](#-testing)
- [Security](#-security)
- [Reliability & Performance](#-reliability--performance)
- [Development Methodology](#-development-methodology)
- [Project Status](#-project-status)
- [Team](#-team)
- [License](#-license)

---

## ✨ Highlights

| | |
|---|---|
| 🧠 **Agentic pipeline** | A fixed 7-node LangGraph state machine with exactly 2 conditional edges — ingest → split → retrieve → validate → score → redline → report. The shape is immutable by constitution; every feature is built *around* the graph. |
| 🔎 **Corrective RAG (CRAG)** | Per-clause retrieval over a local **FAISS** knowledge base of **1,400+ real contract clauses** (Bonterms + **CUAD**, CC BY 4.0) across **39 clause types**, with an automatic **live web-search fallback** when confidence drops below `0.73`. |
| ✅ **Self-RAG validation** | Relevance / support checks discard false alarms; a **recall floor** protects genuinely high-risk clause types. Accuracy is measured by an offline harness reporting precision / recall / F1 **per clause type, each with a 95% bootstrap confidence interval** — best-effort-labeled, not lawyer-reviewed. |
| ✍️ **Automatic redlining** | High-risk clauses get a suggested safer rewrite plus a rationale. |
| 🔀 **Pluggable providers** | One seam swaps **local Ollama** ↔ **Groq** (generation) and **Ollama** ↔ **Cloudflare Workers AI** (embeddings) — no pipeline changes. |
| 🔒 **Private by construction** | In local mode, 100% on-device inference; uploaded contracts **encrypted at rest** (Fernet) in both modes. |
| 🛡️ **Production-grade security** | bcrypt + JWT auth, session hardening, rate-limiting + lockout, prompt-injection defense, security headers, upload magic-byte validation. |
| ♻️ **Durable & resumable** | Job store + LangGraph checkpointer — a killed job **resumes from the last completed node**; dropped DB connections **self-heal** with reconnect + retry. |
| 📡 **Live progress** | Watch the pipeline advance node-by-node over **Server-Sent Events**. |
| 📤 **Real delivery** | Branded PDF report pushed to the user's **Google Drive** + emailed via **Gmail** (MCP). |
| 🧪 **Rigorously tested** | **1,231** backend + **264** frontend tests, built spec-first with TDD across **66** reviewed features. |

---

## 🔐 Local-First by Design

> Contracts are among the most confidential documents a business handles. Sending them to a hosted LLM means the document leaves your control — often permanently.

In its **default local mode**, ContractSentinel runs **every model on-device** through [Ollama](https://ollama.com/):

- **Qwen3:8b** — generative reasoning (clause splitting, validation, scoring, redlining)
- **BGE-M3** — embeddings for retrieval

These are kept as **strictly separate model objects** (the embedding model is never substituted for the generative one). No contract text, clause, or piece of evidence is sent to a third-party API. Uploaded files are additionally **encrypted at rest** with Fernet (AES-128-CBC + HMAC-SHA256).

**Cloud mode is opt-in and explicit.** The hosted demo flips two environment flags (`LLM_PROVIDER=groq`, `EMBED_PROVIDER=cloudflare`) to route generation and embeddings to managed APIs for a zero-GPU deployment. Everything else — the graph, prompts, validation, encryption-at-rest, and per-user isolation — is unchanged. You choose the trade-off; the code doesn't force it.

---

## 🏗️ Architecture — the 7-Node Graph

A **LangGraph `StateGraph`** with exactly **7 sequential nodes** and exactly **2 conditional edges**. This shape is fixed by the project [constitution](specs/000-constitution.md) and treated as immutable — every feature is built *around* the graph, never by adding nodes.

```mermaid
flowchart TD
    U([📄 Upload PDF / DOCX]) --> N1

    N1["1 · IngestAgent<br/>parse · OCR fallback · decrypt-at-rest"] --> N2
    N2["2 · ClauseSplitterAgent<br/>regex pre-pass → LLM boundaries + types"] --> N3
    N3{"3 · CRAG Retrieval<br/>BGE-M3 + FAISS · confidence?"}

    N3 -->|confidence 0.73 or higher| KB[(Local Legal KB<br/>1,400+ clauses)]
    N3 -->|confidence below 0.73| WEB([🌐 Live web search])
    KB --> N4
    WEB --> N4

    N4["4 · Self-RAG Validation<br/>ISREL / ISSUP + recall floor"] --> N5
    N5["5 · RiskScoreAgent<br/>Low / Medium / High + rationale"] --> R{route_on_risk}

    R -->|risky| N6["6 · RedlineAgent<br/>draft safer rewrite"]
    R -->|clean| SK["6 · SkipRedline<br/>mark clean"]
    N6 --> N7
    SK --> N7

    N7["7 · ReportAgent<br/>compile report + evidence trail"] --> END([✅ END])
    END -.post-terminal.-> DEL[["📤 MCP Delivery<br/>Google Drive + Gmail"]]

    style N1 fill:#0E9C92,stroke:#0B6F68,color:#fff
    style N2 fill:#0E9C92,stroke:#0B6F68,color:#fff
    style N4 fill:#0E9C92,stroke:#0B6F68,color:#fff
    style N5 fill:#0E9C92,stroke:#0B6F68,color:#fff
    style N6 fill:#F2A900,stroke:#B37C00,color:#fff
    style N7 fill:#1E2761,stroke:#0E1A38,color:#fff
    style N3 fill:#E4572E,stroke:#A5361A,color:#fff
    style R fill:#E4572E,stroke:#A5361A,color:#fff
    style DEL fill:#1E2761,stroke:#0E1A38,color:#fff
```

**The two conditional edges** (every other transition is a plain linear edge):
1. **CRAG confidence routing** — local FAISS KB vs. live web fallback, merged per clause.
2. **`route_on_risk`** — RedlineAgent vs. SkipRedline.

---

## 🧩 The 7-Node Pipeline

| # | Node | What it does |
|:-:|------|--------------|
| **1** | **IngestAgent** | Parses PDF/DOCX (PyMuPDF / python-docx), OCR fallback (Tesseract) for scans; decrypts the at-rest-encrypted upload to a temp file before parsing. |
| **2** | **ClauseSplitterAgent** | Regex pre-pass proposes clause boundaries; the LLM refines boundaries and assigns clause **types**; size-gated for large documents. |
| **3** | **CRAG Retrieval** | Embeds each clause (BGE-M3), searches a local **FAISS** legal KB, scores confidence; `< 0.73` → **live web fallback**. Evidence merged per clause. |
| **4** | **Self-RAG Validation** | Relevance / ISREL / ISSUP checks discard weak flags; a **recall floor** protects genuinely high-risk clause types from being dropped. |
| **5** | **RiskScoreAgent** | Assigns **Low / Medium / High** with a written rationale (deterministic, temperature-pinned). |
| **6** | **route_on_risk → Redline / Skip** | Risky clauses get a safer rewrite; clean clauses are marked and skipped. |
| **7** | **ReportAgent** | Assembles the final report + full evidence trail; rendered to a branded PDF. |

Every clause that survives validation ends up scored:

🔴 **HIGH** — serious exposure, needs a rewrite &nbsp;·&nbsp; 🟡 **MEDIUM** — worth review/negotiation &nbsp;·&nbsp; 🟢 **LOW** — acceptable, standard wording

---

## 🔄 Request Lifecycle

From upload to delivered report — durable, streamed, and resumable end-to-end.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FE as Next.js (Vercel)
    participant API as FastAPI (Render)
    participant WK as Pipeline Worker
    participant G as LangGraph (7 nodes)
    participant DB as Job Store (SQLite / Turso)
    participant DEL as MCP Delivery

    User->>FE: Upload PDF / DOCX
    FE->>API: POST /api/jobs  (JWT cookie)
    API->>API: magic-byte check · encrypt-at-rest · enqueue
    API-->>FE: 202 job_id
    FE->>API: GET /api/jobs/{id}/events (SSE)
    WK->>G: run pipeline
    loop each node
        G->>DB: checkpoint + progress
        DB-->>API: node advanced
        API-->>FE: SSE progress event
    end
    G->>DB: persist report + denormalized risk summary
    G-->>DEL: deliver PDF → Google Drive + Gmail
    FE->>API: GET /api/dashboard · /api/jobs
    API->>DB: single SELECT (summary on the row — no per-report reads)
    API-->>FE: metrics + history (sub-second)
```

> **Resilience built in:** if the worker is killed mid-run, the LangGraph checkpointer **resumes from the last completed node**; if the database connection drops, the store **reconnects and retries** transparently.

---

## ☁️ Deployment Architecture

The same backend image runs locally (all on-device) or on a free-tier cloud stack. In the hosted demo, the frontend is on **Vercel**, the API is a **Docker** service on **Render**, data lives in **Turso** (libSQL), and the model work is offloaded to **Groq** + **Cloudflare Workers AI**.

```mermaid
flowchart LR
    subgraph Client
        B([🌐 Browser])
    end

    subgraph Edge["Vercel"]
        FE[Next.js Frontend]
    end

    subgraph Render["Render · Docker"]
        API[FastAPI + LangGraph Worker]
    end

    subgraph Providers["Managed Providers (cloud mode)"]
        GROQ[[Groq<br/>gpt-oss-120b]]
        CF[[Cloudflare Workers AI<br/>bge-m3]]
        TURSO[(Turso · libSQL)]
        GOOG[[Google<br/>Drive + Gmail]]
    end

    subgraph Local["Local mode (alternative)"]
        OLL[[Ollama<br/>Qwen3 + BGE-M3]]
        SQL[(SQLite)]
    end

    B --> FE -->|/api proxy| API
    API -->|generation| GROQ
    API -->|embeddings| CF
    API -->|jobs · users · reports| TURSO
    API -->|delivery| GOOG
    API -. swap via provider seam .-> OLL
    API -. swap via provider seam .-> SQL

    style FE fill:#000,color:#fff
    style API fill:#0E9C92,color:#fff
    style GROQ fill:#F55036,color:#fff
    style CF fill:#F38020,color:#fff
    style TURSO fill:#1E2761,color:#fff
    style GOOG fill:#4285F4,color:#fff
    style OLL fill:#333,color:#fff
```

---

## 🔌 Model Provider Seam

A single configuration seam selects the generation and embedding backends. The **BGE-M3 embedding space is identical** across Ollama and Cloudflare, so the same FAISS index serves both.

| Capability | Env flag | Local option | Cloud option(s) |
|------------|----------|--------------|-----------------|
| **Generation** | `LLM_PROVIDER` | `ollama` → Qwen3:8b | `groq` → `openai/gpt-oss-120b` |
| **Embeddings** | `EMBED_PROVIDER` | `ollama` → bge-m3 | `cloudflare` → `@cf/baai/bge-m3` *(or `hf`)* |
| **Data store** | `TURSO_DATABASE_URL` | unset → SQLite file | set → Turso (libSQL over Hrana) |

> Embedding and generative models are kept as **separate seams** (constitution §8) — the embedding model is never substituted for the generative one, in either mode.

---

## 🛠️ Tech Stack

<table>
<tr><td><b>Orchestration</b></td><td>LangGraph · langgraph-checkpoint-sqlite · langchain-core</td></tr>
<tr><td><b>LLM (generative)</b></td><td>Ollama · Qwen3:8b <i>(local)</i> &nbsp;|&nbsp; Groq · <code>gpt-oss-120b</code> <i>(cloud)</i></td></tr>
<tr><td><b>Embeddings</b></td><td>BGE-M3 — via Ollama <i>(local)</i> or Cloudflare Workers AI <i>(cloud)</i></td></tr>
<tr><td><b>Retrieval</b></td><td>FAISS · NumPy · DuckDuckGo Search (web fallback)</td></tr>
<tr><td><b>Document Parsing</b></td><td>PyMuPDF · python-docx · Tesseract OCR</td></tr>
<tr><td><b>API & Data</b></td><td>FastAPI · SSE (sse-starlette) · SQLite / Turso (libSQL) · Alembic · Pydantic v2</td></tr>
<tr><td><b>Security & Delivery</b></td><td>cryptography (Fernet) · passlib/bcrypt · PyJWT · MCP SDK · reportlab · Google API client</td></tr>
<tr><td><b>Frontend</b></td><td>Next.js 14 · TypeScript · Tailwind CSS · Recharts · lucide-react</td></tr>
<tr><td><b>Deployment</b></td><td>Docker · Render (API) · Vercel (frontend) · Turso (data)</td></tr>
<tr><td><b>Testing</b></td><td>pytest (+asyncio, cov, mock) · Vitest · Testing Library</td></tr>
</table>

---

## 📂 Project Structure

```
ContractSentinel/
├── backend/
│   ├── app/
│   │   ├── graph/            # LangGraph StateGraph (builder.py, state.py) + the 7 nodes
│   │   │   └── nodes/        # ingest · splitter · crag · self-rag · risk · redline · report
│   │   ├── rag/              # embeddings, FAISS KB, web retriever, per-user learned KB
│   │   ├── llm/              # Ollama / Groq clients · embed clients · prompt-injection guard
│   │   ├── api/              # FastAPI app, routes, auth, rate-limit, SSE, dashboard aggregation
│   │   ├── runner/           # pipeline runner, job store, registry, worker, DB backend seam
│   │   ├── delivery/         # MCP Drive/Gmail, PDF/email rendering
│   │   ├── mcp_servers/      # MCP server integrations
│   │   ├── security/         # Fernet crypto seam
│   │   ├── models/           # Pydantic models
│   │   ├── db/               # store wiring
│   │   ├── blob_store.py     # disk / Turso BLOB storage for reports & uploads
│   │   └── config.py         # all named config constants + provider flags
│   ├── alembic/              # database migrations (0001 … 0011)
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── app/              # Next.js routes (landing, login, upload, dashboard, reports, …)
│       ├── components/       # UI, charts, report workspace, dashboard, marketing, …
│       └── lib/api/          # provider seam (real ↔ mock)
├── specs/                    # spec-driven workflow: constitution + 66 per-feature specs
├── eval/                     # offline accuracy / variance evaluation harness
├── scripts/                  # OAuth bootstrap, KB build, delivery/latency smoke tools
├── docs/                     # deployment & operations docs
└── render.yaml               # Render blueprint (cloud deployment)
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11**
- **Node.js 18+**
- **[Ollama](https://ollama.com/)** *(for local mode)* with the models pulled:
  ```bash
  ollama pull qwen3:8b
  ollama pull bge-m3
  ```
  > 💡 On a 6 GB GPU, Qwen3:8b runs at roughly a 70/30 GPU/CPU split — pre-warm it before a run.
- **Tesseract OCR** (only needed for scanned PDFs) — [install guide](https://github.com/tesseract-ocr/tesseract)
- *(Optional, for delivery)* Google OAuth credentials — see [`scripts/`](scripts/).

### Installation

```bash
# 1. Clone
git clone <your-repo-url> ContractSentinel
cd ContractSentinel

# 2. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev,eval]"

# 3. Frontend
cd ../frontend
npm install
```

---

## ▶️ Running the App

**Backend** (port 8000, from `backend/`):

```bash
# apply DB migrations (first run / after pulling)
.venv/Scripts/python.exe -m alembic upgrade head

# start the API  (local HTTP dev → AUTH_COOKIE_SECURE=False; default True requires TLS)
AUTH_COOKIE_SECURE=False .venv/Scripts/python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

<details>
<summary>PowerShell equivalent</summary>

```powershell
$env:AUTH_COOKIE_SECURE="False"
.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```
</details>

**Frontend** (port 3000, from `frontend/`):

```bash
npm run dev
```

`frontend/.env.local` must contain `NEXT_PUBLIC_API_PROVIDER=real` (proxies to `:8000`). Then open **http://localhost:3000**.

> **Cloud mode:** set `LLM_PROVIDER=groq`, `EMBED_PROVIDER=cloudflare`, and `TURSO_DATABASE_URL` (+ the matching API keys) — the deployment blueprint in [`render.yaml`](render.yaml) wires this end-to-end.

---

## 🧪 Testing

```bash
# Backend  (from backend/)
.venv/Scripts/python.exe -X utf8 -m pytest -q

# Frontend  (from frontend/)
npm run test
```

**1,231** backend tests · **264** frontend tests — all green. Built spec-first with TDD: tests are written and confirmed failing *before* implementation, and a failing test is fixed by fixing the **code**, never by weakening the test.

---

## 🛡️ Security

Security was developed as a dedicated hardening phase, not an afterthought:

- **Authentication** — email + password (bcrypt with SHA-256 pre-hash), HS256 JWT in an **httpOnly cookie**, sliding 30-min idle timeout + 8-hour absolute cap.
- **Session invalidation** — server-side `session_epoch` enables *log-out-everywhere*, ends other sessions on password change, invalidates on reset.
- **Brute-force defense** — per-IP rate limiting + persisted per-account lockout.
- **Forgot-password** — emailed, time-limited, single-use link; tokens stored **hashed** (HMAC-SHA256); no email-existence disclosure.
- **Encryption at rest** — Fernet encrypts stored **OAuth tokens** and **uploaded contract files** through one key-management seam.
- **Prompt-injection defense** — untrusted contract/evidence text is fenced in per-call-nonce delimiters inside a `user` message; trusted instructions stay in a `system` message — across all generative LLM calls.
- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options: DENY`, a strict CSP, `Referrer-Policy`, COOP, Permissions-Policy (HSTS available, TLS-gated).
- **Upload hardening** — magic-byte validation rejects files whose content doesn't match their extension (PDF → `%PDF`, DOCX → ZIP).
- **Per-user isolation** — every data read is scoped to the owning account; no cross-account visibility.

---

## ⚡ Reliability & Performance

Hardened for a real, always-on deployment — not just a happy-path demo:

- **♻️ Resumable jobs** — a LangGraph SQLite checkpointer means a killed/restarted worker **resumes from the last completed node** instead of re-running from scratch.
- **🔌 Self-healing database** — the libSQL/Turso connection wrapper **detects dropped connections and transparently reconnects + retries**, so a flaky network link doesn't fail a run or a page load.
- **⚡ Denormalized dashboard reads** — the risk summary (counts + per-clause-type breakdown) is **stored on the job row at completion**, so the dashboard and history load from a **single query** with **zero per-report reads** — eliminating an N+1 that made cloud loads slow.
- **🧯 Graceful degradation** — provider failures (embeddings/generation) fall back or surface clearly rather than crashing; best-effort side-effects (delivery, KB learning, summary computation) never alter a job's terminal outcome.
- **📡 Streaming UX** — per-node progress over SSE keeps the UI live during multi-minute analyses.

---

## 📐 Development Methodology

Every feature follows a strict **spec-driven workflow** defined in [`specs/000-constitution.md`](specs/000-constitution.md):

```
spec.md  →  plan.md  →  tasks.md  →  implementation
   └────────── each GATED by a spec-reviewer review before advancing ──────────┘
```

- **No source file** is written until that feature's `spec.md` **and** `plan.md` exist and are **spec-reviewer-approved**.
- **Fixed architecture** — the 7-node / 2-edge graph is immutable; scope changes require an explicit written **constitution amendment**.
- **TDD where practical**; **one branch per feature**, fast-forward merged to `main` only when its full test suite passes.
- **66 features** have shipped through this gate — from the core pipeline to auth, delivery, the cloud provider seams, and the reliability work above.

---

## ✅ Project Status

**ContractSentinel is feature-complete and deployed.** The entire stack — the agent pipeline, the API, durable persistence, the full Next.js frontend, security, delivery, and a live cloud deployment — is implemented, integrated, and tested end-to-end.

- [x] **7-node LangGraph pipeline** — ingest → split → CRAG → Self-RAG → score → redline → report
- [x] **FastAPI backend** — live SSE progress + durable, **resumable** persistence (SQLite / Turso)
- [x] **Full Next.js frontend** — landing, auth, upload, live processing, report workspace, dashboard, history, settings, integrations
- [x] **Pluggable provider seams** — local Ollama ↔ Groq (generation) and Ollama ↔ Cloudflare (embeddings)
- [x] **Cloud deployment** — Dockerized API on Render + Vercel frontend + Turso data
- [x] **Multi-tenant isolation** + **per-user Google Drive** (per-user OAuth)
- [x] **Security hardening** — encryption at rest, session/auth hardening, rate-limiting + lockout, prompt-injection defense, security headers, upload validation
- [x] **Reliability** — resumable checkpoints, self-healing DB reconnect, denormalized dashboard reads
- [x] **Offline evaluation harness** — per-clause-type precision/recall/F1 with 95% bootstrap confidence intervals + Self-RAG recall floor
- [x] **Professional PDF report** + branded HTML email + MCP Drive/Gmail delivery

### 🔭 Future Enhancements *(optional, beyond current scope)*

- Expert (lawyer-confirmed) gold labels + the full-corpus accuracy run — the corpus (CUAD, 1,400+ clauses) and the CI-bounded per-type harness are in place; committed gold labels are heuristic candidates pending human confirmation
- Encryption at rest for generated reports / parsed text (contract files & OAuth tokens already encrypted)
- Dependency-scan remediation wired into CI

---

## 👥 Team

| Name | Role |
|------|------|
| **Yash Joshi** | Backend implementation, agent pipeline, cloud deployment |
| **Bansi** | Frontend implementation |

---

## 📄 License

This project is currently developed for academic / educational purposes. No open-source license has been applied yet — all rights reserved by the authors. Please contact the team before reuse.

---

<div align="center">

*Built with LangGraph, FastAPI, and Next.js — under a strict spec-driven workflow.*

**⭐ If you find this project interesting, consider giving it a star.**

</div>
