import pytest

from audit_engine import (
    AuditConfig,
    AuditEngine,
    Category,
    ProbeObservation,
    RiskSeverity,
    SignalType,
)
from demo_store import DemoStore
from probing import Prober


def _obs(signal, value, price, control=100.0, product="SKU-T", n=5):
    return [
        ProbeObservation(product, signal, value, price, control, f"2026-09-{10 + i:02d}T10:00:00Z")
        for i in range(n)
    ]


def _audit(observations, config=None, include_clean=False):
    eng = AuditEngine(config)
    eng.add_observations(observations)
    return eng.run_audit(include_clean=include_clean)


@pytest.mark.parametrize(
    "price, expected",
    [
        (101.0, RiskSeverity.NONE),
        (103.0, RiskSeverity.LOW),
        (108.0, RiskSeverity.MODERATE),
        (115.0, RiskSeverity.HIGH),
        (85.0, RiskSeverity.HIGH),      # discounts are personalized pricing too
    ],
)
def test_individual_thresholds(price, expected):
    findings = _audit(_obs(SignalType.DEVICE_TYPE, "mobile", price), include_clean=True)
    assert len(findings) == 1
    assert findings[0].severity is expected
    assert findings[0].category is Category.INDIVIDUAL_BASED


def test_market_based_is_never_flagged():
    findings = _audit(_obs(SignalType.INVENTORY_LEVEL, "1", 140.0))
    assert findings[0].severity is RiskSeverity.LAWFUL_DYNAMIC
    assert findings[0].category is Category.MARKET_BASED
    assert not findings[0].severity.is_flagged


def test_market_based_below_lawful_threshold_is_none():
    findings = _audit(_obs(SignalType.TIME_OF_DAY, "3", 100.5), include_clean=True)
    assert findings[0].severity is RiskSeverity.NONE


def test_min_sample_size_guard():
    obs = _obs(SignalType.GEOLOCATION, "NY", 130.0, n=4)
    assert _audit(obs) == []
    assert len(_audit(obs, AuditConfig(min_sample_size=4))) == 1


def test_variance_is_worst_case_variant_not_diluted_average():
    obs = (
        _obs(SignalType.DEVICE_TYPE, "desktop", 100.0)
        + _obs(SignalType.DEVICE_TYPE, "tablet", 100.0)
        + _obs(SignalType.DEVICE_TYPE, "mobile", 109.0)
    )
    f = _audit(obs)[0]
    assert f.variance_pct == 9.0          # not (0 + 0 + 9) / 3
    assert f.severity is RiskSeverity.MODERATE
    assert f.driving_variant == "mobile"
    assert f.direction == "markup"
    assert f.variant_breakdown == {"desktop": 0.0, "mobile": 9.0, "tablet": 0.0}


def test_direction_discount():
    f = _audit(_obs(SignalType.CART_ABANDONMENT, "abandoned_24h", 82.0))[0]
    assert f.direction == "discount"
    assert "lower" in f.detail


def test_findings_sorted_most_severe_first():
    obs = (
        _obs(SignalType.OPERATING_SYSTEM, "macos", 104.0)
        + _obs(SignalType.INVENTORY_LEVEL, "1", 120.0)
        + _obs(SignalType.GEOLOCATION, "NY", 120.0)
        + _obs(SignalType.DEVICE_TYPE, "mobile", 109.0)
    )
    sev = [f.severity for f in _audit(obs)]
    assert sev == [RiskSeverity.HIGH, RiskSeverity.MODERATE, RiskSeverity.LOW, RiskSeverity.LAWFUL_DYNAMIC]


def test_groups_are_per_product():
    obs = _obs(SignalType.DEVICE_TYPE, "mobile", 109.0, product="A") + _obs(
        SignalType.DEVICE_TYPE, "mobile", 100.0, product="B"
    )
    findings = _audit(obs, include_clean=True)
    by_product = {f.product_id: f.severity for f in findings}
    assert by_product == {"A": RiskSeverity.MODERATE, "B": RiskSeverity.NONE}


def test_rejects_nonpositive_control_price():
    with pytest.raises(ValueError):
        AuditEngine().add_observation(
            ProbeObservation("X", SignalType.DEVICE_TYPE, "mobile", 10.0, 0.0, "t")
        )


def test_config_validation():
    with pytest.raises(ValueError):
        AuditConfig(low_threshold=0.1, moderate_threshold=0.05)
    with pytest.raises(ValueError):
        AuditConfig(min_sample_size=0)


def test_end_to_end_against_demo_store_matches_answer_key():
    """The audit, seeing only prices, must recover which signals the demo
    store's rules actually react to — and nothing else."""
    store = DemoStore(noise_pct=0.005, seed=42)
    run = Prober(store, sessions_per_variant=5).run()
    findings = _audit(run.observations)

    flagged = {f.signal_type for f in findings if f.severity.is_flagged}
    lawful = {f.signal_type for f in findings if f.severity is RiskSeverity.LAWFUL_DYNAMIC}

    individual_rules = {r.signal for r in store.rules if r.category == "individual_based"}
    market_rules = {r.signal for r in store.rules if r.category == "market_based"}

    assert flagged == individual_rules
    assert lawful == market_rules
    # Signals with no rule must not be flagged on noise alone.
    assert not flagged & {SignalType.IP_ISP, SignalType.LOGGED_IN_STATE, SignalType.ACCOUNT_TENURE}
