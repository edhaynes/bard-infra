# Refinery Console

The management console for the refinery demo — cdn-sim's NOC chrome re-themed to a
5-section refinery. React 19 + Vite + TypeScript. Talks only to the orchestrator
(CORS-enabled) at `VITE_ORCH_BASE` (default `http://127.0.0.1:7090`).

## What it shows

- **Top bar** — Bring up / Bring down / Reset, mode + blocked-reason pills, tick clock.
- **KPI strip** — units running, sections up, elements, discovered, alarms, tripped/down.
- **Plant** — 5 section cards (S4 Utilities → S1 Crude → S3 Treating → S2 Conversion →
  S5 Tank Farm), each with its units, live telemetry, status dots, and network gear.
- **Side panel** — inject a fault (kind + live target list) and the open-incident list
  with Resolve.

See `../docs/screenshots/` for running + fault-cascade captures.

## Run

```bash
npm install
npm run dev            # Vite dev server on http://127.0.0.1:5175
# or
npm run build && npm run preview -- --port 5175 --host 127.0.0.1
```

Requires the orchestrator running (see `../README.md`):
```bash
cd .. && python -m uvicorn refinery.server:app --port 7090
```

## Tests

Structural Playwright tests (assume orchestrator + console running):
```bash
npx playwright install chromium   # once
npx playwright test
```

> Playwright verifies structure, not aesthetics — visual correctness is signed off from a
> screenshot review (`coding-rules.md` §14).
