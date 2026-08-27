# ContractSentinel — $0 Deployment Runbook (self-serve)

**Goal:** deploy ContractSentinel as a real, always-on product for **$0/month**, at low traffic.
**Approach (hybrid, free):**
- **Frontend** (Next.js) → **Vercel Hobby** or **Cloudflare Pages** (free).
- **Backend** (FastAPI + LangGraph) → **Oracle Cloud "Always Free" ARM VM** (4 cores / 24 GB RAM).
- **Embeddings** (`bge-m3`) → self-hosted via **Ollama on the same VM** (CPU — cheap, private).
- **Generation** (the LLM judgments) → **Groq free API** (fast, free, strong models).
- **DB + uploads** → SQLite + encrypted files on the VM's disk.

> **Why this shape:** there is no free *always-on GPU*. So we run the cheap part (embeddings) locally
> on a free CPU VM and offload the expensive part (generation) to Groq's free API. See §0 for the one
> code change this requires.

> **Honest caveats before you start:**
> - Oracle needs a **credit card for identity verification** (not charged on Always Free) and may be
>   hard to provision in busy regions (retry until an ARM instance is available).
> - Groq's free tier has **rate limits**; fine for a few users, not for scale. Concretely, the free
>   tier caps **~200,000 tokens/day (TPD)** per org for `openai/gpt-oss-120b` — enough for only a
>   handful of full contract analyses per day. Beyond that you get `429 tokens-per-day` errors (which
>   the adapter's backoff cannot clear, since a daily cap does not reset within retries) and reports
>   fall back to **degraded/failsafe**. For steady use, either upgrade to Groq's paid Dev tier, pick a
>   smaller model, or keep `LLM_PROVIDER=ollama` (local, no cap). Measured 2026-08-22: a single 6-doc
>   eval run nearly exhausted the daily budget — see `specs/046-groq-llm-provider/RESULTS.md`.
> - Vercel Hobby is technically **non-commercial** — if that worries you, use Cloudflare Pages.
> - A **custom domain is ~$12/yr** (the only non-$0 item). Use the free `*.vercel.app` subdomain to
>   stay at exactly $0.
> - **Accuracy is not yet legal-grade** — deploy with the built-in "not legal advice" honesty and do
>   not market decision-grade reliability. (Separate from deployment; see the accuracy work.)

---

## 0. Prerequisite code change: the LLM provider adapter (build this BEFORE deploying)

Today every generative call uses `ollama.Client(...)` pointed at a local qwen3. For the free deploy,
**generation** must go to Groq while **embeddings** stay on local `bge-m3`. This is a real feature —
build it on a branch through the normal spec → plan → tasks → reviewer-gate flow.

**What changes (5 generative sites across 4 files → Groq; `reflectors.py` has 2; 1 embedding site stays Ollama):**
- Generative call sites (route to Groq): `app/graph/nodes/splitters/llm_refiner.py`,
  `app/graph/nodes/validators/reflectors.py`, `app/graph/nodes/scorers/risk_scorer.py`,
  `app/graph/nodes/drafters/redline_drafter.py` (and any other `ollama.Client` chat site).
- Embedding call site (stays Ollama → `bge-m3`): `app/graph/nodes/retrievers/embeddings.py`.

**Design:**
1. Add config (§3 constants, env-overridable): `LLM_PROVIDER` (`"ollama"` | `"groq"`, default
   `"ollama"` so local dev is unchanged), `GROQ_API_KEY` (from env), `GROQ_MODEL`
   (e.g. `"openai/gpt-oss-120b"`).
2. Add a thin adapter (e.g. `app/llm/chat_client.py`) exposing the same `chat(messages, format=...)`
   shape the nodes already call. When `LLM_PROVIDER=="groq"`, call Groq's **OpenAI-compatible** endpoint
   (`https://api.groq.com/openai/v1/chat/completions`) with `response_format={"type":"json_object"}`
   for the JSON nodes; else use the existing Ollama path (byte-identical).
3. **Add 429/backoff handling** in the adapter (exponential backoff + a couple of retries) so a Groq
   rate-limit does **not** trip the failsafe → degraded report.
4. Keep `embeddings.py` on Ollama (`bge-m3`) unchanged.
5. **Re-run the eval harness** (`eval.harness.run` + `score`) against the Groq model to get honest new
   accuracy numbers — the qwen3 numbers do **not** carry over.

> Groq free models to consider: `openai/gpt-oss-120b` (strongest, what we validated), `openai/gpt-oss-20b`
> (lighter, higher token budget). Both support JSON mode + `reasoning_effort`. Pick based on the re-eval.
> **Note (measured 2026-08-22, `specs/046-groq-llm-provider/RESULTS.md`):** on our corpus gpt-oss-120b
> **tied** local qwen3:8b on recall/precision — accuracy is bottlenecked upstream (segmentation +
> relevance filtering), not by generative model strength. Groq's only clear win was severity grading
> (80% vs 20% exact). So the adapter is worth it for latency/ops, not for a recall/precision boost.

---

## 1. Accounts to create (all free)

| Service | URL | Notes |
|---|---|---|
| Oracle Cloud | cloud.oracle.com/free | Credit-card identity check; pick a **home region** with ARM capacity |
| Groq | console.groq.com | Create an **API key**; no card required currently |
| Vercel *or* Cloudflare Pages | vercel.com / pages.cloudflare.com | Connect your GitHub repo |
| Google Cloud (OAuth) | console.cloud.google.com | You already have OAuth creds; see §6 |
| GitHub | (existing) | The repo is already here |

---

## 2. Oracle "Always Free" VM

1. **Sign up** at cloud.oracle.com/free, verify identity (card not charged).
2. **Create instance:** Compute → Instances → *Create Instance*.
   - **Image:** Ubuntu 22.04 (ARM).
   - **Shape:** `VM.Standard.A1.Flex` → set **4 OCPU / 24 GB RAM** (the full Always Free ARM allotment).
   - If you get "out of capacity," retry (change availability domain / try again later — ARM is popular).
   - **SSH keys:** upload/generate a key pair; save the private key.
3. **Networking:** open the ports you need in the VCN **Security List** (Ingress rules):
   - `22` (SSH), `443` (HTTPS), `80` (HTTP→for Let's Encrypt). Do **not** expose `11434` (Ollama) or
     `8000` (backend) publicly — keep them behind the reverse proxy / localhost.
4. **SSH in:** `ssh -i <your-key> ubuntu@<public-ip>`.
5. **Also** run Ubuntu's own firewall open for 80/443: `sudo iptables` rules or `netfilter-persistent`
   (Oracle Ubuntu images ship with restrictive iptables — open 80/443, keep 8000/11434 local only).

---

## 3. Install runtime on the VM

```bash
# System + Docker
sudo apt update && sudo apt -y upgrade
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu   # re-login after this

# Ollama (for bge-m3 embeddings only)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull bge-m3
# keep Ollama bound to localhost (default) — it must NOT be public
```

- `bge-m3` on CPU is fine (embeddings are cheap). Confirm: `curl localhost:11434/api/tags`.

---

## 4. Deploy the backend (Docker on the VM)

1. **Clone your repo** on the VM: `git clone <your-repo-url>` and `cd` into `backend/`.
2. **Dockerfile** (add one to `backend/` if not present) — Python 3.11 slim, `uv sync --frozen`, copy
   app, run `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`.
3. **Persistent data:** mount a host directory as a Docker volume for the SQLite DBs + uploads so
   nothing is lost on redeploy:
   - `data/job_store.db`, `data/checkpoints.db`, and the encrypted `UPLOAD_DIR`.
   - e.g. `-v /home/ubuntu/cs-data:/app/data`.
4. **Environment (secrets)** — pass via `--env-file` or Docker secrets (NEVER commit these):
   - `AUTH_SECRET=<64+ random bytes>`
   - `CONTRACT_ENCRYPTION_KEY` / the Fernet key(s) your `crypto` module reads
   - `AUTH_COOKIE_SECURE=True` (you're behind TLS now)
   - `LLM_PROVIDER=groq`, `GROQ_API_KEY=<key>`, `GROQ_MODEL=openai/gpt-oss-120b`
   - `OLLAMA_HOST=http://127.0.0.1:11434` (for local `bge-m3` embeddings)
   - `OLLAMA_EMBED_MODEL_NAME=bge-m3`
   - Google OAuth creds/paths (see §6), delivery toggles as desired
   - CORS: allow your frontend origin (see §5)
5. **Run migrations** on first boot: `alembic upgrade head` (inside the container / one-off).
6. **Start:** `docker run -d --restart=always -p 127.0.0.1:8000:8000 --env-file .env -v /home/ubuntu/cs-data:/app/data <image>`
   (bind to `127.0.0.1` so only the reverse proxy reaches it).

### 4a. TLS + reverse proxy (Caddy = easiest, auto Let's Encrypt)
```bash
sudo apt -y install caddy
```
`/etc/caddy/Caddyfile`:
```
api.yourdomain.com {          # or use the VM public IP + a free DNS name
    reverse_proxy 127.0.0.1:8000
}
```
`sudo systemctl reload caddy` — Caddy fetches a free TLS cert automatically. If you have no domain,
use a free hostname (e.g. DuckDNS) pointed at the VM IP, or Cloudflare's free proxy in front.

---

## 5. Deploy the frontend (Vercel or Cloudflare Pages)

1. Import the GitHub repo; set the project root to `frontend/`.
2. **Env vars:**
   - `NEXT_PUBLIC_API_PROVIDER=real`
   - `NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com` (your backend's public HTTPS URL)
3. Deploy. You get a free `*.vercel.app` / `*.pages.dev` URL (or attach a custom domain later).
4. **Wire CORS + cookies (critical):**
   - Backend `CORS` must allow the exact frontend origin **with credentials** — set
     `CORS_ALLOWED_ORIGINS=https://<app>.vercel.app` (comma-separated for several; feature 048).
   - Auth cookies are `Secure` + cross-site → set **`AUTH_COOKIE_SAMESITE=none`** (with
     `AUTH_COOKIE_SECURE=True`, which you have over HTTPS). This is the switch that makes the session
     cookie actually stick across the frontend→backend boundary; without it the browser silently drops
     it and login won't persist. If instead you put frontend + backend on subdomains of one registrable
     domain (e.g. `app.` + `api.yourdomain.com`), the default `lax` suffices — leave `AUTH_COOKIE_SAMESITE`
     unset. Note: the config **refuses to boot** if `AUTH_COOKIE_SAMESITE=none` without
     `AUTH_COOKIE_SECURE=True` (browsers reject that combination).

---

## 6. Google OAuth (Drive / Gmail delivery)

- **Fastest path (recommended for launch):** keep the OAuth app in **"Testing"** mode. It works
  immediately and supports up to **100 explicitly-added test users** — perfect for a real-but-small
  product. Add yourself + early users as test users.
- **Public path (later):** submitting for **Production** verification (Gmail/Drive scopes) can take
  **days to weeks** of Google review. Only do this when you actually need >100 users.
- Set the **authorized redirect URI** to your deployed backend's callback
  (`https://api.yourdomain.com/api/integrations/google/callback`) and update the OAuth client
  accordingly. **The backend must be told the same value** via `GOOGLE_OAUTH_REDIRECT_URI` (feature 049)
  — it must match the GCP-registered URI exactly or Google rejects the callback.
- Set **`FRONTEND_INTEGRATIONS_URL`** to your deployed frontend's integrations page
  (`https://<app>.vercel.app/integrations`) — the post-connect 302 lands there; left at the localhost
  default the user is bounced to a dead `localhost:3000` after connecting (feature 049).
- Set `OAUTHLIB_RELAX_TOKEN_SCOPE=1` if you hit scope-mismatch errors (known gotcha).

---

## 7. Smoke-test checklist (do all after deploy)

- [ ] `https://api.yourdomain.com/docs` returns 200.
- [ ] Frontend loads over HTTPS; **login works and persists** (cookie crosses the domain boundary).
- [ ] Upload a real contract → analysis completes → **`analysis_degraded` is false** and findings are
      genuine (this proves Groq generation + local `bge-m3` are both working end-to-end).
- [ ] Rate-limit safety: run 2–3 analyses quickly; confirm no 429-triggered degraded reports (proves
      the adapter's backoff works).
- [ ] Delivery: Drive folder + Gmail report arrive (with you as an OAuth test user).
- [ ] Restart the VM / redeploy the container → **data persists** (jobs, users, uploads survive).
- [ ] `security_audit.py --severity high` still clean.

---

## 8. Environment variable reference

| Var | Where | Example / note |
|---|---|---|
| `AUTH_SECRET` | backend | 64+ random bytes; secret manager |
| Fernet key(s) | backend | contract/token encryption; NEVER commit |
| `AUTH_COOKIE_SECURE` | backend | `True` in prod (needs TLS) |
| `CORS_ALLOWED_ORIGINS` | backend | comma-separated; the exact deployed frontend origin(s), e.g. `https://<app>.vercel.app` (unset ⇒ localhost dev default) |
| `AUTH_COOKIE_SAMESITE` | backend | `none` for a cross-site `*.vercel.app`↔VM deploy (**requires `AUTH_COOKIE_SECURE=True`**); `lax` (default) if frontend+backend share a registrable domain |
| `LLM_PROVIDER` | backend | `groq` in prod, `ollama` local |
| `GROQ_API_KEY` | backend | from console.groq.com |
| `GROQ_MODEL` | backend | `openai/gpt-oss-120b` |
| `GOOGLE_OAUTH_REDIRECT_URI` | backend | prod: `https://api.<domain>/api/integrations/google/callback` — must exactly match the URI registered on the GCP Web OAuth client (feature 049) |
| `FRONTEND_INTEGRATIONS_URL` | backend | prod: `https://<app>.vercel.app/integrations` — where OAuth connect/disconnect 302-redirects the browser (feature 049) |
| `OLLAMA_HOST` | backend | `http://127.0.0.1:11434` (local bge-m3) |
| `OLLAMA_EMBED_MODEL_NAME` | backend | `bge-m3` |
| `NEXT_PUBLIC_API_PROVIDER` | frontend | `real` |
| `NEXT_PUBLIC_API_BASE_URL` | frontend | `https://api.yourdomain.com` |
| Google OAuth creds | backend | client id/secret + redirect URI |

---

## 9. Ongoing ops (free)

- **Backups:** `cron` a nightly copy of `/home/ubuntu/cs-data` (SQLite DBs + uploads) to Oracle Object
  Storage (Always Free includes 10 GB) or `rclone` to another free store.
- **Logs:** `docker logs -f <container>`; Caddy logs under `/var/log/caddy`.
- **Restart policy:** `--restart=always` on the container; Ollama runs as a systemd service.
- **Keep the free VM alive:** Oracle may reclaim *idle* Always Free instances — light real traffic or a
  cheap keep-alive ping avoids this.
- **Cost check:** everything above is $0. The only spend is an optional custom domain (~$12/yr).

---

## 10. Order of operations (summary)

1. Build + merge the **LLM provider adapter** (§0) — re-eval on Groq for honest numbers.
2. Provision the **Oracle VM** (§2), install **Docker + Ollama + bge-m3** (§3).
3. Deploy the **backend** container with TLS (§4), run migrations.
4. Deploy the **frontend** (§5); wire CORS + cookies.
5. Point **OAuth** at the deployed backend, keep it in Testing mode (§6).
6. Run the **smoke checklist** (§7).

*Everything here stays within free tiers. Build the adapter first — it's the prerequisite the whole
deploy depends on, and it's also the single biggest lever on analysis quality (a stronger model).*
