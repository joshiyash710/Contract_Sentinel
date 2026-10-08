# ContractSentinel — $0 Deployment Runbook (Render + Turso)

**Goal:** deploy ContractSentinel as a real, durable product for **≈$0/month** at low traffic.

**Shape (all free tiers):**
- **Backend** (FastAPI + LangGraph) → **Render** free web service, built from `backend/Dockerfile` via
  the repo-root `render.yaml` blueprint.
- **Database** (accounts, jobs, reports) → **Turso** (libSQL, SQLite-compatible, durable network DB) —
  because Render's free disk is **ephemeral** (wiped on every restart/redeploy).
- **Embeddings** (`bge-m3`) → **HuggingFace Inference API** (Render free has 512 MB RAM — can't run
  Ollama).
- **Generation** (the LLM judgments) → **Groq** free API.
- **Frontend** (Next.js) → **Vercel Hobby** / **Cloudflare Pages** (free).

> This supersedes the earlier **Oracle Always-Free VM** plan. Oracle is still a valid alternative (24 GB
> ARM VM runs Ollama locally + has a persistent disk, so it needs neither Turso nor HF), but Render +
> Turso avoids the credit-card/provisioning friction and is a modern PaaS deploy. The features are
> reversible: unset the env switches and the app is byte-identical to local (Ollama + SQLite on disk).

---

## 0. What makes this durable (features 048–053)

| Concern | Solution | Feature |
|---|---|---|
| Cross-origin cookies/CORS | `CORS_ALLOWED_ORIGINS` + `AUTH_COOKIE_SAMESITE=none` | 048 |
| Prod OAuth/frontend URLs | `GOOGLE_OAUTH_REDIRECT_URI` + `FRONTEND_INTEGRATIONS_URL` | 049 |
| Embeddings off-box | `EMBED_PROVIDER=hf` (HF `bge-m3`) | 050 |
| Accounts/jobs survive restart | `TURSO_DATABASE_URL` (store DB → Turso) | 051 |
| Reports survive restart | report `.json`/`.md` → Turso BLOBs | 052 |
| Blueprint + fail-fast + this runbook | `render.yaml` + startup guard | 053 |

**Resume-on-boot** is feature 012: on restart the backend re-enqueues non-terminal jobs from the (now
durable) Turso store. A job interrupted mid-run cannot resume its checkpoint (kept ephemeral) and its
upload is gone, so it fails cleanly — accepted trade; completed reports/accounts are durable.

---

## 1. Pinned secrets — **MANDATORY** (data loss otherwise)

On Render's ephemeral disk these regenerate on **every restart** unless pinned via env:

- **`AUTH_SECRET`** — JWT signing key. Not pinned ⇒ every restart invalidates **all sessions** (everyone
  logged out). Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- **`CONTRACTSENTINEL_ENCRYPTION_KEY`** — Fernet at-rest key (encrypts Google OAuth tokens). Not pinned ⇒
  a restart regenerates it and **all Turso-stored OAuth-token ciphertext becomes undecryptable** (users'
  Drive connections silently break). Generate:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

**Pin both in the Render dashboard.** The startup guard warns if `CONTRACTSENTINEL_ENCRYPTION_KEY` is
unset while `TURSO_DATABASE_URL` is set, and hard-fails on a missing HF/Groq/Turso token.

---

## 1b. Feature-flag defaults you inherit (features 057–061)

The source-locator traceability chain is **ON by default** as of feature 060 — neither flag is in
`render.yaml`, so prod gets:

- **`PDF_SOURCE_LOCATOR_ENABLED=True`** → findings carry PDF clause locators; the in-workspace PDF viewer +
  click-to-highlight (057) work out of the box. (055 Task 12 measured the dict-extraction path as
  content-identical to the plain path: min 99.71% char similarity, 0/30 clause-count change —
  `backend/eval/RESULTS_055.md`.)
- **`UPLOAD_SOURCE_RETENTION_ENABLED=True`** → uploaded contracts are **kept in Turso indefinitely** (so
  `GET /api/jobs/{id}/source` can serve them to the viewer). Mind Turso's 5 GB free tier; set either env var
  to `False` in the dashboard to opt out (reverts to feature-054 terminal-delete).

Two flags stay **OFF** unless you set them explicitly:

