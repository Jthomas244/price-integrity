# PriceIntegrity — Pricing Compliance Audit Engine

*(working title)*

An open-source tool that audits an e-commerce pricing engine to determine
whether price variance is driven by lawful **market conditions** (inventory,
demand, seasonality) or by **individual consumer characteristics** (device,
location, browsing history) — the distinction regulators draw between
"dynamic pricing" and "personalized / surveillance pricing".

It probes only storefronts the author controls: [GhostCart](https://ghostcart-ten.vercel.app)
(a satirical fake store built for exactly this purpose) and an in-process demo
store used by the test suite. It never touches a real third-party retailer.

## How it works

1. **Factorial prober** (`backend/probing/factorial.py`) — runs synthetic
   sessions in which *every* signal is assigned a value at random (a
   randomized factorial experiment), so each signal's effect can be
   estimated while holding the others constant. Against GhostCart that's
   the full 3 × 2 × 4 × 8 = 192-cell design per product; against the
   13-signal demo store a random design.
2. **Regression audit engine** (`backend/audit_engine/rigorous.py`) — sees
   only prices. Per product, fits log(price) on all signals plus every
   pairwise interaction between individual-based signals, by Huber
   (robust) regression. Every coefficient gets a t-test; p-values are
   Benjamini-Hochberg FDR-corrected (individual-based terms as their own
   family). Effects are reported as exact percentages with 95% confidence
   intervals. A signal is flagged only if significant *and* ≥ 3%.
3. **Report** (`backend/audit_engine/report.py`) — JSON payload plus a
   standalone HTML page written for a non-technical reader: headline,
   per-signal cards with CI and corrected p-value, compounding
   (interaction) effects, signals that came back clean, lawful dynamic
   pricing observed.

The original one-signal-at-a-time prober and threshold engine
(`probing/prober.py`, `audit_engine/engine.py`) are still there — they're
the legible baseline and the demo store's test bed — selectable with
`"engine": "threshold"` on `POST /audit`.

Severity bands (individual-based signals only): LOW ≥ 3%, MODERATE ≥ 8%,
HIGH ≥ 15%. Market-based effects ≥ 1% are reported as *lawful dynamic*.
Configurable via `AuditConfig`.

### Statistical claims, and where they're tested

| Claim | Test |
| --- | --- |
| Recovers GhostCart's exact rules (×1.10 mobile, ×1.06 abandonment, ×1.08 interaction, inventory slope) | `tests/test_rigorous.py::TestGhostCartRecovery` |
| The referrer decoy stays clean in every combination of the other signals | `test_referrer_decoy_*` |
| Effects are attributed correctly even when signals are confounded | `test_confounded_design_is_still_attributed_correctly` |
| Huber fit resists outlier probes that would swing OLS | `test_huber_resists_outliers_better_than_ols` |
| Benjamini-Hochberg implemented correctly | `TestBenjaminiHochberg` |
| False-discovery rate ≤ 5% under the null, by Monte Carlo (300 simulated audits) | `test_monte_carlo_false_discovery_rate_is_controlled` |
| Power: a real 10% effect is found in ≥ 49/50 noisy audits | `test_monte_carlo_power_on_real_effect` |
| Whole pipeline over HTTP against a contract-faithful fake GhostCart | `tests/test_factorial.py::test_full_pipeline_against_fake_ghostcart` |

## Auditing live GhostCart

GhostCart exposes `POST /api/persona-price`, a side channel gated by a
shared secret (contract: `docs/ghostcart-persona-price-contract.md`).

```bash
cp .env.example .env      # then paste GHOSTCART_PROBE_SECRET
cd backend && .venv/bin/python scripts/audit_ghostcart.py
```

That probes 10 products × 192 sessions and writes
`reports/ghostcart-latest.{json,html}`.

## Running the backend

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn api.main:app --reload
```

| Endpoint | Purpose |
| --- | --- |
| `GET  /catalog` | Products in the demo store |
| `GET  /signals` | The signal taxonomy and which bucket each signal is in |
| `GET  /rules` | The demo store's real pricing rules — the audit's answer key |
| `POST /audit` | Probe + audit the demo store → JSON report (`engine`: `threshold` \| `regression`) |
| `POST /audit/html` | Same, rendered as HTML |
| `GET  /ghostcart` | Whether the live target is configured, and the signal space it varies |
| `POST /audit/ghostcart` | Probe live GhostCart → JSON report (needs `GHOSTCART_PROBE_SECRET`) |
| `POST /audit/ghostcart/html` | Same, rendered as HTML |

Interactive docs at `http://localhost:8000/docs`.

### Deploying

- **Backend** — `backend/Dockerfile` (uvicorn on `$PORT`); `render.yaml` is a
  Render blueprint for it. Set `GHOSTCART_PROBE_SECRET` and `CORS_ORIGINS`
  (the frontend's origin).
- **Frontend** — a Next.js app rooted at `frontend/`; on Vercel set the root
  directory to `frontend` and `NEXT_PUBLIC_API_URL` to the backend's URL.
  Without a backend the site still works — the report page shows the
  committed audit and explains that live re-runs are off.

## Tests

```bash
cd backend && .venv/bin/pytest -q
```

Dependencies: fastapi, uvicorn, httpx, numpy, scipy (no statsmodels, no pandas).

## Status

- [x] Phase 0 — GhostCart `/api/persona-price` endpoint (in the GhostCart repo)
- [x] Phase 1 — Factorial HTTP prober + GhostCart client
- [x] Phase 2 — Rigorous audit engine (Huber IRLS, BH-FDR, interactions, Monte Carlo check)
- [x] Phase 3 — Report generator (interaction findings, CIs, corrected p-values)
- [x] First real audit of live GhostCart — `reports/ghostcart-latest.{json,html}`
- [x] Phase 4 — Next.js frontend (`frontend/`): landing, report with live re-run and
      interactive visualizations, methodology; GhostCart's `/audit` shows the real result
- [x] Phase 5 — Packaging (MIT LICENSE, `docs/methodology.md`)
- [ ] Phase 6 — Deploy (frontend on Vercel, API on Render)
