"""RigorousAuditEngine: the statistical core.

The threshold engine in ``engine.py`` compares a group's mean price delta
against fixed percentage cut-offs. That is legible but it isn't inference:
it can't tell a real effect from noise, can't isolate one signal when
several vary together, and can't see compounding effects between signals.

This engine fixes all of that:

  1. SIGNIFICANCE, not just magnitude. Every effect is tested against
     noise with a regression t-test, not compared to an arbitrary cutoff.
  2. CONFOUND CONTROL. Price is modelled as a function of ALL signals at
     once, so each coefficient is that signal's effect holding the others
     constant.
  3. MULTIPLE-COMPARISON CORRECTION. Many signals × many products inflates
     the false-positive rate, so every p-value is Benjamini-Hochberg
     FDR-corrected before anything is reported.
  4. ROBUSTNESS. Huber M-estimation (iteratively reweighted least squares)
     instead of plain OLS, so a handful of glitchy probes can't swing a
     finding.
  5. INTERACTIONS between individual-based signals, to catch compounding
     personalization (mobile + abandoned cart costing more together than
     either alone).

Because the prober *assigns* signal values to each synthetic session rather
than observing naturally occurring ones, the data is a randomized factorial
experiment and the coefficients estimate causal effects, not correlations.

The model is fit on log(price). Real pricing engines apply multiplicative
rules (×1.10 for mobile, ×1.06 for an abandoned cart), which are additive in
log space — so exp(coef) − 1 is the exact percentage effect, and a product
that costs $6,800 is analysed on the same footing as one that costs $18.

Dependencies: numpy and scipy only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

from .models import (
    AuditConfig,
    AuditFinding,
    Category,
    INDIVIDUAL_BASED_SIGNALS,
    RiskSeverity,
    SignalType,
)

SignalValue = object  # str | bool | int | float


@dataclass(frozen=True)
class SessionObservation:
    """One synthetic session: the full set of signal values the prober
    assigned to it, and the price the store quoted. Unlike the threshold
    engine's ``ProbeObservation`` there is no control price — the
    regression's intercept plays that role."""

    product_id: str
    price: float
    signals: Mapping[SignalType, SignalValue]
    timestamp: str

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price!r}")
        if not self.signals:
            raise ValueError("signals must not be empty")


# --- Robust regression: Huber M-estimation via IRLS ------------------------

HUBER_C = 1.345  # 95% efficiency under normal errors


def _robust_scale(resid: np.ndarray) -> float:
    """Median absolute deviation, scaled to match the standard deviation
    under normal errors. Floored so an (almost) perfectly deterministic
    target can't collapse the scale to zero."""
    med = np.median(resid)
    mad = np.median(np.abs(resid - med))
    return max(mad / 0.6745, 1e-9)


def _huber_weights(resid: np.ndarray, scale: float, c: float = HUBER_C) -> np.ndarray:
    u = np.abs(resid) / scale
    w = np.ones_like(u)
    mask = u > c
    w[mask] = c / u[mask]
    return w


def fit_huber_regression(
    X: np.ndarray, y: np.ndarray, max_iter: int = 50, tol: float = 1e-8
) -> Tuple[np.ndarray, np.ndarray, int]:
    """Iteratively reweighted least squares with a Huber loss.

    Returns ``(coefficients, standard_errors, degrees_of_freedom)``.
    """
    n, p = X.shape
    ridge = 1e-10 * np.eye(p)  # keeps the solve stable if a column is nearly constant
    beta = np.linalg.lstsq(X, y, rcond=None)[0]  # OLS start

    for _ in range(max_iter):
        resid = y - X @ beta
        w = _huber_weights(resid, _robust_scale(resid))
        beta_new = np.linalg.solve(X.T @ (w[:, None] * X) + ridge, X.T @ (w * y))
        converged = np.max(np.abs(beta_new - beta)) < tol
        beta = beta_new
        if converged:
            break

    # Standard errors: Huber's (1973) asymptotic covariance for an
    # M-estimator, s² · E[ψ²] / E[ψ']² · (XᵀX)⁻¹, where ψ is the Huber
    # score. On clean Gaussian data this reduces to the OLS covariance; with
    # outliers present the ψ terms stop them inflating the variance.
    resid = y - X @ beta
    scale = _robust_scale(resid)
    u = resid / scale
    psi = np.clip(u, -HUBER_C, HUBER_C)
    psi_prime = (np.abs(u) <= HUBER_C).astype(float)
    dof = max(n - p, 1)
    kappa = float(np.mean(psi_prime)) or 1e-12
    # Huber's small-sample correction K = 1 + (p/n)·Var(ψ')/E[ψ']².
    K = 1 + (p / n) * float(np.var(psi_prime)) / kappa**2
    sigma2 = K * scale**2 * float(np.sum(psi**2) / dof) / kappa**2
    XtX_inv = np.linalg.inv(X.T @ X + ridge)
    se = np.sqrt(np.clip(np.diag(sigma2 * XtX_inv), 0, None))
    return beta, se, dof


