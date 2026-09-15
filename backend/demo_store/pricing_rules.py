"""Pricing engine for the demo storefront.

Each rule reacts to exactly one signal from the audit taxonomy and
returns a price multiplier (1.0 == no change). Rules are tagged with the
SignalType they respond to so the demo is self-documenting — but the
audit engine never sees these tags; it has to infer the behaviour from
observed prices alone, exactly as it would against a black-box retailer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Callable, FrozenSet, List, Optional, Sequence

from audit_engine.models import SignalType

from .catalog import CATALOG, Product, get_product


@dataclass(frozen=True)
class SessionContext:
    """Everything the storefront knows about one shopping session.

    Defaults describe the neutral "control" session the prober compares
    every variant against.
    """

    # Market-based signals
    inventory_level: Optional[int] = None   # None -> use the product's default stock
    hour: int = 12                          # 0-23, local store time
    day_of_week: str = "wednesday"
    season: str = "off_peak"                # off_peak | holiday | clearance

    # Individual-based signals
    device_type: str = "desktop"            # desktop | mobile | tablet
    operating_system: str = "windows"       # windows | macos | linux | android | ios
    geolocation: str = "OH"                 # US state code
    ip_isp: str = "residential_cable"       # residential_cable | residential_fiber | mobile_carrier | datacenter
    browsing_history: str = "none"          # none | viewed_once | viewed_3x
    cart_abandonment: str = "none"          # none | abandoned_24h | abandoned_7d
    referrer_source: str = "direct"         # direct | search | social | coupon_site
    logged_in_state: str = "guest"          # guest | logged_in
    account_tenure: str = "none"            # none | new | established

    def with_signal(self, signal_type: SignalType, raw_value: str) -> "SessionContext":
        """Return a copy with exactly one signal changed. Used by the prober."""
        field_name = SIGNAL_FIELDS[signal_type]
        value = _coerce(field_name, raw_value)
        return replace(self, **{field_name: value})


# Which SessionContext field each taxonomy signal maps onto.
SIGNAL_FIELDS = {
    SignalType.INVENTORY_LEVEL: "inventory_level",
    SignalType.TIME_OF_DAY: "hour",
    SignalType.DAY_OF_WEEK: "day_of_week",
    SignalType.SEASONAL_DEMAND: "season",
    SignalType.DEVICE_TYPE: "device_type",
    SignalType.OPERATING_SYSTEM: "operating_system",
    SignalType.GEOLOCATION: "geolocation",
    SignalType.IP_ISP: "ip_isp",
    SignalType.BROWSING_HISTORY: "browsing_history",
    SignalType.CART_ABANDONMENT: "cart_abandonment",
    SignalType.REFERRER_SOURCE: "referrer_source",
    SignalType.LOGGED_IN_STATE: "logged_in_state",
    SignalType.ACCOUNT_TENURE: "account_tenure",
}
assert set(SIGNAL_FIELDS) == set(SignalType)

_INT_FIELDS = {"inventory_level", "hour"}


def _coerce(field_name: str, raw_value: str):
    return int(raw_value) if field_name in _INT_FIELDS else raw_value


# --- Rules ------------------------------------------------------------------

Condition = Callable[[Product, SessionContext], float]


@dataclass(frozen=True)
class PricingRule:
    name: str
    signal: SignalType
    multiplier_for: Condition
    description: str
    product_ids: Optional[FrozenSet[str]] = None   # None -> applies to every product

    def applies_to(self, product: Product) -> bool:
        return self.product_ids is None or product.product_id in self.product_ids

    @property
    def category(self) -> str:
        return self.signal.category.value


def _low_stock(product: Product, ctx: SessionContext) -> float:
    stock = product.inventory if ctx.inventory_level is None else ctx.inventory_level
    if stock <= 5:
        return 1.20
    if stock <= 15:
        return 1.10
    return 1.0


def _off_peak_hours(product: Product, ctx: SessionContext) -> float:
    return 0.95 if 0 <= ctx.hour <= 5 else 1.0


def _weekend_demand(product: Product, ctx: SessionContext) -> float:
    return 1.04 if ctx.day_of_week in ("saturday", "sunday") else 1.0


def _seasonal(product: Product, ctx: SessionContext) -> float:
    return {"holiday": 1.08, "clearance": 0.85}.get(ctx.season, 1.0)


def _mobile_markup(product: Product, ctx: SessionContext) -> float:
    return 1.09 if ctx.device_type == "mobile" else 1.0


def _apple_markup(product: Product, ctx: SessionContext) -> float:
    return 1.05 if ctx.operating_system in ("macos", "ios") else 1.0


def _regional_markup(product: Product, ctx: SessionContext) -> float:
    return 1.12 if ctx.geolocation in ("NY", "CA", "MA") else 1.0


def _cart_winback(product: Product, ctx: SessionContext) -> float:
    return 0.82 if ctx.cart_abandonment == "abandoned_24h" else 1.0


def _repeat_visitor(product: Product, ctx: SessionContext) -> float:
    return 1.04 if ctx.browsing_history == "viewed_3x" else 1.0


def _coupon_referrer(product: Product, ctx: SessionContext) -> float:
    return 0.90 if ctx.referrer_source == "coupon_site" else 1.0


DEFAULT_RULES: List[PricingRule] = [
    # -- market-based (lawful dynamic pricing) --
    PricingRule(
        "low_stock_markup", SignalType.INVENTORY_LEVEL, _low_stock,
        "+10% when stock <= 15 units, +20% when stock <= 5.",
    ),
    PricingRule(
        "off_peak_hours_discount", SignalType.TIME_OF_DAY, _off_peak_hours,
        "-5% between midnight and 6am.",
    ),
    PricingRule(
        "weekend_demand", SignalType.DAY_OF_WEEK, _weekend_demand,
        "+4% on Saturdays and Sundays.",
    ),
    PricingRule(
        "seasonal_demand", SignalType.SEASONAL_DEMAND, _seasonal,
        "+8% in the holiday season, -15% during clearance.",
    ),
    # -- individual-based (personalized / surveillance pricing) --
    PricingRule(
        "mobile_device_markup", SignalType.DEVICE_TYPE, _mobile_markup,
        "+9% for mobile sessions on headphones and running shoes.",
        product_ids=frozenset({"SKU-1001", "SKU-3003"}),
    ),
    PricingRule(
        "apple_os_markup", SignalType.OPERATING_SYSTEM, _apple_markup,
        "+5% for macOS / iOS sessions.",
    ),
    PricingRule(
        "regional_markup", SignalType.GEOLOCATION, _regional_markup,
        "+12% for shoppers geolocated in NY, CA or MA.",
    ),
    PricingRule(
        "cart_abandonment_winback", SignalType.CART_ABANDONMENT, _cart_winback,
        "-18% for shoppers who abandoned a cart in the last 24h.",
    ),
    PricingRule(
        "repeat_visitor_markup", SignalType.BROWSING_HISTORY, _repeat_visitor,
        "+4% once a shopper has viewed the product three or more times.",
        product_ids=frozenset({"SKU-2002", "SKU-4004"}),
    ),
    PricingRule(
        "coupon_site_referrer_discount", SignalType.REFERRER_SOURCE, _coupon_referrer,
        "-10% for sessions arriving from coupon aggregators.",
    ),
    # Deliberately NO rules for ip_isp, logged_in_state or account_tenure —
    # the audit should report those signals as clean.
]


@dataclass
class Quote:
    product_id: str
    price: float
    base_price: float
    applied_rules: List[str] = field(default_factory=list)


class DemoStore:
    """The storefront the prober runs sessions against.

    ``noise_pct`` adds small, seeded per-quote jitter (e.g. 0.005 == ±0.5%)
    to simulate the rounding / A-B-test wobble a real pricing engine
    shows. It is what makes repeated sessions per variant meaningful and
    gives ``min_sample_size`` something to guard against.
    """

    def __init__(
        self,
        rules: Optional[Sequence[PricingRule]] = None,
        catalog: Optional[Sequence[Product]] = None,
        noise_pct: float = 0.0,
        seed: Optional[int] = 0,
    ) -> None:
        if noise_pct < 0:
            raise ValueError("noise_pct must be >= 0")
        self.rules: List[PricingRule] = list(DEFAULT_RULES if rules is None else rules)
        self.catalog: List[Product] = list(CATALOG if catalog is None else catalog)
        self._by_id = {p.product_id: p for p in self.catalog}
        self.noise_pct = noise_pct
        self._rng = random.Random(seed)

    def product(self, product_id: str) -> Product:
        if product_id in self._by_id:
            return self._by_id[product_id]
        return get_product(product_id)

    def quote(self, product_id: str, ctx: SessionContext) -> Quote:
        product = self.product(product_id)
        price = product.base_price
        applied: List[str] = []
        for rule in self.rules:
            if not rule.applies_to(product):
                continue
            m = rule.multiplier_for(product, ctx)
            if m != 1.0:
                price *= m
                applied.append(rule.name)
        if self.noise_pct:
            price *= 1 + self._rng.uniform(-self.noise_pct, self.noise_pct)
        return Quote(product_id, round(price, 2), product.base_price, applied)
