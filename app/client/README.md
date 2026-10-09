# TensorForge 2.0: Web Client (`app/client`)

The browser UI for the ticket classifier: **React 19 + TypeScript + Vite + Tailwind CSS 4**.
It is a **separate app** from the API. It builds to static files (`dist/`), is hosted on **AWS Amplify**, and calls
the API engine (`app/server`) over HTTPS with CORS. The API container never serves the UI.

```
Browser ──► AWS Amplify (static UI, this folder) 
   │
   └──fetch + X-API-Key──► API engine container (app/server)  ← allows the Amplify origin via CORS_ORIGINS
```

The design rationale is in `Resources/architecture_frontend.md` §0: who uses it, why it is deliberately not
flashy, why React + Vite rather than Next.js (A12), and why the UI is separate from the API (A13).

## Commands

Requires Node ≥ 22.12.

```bash
cd app/client
npm ci              # install exact versions from package-lock.json
npm run dev         # dev server on http://localhost:5173, API calls proxied to the engine on :8000
npm test            # unit tests (CSV parser, file loading, validation): Vitest
npm run typecheck   # TypeScript, no emit
npm run build       # type-check + production build to dist/
```

`npm run dev` expects the engine on `http://127.0.0.1:8000` and proxies to it, so the page and the API share an
origin and no CORS is needed. Point it elsewhere with `ENGINE_URL=http://host:port npm run dev`.

| Build-time variable | Meaning |
|---|---|
| `VITE_API_BASE_URL` | The API's base URL, e.g. `https://api.example.com` (no trailing slash). **Required for production builds**: without it the page shows a "Not configured" banner. Leave it unset for `npm run dev` |

When the page asks for the **API key**, enter the key the server was started with. The key is checked against the
API, kept in `sessionStorage` (or `localStorage` if you tick "Remember on this device") and sent as `X-API-Key`.
It never appears in the source or the build.

**Manual end-to-end test:** see [TESTING.md](TESTING.md) (step-by-step, with test files in `test-data/` and expected results).

## Deploy on AWS Amplify

1. **API first.** Deploy the API container on its HTTPS host. Start it with the extra variable
   `CORS_ORIGINS=https://main.<app-id>.amplifyapp.com` (the exact Amplify URL from step 3; you can add it after
   the first Amplify deploy and restart the API).
2. **Create the Amplify app.** In the Amplify console, choose *Host web app* → GitHub → this repository and the
   branch. Tick **"My app is a monorepo"** and set the app root to `app/client`. Amplify picks up `amplify.yml`
   from the repo root: Node 22, `npm ci`, `npm test`, `npm run build`, publish `dist/`.
3. **Set the API address.** *App settings → Environment variables*: `VITE_API_BASE_URL = https://<api-host>`.
   It is baked in at build time, so **redeploy** after changing it.
4. **Allow the site in the API.** Put the Amplify URL (e.g. `https://main.d1abc2xyz.amplifyapp.com`) in the API's
   `CORS_ORIGINS` and restart the API.
5. **Check.** Open the Amplify URL. The header should show "Model ready · v1.2-…". Then enter the key and
   classify a sample.

The page uses hash navigation (`#batch`, `#jobs`), so Amplify needs no rewrite rules. The API must be HTTPS:
browsers block calls from an HTTPS page to an HTTP API.

**If the header says "Server unreachable":** the API is down, `VITE_API_BASE_URL` is wrong, or the API's
`CORS_ORIGINS` doesn't contain the exact Amplify URL (scheme + host, no trailing slash). The browser console shows a
CORS error in the last case.

## What's in it

| View | For | What it does |
|---|---|---|
| **Classify** | Support agents, judges | One ticket → category, team, urgency, secondary issue and a confidence meter with the 70 % review threshold. One-click samples in Sinhala, Tamil, Singlish, Tanglish, mixed script and English |
| **Batch** | Team leads / managers | Drop a CSV, JSON or JSONL file. Rows are checked before sending. **≤ 100 tickets → `/predict/batch`** (instant), **101–5,000 → `/batch/jobs`** (background). Shows a summary (urgent, needs review, per-team load), a filterable table and CSV export (original columns plus predictions) |
| **Jobs** | Team leads, engineers | Background jobs started from this browser (or opened by ID): live progress (follows `Retry-After`), cancel or delete, view and download results |
| **API** | Integration engineers | Endpoint list, copy-ready `curl` examples, links to `/docs` and `/redoc` |

