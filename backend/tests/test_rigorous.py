"""Tests for the regression audit engine.

Every statistical claim the project makes has a test here:
  - effects are recovered with the right magnitude and direction,
  - a decoy signal with no effect stays clean in every combination,
  - interactions are detected and attributed to the right pair,
  - the Benjamini-Hochberg procedure is implemented correctly,
  - the Huber fit shrugs off outliers that would swing plain OLS,
  - the whole pipeline's false-discovery rate is checked by Monte Carlo.

``ghostcart_price`` below is a Python transcription of GhostCart's
``personaPrice`` rule function, straight from docs/ghostcart-persona-price-
contract.md, so the engine is graded against the exact target it will probe.
"""

from __future__ import annotations

from itertools import product as cartesian
from typing import Dict, List

import numpy as np
import pytest

from audit_engine import (
    AuditConfig,
    Category,
    RigorousAuditEngine,
    RiskSeverity,
    SessionObservation,
    SignalType,
    build_report,
    render_html,
)
from audit_engine.rigorous import benjamini_hochberg, fit_huber_regression

S = SignalType

# --- GhostCart's exact rule set (contract §"Rule set") -------------------

GHOSTCART_PRODUCTS = {"GC-0001": 89.99, "GC-0009": 18.00, "GC-0010": 6800.00}
GHOSTCART_REFERENCE = {
    S.DEVICE_TYPE: "desktop",
    S.CART_ABANDONMENT: False,
    S.REFERRER_SOURCE: "direct",
    S.INVENTORY_LEVEL: 50,
}
DEVICES = ["mobile", "desktop", "tablet"]
REFERRERS = ["search", "direct", "social", "email"]
INVENTORIES = [1, 10, 25, 40, 50, 60, 80, 100]


def ghostcart_price(base: float, device: str, abandoned: bool, referrer: str, inventory: int) -> float:
    price = base
    if device == "mobile":
        price *= 1.10
    if abandoned:
        price *= 1.06
    if device == "mobile" and abandoned:
        price *= 1.08
    adj = max(-0.10, min(0.10, (50 - inventory) * 0.002))
    price *= 1 + adj
    return round(price, 2)


def ghostcart_sessions(products=GHOSTCART_PRODUCTS, noise_pct: float = 0.0, seed: int = 0) -> List[SessionObservation]:
    """Full factorial over the categorical signals × a grid of inventory
    levels: 3 × 2 × 4 × 8 = 192 sessions per product."""
    rng = np.random.default_rng(seed)
    out = []
    for pid, base in products.items():
        for device, abandoned, referrer, inv in cartesian(DEVICES, [True, False], REFERRERS, INVENTORIES):
            price = ghostcart_price(base, device, abandoned, referrer, inv)
            if noise_pct:
                price = round(price * (1 + rng.normal(0, noise_pct)), 2)
            out.append(SessionObservation(
                product_id=pid,
                price=price,
                signals={S.DEVICE_TYPE: device, S.CART_ABANDONMENT: abandoned,
                         S.REFERRER_SOURCE: referrer, S.INVENTORY_LEVEL: inv},
                timestamp="2026-09-15T00:00:00Z",
            ))
    return out


def run(observations, config=None, reference=GHOSTCART_REFERENCE, include_clean=True):
    engine = RigorousAuditEngine(config, reference_levels=reference)
    engine.add_observations(observations)
    return engine, engine.run_audit(include_clean=include_clean)


def by_term(findings) -> Dict[tuple, object]:
    return {(f.product_id, tuple(s.value for s in f.signals)): f for f in findings}


# --- Recovery of the GhostCart rule set ---------------------------------