# --- Multiple-comparison correction: Benjamini-Hochberg FDR ----------------

def benjamini_hochberg(pvals: Sequence[float], alpha: float) -> Tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg step-up procedure.

    Returns ``(reject, q_values)``: which hypotheses are rejected at false
    discovery rate ``alpha``, and the corrected (monotone) p-values.
    """
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    if m == 0:
        return np.zeros(0, dtype=bool), np.zeros(0)

    order = np.argsort(p)
    ranked = p[order]
    ranks = np.arange(1, m + 1)

    below = ranked <= ranks / m * alpha
    if below.any():
        cutoff = ranked[np.max(np.flatnonzero(below))]
        reject = p <= cutoff
    else:
        reject = np.zeros(m, dtype=bool)

    # q-values: enforce monotonicity from the largest p-value downward.
    q_ranked = np.minimum.accumulate((ranked * m / ranks)[::-1])[::-1]
    q = np.empty(m)
    q[order] = np.clip(q_ranked, 0, 1)
    return reject, q


# --- Design matrix ----------------------------------------------------------

@dataclass(frozen=True)
class _Term:
    """One column of the design matrix.

    ``levels`` holds one ``(signal, level)`` pair for a main effect and two
    for an interaction. For a numeric signal ``level`` is the string
    "slope" and the column is the centred numeric value.
    """

    levels: Tuple[Tuple[SignalType, str], ...]

    @property
    def signals(self) -> Tuple[SignalType, ...]:
        return tuple(sig for sig, _ in self.levels)

    @property
    def is_interaction(self) -> bool:
        return len(self.levels) > 1


@dataclass
class _Design:
    X: np.ndarray
    terms: List[_Term]                                   # excludes the intercept column
    numeric_range: Dict[SignalType, Tuple[float, float, float]]  # sig -> (min, max, reference)


def _is_numeric(values: Sequence[SignalValue]) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def _level_key(v: SignalValue) -> str:
    return str(v)


def _build_design(
    observations: Sequence[SessionObservation],
    reference_levels: Mapping[SignalType, SignalValue],
) -> _Design:
    n = len(observations)
    signals = sorted({s for o in observations for s in o.signals}, key=lambda s: s.value)

    columns: List[np.ndarray] = []
    terms: List[_Term] = []
    numeric_range: Dict[SignalType, Tuple[float, float, float]] = {}
    # Per signal, the dummy/numeric columns it contributed (for interactions).
    by_signal: Dict[SignalType, List[Tuple[_Term, np.ndarray]]] = defaultdict(list)

    for sig in signals:
        values = [o.signals.get(sig) for o in observations]
        if any(v is None for v in values):
            raise ValueError(f"signal {sig.value} is missing from some sessions")

        if _is_numeric(values):
            arr = np.asarray(values, dtype=float)
            ref = float(reference_levels.get(sig, arr.mean()))
            numeric_range[sig] = (float(arr.min()), float(arr.max()), ref)
            col = arr - ref  # centre on the reference so the intercept is the control price
            term = _Term(((sig, "slope"),))
            columns.append(col)
            terms.append(term)
            by_signal[sig].append((term, col))
            continue

        keys = [_level_key(v) for v in values]
        levels = sorted(set(keys))
        if sig in reference_levels:
            ref_key = _level_key(reference_levels[sig])
            if ref_key not in levels:
                raise ValueError(f"reference level {ref_key!r} for {sig.value} never observed")
        elif all(isinstance(v, bool) for v in values):
            ref_key = "False"
        else:
            ref_key = levels[0]
        for level in levels:
            if level == ref_key:
                continue
            col = np.asarray([1.0 if k == level else 0.0 for k in keys])
            term = _Term(((sig, level),))
            columns.append(col)
            terms.append(term)
            by_signal[sig].append((term, col))

    # Pairwise interactions among individual-based signals only — this is
    # where compounding personalization would show up.
    individual = [s for s in signals if s in INDIVIDUAL_BASED_SIGNALS]
    for a, b in combinations(individual, 2):
        for ta, ca in by_signal[a]:
            for tb, cb in by_signal[b]:
                columns.append(ca * cb)
                terms.append(_Term(ta.levels + tb.levels))

    X = np.column_stack([np.ones(n)] + columns) if columns else np.ones((n, 1))
    return _Design(X=X, terms=terms, numeric_range=numeric_range)


# --- Engine -----------------------------------------------------------------

@dataclass
class _TermResult:
    product_id: str
    term: _Term
    coef: float
    se: float
    p_value: float
    n: int
    q_value: float = float("nan")
    reject: bool = False

    @property
    def effect(self) -> float:
        """Multiplicative effect of the term as a fraction (0.10 == +10%)."""
        return float(np.expm1(self.coef))


@dataclass
class RegressionDiagnostics:
    """Per-product fit summary, for the report's methodology section."""

    product_id: str
    n_observations: int
    n_parameters: int
    fitted: bool
    reason: Optional[str] = None
    # Price of the reference (control) session: the median observed price of
    # sessions at every reference level when the design contains such
    # sessions (a full factorial always does), else exp(intercept).
    control_price: Optional[float] = None


