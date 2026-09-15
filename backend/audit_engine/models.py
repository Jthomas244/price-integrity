"""Core data types for the audit engine.

The signal taxonomy mirrors how the FTC and state surveillance-pricing
laws frame the problem:

  - "Dynamic" pricing responds to MARKET conditions (inventory,
    time-of-day, seasonal demand) — generally lawful, low disclosure risk.
  - "Personalized" / "surveillance" pricing responds to INDIVIDUAL
    characteristics (device, location, browsing/cart history,
    account tenure) — this is what draws regulatory scrutiny.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional


class SignalType(Enum):
    # Market-based signals — legitimate dynamic pricing
    INVENTORY_LEVEL = "inventory_level"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    SEASONAL_DEMAND = "seasonal_demand"

    # Individual-based signals — surveillance / personalized pricing risk
    DEVICE_TYPE = "device_type"
    OPERATING_SYSTEM = "operating_system"
    GEOLOCATION = "geolocation"
    IP_ISP = "ip_isp"
    BROWSING_HISTORY = "browsing_history"
    CART_ABANDONMENT = "cart_abandonment"
    REFERRER_SOURCE = "referrer_source"
    LOGGED_IN_STATE = "logged_in_state"
    ACCOUNT_TENURE = "account_tenure"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")

    @property
    def category(self) -> "Category":
        return Category.MARKET_BASED if self in MARKET_BASED_SIGNALS else Category.INDIVIDUAL_BASED


class Category(Enum):
    MARKET_BASED = "market_based"
    INDIVIDUAL_BASED = "individual_based"


MARKET_BASED_SIGNALS: FrozenSet[SignalType] = frozenset(
    {
        SignalType.INVENTORY_LEVEL,
        SignalType.TIME_OF_DAY,
        SignalType.DAY_OF_WEEK,
        SignalType.SEASONAL_DEMAND,
    }
)

INDIVIDUAL_BASED_SIGNALS: FrozenSet[SignalType] = frozenset(
    {
        SignalType.DEVICE_TYPE,
        SignalType.OPERATING_SYSTEM,
        SignalType.GEOLOCATION,
        SignalType.IP_ISP,
        SignalType.BROWSING_HISTORY,
        SignalType.CART_ABANDONMENT,
        SignalType.REFERRER_SOURCE,
        SignalType.LOGGED_IN_STATE,
        SignalType.ACCOUNT_TENURE,
    }
)

assert MARKET_BASED_SIGNALS | INDIVIDUAL_BASED_SIGNALS == frozenset(SignalType)
assert not (MARKET_BASED_SIGNALS & INDIVIDUAL_BASED_SIGNALS)


class RiskSeverity(Enum):
    NONE = "none"                 # no meaningful variance detected
    LAWFUL_DYNAMIC = "lawful"     # variance explained by market signals
    LOW = "low"                   # small individual-based variance
    MODERATE = "moderate"
    HIGH = "high"                 # large, consistent individual-based variance

    @property
    def rank(self) -> int:
        """Lower is more severe; used for sorting findings."""
        return _SEVERITY_RANK[self]

    @property
    def is_flagged(self) -> bool:
        return self in (RiskSeverity.LOW, RiskSeverity.MODERATE, RiskSeverity.HIGH)


_SEVERITY_RANK = {
    RiskSeverity.HIGH: 0,
    RiskSeverity.MODERATE: 1,
    RiskSeverity.LOW: 2,
    RiskSeverity.LAWFUL_DYNAMIC: 3,
    RiskSeverity.NONE: 4,
}


@dataclass(frozen=True)
class ProbeObservation:
    """One synthetic session result: a specific signal value and the
    price the demo storefront returned for a fixed product, compared
    against a neutral control session."""

    product_id: str
    signal_type: SignalType
    signal_value: str      # e.g. "mobile" / "desktop", "NY" / "CA"
    price: float
    control_price: float   # price under the neutral/baseline session
    timestamp: str

    @property
    def delta(self) -> float:
        """Signed fractional change vs. control (0.09 == 9% higher)."""
        return (self.price - self.control_price) / self.control_price


@dataclass
class AuditFinding:
    product_id: str
    signal_type: SignalType
    category: Category
    variance_pct: float            # worst-case |mean delta| across variants, in percent
    severity: RiskSeverity
    sample_size: int
    detail: str
    driving_variant: Optional[str] = None      # the signal value that produced variance_pct
    direction: Optional[str] = None            # "markup" | "discount" | None
    variant_breakdown: Dict[str, float] = field(default_factory=dict)  # value -> mean delta %

    # --- Populated only by the regression engine (audit_engine.rigorous) ---
    # "main_effect": one signal on its own. "interaction": the extra effect
    # of two individual-based signals occurring together, beyond the sum of
    # their main effects (compounding personalization).
    effect_type: str = "main_effect"
    # Every signal involved; for interactions this has two entries and
    # ``signal_type`` is the first of them.
    signals: List[SignalType] = field(default_factory=list)
    # 95% confidence interval for the driving effect, in percent.
    ci_low_pct: Optional[float] = None
    ci_high_pct: Optional[float] = None
    # Benjamini-Hochberg corrected p-value (q-value) for the driving effect.
    p_value_corrected: Optional[float] = None
    # Which levels survived FDR correction, e.g. ["mobile"]. Levels present
    # in ``variant_breakdown`` but absent here were tested and not
    # statistically distinguishable from the reference level.
    significant_variants: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.signals:
            self.signals = [self.signal_type]

    @property
    def is_interaction(self) -> bool:
        return self.effect_type == "interaction"

    @property
    def term(self) -> str:
        """Human label: "device type" or "device type × cart abandonment"."""
        return " × ".join(s.label for s in self.signals)

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "signal_type": self.signal_type.value,
            "signal_label": self.signal_type.label,
            "category": self.category.value,
            "variance_pct": self.variance_pct,
            "severity": self.severity.value,
            "sample_size": self.sample_size,
            "detail": self.detail,
            "driving_variant": self.driving_variant,
            "direction": self.direction,
            "variant_breakdown": dict(self.variant_breakdown),
            "effect_type": self.effect_type,
            "signals": [s.value for s in self.signals],
            "term": self.term,
            "ci_low_pct": self.ci_low_pct,
            "ci_high_pct": self.ci_high_pct,
            "p_value_corrected": self.p_value_corrected,
            "significant_variants": list(self.significant_variants),
        }


@dataclass(frozen=True)
class AuditConfig:
    """Severity thresholds — deliberately conservative starting points,
    meant to be tuned against real probe data."""

    low_threshold: float = 0.03        # 3%+  individual-based variance
    moderate_threshold: float = 0.08   # 8%+
    high_threshold: float = 0.15       # 15%+
    lawful_threshold: float = 0.01     # 1%+  market-based variance worth surfacing
    min_sample_size: int = 5           # don't flag on a single lucky/unlucky observation

    # Regression engine only (audit_engine.rigorous):
    alpha: float = 0.05                # significance level, applied AFTER FDR correction
    min_obs_per_param: int = 8         # sessions per regression parameter before a product is fit

    def __post_init__(self) -> None:
        if not (0 < self.low_threshold < self.moderate_threshold < self.high_threshold):
            raise ValueError("thresholds must satisfy 0 < low < moderate < high")
        if self.min_sample_size < 1:
            raise ValueError("min_sample_size must be >= 1")
        if not (0 < self.alpha < 1):
            raise ValueError("alpha must be in (0, 1)")
        if self.min_obs_per_param < 1:
            raise ValueError("min_obs_per_param must be >= 1")
