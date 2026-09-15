from collections import Counter

from audit_engine import SignalType
from demo_store import DemoStore
from probing import SIGNAL_VARIANTS, Prober


def test_produces_observations_for_every_signal_type():
    run = Prober(DemoStore(), sessions_per_variant=2).run()
    seen = {o.signal_type for o in run.observations}
    assert seen == set(SignalType)


def test_observation_count_is_products_x_variants_x_sessions():
    store = DemoStore()
    n = 3
    run = Prober(store, sessions_per_variant=n).run()
    expected = 0
    for p in store.catalog:
        for signal, values in SIGNAL_VARIANTS.items():
            variants = list(values)
            if signal is SignalType.INVENTORY_LEVEL and str(p.inventory) not in variants:
                variants.append(str(p.inventory))
            expected += len(variants) * n
    assert run.session_count == expected


def test_control_variant_matches_control_price():
    run = Prober(DemoStore(), sessions_per_variant=1).run()
    for obs in run.observations:
        control_value = SIGNAL_VARIANTS[obs.signal_type][0]
        if obs.signal_type is SignalType.INVENTORY_LEVEL:
            continue  # control is the product's real stock, checked below
        if obs.signal_value == control_value:
            assert obs.price == obs.control_price, obs


def test_inventory_control_is_products_real_stock():
    store = DemoStore()
    run = Prober(store, sessions_per_variant=1).run(
        product_ids=["SKU-4004"], signal_types=[SignalType.INVENTORY_LEVEL]
    )
    stock = str(store.product("SKU-4004").inventory)
    control_obs = [o for o in run.observations if o.signal_value == stock]
    assert len(control_obs) == 1
    assert control_obs[0].price == control_obs[0].control_price


def test_subset_of_products_and_signals():
    run = Prober(DemoStore(), sessions_per_variant=1).run(
        product_ids=["SKU-1001"], signal_types=[SignalType.DEVICE_TYPE]
    )
    assert {o.product_id for o in run.observations} == {"SKU-1001"}
    assert {o.signal_type for o in run.observations} == {SignalType.DEVICE_TYPE}
    assert Counter(o.signal_value for o in run.observations) == {"desktop": 1, "mobile": 1, "tablet": 1}


def test_timestamps_reflect_time_signals():
    run = Prober(DemoStore(), sessions_per_variant=1).run(
        product_ids=["SKU-1001"], signal_types=[SignalType.TIME_OF_DAY, SignalType.DAY_OF_WEEK]
    )
    by = {(o.signal_type, o.signal_value): o.timestamp for o in run.observations}
    assert by[(SignalType.TIME_OF_DAY, "3")].endswith("T03:00:00Z")
    assert by[(SignalType.DAY_OF_WEEK, "saturday")].startswith("2026-09-12")
    assert by[(SignalType.DAY_OF_WEEK, "monday")].startswith("2026-09-07")


def test_rejects_zero_sessions():
    import pytest
    with pytest.raises(ValueError):
        Prober(DemoStore(), sessions_per_variant=0)