- **`CRAG_LIVE_CLAUSE_PROGRESS_ENABLED`** (059) — live per-clause retrieval narration, including the
  **"live web search" fallback indicator**. Set `True` to surface it in the processing view.
- **`CRAG_USER_KB_ENABLED`** (061) — per-user learned clause KB. **Leave OFF on Render:** v1 stores the
  per-user indexes on the **ephemeral** local disk (`data/kb/users/`), which Render wipes on every redeploy.
  Enable only on a durable-disk host (e.g. the Oracle VM alternative) or after a durable-storage follow-up.

---

## 2. External setup (one-time)

1. **Turso** (app.turso.tech): create a database → copy its **URL** (`libsql://<db>-<org>.turso.io`)
   and a **database-scoped** auth token (`turso db tokens create <db>` or the DB's "Create Token" —
   **not** the account/platform API token, which 401s). → `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.
2. **HuggingFace** (huggingface.co → Settings → Access Tokens): a free **read** token → `HF_API_TOKEN`.
3. **Groq** (console.groq.com): a free API key → `GROQ_API_KEY`.
4. **Google OAuth** (only for Drive/Gmail delivery): in the GCP Web OAuth client, add the Render
   callback as an authorized redirect URI and set `GOOGLE_OAUTH_REDIRECT_URI` to match **exactly**; set
   `FRONTEND_INTEGRATIONS_URL` to your Vercel `/integrations` page.
5. **Frontend**: deploy Next.js to Vercel/Cloudflare; set `NEXT_PUBLIC_API_PROVIDER=real` and point it
   at the Render API origin; add that origin to `CORS_ALLOWED_ORIGINS`.

---

## 3. Deploy

The blueprint is `render.yaml` (repo root): one `type: web`, `runtime: docker`, `rootDir: backend`,
`healthCheckPath: /api/health`, non-secrets inline, secrets `sync: false` (dashboard-set). No Render
Postgres (Turso is the DB).

1. Push the branch; in Render, **New → Blueprint**, point at the repo.
2. Set every `sync: false` value in the dashboard (the pinned secrets §1 + Turso/HF/Groq + CORS/OAuth
   URLs).
3. Deploy. The container entrypoint runs the **Turso-aware** migration (`upgrade_to_head`, which builds
   the `sqlite+libsql://` URL when `TURSO_DATABASE_URL` is set — `sqlalchemy-libsql` is installed in the
   Linux image) then starts uvicorn.

### Keep-alive
Render free spins down after **15 min idle** (~1 min cold start). Configure a free cron (cron-job.org)
to `GET https://<your-service>.onrender.com/api/health` every ~10 min so the instance stays warm.

---

## 3b. Post-deploy: turn on email + real embeddings (two things that silently no-op)

The app runs fine without either of these — it just quietly **doesn't send email** and **under-reports risky
clauses**. Both are easy to miss; walk this checklist after the first deploy.

### Email — password reset AND report delivery (one shared dependency)

Both emails send through the **same** central-Gmail path: `password_reset_email.send_reset_email` and the
report delivery both call `send_report_via_gmail(...)` with the **central Google token**
(`materialize_central_token_tempfile()` → `GOOGLE_OAUTH_TOKEN_PATH`, default
`data/secrets/google_token.json`). If that token file is absent the helper returns `None` and the send
"fails naturally"; the reset task **swallows the failure** and still returns the generic
"if an account exists…" 200 — so a missing token is invisible to the user. On Render's **ephemeral disk**
that file does not exist unless you provide it as a Secret File.

- [ ] Mint a **plaintext** central token locally (one-time; opens a browser for consent):
      `cd backend && .venv/Scripts/python.exe scripts/mint_plain_token.py` → writes
      `data/secrets/google_token_plain.json`. (Plaintext avoids the encryption-key-mismatch failure mode:
      a Fernet-encrypted token only decrypts if Render's `CONTRACTSENTINEL_ENCRYPTION_KEY` matches the
      machine that wrote it.)
- [ ] Render dashboard → add a **Secret File** named `google_token.json` containing that file's contents.
- [ ] Set env **`GOOGLE_OAUTH_TOKEN_PATH=/etc/secrets/google_token.json`**.
- [ ] Set env **`FRONTEND_RESET_URL=https://<your-vercel-app>/reset`** — the default is
      `http://localhost:3000/reset`, so the email would send but the link would be dead in prod.
