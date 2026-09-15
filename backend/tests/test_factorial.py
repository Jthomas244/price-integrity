"""Factorial prober + GhostCart HTTP target.

The GhostCart target is exercised against an httpx.MockTransport that
implements docs/ghostcart-persona-price-contract.md verbatim — gating,
validation, the rule set, rounding — so the whole pipeline (HTTP → prober
→ regression engine → report) is tested without touching the network.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Dict

import httpx
import pytest

from audit_engine import Category, RigorousAuditEngine, RiskSeverity, SignalType, build_report
from demo_store import DemoStore
from probing import (
    GHOSTCART_AUDIT_PRODUCTS,
    GHOSTCART_SIGNAL_SPACE,
    DemoStoreTarget,
    FactorialProber,
    GhostCartError,
    GhostCartTarget,
)
from probing.ghostcart import ENDPOINT, PROBE_HEADER

S = SignalType
SECRET = "test-secret"
BASES = {p["productId"]: p["basePrice"] for p in GHOSTCART_AUDIT_PRODUCTS}


# --- A faithful fake of the endpoint -------------------------------------

def persona_price(base: float, signals: dict) -> tuple[float, list]:
    price, rules = base, []
    if signals["device_type"] == "mobile":
        price *= 1.10
        rules.append("device_type:mobile")
    if signals["cart_abandonment"] is True:
        price *= 1.06
        rules.append("cart_abandonment:true")
    if signals["device_type"] == "mobile" and signals["cart_abandonment"] is True:
        price *= 1.08
        rules.append("device_type:mobile×cart_abandonment:true")
    adj = max(-0.10, min(0.10, (50 - signals["inventory_level"]) * 0.002))
    if adj:
        price *= 1 + adj
        rules.append("inventory_level")
    return round(price, 2), rules


class FakeGhostCart:
    def __init__(self, enabled: bool = True, secret: str = SECRET, flaky_every: int = 0):
        self.enabled, self.secret, self.flaky_every = enabled, secret, flaky_every
        self.calls = 0
        self.seen: list = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.url.path != ENDPOINT:
            return httpx.Response(404)
        if not self.enabled or request.headers.get(PROBE_HEADER) != self.secret:
            return httpx.Response(404)  # empty body, indistinguishable from a missing route
        if self.flaky_every and self.calls % self.flaky_every == 0:
            return httpx.Response(502, text="bad gateway")
        if request.method == "GET":
            return httpx.Response(200, json={"products": GHOSTCART_AUDIT_PRODUCTS})
        try:
            body = json.loads(request.content)
        except ValueError:
            return httpx.Response(400, json={"error": "body must be JSON"})
        pid = body.get("productId")
        if not pid:
            return httpx.Response(400, json={"error": "productId is required"})
        if pid not in BASES:
            return httpx.Response(404, json={"error": f"productId '{pid}' is not in the audit-enabled subset"})
        sig = body.get("signals") or {}
        problems = []
        if sig.get("device_type") not in ("mobile", "desktop", "tablet"):
            problems.append("device_type")
        if not isinstance(sig.get("cart_abandonment"), bool):
            problems.append("cart_abandonment")
        if sig.get("referrer_source") not in ("search", "direct", "social", "email"):
            problems.append("referrer_source")
        inv = sig.get("inventory_level")
        if not isinstance(inv, int) or isinstance(inv, bool) or not 0 <= inv <= 100000:
            problems.append("inventory_level")
        if problems:
            return httpx.Response(400, json={"error": "invalid signals", "details": problems})
        self.seen.append((pid, sig))
        price, rules = persona_price(BASES[pid], sig)
        return httpx.Response(200, json={"productId": pid, "basePrice": BASES[pid], "price": price, "appliedRules": rules},
                              headers={"Cache-Control": "no-store"})


def make_target(fake: FakeGhostCart, secret: str = SECRET, **kw) -> GhostCartTarget:
    client = httpx.Client(base_url="https://ghostcart.test", transport=httpx.MockTransport(fake.handler),
                          headers={PROBE_HEADER: secret})
    return GhostCartTarget(secret, base_url="https://ghostcart.test", client=client, **kw)


# --- GhostCartTarget -----------------------------------------------------

def test_quote_sends_contract_shape_and_returns_price():
    fake = FakeGhostCart()
    t = make_target(fake)
    price = t.quote("GC-0001", {S.DEVICE_TYPE: "mobile", S.CART_ABANDONMENT: True,
                                S.REFERRER_SOURCE: "search", S.INVENTORY_LEVEL: 22})
    assert price == pytest.approx(119.67)  # the contract's worked example
    (pid, sig), = fake.seen
    assert pid == "GC-0001"
    assert sig == {"device_type": "mobile", "cart_abandonment": True, "referrer_source": "search", "inventory_level": 22}


def test_quote_full_exposes_applied_rules_but_prober_never_uses_them():
    t = make_target(FakeGhostCart())
    data = t.quote_full("GC-0001", {S.DEVICE_TYPE: "mobile", S.CART_ABANDONMENT: True,
                                    S.REFERRER_SOURCE: "search", S.INVENTORY_LEVEL: 22})
    assert "device_type:mobile×cart_abandonment:true" in data["appliedRules"]


def test_gating_failure_is_explained():
    t = make_target(FakeGhostCart(), secret="wrong")
    with pytest.raises(GhostCartError, match="gating failed"):
        t.quote("GC-0001", {S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False,
                            S.REFERRER_SOURCE: "direct", S.INVENTORY_LEVEL: 50})


def test_disabled_endpoint_is_explained():
    t = make_target(FakeGhostCart(enabled=False))
    with pytest.raises(GhostCartError, match="PERSONA_PRICING_ENABLED"):
        t.quote("GC-0001", {S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False,
                            S.REFERRER_SOURCE: "direct", S.INVENTORY_LEVEL: 50})


def test_unknown_product_and_bad_signals_surface_the_error_body():
    t = make_target(FakeGhostCart())
    ok = {S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False, S.REFERRER_SOURCE: "direct", S.INVENTORY_LEVEL: 50}
    with pytest.raises(GhostCartError, match="not in the audit-enabled subset"):
        t.quote("GC-9999", ok)
    with pytest.raises(GhostCartError, match="invalid signals"):
        t.quote("GC-0001", {**ok, S.REFERRER_SOURCE: "coupon_site"})


def test_retries_on_5xx(monkeypatch):
    monkeypatch.setattr("probing.ghostcart.time.sleep", lambda s: None)
    fake = FakeGhostCart(flaky_every=2)  # every second call is a 502
    t = make_target(fake, retries=3)
    ok = {S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False, S.REFERRER_SOURCE: "direct", S.INVENTORY_LEVEL: 50}
    assert t.quote("GC-0001", ok) == pytest.approx(89.99)
    assert t.quote("GC-0001", ok) == pytest.approx(89.99)


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr("probing.ghostcart.time.sleep", lambda s: None)
    fake = FakeGhostCart(flaky_every=1)  # always 502
    t = make_target(fake, retries=2)
    with pytest.raises(GhostCartError, match="after 2 attempts"):
        t.quote("GC-0001", {S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False,
                            S.REFERRER_SOURCE: "direct", S.INVENTORY_LEVEL: 50})


def test_product_listing_and_static_fallback():
    assert make_target(FakeGhostCart()).product_ids() == [p["productId"] for p in GHOSTCART_AUDIT_PRODUCTS]
    # Gated off → listing 404s → fall back to the contract table rather than probing nothing.
    assert make_target(FakeGhostCart(enabled=False)).product_ids() == [p["productId"] for p in GHOSTCART_AUDIT_PRODUCTS]


def test_secret_is_required():
    with pytest.raises(ValueError, match="GHOSTCART_PROBE_SECRET"):
        GhostCartTarget("")


def test_signal_space_matches_contract():
    space = GhostCartTarget(SECRET).signal_space()
    assert space[S.DEVICE_TYPE] == ["desktop", "mobile", "tablet"]
    assert space[S.CART_ABANDONMENT] == [False, True]
    assert set(space[S.REFERRER_SOURCE]) == {"search", "direct", "social", "email"}
    assert all(isinstance(v, int) and 0 <= v <= 100000 for v in space[S.INVENTORY_LEVEL])


# --- FactorialProber -----------------------------------------------------

def test_full_design_is_balanced_and_shuffled():
    fake = FakeGhostCart()
    prober = FactorialProber(make_target(fake), design="full", seed=1)
    run = prober.run(product_ids=["GC-0001"])
    assert run.cells == 3 * 2 * 4 * 8
    assert run.session_count == 192 and not run.failures
    # every level of every signal appears equally often
    for sig, levels in GHOSTCART_SIGNAL_SPACE.items():
        counts = Counter(o.signals[sig] for o in run.observations)
        assert set(counts) == set(levels)
        assert len(set(counts.values())) == 1
    # every cell exactly once
    cells = Counter(tuple(sorted((s.value, str(v)) for s, v in o.signals.items())) for o in run.observations)
    assert set(cells.values()) == {1}
    # not in Cartesian-product order
    first_devices = [o.signals[S.DEVICE_TYPE] for o in run.observations[:20]]
    assert len(set(first_devices)) > 1


def test_replicates_multiply_the_design():
    run = FactorialProber(make_target(FakeGhostCart()), replicates=2).run(product_ids=["GC-0002"])
    assert run.sessions_per_product == 384 == run.session_count


def test_random_design_draws_each_signal_independently():
    t = DemoStoreTarget(DemoStore(seed=1), signals=[S.DEVICE_TYPE, S.GEOLOCATION])
    run = FactorialProber(t, design="random", n_sessions=300, seed=5).run(product_ids=["SKU-1001"])
    assert run.session_count == 300
    devices = Counter(o.signals[S.DEVICE_TYPE] for o in run.observations)
    assert set(devices) == {"desktop", "mobile", "tablet"}
    assert min(devices.values()) > 50  # roughly uniform


def test_random_design_requires_n_sessions():
    with pytest.raises(ValueError):
        FactorialProber(make_target(FakeGhostCart()), design="random")
    with pytest.raises(ValueError):
        FactorialProber(make_target(FakeGhostCart()), design="latin")


def test_same_seed_same_sessions():
    a = FactorialProber(make_target(FakeGhostCart()), seed=9).run(product_ids=["GC-0001"])
    b = FactorialProber(make_target(FakeGhostCart()), seed=9).run(product_ids=["GC-0001"])
    assert [o.signals for o in a.observations] == [o.signals for o in b.observations]


def test_failed_sessions_are_recorded_not_fabricated(monkeypatch):
    monkeypatch.setattr("probing.ghostcart.time.sleep", lambda s: None)
    fake = FakeGhostCart(flaky_every=1)
    run = FactorialProber(make_target(fake, retries=1)).run(product_ids=["GC-0001"])
    assert run.session_count == 0
    assert len(run.failures) == 192
    assert "after 1 attempts" in run.failures[0].error
    assert run.failures[0].signals.keys() == {"device_type", "cart_abandonment", "referrer_source", "inventory_level"}


def test_concurrent_run_matches_serial():
    serial = FactorialProber(make_target(FakeGhostCart()), seed=2, concurrency=1).run(product_ids=["GC-0003"])
    parallel = FactorialProber(make_target(FakeGhostCart()), seed=2, concurrency=8).run(product_ids=["GC-0003"])
    key = lambda o: (tuple(sorted((s.value, str(v)) for s, v in o.signals.items())), o.price)
    assert sorted(map(key, serial.observations)) == sorted(map(key, parallel.observations))


def test_run_metadata():
    run = FactorialProber(make_target(FakeGhostCart())).run(product_ids=["GC-0001", "GC-0002"])
    d = run.to_dict()
    assert d["target"] == "GhostCart" and d["design"] == "full"
    assert d["products_probed"] == ["GC-0001", "GC-0002"]
    assert d["signals_probed"] == ["cart_abandonment", "device_type", "inventory_level", "referrer_source"]
    assert d["reference_levels"] == {"device_type": "desktop", "cart_abandonment": False,
                                     "referrer_source": "direct", "inventory_level": 50}
    assert d["session_count"] == 384 and d["failure_count"] == 0
    assert d["started_at"] <= d["finished_at"]


# --- End to end: HTTP → prober → engine → report -------------------------

def test_full_pipeline_against_fake_ghostcart():
    fake = FakeGhostCart()
    target = make_target(fake)
    run = FactorialProber(target, concurrency=4).run()
    assert run.session_count == 10 * 192
    assert fake.calls >= run.session_count

    engine = RigorousAuditEngine(reference_levels=target.reference_levels())
    engine.add_observations(run.observations)
    findings = engine.run_audit(include_clean=True)

    by: Dict[tuple, object] = {(f.product_id, tuple(s.value for s in f.signals)): f for f in findings}
    for pid in BASES:
        assert by[(pid, ("device_type",))].variance_pct == pytest.approx(10.0, abs=0.05)
        assert by[(pid, ("cart_abandonment",))].variance_pct == pytest.approx(6.0, abs=0.05)
        assert by[(pid, ("cart_abandonment", "device_type"))].variance_pct == pytest.approx(8.0, abs=0.05)
        assert by[(pid, ("inventory_level",))].severity is RiskSeverity.LAWFUL_DYNAMIC
        assert by[(pid, ("referrer_source",))].severity is RiskSeverity.NONE

    report = build_report(findings, store_name=run.target, observation_count=run.session_count,
                          products=run.products_probed, signals_tested=[SignalType(s) for s in run.signals_probed])
    assert report["summary"]["highest_severity"] == "moderate"
    assert report["summary"]["clean_individual_signals"] == ["referrer_source"]
    assert report["summary"]["flagged_finding_count"] == 30  # 3 flagged terms × 10 products
    assert all(f["category"] == Category.INDIVIDUAL_BASED.value for f in report["findings"])