The header shows the API's live `/health` status and the served `model_version`. Every number on the page comes from
a real API response. Nothing is simulated.

### Batch file format

```csv
ticket_id,channel,subject,text
T-001,chat,,"bro mage order eka late, refund ekak denna"
T-002,email,Payment issue,"I was charged twice for the same ride."
```

- `channel` (`chat` | `email` | `call_transcript`) and `text` are required. `subject` and `ticket_id` are optional.
  If there is no `ticket_id` column, ids `row-<n>` are generated.
- Standard CSV quoting is supported, including line breaks inside quoted text. The competition CSVs parse
  identically to Python's `csv` module (covered by a unit test when `Resources/` is present). UTF-8 with or
  without BOM.
- Extra columns (e.g. `language`, `category`) are ignored for prediction and kept in the export.
- JSON: a list of tickets or `{"tickets": [...]}`. JSONL: one ticket per line.
- Exported CSVs start with a UTF-8 BOM so Excel shows Sinhala and Tamil correctly.

## Code layout

```
index.html                     HTML shell (theme applied before first paint)
vite.config.ts                 dev proxy to the engine, Vitest config
../../amplify.yml              AWS Amplify build spec (monorepo app root app/client)
src/main.tsx                   React root
src/App.tsx                    header (health, key, theme), accessible tabs synced with the URL hash, config/health banners
src/index.css                  Tailwind 4 + semantic theme tokens (light/dark), shared utilities
src/lib/types.ts               API contract types (mirrors the OpenAPI v2.1.0 schemas)
src/lib/api.ts                 API base URL (VITE_API_BASE_URL), fetch wrapper, contract errors → plain-language messages, API-key store
src/lib/tickets.ts             categories → teams, samples, file loading + validation (mirrors the contract)
src/lib/csv.ts                 RFC 4180 CSV parse/serialise
src/lib/format.ts              number/time formatting, file download
src/hooks/useAppState.ts       useApiKey, useHealth (polling), useTheme
src/components/ui.tsx          Button, Badge, Note, Card, StatTile, … (one component vocabulary)
src/components/feedback.tsx    toasts + confirm dialog
src/components/KeyDialog.tsx   API-key dialog (verifies the key, opens on any 401)
src/features/classify/         Classify view + prediction card
src/features/batch/            Batch view (file → validate → sync batch or async job)
src/features/jobs/             job store (polling outside React) + Jobs view
src/features/results/          shared results summary, per-team bars, table, export
src/features/api/              API view
```

Dependencies are pinned (`--save-exact`) and kept minimal: `react` and `react-dom` at runtime. Everything else
(Vite, Tailwind, TypeScript, Vitest) is build or test tooling.

## UX and accessibility notes

- Calm, neutral UI. Colour is used for meaning only (blue = action, red = urgent/error, amber = needs review,
  green = OK), and status is always shown with text and an icon, never colour alone.
- Light and dark themes follow the OS, with a toggle. Theme colours are CSS variables mapped into Tailwind
  (`bg-surface`, `text-muted`, `bg-mark`…), so components have no `dark:` variants. Data-mark colours are validated
  per theme for contrast and colour-blind separation.
- Keyboard: tabs use arrow keys / Home / End, <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>Enter</kbd> classifies, and focus
  rings are visible. Results and job progress are announced via `aria-live`.
- Respects `prefers-reduced-motion`. Responsive down to 360 px (on narrow screens the result scrolls into view).
  44 px touch targets.
- React escapes all ticket text, so ticket content can't inject markup.
- Sinhala and Tamil rely on system fonts (`Nirmala UI` on Windows, `Sinhala/Tamil Sangam MN` on macOS, `Noto` on
  Android and most Linux desktops). A machine without them shows boxes; install `fonts-noto` on bare Linux.
