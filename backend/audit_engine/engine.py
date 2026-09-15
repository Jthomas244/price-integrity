"""AuditEngine: turns ProbeObservations into AuditFindings.

Given price observations collected across many synthetic sessions (each
varying one signal at a time against a controlled demo storefront),
figure out which signals are actually moving the price, and classify
each into the market-based or individual-based bucket.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Dict, Iterable, List, Optional, Tuple

from .models import (
    AuditConfig,
    AuditFinding,
    Category,
    ProbeObservation,
    RiskSeverity,
    SignalType,
)


class AuditEngine:
    def __init__(self, config: Optional[AuditConfig] = None) -> None:
        self.config = config or AuditConfig()
        self._observations: List[ProbeObservation] = []

    # -- ingestion -------------------------------------------------------

    def add_observation(self, obs: ProbeObservation) -> None:
        if obs.control_price <= 0:
            raise ValueError(f"control_price must be positive, got {obs.control_price!r}")
        self._observations.append(obs)

    def add_observations(self, observations: Iterable[ProbeObservation]) -> None:
        for obs in observations:
            self.add_observation(obs)

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    # -- analysis --------------------------------------------------------

    def _group_by_signal(self) -> Dict[Tuple[str, SignalType], List[ProbeObservation]]:
        groups: Dict[Tuple[str, SignalType], List[ProbeObservation]] = defaultdict(list)
        for obs in self._observations:
            groups[(obs.product_id, obs.signal_type)].append(obs)
        return dict(groups)

    @staticmethod
    def _variant_means(obs_list: List[ProbeObservation]) -> Dict[str, float]:
        """Mean signed delta per signal value, e.g. {"mobile": 0.09, "desktop": 0.0}."""
        by_value: Dict[str, List[float]] = defaultdict(list)
        for obs in obs_list:
            by_value[obs.signal_value].append(obs.delta)
        return {value: mean(deltas) for value, deltas in by_value.items()}

    def _classify_severity(self, category: Category, variance: float) -> RiskSeverity:
        cfg = self.config
        if category is Category.MARKET_BASED:
            # Market-based variance is expected and lawful. We still
            # surface it for visibility, but never flag it as risk.
            return RiskSeverity.LAWFUL_DYNAMIC if variance >= cfg.lawful_threshold else RiskSeverity.NONE

        if variance >= cfg.high_threshold:
            return RiskSeverity.HIGH
        if variance >= cfg.moderate_threshold:
            return RiskSeverity.MODERATE
        if variance >= cfg.low_threshold:
            return RiskSeverity.LOW
        return RiskSeverity.NONE

    def run_audit(self, include_clean: bool = False) -> List[AuditFinding]:
        """Analyse every (product, signal) group with enough samples.

        By default only findings with detectable variance are returned
        (flagged individual-based ones plus lawful market-based ones).
        Pass ``include_clean=True`` to also get NONE-severity findings, so
        a report can say "we tested this signal and found nothing".
        Groups below ``min_sample_size`` are always skipped.
        """
        findings: List[AuditFinding] = []

        for (product_id, signal_type), obs_list in self._group_by_signal().items():
            if len(obs_list) < self.config.min_sample_size:
                continue  # not enough data to say anything meaningful yet

            variant_means = self._variant_means(obs_list)

            # Worst-case differential: the single signal value whose mean
            # price diverges most from control. Averaging |delta| over all
            # observations would dilute a real finding whenever most
            # variants happen to match the control session.
            driving_variant, driving_delta = max(
                variant_means.items(), key=lambda kv: abs(kv[1])
            )
            variance = abs(driving_delta)

            category = signal_type.category
            severity = self._classify_severity(category, variance)

            if severity is RiskSeverity.NONE and not include_clean:
                continue

            direction: Optional[str] = None
            if severity is not RiskSeverity.NONE:
                direction = "markup" if driving_delta > 0 else "discount"

            findings.append(
                AuditFinding(
                    product_id=product_id,
                    signal_type=signal_type,
                    category=category,
                    variance_pct=round(variance * 100, 2),
                    severity=severity,
                    sample_size=len(obs_list),
                    detail=self._describe(signal_type, category, severity, variance, driving_variant, direction),
                    driving_variant=driving_variant if severity is not RiskSeverity.NONE else None,
                    direction=direction,
                    variant_breakdown={v: round(d * 100, 2) for v, d in sorted(variant_means.items())},
                )
            )

        # Highest-risk findings first, then by size of variance, then stable by product/signal
        findings.sort(key=lambda f: (f.severity.rank, -f.variance_pct, f.product_id, f.signal_type.value))
        return findings

    @staticmethod
    def _describe(
        signal_type: SignalType,
        category: Category,
        severity: RiskSeverity,
        variance: float,
        driving_variant: str,
        direction: Optional[str],
    ) -> str:
        pct = round(variance * 100, 1)
        label = signal_type.label

        if severity is RiskSeverity.NONE:
            return f"No meaningful price variance detected across {label} values."

        verb = "higher" if direction == "markup" else "lower"
        if category is Category.MARKET_BASED:
            return (
                f"Price is up to {pct}% {verb} depending on {label} "
                f"(driven by \"{driving_variant}\") — consistent with lawful "
                f"dynamic pricing based on market conditions."
            )
        return (
            f"Shoppers with {label} = \"{driving_variant}\" see prices {pct}% {verb} "
            f"than the control session. {label.capitalize()} is an individual-level "
            f"signal; this pattern is what regulators classify as personalized/"
            f"surveillance pricing and increasingly require disclosure for."
        )