class TestGhostCartRecovery:
    @pytest.fixture(scope="class")
    @staticmethod
    def findings():
        _, findings = run(ghostcart_sessions())
        return by_term(findings)

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_mobile_markup_is_ten_percent(self, findings, pid):
        f = findings[(pid, ("device_type",))]
        assert f.severity is RiskSeverity.MODERATE
        assert f.category is Category.INDIVIDUAL_BASED
        assert f.driving_variant == "device type = mobile"
        assert f.direction == "markup"
        assert f.variance_pct == pytest.approx(10.0, abs=0.05)
        assert f.variant_breakdown["device type = tablet"] == pytest.approx(0.0, abs=0.05)
        assert f.significant_variants == ["device type = mobile"]
        assert f.p_value_corrected < 0.001

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_abandonment_markup_is_six_percent(self, findings, pid):
        f = findings[(pid, ("cart_abandonment",))]
        assert f.severity is RiskSeverity.LOW
        assert f.variance_pct == pytest.approx(6.0, abs=0.05)
        assert f.direction == "markup"

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_mobile_x_abandonment_interaction_is_eight_percent(self, findings, pid):
        f = findings[(pid, ("cart_abandonment", "device_type"))]
        assert f.effect_type == "interaction"
        assert f.is_interaction
        assert f.severity is RiskSeverity.MODERATE
        assert f.category is Category.INDIVIDUAL_BASED
        assert f.variance_pct == pytest.approx(8.0, abs=0.05)
        assert f.significant_variants == ["cart abandonment = True × device type = mobile"]
        # tablet × abandonment is not a rule
        assert f.variant_breakdown["cart abandonment = True × device type = tablet"] == pytest.approx(0.0, abs=0.05)

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_inventory_is_lawful_dynamic(self, findings, pid):
        f = findings[(pid, ("inventory_level",))]
        assert f.severity is RiskSeverity.LAWFUL_DYNAMIC
        assert f.category is Category.MARKET_BASED
        # +0.2%/unit below 50, −0.2%/unit above (linear slope, capped at ±10%
        # in the real function so the extremes are approximate).
        assert f.variant_breakdown["inventory level = 1"] > 5
        assert f.variant_breakdown["inventory level = 100"] < -5

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_referrer_decoy_is_clean(self, findings, pid):
        f = findings[(pid, ("referrer_source",))]
        assert f.severity is RiskSeverity.NONE
        assert f.significant_variants == []
        assert f.driving_variant is None
        for level, pct in f.variant_breakdown.items():
            assert pct == pytest.approx(0.0, abs=0.05), level

    @pytest.mark.parametrize("pid", list(GHOSTCART_PRODUCTS))
    def test_referrer_decoy_interactions_are_clean(self, findings, pid):
        # Mirrors GhostCart's personaPricing.test.ts: the decoy has zero
        # effect in every combination of the other signals.
        for pair in (("cart_abandonment", "referrer_source"), ("device_type", "referrer_source")):
            f = findings[(pid, pair)]
            assert f.severity is RiskSeverity.NONE, pair
            assert f.significant_variants == []

    def test_effect_size_is_independent_of_base_price(self, findings):
        # log-price model: an $18 product and a $6,800 product report the
        # same ×1.10 rule as the same percentage.
        cheap = findings[("GC-0009", ("device_type",))].variance_pct
        dear = findings[("GC-0010", ("device_type",))].variance_pct
        assert cheap == pytest.approx(dear, abs=0.05)

    def test_confidence_intervals_bracket_the_estimate(self, findings):
        for f in findings.values():
            if f.severity is RiskSeverity.NONE:
                continue
            assert f.ci_low_pct <= f.variance_pct * (1 if f.direction == "markup" else -1) <= f.ci_high_pct

    def test_ordering_and_hidden_clean(self):
        _, findings = run(ghostcart_sessions(), include_clean=False)
        assert all(f.severity is not RiskSeverity.NONE for f in findings)
        ranks = [f.severity.rank for f in findings]
        assert ranks == sorted(ranks)

    def test_only_one_product_probed(self):
        _, findings = run(ghostcart_sessions({"GC-0001": 89.99}))
        assert {f.product_id for f in findings} == {"GC-0001"}


