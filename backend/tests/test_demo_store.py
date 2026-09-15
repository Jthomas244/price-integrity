from audit_engine import SignalType
from demo_store import CATALOG, DEFAULT_RULES, DemoStore, SessionContext
from demo_store.pricing_rules import SIGNAL_FIELDS


def test_catalog_meets_v1_acceptance():
    assert len(CATALOG) >= 3
    assert len({p.product_id for p in CATALOG}) == len(CATALOG)


def test_rules_span_both_categories():
    cats = {r.category for r in DEFAULT_RULES}
    assert cats == {"market_based", "individual_based"}
    assert len(DEFAULT_RULES) >= 4


def test_control_session_gets_base_price_for_well_stocked_product():
    store = DemoStore()
    q = store.quote("SKU-1001", SessionContext())
    assert q.price == 54.99
    assert q.applied_rules == []


def test_control_session_reflects_real_stock_level():
    # SKU-4004 has 8 units in stock, so its control session is already in
    # low-stock territory — that's the storefront's genuine state.
    store = DemoStore()
    q = store.quote("SKU-4004", SessionContext())
    assert q.applied_rules == ["low_stock_markup"]
    assert q.price == round(229.00 * 1.10, 2)


def test_mobile_markup_is_product_scoped():
    store = DemoStore()
    mobile = SessionContext(device_type="mobile")
    assert store.quote("SKU-1001", mobile).price == round(54.99 * 1.09, 2)
    assert "mobile_device_markup" not in store.quote("SKU-2002", mobile).applied_rules


def test_rules_stack_multiplicatively():
    store = DemoStore()
    ctx = SessionContext(geolocation="NY", referrer_source="coupon_site")
    q = store.quote("SKU-3003", ctx)
    assert q.price == round(119.00 * 1.12 * 0.90, 2)
    assert q.applied_rules == ["regional_markup", "coupon_site_referrer_discount"]


def test_with_signal_changes_exactly_one_field():
    base = SessionContext()
    for signal, field_name in SIGNAL_FIELDS.items():
        raw = "7" if field_name in ("inventory_level", "hour") else "probe"
        changed = base.with_signal(signal, raw)
        diff = {k for k in base.__dict__ if getattr(base, k) != getattr(changed, k)}
        assert diff == {field_name}


def test_every_signal_maps_to_a_session_field():
    assert set(SIGNAL_FIELDS) == set(SignalType)


def test_noise_is_seeded_and_bounded():
    a = DemoStore(noise_pct=0.01, seed=7)
    b = DemoStore(noise_pct=0.01, seed=7)
    ctx = SessionContext()
    prices_a = [a.quote("SKU-1001", ctx).price for _ in range(20)]
    prices_b = [b.quote("SKU-1001", ctx).price for _ in range(20)]
    assert prices_a == prices_b
    assert all(abs(p - 54.99) / 54.99 <= 0.0101 for p in prices_a)
    assert len(set(prices_a)) > 1


def test_unknown_product_raises():
    import pytest
    with pytest.raises(KeyError):
        DemoStore().quote("SKU-0000", SessionContext())
