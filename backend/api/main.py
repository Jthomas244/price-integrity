"""FastAPI app exposing the demo storefront and the audit pipeline.

    uvicorn api.main:app --reload          # from backend/

Endpoints
    GET  /health
    GET  /catalog        products in the demo store
    GET  /signals        the signal taxonomy (with which bucket each is in)
    GET  /rules          the demo store's pricing rules (the "answer key")
    POST /audit          run probe + audit against the demo store, return the JSON report
    POST /audit/html     same, rendered as a standalone HTML page
    GET  /ghostcart      whether the live GhostCart target is configured, and what it exposes
    POST /audit/ghostcart        probe live GhostCart (factorial design + regression engine)
    POST /audit/ghostcart/html   same, as HTML
"""

from __future__ import annotations

import os
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from audit_engine import (
    REGRESSION_METHODOLOGY_NOTE,
    AuditConfig,
    AuditEngine,
    RigorousAuditEngine,
    SignalType,
    build_report,
    render_html,
)
from demo_store import DemoStore
from probing import (
    GHOSTCART_REFERENCE_LEVELS,
    GHOSTCART_SIGNAL_SPACE,
    DemoStoreTarget,
    FactorialProber,
    GhostCartTarget,
    Prober,
    SIGNAL_VARIANTS,
)
from settings import ghostcart_base_url, ghostcart_secret

STORE_NAME = "PriceIntegrity demo storefront"

app = FastAPI(
    title="PriceIntegrity API",
    description=(
        "Audits a pricing engine to separate lawful market-based dynamic "
        "pricing from individual-based (personalized / surveillance) pricing. "
        "All probes run against a demo storefront this service fully controls."
    ),
    version="0.1.0",
)

# The Next.js frontend runs on a different origin. Override in deployment
# with a comma-separated CORS_ORIGINS env var.
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class AuditRequest(BaseModel):
    sessions_per_variant: int = Field(5, ge=1, le=50, description="Synthetic sessions per signal value")
    product_ids: Optional[List[str]] = Field(None, description="Subset of catalog product IDs; default all")
    signal_types: Optional[List[SignalType]] = Field(None, description="Subset of signals to probe; default all")
    seed: int = Field(42, description="Seed for the store's price jitter, for reproducible runs")
    noise_pct: float = Field(0.005, ge=0, le=0.05, description="Per-quote price jitter, e.g. 0.005 == ±0.5%")
    min_sample_size: int = Field(5, ge=1, description="Minimum observations before a signal is assessed")
    engine: Literal["threshold", "regression"] = Field(
        "threshold",
        description="threshold: one-signal-at-a-time probe + worst-case mean delta. "
                    "regression: randomized factorial probe + Huber regression with FDR correction.",
    )
    n_sessions: int = Field(1500, ge=50, le=20000, description="regression engine only: random-design sessions per product")
    alpha: float = Field(0.05, gt=0, lt=1, description="regression engine only: FDR level")


class GhostCartAuditRequest(BaseModel):
    product_ids: Optional[List[str]] = Field(None, description="Subset of GC- ids; default: everything the endpoint lists")
    replicates: int = Field(1, ge=1, le=3, description="Repeats of the 192-cell factorial per product")
    seed: int = Field(42, description="Session-order shuffle seed")
    concurrency: int = Field(8, ge=1, le=16)
    alpha: float = Field(0.05, gt=0, lt=1, description="FDR level")


def _validate(req: AuditRequest, known: set) -> None:
    if req.product_ids is not None:
        unknown = sorted(set(req.product_ids) - known)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown product_ids: {unknown}")
        if not req.product_ids:
            raise HTTPException(status_code=422, detail="product_ids must not be empty")
    if req.signal_types is not None and not req.signal_types:
        raise HTTPException(status_code=422, detail="signal_types must not be empty")