class TestNoisyRecovery:
    """The same rule set under ±1.5% per-quote jitter."""

    def test_effects_survive_noise_and_decoy_stays_clean(self):
        _, findings = run(ghostcart_sessions({"GC-0001": 89.99}, noise_pct=0.015, seed=7))
        f = by_term(findings)
        assert f[("GC-0001", ("device_type",))].severity is RiskSeverity.MODERATE
        assert f[("GC-0001", ("device_type",))].variance_pct == pytest.approx(10.0, abs=1.5)
        assert f[("GC-0001", ("cart_abandonment",))].severity is RiskSeverity.LOW
        assert f[("GC-0001", ("cart_abandonment",))].variance_pct == pytest.approx(6.0, abs=1.5)
        inter = f[("GC-0001", ("cart_abandonment", "device_type"))]
        # 8% sits on the LOW/MODERATE edge; under noise the band can go
        # either way but the estimate and its significance must not.
        assert inter.severity in (RiskSeverity.LOW, RiskSeverity.MODERATE)
        assert inter.variance_pct == pytest.approx(8.0, abs=2.0)
        assert inter.significant_variants == ["cart abandonment = True × device type = mobile"]
        assert f[("GC-0001", ("inventory_level",))].severity is RiskSeverity.LAWFUL_DYNAMIC
        assert f[("GC-0001", ("referrer_source",))].severity is RiskSeverity.NONE

    def test_confidence_interval_widens_with_noise(self):
        _, clean = run(ghostcart_sessions({"GC-0001": 89.99}))
        _, noisy = run(ghostcart_sessions({"GC-0001": 89.99}, noise_pct=0.015))
        width = lambda f: f.ci_high_pct - f.ci_low_pct
        c = by_term(clean)[("GC-0001", ("device_type",))]
        n = by_term(noisy)[("GC-0001", ("device_type",))]
        assert width(n) > width(c)


# --- Confound control ---------------------------------------------------

def test_confounded_design_is_still_attributed_correctly():
    """If the prober had (wrongly) let mobile sessions also tend to see low
    stock, a naive per-signal comparison would blame device for the
    inventory effect. The regression holds inventory constant."""
    rng = np.random.default_rng(3)
    obs = []
    for _ in range(400):
        device = rng.choice(["mobile", "desktop"])
        # correlated: mobile sessions mostly see low inventory
        inv = int(rng.integers(1, 30)) if device == "mobile" else int(rng.integers(40, 100))
        abandoned = bool(rng.integers(0, 2))
        price = ghostcart_price(89.99, device, abandoned, "direct", inv)
        price = round(price * (1 + rng.normal(0, 0.01)), 2)
        obs.append(SessionObservation("GC-0001", price, {
            S.DEVICE_TYPE: device, S.INVENTORY_LEVEL: inv, S.CART_ABANDONMENT: abandoned,
        }, "t"))
    _, findings = run(obs, reference={S.DEVICE_TYPE: "desktop", S.CART_ABANDONMENT: False, S.INVENTORY_LEVEL: 50})
    f = by_term(findings)
    assert f[("GC-0001", ("device_type",))].variance_pct == pytest.approx(10.0, abs=1.5)
    assert f[("GC-0001", ("inventory_level",))].severity is RiskSeverity.LAWFUL_DYNAMIC


# --- Sample-size guard --------------------------------------------------

def test_too_few_sessions_is_skipped_not_guessed():
    obs = ghostcart_sessions({"GC-0001": 89.99})[::5]  # 39 sessions; 19 parameters need 152
    engine, findings = run(obs)
    assert findings == []
    (diag,) = engine.diagnostics
    assert diag.fitted is False
    assert diag.n_parameters == 19
    assert "152" in diag.reason


def test_min_obs_per_param_is_configurable():
    obs = ghostcart_sessions({"GC-0001": 89.99})[::5]
    engine, findings = run(obs, config=AuditConfig(min_obs_per_param=2))
    assert engine.diagnostics[0].fitted is True
    assert findings


def test_missing_signal_in_some_sessions_is_an_error():
    obs = ghostcart_sessions({"GC-0001": 89.99})
    bad = SessionObservation("GC-0001", 90.0, {S.DEVICE_TYPE: "mobile"}, "t")
    engine = RigorousAuditEngine(reference_levels=GHOSTCART_REFERENCE)
    engine.add_observations(obs + [bad])
    with pytest.raises(ValueError, match="missing"):
        engine.run_audit()


def test_unknown_reference_level_is_an_error():
    obs = ghostcart_sessions({"GC-0001": 89.99})
    with pytest.raises(ValueError, match="never observed"):
        run(obs, reference={**GHOSTCART_REFERENCE, S.DEVICE_TYPE: "smart_fridge"})