- [ ] Redeploy, then test: trigger a password reset (email should arrive) and run an analysis (the report
      email should arrive). If not, check logs for `reset email send failed`, Gmail `invalid_grant`
      (token expired/revoked → re-mint), or `no recipient configured`.

`MCP_DELIVERY_ENABLED` / `MCP_GMAIL_ENABLED` already default **True** — the token is the only missing piece.
Gmail stays central (031 amendment); per-user Drive is a separate connection.

### Embeddings — why prod finds fewer risky clauses than local

`render.yaml` sets `EMBED_PROVIDER=hf`. HuggingFace **serverless inference is now credit-gated** — a free
read token returns **`402 Payment Required`** on every embed. CRAG then opens its embedding **circuit
breaker** and routes every clause to **web search**; the thin web evidence makes **Self-RAG discard the
findings**, so a contract that surfaced medium-risk clauses locally can return a **clean "no risky clauses"**
report in prod. This is NOT the LLM — generation (Groq) is unaffected, and the service couldn't even boot
with an empty `GROQ_API_KEY` (startup guard). It is purely the embedding/evidence path.

- [ ] Confirm the symptom in Render logs on a fresh run: `402` on HF embeds + `embedding circuit breaker
      OPENED`, then all clauses `web_fallback`.
- [ ] Fix — pick one:
      - **Add HF credits** (a small usage-priced plan at huggingface.co; a corpus's worth of embeds is cents).
        `EMBED_PROVIDER=hf` then returns real vectors → local-KB retrieval + findings restored. **No redeploy
        needed** — the index already ships in the image.
      - **Move embeddings to Ollama** (the Oracle-VM alternative in §0): `EMBED_PROVIDER=ollama` with Ollama
        running on a host that has the RAM. Render free (512 MB) can't run Ollama, so this means a different
        host.
- [ ] (Optional, for diagnosis) Set `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED=True` to watch the web-fallback
      indicator fire live in the processing view.

Until embeddings work, prod judges clauses on **web evidence only** and will under-report vs local — an
accepted interim posture (deploy "option C"), fully reversible by either fix above.

---

## 4. Go-live checklist (the deferred Linux/Turso validations)

Run these in the Render container (or a Linux/WSL/Docker env) before trusting the deploy:

- [ ] **050 AC-10** — rebuild the KB index through HF so indexed vectors match prod query embeddings:
      `EMBED_PROVIDER=hf HF_API_TOKEN=… python scripts/build_kb.py`, then re-run the retrieval eval and
      record recall/precision vs the Ollama baseline. (Ship the rebuilt `data/kb/clauses.faiss` in the
      image — the **`Dockerfile`** now `COPY data/kb`.)
- [ ] **051 AC-10** — `alembic upgrade head` replays `0001…0009` on Turso (the entrypoint does this on
      boot); register → login → submit a job → read it back; **restart** the service and confirm the
      account + job survive.
- [ ] **052 AC-9** — confirm report `.json`/`.md` BLOBs are in Turso (not on disk); after a restart the
      report still **downloads** and delivery still attaches md/json/pdf with no temp leak.
- [ ] **Dockerfile build** — validate the image builds (build context = `backend/`, EC-6) with tesseract
      + the KB index present.

Record results at the bottom of this file.

---

## 5. Honest caveats

- **Groq free tier** caps ~200,000 tokens/day — a handful of full analyses. Beyond that → `429` →
  degraded/failsafe reports. Upgrade Groq, pick a smaller model, or keep generation local.
- **HuggingFace free Inference** can cold-start (503) / rate-limit; embedding calls degrade gracefully to
  the CRAG circuit breaker (web fallback), not a crash.
- **Turso free tier** (5 GB, 10 M writes/mo) is ample here and does **not** expire (unlike Render's free
  Postgres — which we don't use).
- **Vercel Hobby** is non-commercial — use Cloudflare Pages if that matters.
- **Accuracy is not legal-grade** — deploy with the built-in "not legal advice" honesty; do not market
  decision-grade reliability.

---

## Go-live results
_(fill in after the AC-10/AC-9 validations above)_