class RigorousAuditEngine:
    """Robust-regression audit with FDR control and interaction detection.

    Usage mirrors the threshold engine: add observations, call
    ``run_audit``. Findings come back as ``AuditFinding`` so ``report.py``
    renders them unchanged, with the statistical fields filled in.
    """

    def __init__(
        self,
        config: Optional[AuditConfig] = None,
        reference_levels: Optional[Mapping[SignalType, SignalValue]] = None,
    ) -> None:
        """``reference_levels`` names the control value of each signal —
        the level every other level is compared against (for a numeric
        signal, the value the intercept is centred on). Defaults: ``False``
        for booleans, the alphabetically first level otherwise, the mean
        for numeric signals."""
        self.config = config or AuditConfig()
        self.reference_levels: Dict[SignalType, SignalValue] = dict(reference_levels or {})
        self._observations: List[SessionObservation] = []
        self.diagnostics: List[RegressionDiagnostics] = []

    # -- ingestion -------------------------------------------------------

    def add_observation(self, obs: SessionObservation) -> None:
        self._observations.append(obs)

    def add_observations(self, observations: Iterable[SessionObservation]) -> None:
        for obs in observations:
            self.add_observation(obs)

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    # -- analysis --------------------------------------------------------

    def _fit_product(self, product_id: str, obs: List[SessionObservation]) -> Tuple[List[_TermResult], _Design]:
        design = _build_design(obs, self.reference_levels)
        n, p = design.X.shape
        if n < p * self.config.min_obs_per_param:
            self.diagnostics.append(RegressionDiagnostics(
                product_id, n, p, fitted=False,
                reason=f"{n} sessions is below the {p * self.config.min_obs_per_param} needed "
                       f"for {p} parameters ({self.config.min_obs_per_param} per parameter)",
            ))
            return [], design

        y = np.log(np.asarray([o.price for o in obs], dtype=float))
        beta, se, dof = fit_huber_regression(design.X, y)
        self.diagnostics.append(RegressionDiagnostics(
            product_id, n, p, fitted=True, control_price=self._control_price(obs, beta[0]),
        ))

        results: List[_TermResult] = []
        for i, term in enumerate(design.terms, start=1):  # column 0 is the intercept
            coef, coef_se = float(beta[i]), float(se[i])
            if coef_se == 0.0:
                continue  # column carried no information (e.g. a level never varied)
            t_stat = coef / coef_se
            p_value = float(2 * stats.t.sf(abs(t_stat), dof))
            results.append(_TermResult(product_id, term, coef, coef_se, p_value, n))
        return results, design

    def _control_price(self, obs: List[SessionObservation], intercept: float) -> float:
        ref = self.reference_levels
        at_ref = [
            o.price for o in obs
            if all(_level_key(o.signals.get(s)) == _level_key(v) for s, v in ref.items() if s in o.signals)
        ] if ref else []
        if at_ref:
            return round(float(np.median(at_ref)), 2)
        return round(float(np.exp(intercept)), 2)

    def run_audit(self, include_clean: bool = False) -> List[AuditFinding]:
        """Fit one robust regression per product, FDR-correct every
        coefficient across all products, and roll the surviving terms up
        into one finding per (product, signal) or (product, signal pair).

        Pass ``include_clean=True`` to also get NONE-severity findings for
        signals that were tested and showed no significant effect.
        """
        self.diagnostics = []
        by_product: Dict[str, List[SessionObservation]] = defaultdict(list)
        for o in self._observations:
            by_product[o.product_id].append(o)

        results: List[_TermResult] = []
        designs: Dict[str, _Design] = {}
        for product_id in sorted(by_product):
            product_results, designs[product_id] = self._fit_product(product_id, by_product[product_id])
            results.extend(product_results)

        # FDR-correct in two families. Individual-based terms are the
        # hypotheses the audit makes claims about; correcting them on their
        # own means a store's (expected, lawful) inventory effect can't
        # loosen the cutoff for a personalized-pricing finding.
        for family in (
            [r for r in results if any(s in INDIVIDUAL_BASED_SIGNALS for s in r.term.signals)],
            [r for r in results if not any(s in INDIVIDUAL_BASED_SIGNALS for s in r.term.signals)],
        ):
            if not family:
                continue
            reject, q = benjamini_hochberg([r.p_value for r in family], self.config.alpha)
            for r, rej, qv in zip(family, reject, q):
                r.reject, r.q_value = bool(rej), float(qv)

        # Group terms into findings.
        groups: Dict[Tuple[str, Tuple[SignalType, ...]], List[_TermResult]] = defaultdict(list)
        for r in results:
            groups[(r.product_id, r.term.signals)].append(r)

        findings: List[AuditFinding] = []
        for (product_id, sigs), group in groups.items():
            finding = self._summarise(product_id, sigs, group, designs[product_id])
            if finding.severity is RiskSeverity.NONE and not include_clean:
                continue
            findings.append(finding)

        findings.sort(key=lambda f: (f.severity.rank, -f.variance_pct, f.product_id, f.term))
        return findings

    def _summarise(
        self,
        product_id: str,
        sigs: Tuple[SignalType, ...],
        group: List[_TermResult],
        design: _Design,
    ) -> AuditFinding:
        cfg = self.config
        is_interaction = len(sigs) > 1
        category = (
            Category.INDIVIDUAL_BASED
            if any(s in INDIVIDUAL_BASED_SIGNALS for s in sigs)
            else Category.MARKET_BASED
        )

        # Each term becomes one or more "variants": a dummy is its level; a
        # numeric slope is evaluated at the observed extremes so the
        # breakdown reads "inventory 1: +9.8%, inventory 100: −10%".
        variants: List[Tuple[str, float, float, float, float, bool]] = []  # label, effect, lo, hi, q, sig
        for r in group:
            t_crit = stats.t.ppf(1 - cfg.alpha / 2, max(r.n - len(design.terms) - 1, 1))
            for label, multiplier in self._variant_multipliers(r.term, design):
                coef = r.coef * multiplier
                half = t_crit * r.se * abs(multiplier)
                variants.append((
                    label,
                    float(np.expm1(coef)),
                    float(np.expm1(coef - half)),
                    float(np.expm1(coef + half)),
                    r.q_value,
                    r.reject,
                ))

        breakdown = {label: round(effect * 100, 2) + 0.0 for label, effect, *_ in variants}
        significant = [v for v in variants if v[5]]
        worst_any = max(variants, key=lambda v: abs(v[1]))
        worst_sig = max(significant, key=lambda v: abs(v[1])) if significant else None

        # Prices are quoted in cents, so a ×1.08 rule can come back as 7.996%
        # on a cheap product; classify on the reported (2 dp) figure so the
        # same rule lands in the same band on every product.
        variance = round(abs(worst_sig[1]) if worst_sig else abs(worst_any[1]), 4)
        severity = self._classify_severity(category, variance, bool(worst_sig))
        flagged = severity is not RiskSeverity.NONE
        direction = ("markup" if worst_sig[1] > 0 else "discount") if flagged and worst_sig else None

        primary = worst_sig or worst_any
        return AuditFinding(
            product_id=product_id,
            signal_type=sigs[0],
            category=category,
            variance_pct=round(variance * 100, 2),
            severity=severity,
            sample_size=group[0].n,
            detail=self._describe(sigs, category, severity, variance, primary[0], direction, primary[4], is_interaction),
            driving_variant=primary[0] if flagged else None,
            direction=direction,
            variant_breakdown=breakdown,
            effect_type="interaction" if is_interaction else "main_effect",
            signals=list(sigs),
            ci_low_pct=round(primary[2] * 100, 2),
            ci_high_pct=round(primary[3] * 100, 2),
            p_value_corrected=round(primary[4], 4),
            significant_variants=[v[0] for v in significant],
            variant_ci={label: (round(lo * 100, 2) + 0.0, round(hi * 100, 2) + 0.0) for label, _, lo, hi, *_ in variants},
        )

    @staticmethod
    def _variant_multipliers(term: _Term, design: _Design) -> List[Tuple[str, float]]:
        """Expand a term into labelled points at which to evaluate it.

        A dummy term is a single point with multiplier 1. A numeric slope
        is evaluated at the observed minimum and maximum relative to the
        reference, e.g. ``("inventory level = 1", -39.0)`` when the
        reference stock is 40.
        """
        labels: List[str] = []
        multiplier = 1.0
        numeric_points: List[Tuple[str, float]] = []
        for sig, level in term.levels:
            if level == "slope":
                lo, hi, ref = design.numeric_range[sig]
                numeric_points = [(f"{sig.label} = {_fmt(lo)}", lo - ref), (f"{sig.label} = {_fmt(hi)}", hi - ref)]
            else:
                labels.append(f"{sig.label} = {level}")

        if not numeric_points:
            return [(" × ".join(labels), multiplier)]
        out = []
        for label, mult in numeric_points:
            if mult == 0.0:
                continue  # an extreme that coincides with the reference has no effect by definition
            out.append((" × ".join(labels + [label]), mult))
        return out or [(" × ".join(labels + [numeric_points[0][0]]), 0.0)]

    def _classify_severity(self, category: Category, variance: float, significant: bool) -> RiskSeverity:
        cfg = self.config
        if not significant:
            return RiskSeverity.NONE
        if category is Category.MARKET_BASED:
            return RiskSeverity.LAWFUL_DYNAMIC if variance >= cfg.lawful_threshold else RiskSeverity.NONE
        if variance >= cfg.high_threshold:
            return RiskSeverity.HIGH
        if variance >= cfg.moderate_threshold:
            return RiskSeverity.MODERATE
        if variance >= cfg.low_threshold:
            return RiskSeverity.LOW
        return RiskSeverity.NONE

    @staticmethod
    def _describe(
        sigs: Tuple[SignalType, ...],
        category: Category,
        severity: RiskSeverity,
        variance: float,
        variant_label: str,
        direction: Optional[str],
        q_value: float,
        is_interaction: bool,
    ) -> str:
        term = " × ".join(s.label for s in sigs)
        pct = round(variance * 100, 1)

        if severity is RiskSeverity.NONE:
            if is_interaction:
                return (
                    f"No compounding effect between {term}: the two signals together "
                    f"do not move the price beyond what each does alone."
                )
            return (
                f"No statistically significant price effect from {term} after "
                f"controlling for every other signal (FDR-corrected)."
            )

        verb = "higher" if direction == "markup" else "lower"
        stat = f"(FDR-corrected p = {q_value:.4f})"
        if category is Category.MARKET_BASED:
            return (
                f"Price is {pct}% {verb} at {variant_label} than at the control level "
                f"{stat} — consistent with lawful dynamic pricing based on market conditions."
            )
        if is_interaction:
            return (
                f"Sessions with {variant_label} pay an additional {pct}% {verb} "
                f"beyond the sum of each signal's own effect {stat}. A compounding "
                f"effect between two individual-level signals is a stronger "
                f"surveillance-pricing indicator than either alone."
            )
        return (
            f"Shoppers with {variant_label} see prices {pct}% {verb} than the control "
            f"session, holding every other signal constant {stat}. {term.capitalize()} "
            f"is an individual-level signal; this pattern is what regulators classify "
            f"as personalized/surveillance pricing and increasingly require disclosure for."
        )


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"
