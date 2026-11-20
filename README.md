# GST CashPilot (prototype)

Know your GST cash before you file. It matches purchase invoices with GSTR-2B, decides which credit is Eligible, At risk or Blocked with the GST rule shown, shows vendors that block credit, scans invoices, and prepares a GSTR-3B draft. **Draft only. Nothing is filed.** Dummy data only.

```
cashpilot/
  api/    FastAPI backend, MVC (Python)
  web/    Next.js app (React), static export for Firebase Hosting
  firebase.json, run.sh
```

## Run it

```bash
./run.sh                      # API on http://localhost:8010, web on http://localhost:3000
```

Or by hand:

```bash
cd api && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --port 8010          # seeds the demo data on first start (AUTO_SEED=true)

cd web && npm install && npm run dev      # http://localhost:3000
```

Port 8010 is used because 8000 is often taken. `web/.env.local` holds `NEXT_PUBLIC_API_URL`.

Tests: `cd api && source .venv/bin/activate && python -m pytest -q` (18 tests).

## What you see

| Page | What it does |
| --- | --- |
| Overview | KPI grid (total purchase cost first), trend charts (Spend, Cash & tax, ITC mix, Match quality), ITC composition, section cards, vendors table on the Overview (order, period, risk filter, search; 5, 10, 15 or 20 rows per page), generated insights, Ask CashPilot (ADK), processing-layer strip |
| Invoice scanner | Upload or drop a PDF/photo, see the original, extracted fields with confidence, plain-code checks, confirm, and the effect on your cash payable |
| Reconciliation | Section by section (matched, amount mismatch, missing in 2B, missing in books) with filters; a drawer per item with books vs GSTR-2B, the RAG rule, and the decision trace through the layers |
| GSTR-3B draft | Tables 3.1, 4 and 6, Case A (eligible only) and Case B (eligible + at risk), PDF download |
| Ask CashPilot (floating chat, every page) | Type or speak a question (nine Indian languages). The browser turns speech into text, the API understands it with plain code (vendor, status, match type, amount, month, invoice number, cash payable) and answers from saved results, with result rows that open the detail panels. Open questions go to the Google ADK agents. Read-only |
| Processing layers | Six layers with status, counts, timing, engine and what each one feeds; run again; upload the three monthly files |

Nothing is hard coded in the UI. Every number comes from the API, which computes it from the database. The October 2026 month is loaded from the files in `api/app/data/sample/` (38 matched, 5 amount mismatch, 7 missing in 2B, 3 missing in books; cash payable ₹1,76,642.50 safe and ₹1,45,000 if at-risk is claimed). May to September are generated fixtures in the same file formats and go through the same intake code.

## Voice (Gemini Live) and Vertex AI

- **Gemini Live voice assistant.** In the floating chat, the mic opens a real-time voice session: the browser streams the microphone to `WS /api/v1/live`, the API relays it to Gemini Live (`GEMINI_LIVE_MODEL`, default `gemini-3.8-live`), and the spoken reply plays back as it arrives. The assistant answers in the language you speak. For data questions it calls a tool that runs the same exact, read-only search as the typed chat, so it never invents numbers. Without Gemini, the mic falls back to the browser's speech recognition.
- **Vertex AI backend.** `GENAI_BACKEND=vertex` sends Gemini and the ADK agents through Vertex AI in your Google Cloud project (set `GOOGLE_CLOUD_PROJECT`, or `VERTEX_API_KEY` for express mode). Needs billing, the Vertex AI API enabled, and `gcloud auth application-default login`.
- **Vertex AI Search for the GST rules.** `RAG_BACKEND=vertex_search` runs the rule search on a Vertex AI Search data store instead of the local embeddings, and falls back to local if it fails. Create the data store once with `python scripts/vertex_search_setup.py --project YOUR_PROJECT`.

## AlloyDB (connected)

The API runs on AlloyDB for PostgreSQL when `DATABASE_URL` is a PostgreSQL address, and on local SQLite when it is not set.

```bash
cd api
python scripts/alloydb_setup.py --admin-url "postgresql+psycopg://postgres:PW@HOST/postgres?sslmode=require" --app-password APP_PW --rls
# then in api/.env:
DATABASE_URL=postgresql+psycopg://cashpilot_app:APP_PW@HOST/postgres?sslmode=require
```

The script creates the tables, the restricted role `cashpilot_app` and row level security. The API connects as that role, and `set_tenant` sets the business per transaction. Your public IP must be in the instance's authorized networks (`gcloud alloydb instances update ... --authorized-external-networks=IP/32`). Delete the cluster when you are done to stop the charge: `gcloud alloydb clusters delete cashpilot --region asia-south1 --force`.

