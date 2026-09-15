# PriceIntegrity — project context for Claude Code

*(Working title. Final name still pending — "PriceIntegrity" is used
throughout; do a global rename when it's decided.)*

## What this is

An open-source (MIT) pricing-compliance audit tool. It probes an
e-commerce pricing engine with synthetic sessions and determines whether
price variance is driven by lawful **market conditions** (inventory, time
of day, demand) or by **individual consumer characteristics** (device,
location, history, account status) — the distinction the FTC and state
laws like New York's Algorithmic Pricing Disclosure Act (in effect
Nov 10, 2025) now draw between "dynamic" and "personalized/surveillance"
pricing.

Portfolio piece, not a commercial product. It pairs with VaultAP (B2B
pre-payment fraud detection) and GhostCart so the body of work reads as
one specialty: trust and risk tooling for commerce.

**Firm non-goal:** never probe a real third-party retailer. The only
target is GhostCart, a storefront Julian owns outright. Anything that
points this at someone else's site is out of scope for v1 and a legal
risk to attach to a real name.

## Relationship to GhostCart (the audit target)

GhostCart (`~/Downloads/ghostcart`, github.com/Jthomas244/ghostcart,
live at https://ghostcart-ten.vercel.app) is a completed satirical
e-commerce site. It exposes **two** pricing surfaces. Do not confuse them:

| | `/api/persona-price` | `/api/price` |
|---|---|---|
| Purpose | **The audit target for this project** | Public demo behind GhostCart's `/pricing-lab` and `/audit` pages |
| Access | Double-gated: `PERSONA_PRICING_ENABLED` + `X-PriceIntegrity-Probe` header (404 otherwise) | Open, CORS `*` |
| Signals | 4: `device_type`, `cart_abandonment`, `referrer_source` (no-effect decoy), `inventory_level`, + mobile×abandonment interaction | 7 personas, 9 rules |
| Products | 10 (`GC-0001`…`GC-0010`) | all 128 |
| Determinism | Pure, no jitter | ±0.5% jitter unless `noise=0` |

**Contract: `docs/ghostcart-persona-price-contract.md`** — request/response
shapes, exact rule magnitudes, the product subset with base prices and
control inventory. It was finalized 2026-09-15 (GhostCart tag v0.6) and
the Phase 1 prober should be built against it without further
coordination. Do not ask GhostCart for new signals; the 4-signal set is a
deliberate constraint (see "The gap" below for why that constraint is
currently aspirational).

The probe secret is set only in GhostCart's Vercel production env. Get it
with `vercel env pull` from the ghostcart repo, or ask Julian. It goes in
this project's `.env` as `GHOSTCART_PROBE_SECRET`; never commit it.

GhostCart and PriceIntegrity reference each other publicly — GhostCart
is the origin story (built a fake store, saw how easy per-customer price
rigging would be). GhostCart's `/audit` page is already a funnel *into*
this project; once a real audit runs, that page should show the real
report instead of its derived preview.

## What's on disk (verified 2026-09-15, end of day)

`backend/` — Python 3.14 (`backend/.venv`), FastAPI, **113 tests green**
(`backend/.venv/bin/pytest -q` from `backend/`). Deps: fastapi, uvicorn,
httpx, numpy, scipy; dev: pytest. No pandas, no statsmodels.

- `audit_engine/models.py` — `SignalType` (13 signals: 4 market-based,
  9 individual-based), `Category`, `RiskSeverity`, `ProbeObservation`
  (threshold engine's one-signal shape), `AuditFinding` (shared by both
  engines; regression fills `effect_type`, `signals`, `ci_low_pct`,
  `ci_high_pct`, `p_value_corrected`, `significant_variants`),
  `AuditConfig` (LOW ≥ 3%, MODERATE ≥ 8%, HIGH ≥ 15%, lawful ≥ 1%,
  `alpha` 0.05, `min_obs_per_param` 8).
- `audit_engine/rigorous.py` — **`RigorousAuditEngine`**, the port of
  `audit_engine_v2_rigorous.py` (recovered from `~/Downloads` on
  2026-09-15). `SessionObservation` (all signals per session). Per
  product: log(price) ~ all signals + pairwise interactions among
  individual-based signals, Huber IRLS with Huber's asymptotic SEs and
  small-sample correction; t-tests; BH-FDR in two families
  (individual-based terms, market-based terms — pooling them let the
  store's real inventory effect loosen the cutoff for personalization
  terms, measured 10% vs 5% any-rejection under the null); one finding
  per (product, signal) or (product, signal pair) with a per-level
  breakdown; numeric signals reported at their observed extremes vs the
  reference. Flagged only if significant AND ≥ 3%.
- `audit_engine/engine.py` — the original threshold engine (worst-case
  per-variant mean delta). Kept as the legible baseline; `/audit`
  defaults to it.
- `audit_engine/report.py` — JSON + HTML. Handles both engines:
  `methodology_note`, `probe`, `diagnostics` kwargs; interaction cards;
  CI + corrected p line; ✓ on FDR-significant levels.
- `probing/factorial.py` — `FactorialProber` over a `PricingTarget`
  (`probing/targets.py`): `full` design (Cartesian product × replicates,
  shuffled) or `random` (n_sessions). Thread-pool `concurrency`.
  Failures recorded as `ProbeFailure`, never fabricated.
- `probing/ghostcart.py` — `GhostCartTarget`: httpx client for
  `POST /api/persona-price`, secret header, retries on 5xx, explains
  the empty-404 gating failure. Signal space = the contract's (device
  desktop/mobile/tablet, cart_abandonment bool, referrer
  direct/search/social/email, inventory grid 1…100, reference 50).
  Static product table as fallback for `GET`.
