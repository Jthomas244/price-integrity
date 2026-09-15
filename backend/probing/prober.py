"""Prober: runs synthetic sessions against the demo storefront.

For every product × signal × variant it builds a session that differs
from the neutral control session in exactly one signal, quotes both, and
records a ProbeObservation. Repeating each variant ``sessions_per_variant``
times gives the audit engine a sample size to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from audit_engine.models import ProbeObservation, SignalType
from demo_store import DemoStore, SessionContext

# The values the prober will try for each signal. The first entry of each
# list is the control value, so every dimension includes a "no change"
# variant the audit can sanity-check against.
SIGNAL_VARIANTS: Dict[SignalType, List[str]] = {
    # Inventory is special: the product's real stock level is prepended
    # as the control variant at probe time (see Prober._variants_for).
    SignalType.INVENTORY_LEVEL: ["50", "15", "5", "1"],
    SignalType.TIME_OF_DAY: ["12", "3", "9", "20"],
    SignalType.DAY_OF_WEEK: ["wednesday", "monday", "friday", "saturday", "sunday"],
    SignalType.SEASONAL_DEMAND: ["off_peak", "holiday", "clearance"],
    SignalType.DEVICE_TYPE: ["desktop", "mobile", "tablet"],
    SignalType.OPERATING_SYSTEM: ["windows", "macos", "linux", "android", "ios"],
    SignalType.GEOLOCATION: ["OH", "TX", "NY", "CA", "WA"],
    SignalType.IP_ISP: ["residential_cable", "residential_fiber", "mobile_carrier", "datacenter"],
    SignalType.BROWSING_HISTORY: ["none", "viewed_once", "viewed_3x"],
    SignalType.CART_ABANDONMENT: ["none", "abandoned_24h", "abandoned_7d"],
    SignalType.REFERRER_SOURCE: ["direct", "search", "social", "coupon_site"],
    SignalType.LOGGED_IN_STATE: ["guest", "logged_in"],
    SignalType.ACCOUNT_TENURE: ["none", "new", "established"],
}
assert set(SIGNAL_VARIANTS) == set(SignalType), "every signal needs probe variants"

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Wednesday 2026-09-09 — the control session's date. Chosen so that
# day_of_week variants can be expressed as real calendar dates.
_EPOCH = datetime(2026, 9, 9, tzinfo=timezone.utc)
assert _WEEKDAYS[_EPOCH.weekday()] == "wednesday"


@dataclass
class ProbeRun:
    observations: List[ProbeObservation] = field(default_factory=list)
    sessions_per_variant: int = 0
    products_probed: List[str] = field(default_factory=list)
    signals_probed: List[str] = field(default_factory=list)

    @property
    def session_count(self) -> int:
        return len(self.observations)


class Prober:
    def __init__(
        self,
        store: DemoStore,
        sessions_per_variant: int = 5,
        control: Optional[SessionContext] = None,
        variants: Optional[Dict[SignalType, Sequence[str]]] = None,
    ) -> None:
        if sessions_per_variant < 1:
            raise ValueError("sessions_per_variant must be >= 1")
        self.store = store
        self.sessions_per_variant = sessions_per_variant
        self.control = control or SessionContext()
        self.variants = {k: list(v) for k, v in (variants or SIGNAL_VARIANTS).items()}

    def run(
        self,
        product_ids: Optional[Iterable[str]] = None,
        signal_types: Optional[Iterable[SignalType]] = None,
    ) -> ProbeRun:
        products = list(product_ids) if product_ids is not None else [p.product_id for p in self.store.catalog]
        signals = list(signal_types) if signal_types is not None else list(self.variants)

        run = ProbeRun(
            sessions_per_variant=self.sessions_per_variant,
            products_probed=products,
            signals_probed=[s.value for s in signals],
        )
        for product_id in products:
            for signal in signals:
                for value in self._variants_for(product_id, signal):
                    ctx = self.control.with_signal(signal, value)
                    for i in range(self.sessions_per_variant):
                        # Quote the control alongside every probe so any
                        # per-quote noise is sampled fairly on both sides.
                        control_price = self.store.quote(product_id, self.control).price
                        price = self.store.quote(product_id, ctx).price
                        run.observations.append(
                            ProbeObservation(
                                product_id=product_id,
                                signal_type=signal,
                                signal_value=value,
                                price=price,
                                control_price=control_price,
                                timestamp=_timestamp_for(ctx, session_index=i),
                            )
                        )
        return run

    def _variants_for(self, product_id: str, signal: SignalType) -> List[str]:
        values = list(self.variants[signal])
        if signal is SignalType.INVENTORY_LEVEL and self.control.inventory_level is None:
            # The control session observes the product's real stock, so
            # make that the first (control) variant and avoid duplicates.
            stock = str(self.store.product(product_id).inventory)
            values = [stock] + [v for v in values if v != stock]
        return values


def _timestamp_for(ctx: SessionContext, session_index: int) -> str:
    """Synthesize an ISO timestamp consistent with the session's time signals."""
    day_offset = _WEEKDAYS.index(ctx.day_of_week) - _EPOCH.weekday()
    when = _EPOCH + timedelta(weeks=session_index, days=day_offset, hours=ctx.hour)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