## Backend: MVC

| Layer | Where | Role |
| --- | --- | --- |
| **Model** | `api/app/models/` | SQLAlchemy entities (the ER diagram) |
| **View** | `api/app/schemas/views.py` | Pydantic response and request shapes |
| **Controller** | `api/app/controllers/` | Routers: dashboard, vendors, reconciliation, scans, draft, pipeline, ingest, copilot, system |
| Services | `api/app/services/` | Business logic the controllers call: ingest, matching, itc, rag, tax, analytics, ocr, pipeline, pdf |
| Agents | `api/app/agents/` | Google ADK agents and their tools |
| Core | `api/app/core/` | Settings, database, auth |

## Processing layers

1. **Intake** reads GSTR-2B (xlsx), the purchase register and the sales summary, plus scanned invoices.
2. **Normalize** cleans invoice numbers (`INV/001` and `inv-0001` both become `INV1`) and validates GSTINs.
3. **Match** on supplier GSTIN + cleaned number, ₹1 tolerance, plain Python, no fuzzy matching.
4. **Rule retrieval (RAG)** finds the GST rule passage for each case.
5. **ITC decision** applies the rules in order (not in 2B, blocked category, too old, books above 2B, otherwise eligible). No rule found means At risk and "no rule found".
6. **Tax and draft** computes cash payable per head and the GSTR-3B draft.

Every KPI card and insight shows the layer that produced it (L1 to L6).

## Google ecosystem

| Part | Used for |
| --- | --- |
| Google ADK (`google-adk`) | Root, extraction, eligibility and draft agents; tools read the business from session state, never from the model |
| Gemini (`google-genai`) | Invoice reading (multimodal), plain-words explanations, embeddings. Optional |
| AlloyDB for PostgreSQL | Production database, pgvector, row level security (`api/db/alloydb_schema.sql`). SQLite locally |
| Firebase Auth | Google sign in (web) and ID token check (API) |
| Firebase Hosting | Serves the static Next.js build |
| Cloud Run | Hosts the FastAPI service (`api/Dockerfile`) |

### Offline mode (default) and live mode

With no `GEMINI_API_KEY` everything runs locally:

- **OCR**: PDFs with a text layer are parsed locally. Photos and scanned PDFs need Gemini.
- **Embeddings**: a local hashing embedding (768 dimensions) with a small tag boost.
- **Explain with Gemini** and **Ask CashPilot** show a clear message that a key is needed.

Set `GEMINI_API_KEY` (from Google AI Studio) in `api/.env` to switch on Gemini reading, Gemini embeddings (re-embedded automatically) and the ADK agents. The header shows which engines are active.

## Deploy (automatic)

Every push to `main` runs `.github/workflows/deploy.yml`: tests, then the API goes to **Cloud Run** (`cashpilot-api`, asia-south1, private link to AlloyDB, secrets from Secret Manager), then the web app is built against that API and deployed to **Firebase Hosting**. GitHub signs in to Google Cloud with Workload Identity Federation, so no keys are stored. Live site: https://gstcashcopilot.web.app

## Deploy by hand

**Web, Firebase Hosting**

```bash
cd web
NEXT_PUBLIC_API_URL=https://YOUR-API-URL NEXT_PUBLIC_FIREBASE_API_KEY=... NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=... \
NEXT_PUBLIC_FIREBASE_PROJECT_ID=... NEXT_PUBLIC_FIREBASE_APP_ID=... npm run build     # writes web/out
cd .. && cp .firebaserc.example .firebaserc && firebase deploy --only hosting
```

**API, Cloud Run**

```bash
cd api
gcloud run deploy cashpilot-api --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars AUTH_MODE=firebase,FIREBASE_PROJECT_ID=...,DATABASE_URL=postgresql+psycopg://... \
  --set-secrets GEMINI_API_KEY=gemini-key:latest
```

Apply `api/db/alloydb_schema.sql` to AlloyDB first and connect the API as the restricted role `cashpilot_app`, so row level security applies. Add your Hosting URL to `CORS_ORIGINS` (`*.web.app` and `*.firebaseapp.com` are already allowed).

**Agents on Agent Runtime** (design document option): the ADK agents in `app/agents/definitions.py` can be deployed with `adk deploy agent_engine`. The web app needs a Google credential to call Agent Runtime directly, so this prototype keeps the FastAPI service in front (risk R7 in the design).
used up. **Gemini Live streaming (a live spoken conversation through a backend WebSocket) is not built.**
- Not built: filing, bank balance, interest, notices, Tally/Zoho connectors, many users per business.