- `probing/targets.py` — `DemoStoreTarget` adapts the in-process demo
  store (string-valued signals, `SIGNAL_VARIANTS` control first).
- `probing/prober.py` — the original one-at-a-time prober (demo store).
- `api/main.py` — `GET /health /catalog /signals /rules /ghostcart`,
  `POST /audit` (`engine: threshold|regression`), `/audit/html`,
  `POST /audit/ghostcart[/html]` (503 without the secret).
- `scripts/audit_ghostcart.py` — CLI: live probe → `reports/ghostcart-latest.{json,html}`.
- `scripts/export_summary.py` — condenses a report to one row per term;
  its output is committed in the GhostCart repo as `src/lib/audit-result.json`
  and rendered by GhostCart's `/audit` page. **Re-run + copy after any
  audit that changes the numbers.**
- Report payload additions 2026-09-15: `variant_ci` (95% CI per level) on
  every finding; `control_price` (median observed price at the reference
  cell, else exp(intercept)) in diagnostics. The frontend's charts depend on both.
- `settings.py` — loads `.env` from project root; `ghostcart_secret()`.
- `tests/test_rigorous.py` (43) — GhostCart rule recovery (exact
  transcription of the contract's rule function), decoy clean in every
  combination, confound test, BH textbook cases, Huber vs OLS on
  outliers, Monte Carlo FDR (300 null audits, ≤ 30 may reject any
  individual term; ≤ 5 may produce a finding), power. `tests/test_factorial.py`
  (19) — `FakeGhostCart` httpx.MockTransport implementing the contract
  verbatim; full pipeline HTTP → report. `tests/test_api.py` (+5).
- `.gitignore` (root), `.env.example`, `LICENSE` (MIT),
  `docs/methodology.md`. Git repo initialised (`main`), no remote yet.
  `.env` holds the (rotated) probe secret. `reports/ghostcart-latest.{json,html}`
  is the first real audit (committed; timestamped copies are ignored).

`frontend/` — Next 14.2.5 + Tailwind 3 + lucide-react (GhostCart's stack),
`npm run dev` / `npm run build` (both run `scripts/sync-data.mjs` first,
which copies `reports/ghostcart-latest.json` and `docs/methodology.md`
into `src/data/`; the copies are committed so a Vercel build rooted at
`frontend/` works). Routes: `/` landing (numbers come from the committed
report via `distinctTerms`), `/report` (`ReportClient` shows the committed
report and can POST `/audit/ghostcart` on the backend for a live re-run —
verified working in the browser, 12 s), `/methodology` (react-markdown of
the doc). Findings are grouped per term (`TermGroup`) with a per-product
table. "At a glance" on `/report`: `EffectLadder` (SVG forest plot of every
level, hue = category, severity bands, hover tooltip; palette validated
with the dataviz skill: individual #B42318, market #12907A, clean grey)
and `ShopperMatrix` (device × cart price grid reconstructed from the
report's estimates + control price, with product / referrer-decoy /
stock-level controls; reproduces GhostCart's real prices to the cent). Env: `NEXT_PUBLIC_API_URL` (default localhost:8000),
`NEXT_PUBLIC_GHOSTCART_URL`, `NEXT_PUBLIC_REPO_URL` (`frontend/.env.example`).
Backend needs `CORS_ORIGINS` set to the frontend origin. Dev servers:
`AI Port 1/.claude/launch.json` (`pi-frontend`; `pi-backend` config exists
but the sandbox refuses to exec the venv binary — start uvicorn from Bash).
- **Secret (rotated 2026-09-15):** `PERSONA_PRICING_SECRET` is a Vercel
  *Sensitive* var, so `vercel env pull` returns `[SENSITIVE]`. The value
  was rotated; the new one is in `price-integrity/.env` and on Vercel
  production (deployment `bj66t8rdd`). If it's ever lost, rotate again:
  Claude Code can `vercel env rm` but the harness blocks `vercel env add`
  and `vercel redeploy` — Julian runs those two in his terminal
  (`redeploy` takes no `--yes`; "Error: fetch failed" after the URL is
  printed is just polling — check `vercel ls --prod`).

Spec files (in `~/Downloads`, not in the repo): `PriceIntegrity.md`,
`PriceAudit.md`, `GHOSTCART_PHASE0_CLAUDE.md`, and the recovered
`audit_engine_v2_rigorous.py` / `audit_engine_sketch.py`.

## The gap — resolved 2026-09-15

`audit_engine_v2_rigorous.py` turned up in `~/Downloads` and was ported
(option 3). Its `__main__` demo used exactly GhostCart's 4-signal set,
which is where the "validated 4-signal set" claim came from. No
`prober_sketch.py` was found; the factorial prober was written fresh.

Deviations from the original file, all deliberate:
- log(price) instead of price (multiplicative rules → exact % effects,
  base-price-independent; the original divided by median price).
- Huber asymptotic SEs with small-sample correction (the original used
  weighted residual variance; CI coverage was 87% vs 93–95% now).
- BH in two families (see above). The original pooled everything.
- Findings roll up per signal with a level breakdown rather than one per
  dummy, so `report.py` didn't need a rewrite.
- Practical-significance floor: significant-but-<3% individual effects
  are reported clean, not LOW.

GhostCart's `/audit` page promise (regression + multiple-comparison
correction) is now backed by code and tests.

## Build phases (from the spec, annotated)

- [x] **Phase 0 (GhostCart repo)** — persona-pricing endpoint. Live.
- [x] **Phase 1 — Probing engine.** Factorial HTTP prober + GhostCart client.
- [x] **Phase 2 — Rigorous audit engine.** Ported + tested.
- [x] **Phase 3 — Report generator.** Interactions, CIs, corrected p.
- [x] **First live run (2026-09-15).** 10 products × 192 sessions,
      1,920 requests, 0 failures, 13 s at concurrency 8. Result matched
      the contract on every product: mobile +10.00% MODERATE,
      abandonment +6.00% LOW, mobile × abandonment +8.00% MODERATE
      interaction, inventory lawful (+10.3% at stock 1 / −9.5% at 100),
      referrer and both referrer interactions clean. CIs ±0.18pp,
      q = 0. Re-run: `backend/.venv/bin/python scripts/audit_ghostcart.py`.
- [x] **Phase 4 — Frontend.** Built 2026-09-15, incl. the two
      visualizations. **GhostCart side done too** (commit `aa5fb89` in
      `~/Downloads/ghostcart`, not yet pushed/deployed): `/audit` renders
      the real result from `src/lib/audit-result.json`; links to
      `$NEXT_PUBLIC_PRICEINTEGRITY_URL/report` once that env var is set.
      **Portfolio card added** (commit `2a42096` in `AI Port 2/portfolio`,
      not pushed): status "In Progress", repo link only — add `url` and a
      `/projects/priceintegrity.jpg` screenshot after deploy.
- [x] **Phase 5 — Packaging.** LICENSE, `docs/methodology.md`, `git init`.
- [ ] **Phase 6 — Publish.** [x] github.com/Jthomas244/price-integrity
      created and pushed 2026-09-15. [x] `backend/Dockerfile` +
      `render.yaml` added (Docker daemon wasn't running, so the image is
      untested locally — first Render build will tell). Remaining, all
      Julian's (deploys are blocked for Claude Code): deploy backend
      (Render blueprint; set `GHOSTCART_PROBE_SECRET`, fix `CORS_ORIGINS`
      to the real frontend origin), deploy frontend (Vercel, root
      `frontend`, `NEXT_PUBLIC_API_URL`), push GhostCart + set
      `NEXT_PUBLIC_PRICEINTEGRITY_URL`, then finish the card on
      julianthomas.dev
      (`AI Port 2/portfolio/src/data/projects.ts`, same pattern as the
      VaultAP and GhostCart cards).

## Conventions

- **Git identity:** commits must be authored as `talon244@gmail.com` (now
  set in `git config --global`). Vercel blocks any deployment whose commit
  author isn't on the account — the 2026-09-15 GhostCart deploys stalled
  as "blocked" because commits carried `julian@Mac.fios-router.home`.
  Commits before `c4c68c7` (GhostCart) / this one (here) still have the
  bad author; harmless unless rewritten, which Julian can do with
  `git filter-branch --env-filter` + force-push if he wants a clean log.

- Run tests from `backend/`: `.venv/bin/pytest -q`. Keep them green;
  add tests for every rule direction and every statistical claim
  (mirror how GhostCart's `personaPricing.test.ts` proves the decoy has
  zero effect across all combinations).
- Stats deps: numpy and scipy only (pandas allowed by the spec but not
  needed; no statsmodels).
- Code was written 3.9-compatible; that constraint is gone (3.14 venv).
- Deployment target when ready: Vercel (frontend) + Render/Fly (backend),
  matching the rest of the portfolio.
- Related memory: `[[ghostcart-project]]`, `[[price-integrity-project]]`
  in Claude's memory dir for cross-session context.

## Open decisions (Julian, not Claude Code)

- Final project name.
- Whether pluggable adapters for other sites (under explicit permission)
  are ever in scope — not v1.