def _run_pipeline(req: AuditRequest) -> dict:
    store = DemoStore(noise_pct=req.noise_pct, seed=req.seed)
    _validate(req, {p.product_id for p in store.catalog})

    if req.engine == "regression":
        target = DemoStoreTarget(store, signals=req.signal_types)
        run = FactorialProber(target, design="random", n_sessions=req.n_sessions, seed=req.seed).run(req.product_ids)
        engine = RigorousAuditEngine(AuditConfig(alpha=req.alpha), reference_levels=target.reference_levels())
        engine.add_observations(run.observations)
        findings = engine.run_audit(include_clean=True)
        return build_report(
            findings,
            store_name=STORE_NAME,
            observation_count=run.session_count,
            products=run.products_probed,
            signals_tested=[SignalType(s) for s in run.signals_probed],
            methodology_note=REGRESSION_METHODOLOGY_NOTE,
            probe=run.to_dict(),
            diagnostics=engine.diagnostics,
        )

    probe = Prober(store, sessions_per_variant=req.sessions_per_variant).run(
        product_ids=req.product_ids, signal_types=req.signal_types
    )
    engine = AuditEngine(AuditConfig(min_sample_size=req.min_sample_size))
    engine.add_observations(probe.observations)
    findings = engine.run_audit(include_clean=True)
    return build_report(
        findings,
        store_name=STORE_NAME,
        sessions_per_variant=probe.sessions_per_variant,
        observation_count=probe.session_count,
        products=probe.products_probed,
        signals_tested=[SignalType(s) for s in probe.signals_probed],
    )


def _ghostcart_target() -> GhostCartTarget:
    secret = ghostcart_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="GhostCart target is not configured (GHOSTCART_PROBE_SECRET unset)")
    return GhostCartTarget(secret, base_url=ghostcart_base_url())


def _run_ghostcart(req: GhostCartAuditRequest) -> dict:
    target = _ghostcart_target()
    try:
        known = target.product_ids()
        if req.product_ids is not None:
            unknown = sorted(set(req.product_ids) - set(known))
            if unknown:
                raise HTTPException(status_code=422, detail=f"unknown product_ids: {unknown}")
            if not req.product_ids:
                raise HTTPException(status_code=422, detail="product_ids must not be empty")

        prober = FactorialProber(target, replicates=req.replicates, seed=req.seed, concurrency=req.concurrency)
        run = prober.run(req.product_ids)
    finally:
        target.close()

    if not run.observations:
        detail = run.failures[0].error if run.failures else "no sessions completed"
        raise HTTPException(status_code=502, detail=f"GhostCart probe failed: {detail}")

    engine = RigorousAuditEngine(AuditConfig(alpha=req.alpha), reference_levels=target.reference_levels())
    engine.add_observations(run.observations)
    findings = engine.run_audit(include_clean=True)
    return build_report(
        findings,
        store_name=f"GhostCart ({target.base_url})",
        observation_count=run.session_count,
        products=run.products_probed,
        signals_tested=[SignalType(s) for s in run.signals_probed],
        methodology_note=REGRESSION_METHODOLOGY_NOTE,
        probe=run.to_dict(),
        diagnostics=engine.diagnostics,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/catalog")
def catalog() -> dict:
    store = DemoStore()
    return {"store": STORE_NAME, "products": [p.to_dict() for p in store.catalog]}


@app.get("/signals")
def signals() -> dict:
    return {
        "signals": [
            {
                "signal_type": s.value,
                "label": s.label,
                "category": s.category.value,
                "probe_variants": SIGNAL_VARIANTS[s],
            }
            for s in SignalType
        ]
    }


@app.get("/rules")
def rules() -> dict:
    """The demo store's actual pricing rules — the answer key the audit is
    graded against. A real audit target would never expose this."""
    store = DemoStore()
    return {
        "rules": [
            {
                "name": r.name,
                "signal_type": r.signal.value,
                "category": r.category,
                "description": r.description,
                "product_ids": sorted(r.product_ids) if r.product_ids else None,
            }
            for r in store.rules
        ]
    }


@app.post("/audit")
def audit(req: AuditRequest) -> dict:
    return _run_pipeline(req)


@app.post("/audit/html", response_class=HTMLResponse)
def audit_html(req: AuditRequest) -> str:
    return render_html(_run_pipeline(req))


@app.get("/ghostcart")
def ghostcart_info() -> dict:
    """Is the live target wired up, and what does the audit vary?"""
    return {
        "configured": ghostcart_secret() is not None,
        "base_url": ghostcart_base_url(),
        "signal_space": {s.value: v for s, v in GHOSTCART_SIGNAL_SPACE.items()},
        "reference_levels": {s.value: v for s, v in GHOSTCART_REFERENCE_LEVELS.items()},
        "cells_per_product": 3 * 2 * 4 * 8,
    }


@app.post("/audit/ghostcart")
def audit_ghostcart(req: GhostCartAuditRequest) -> dict:
    return _run_ghostcart(req)


@app.post("/audit/ghostcart/html", response_class=HTMLResponse)
def audit_ghostcart_html(req: GhostCartAuditRequest) -> str:
    return render_html(_run_ghostcart(req))