def test_default_reference_levels():
    """Without explicit references: False for booleans, alphabetical first
    otherwise. 'desktop' < 'mobile' < 'tablet' and 'direct' < 'email' <
    'search' < 'social', so GhostCart's controls are the defaults anyway."""
    _, findings = run(ghostcart_sessions({"GC-0001": 89.99}), reference=None)
    f = by_term(findings)[("GC-0001", ("device_type",))]
    assert f.variance_pct == pytest.approx(10.0, abs=0.05)
    assert set(f.variant_breakdown) == {"device type = mobile", "device type = tablet"}


def test_session_observation_validation():
    with pytest.raises(ValueError):
        SessionObservation("x", 0.0, {S.DEVICE_TYPE: "mobile"}, "t")
    with pytest.raises(ValueError):
        SessionObservation("x", 10.0, {}, "t")


# --- Benjamini-Hochberg -------------------------------------------------

class TestBenjaminiHochberg:
    def test_textbook_example(self):
        # Benjamini & Hochberg (1995) style: with m=5 and alpha=0.05 the
        # thresholds are 0.01, 0.02, 0.03, 0.04, 0.05.
        p = [0.001, 0.015, 0.04, 0.2, 0.9]
        reject, q = benjamini_hochberg(p, 0.05)
        # 0.001<=0.01 yes, 0.015<=0.02 yes, 0.04<=0.03 no -> largest k=2
        assert reject.tolist() == [True, True, False, False, False]
        assert q.tolist() == pytest.approx([0.005, 0.0375, 0.0666667, 0.25, 0.9], rel=1e-6)

    def test_q_values_are_monotone_in_p(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(size=50)
        _, q = benjamini_hochberg(p, 0.05)
        order = np.argsort(p)
        assert np.all(np.diff(q[order]) >= -1e-12)
        assert np.all(q >= p - 1e-12)

    def test_nothing_rejected_when_all_large(self):
        reject, q = benjamini_hochberg([0.5, 0.6, 0.9], 0.05)
        assert not reject.any()
        assert np.all(q <= 1)

    def test_everything_rejected_when_all_tiny(self):
        reject, _ = benjamini_hochberg([1e-9] * 10, 0.05)
        assert reject.all()

    def test_empty(self):
        reject, q = benjamini_hochberg([], 0.05)
        assert len(reject) == 0 and len(q) == 0

    def test_step_up_rescues_a_borderline_p(self):
        # 0.03 alone would fail Bonferroni (0.05/3 = 0.0167) but BH's
        # step-up accepts it because 0.02 <= 2/3*0.05 = 0.0333 ... and
        # 0.03 <= 3/3*0.05 = 0.05, so all three are rejected.
        reject, _ = benjamini_hochberg([0.001, 0.02, 0.03], 0.05)
        assert reject.tolist() == [True, True, True]


# --- Huber robustness ---------------------------------------------------

def test_huber_resists_outliers_better_than_ols():
    rng = np.random.default_rng(11)
    n = 200
    x = rng.uniform(-1, 1, n)
    X = np.column_stack([np.ones(n), x])
    true_beta = np.array([1.0, 0.5])
    y = X @ true_beta + rng.normal(0, 0.05, n)
    y[:8] += 3.0  # a handful of glitchy probes

    ols = np.linalg.lstsq(X, y, rcond=None)[0]
    huber, se, dof = fit_huber_regression(X, y)
    assert dof == n - 2
    assert np.abs(huber - true_beta).max() < np.abs(ols - true_beta).max()
    assert np.abs(huber - true_beta).max() < 0.05
    assert np.all(se > 0)


def test_huber_matches_ols_on_clean_gaussian_data():
    rng = np.random.default_rng(5)
    n = 500
    X = np.column_stack([np.ones(n), rng.normal(size=n)])
    y = X @ np.array([2.0, -1.0]) + rng.normal(0, 0.1, n)
    ols = np.linalg.lstsq(X, y, rcond=None)[0]
    huber, _, _ = fit_huber_regression(X, y)
    assert huber == pytest.approx(ols, abs=0.01)


def test_outlier_probes_do_not_create_a_finding():
    """A few wildly wrong quotes on mobile sessions must not turn the
    decoy or an interaction into a finding, nor distort the mobile effect."""
    obs = ghostcart_sessions({"GC-0001": 89.99}, noise_pct=0.01, seed=2)
    rng = np.random.default_rng(9)
    corrupted = []
    for o in obs:
        price = o.price
        if o.signals[S.REFERRER_SOURCE] == "email" and rng.random() < 0.05:
            price = round(price * 1.5, 2)  # ~5% of email sessions glitch by +50%
        corrupted.append(SessionObservation(o.product_id, price, o.signals, o.timestamp))
    _, findings = run(corrupted)
    f = by_term(findings)
    assert f[("GC-0001", ("device_type",))].variance_pct == pytest.approx(10.0, abs=1.5)
    assert f[("GC-0001", ("referrer_source",))].severity is RiskSeverity.NONE


# --- Monte Carlo false-discovery check ----------------------------------

def _null_store_sessions(rng, n_sessions: int = 160) -> List[SessionObservation]:
    """A store with NO personalized pricing: only inventory and noise move
    the price. Every individual-based term is a true null."""
    obs = []
    for _ in range(n_sessions):
        device = rng.choice(DEVICES)
        abandoned = bool(rng.integers(0, 2))
        referrer = rng.choice(REFERRERS)
        inv = int(rng.integers(1, 101))
        price = 89.99 * (1 + max(-0.1, min(0.1, (50 - inv) * 0.002)))
        price = round(price * (1 + rng.normal(0, 0.01)), 2)
        obs.append(SessionObservation("GC-0001", price, {
            S.DEVICE_TYPE: device, S.CART_ABANDONMENT: abandoned,
            S.REFERRER_SOURCE: referrer, S.INVENTORY_LEVEL: inv,
        }, "t"))
    return obs


def test_monte_carlo_false_discovery_rate_is_controlled():
    """Under the null of "no personalized pricing" (only inventory and
    noise move the price), the chance that ANY individual-based term
    survives FDR correction must be at most alpha — under a global null
    the FDR bound is a family-wise bound. 300 simulated audits at
    alpha=0.05: expect ~15 such audits, sd ~3.8; 30 (about 4 sd) is the
    failure line. Separately, a reported *finding* also needs a ≥3%
    effect, so the rate of false personalized-pricing findings is far
    lower again.

    The individual-based terms are corrected as their own family: pooling
    them with the store's real inventory effect would make the BH step-up
    more lenient for the terms the audit actually makes claims about."""
    rng = np.random.default_rng(2026)
    sims = 300
    any_rejection = 0
    false_findings = 0
    for _ in range(sims):
        engine = RigorousAuditEngine(AuditConfig(min_obs_per_param=8), reference_levels=GHOSTCART_REFERENCE)
        engine.add_observations(_null_store_sessions(rng))
        findings = engine.run_audit(include_clean=True)
        individual = [f for f in findings if f.category is Category.INDIVIDUAL_BASED]
        if any(f.significant_variants for f in individual):
            any_rejection += 1
        if any(f.severity.is_flagged for f in individual):
            false_findings += 1
    assert any_rejection <= 30, f"{any_rejection}/{sims} null audits rejected an individual-based term"
    assert false_findings <= 5, f"{false_findings}/{sims} null audits produced a personalized-pricing finding"


def test_monte_carlo_power_on_real_effect():
    """The mirror image: with GhostCart's real rules and 1% noise, the
    mobile markup is found essentially every time."""
    rng = np.random.default_rng(99)
    hits = 0
    sims = 50
    for i in range(sims):
        obs = ghostcart_sessions({"GC-0001": 89.99}, noise_pct=0.01, seed=int(rng.integers(1 << 30)))
        _, findings = run(obs, include_clean=False)
        f = by_term(findings)
        if ("GC-0001", ("device_type",)) in f and f[("GC-0001", ("device_type",))].severity is RiskSeverity.MODERATE:
            hits += 1
    assert hits >= sims - 1


# --- Report integration -------------------------------------------------

def test_report_renders_regression_findings():
    _, findings = run(ghostcart_sessions({"GC-0001": 89.99}))
    report = build_report(findings, store_name="GhostCart", observation_count=192)
    assert report["summary"]["highest_severity"] == "moderate"
    payload = report["findings"][0]
    assert payload["p_value_corrected"] is not None
    assert payload["ci_low_pct"] <= payload["ci_high_pct"]
    assert any(f["effect_type"] == "interaction" for f in report["findings"])
    html = render_html(report)
    assert "cart abandonment" in html and "×" in html
