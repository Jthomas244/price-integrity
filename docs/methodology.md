# Methodology

How PriceIntegrity decides whether a price difference is *dynamic pricing*
(lawful, market-driven) or *personalized pricing* (driven by who the shopper
is), and why each step is there.

## 1. The question, framed the way regulators frame it

The FTC's 2024–25 surveillance-pricing inquiry and New York's Algorithmic
Pricing Disclosure Act (effective 10 Nov 2025) both turn on one distinction:
is a price set using **market conditions** that apply to everyone at that
moment, or using **personal data** about the individual shopper?

The audit encodes that distinction as a fixed taxonomy of signals
(`audit_engine/models.py`):

| Bucket | Signals | Treatment |
| --- | --- | --- |
| Market-based | inventory level, time of day, day of week, seasonal demand | Reported as *lawful dynamic pricing* if ≥ 1% |
| Individual-based | device type, operating system, geolocation, ISP, browsing history, cart abandonment, referrer source, logged-in state, account tenure | Flagged as *personalized pricing* if significant and ≥ 3% |

Nothing about a signal's *effect* changes its bucket. A 20% inventory
markup is lawful; a 3% device markup is a finding. The bucket is a legal
category, not a statistical one.

## 2. Synthetic sessions, not real shoppers

The prober (`probing/factorial.py`) never observes real customers. It
*constructs* sessions — "a mobile shopper, arriving from search, with an
abandoned cart, while stock is 25" — asks the store for a price, and
records it. That has two consequences that carry the rest of the method:

- **Randomized assignment.** Because the audit chooses each session's
  signals at random and independently, the data is a randomized factorial
  experiment. Signals cannot be confounded with each other by construction,
  and the effects estimated in §3 are causal effects of each signal on
  price, not correlations.
- **Full control of the design.** Against GhostCart the prober runs the
  complete Cartesian product of every signal level (3 device × 2 cart × 4
  referrer × 8 inventory = 192 sessions per product), shuffled. Balanced,
  orthogonal designs give the most precise estimate per request. When the
  full factorial is too large (the demo store's 13 signals) the prober
  draws each signal uniformly instead.

Session order is shuffled so a store whose prices drift over time cannot
make a late-probed signal look like a rule.

Only two targets exist: GhostCart, a storefront the author owns, and an
in-process demo store. Probing a third-party retailer is out of scope.

## 3. One regression per product, on log(price)

For each product the engine (`audit_engine/rigorous.py`) fits

```
log(price) = β₀ + Σ βᵢ·signalᵢ + Σ βⱼₖ·(individualⱼ × individualₖ) + ε
```

- **Every signal at once.** Each coefficient is that signal's effect
  *holding every other signal constant*. A naive per-signal comparison
  would attribute an inventory effect to device if the two happened to
  co-vary; the regression cannot.
- **log(price).** Pricing engines apply multiplicative rules (×1.10 for
  mobile), which are additive in log space. So `exp(β) − 1` is the exact
  percentage effect, and an $18 product and a $6,800 product are analysed
  identically. Categorical signals are one-hot encoded against a declared
  reference level (the control session); numeric signals (inventory) enter
  as a slope centred on their reference value and are reported at the
  observed extremes ("inventory 1: +9.8%, inventory 100: −10%").
- **Pairwise interactions between individual-based signals.** A store can
  personalize without any single signal looking bad — mobile *and*
  abandoned cart together costing 8% more than the two effects add up to.
  The interaction terms catch that compounding. Market × individual
  interactions are not modelled; they would be classified as
  individual-based anyway and would double the parameter count.
- **Huber M-estimation** (iteratively reweighted least squares, c = 1.345)
  instead of ordinary least squares. Residuals beyond 1.345 robust standard
  deviations are down-weighted, so a handful of glitchy responses cannot
  swing a coefficient. Standard errors use Huber's asymptotic covariance
  with the small-sample correction K = 1 + (p/n)·Var(ψ′)/E[ψ′]²; on clean
  Gaussian data this reduces to OLS. Measured 95% CI coverage: 93–94%
  (OLS on the same data: 94%).
- **Minimum sample size.** A product is fit only when it has at least 8
  sessions per parameter (152 for GhostCart's 19-parameter model);
  otherwise it is skipped and the report says so. The engine never
  guesses.

## 4. Significance, then multiple-comparison correction

Every coefficient gets a t-test (two-sided, n − p degrees of freedom).
An audit tests many hypotheses — GhostCart: 18 terms × 10 products — so
raw p-values would produce false findings by volume. All p-values are
corrected with the **Benjamini-Hochberg** procedure at a false discovery
rate of 5%.

Correction runs in **two families**: individual-based terms (main effects
and interactions), and market-based terms. Pooling them would let a store's
real and expected inventory effect — a certain rejection — loosen the
step-up cutoff for exactly the terms the audit makes claims about. In
simulation that pooling raised the null rejection rate on personalization
terms from ~5% to ~10%; the two-family split brings it back to nominal.

## 5. From coefficients to findings

Terms are rolled up into one finding per (product, signal) or (product,
signal pair), with every level's estimated effect shown. The finding's
headline effect is the largest *significant* level. Severity:

| Category | Condition | Severity |
| --- | --- | --- |
| Individual-based | significant, ≥ 15% | HIGH |
| Individual-based | significant, ≥ 8% | MODERATE |
| Individual-based | significant, ≥ 3% | LOW |
| Individual-based | not significant, or < 3% | clean |
| Market-based | significant, ≥ 1% | lawful dynamic |
| Market-based | otherwise | clean |

The 3% floor is a practical-significance gate: with enough sessions a
0.2% effect can be statistically certain and still not be something a
regulator, or a shopper, would act on. It also absorbs cent-rounding.

Each finding carries the effect estimate, its 95% confidence interval, the
FDR-corrected p-value, the sample size, and which levels survived
correction. The HTML report is written for a non-technical reader first
(headline, then cards) with the statistics one line below.

## 6. Validation

Every claim above has a test in `backend/tests/test_rigorous.py` and
`backend/tests/test_factorial.py`:

- **Rule recovery.** Against an exact transcription of GhostCart's rule
  function the engine reports mobile +10.00%, cart abandonment +6.00%,
  mobile × abandonment +8.00%, inventory as lawful, and the referrer decoy
  as clean — on every product, including the interaction terms involving
  the decoy.
- **Confounding.** With mobile sessions deliberately steered toward low
  stock, the device effect is still recovered at 10% and inventory is
  still attributed to inventory.
- **Robustness.** 5% of one referrer's sessions inflated by 50% do not
  create a referrer finding or move the device estimate.
- **Benjamini-Hochberg.** Textbook cases, monotone q-values, step-up
  behaviour.
- **False discovery rate, by Monte Carlo.** 300 simulated audits of a
  store with no personalized pricing (inventory + 1% noise only). The
  number of audits in which *any* individual-based term survives
  correction is bounded at 30 (≈ 4 sd above the expected 15 at α = 0.05;
  observed 12–18 across seeds). The number that produce an actual
  finding (significant *and* ≥ 3%) is bounded at 5; observed 0.
- **Power.** With 1% noise and 192 sessions, the 10% mobile effect is
  found as MODERATE in at least 49 of 50 audits.
- **The wire.** An `httpx.MockTransport` implements the GhostCart
  contract verbatim (gating, validation, rules, rounding); the whole
  pipeline from HTTP request to rendered report runs against it.

## 7. Known limits

- The model is additive in log space with pairwise interactions among
  individual signals only. A store whose rules depend on three-way
  combinations, or on a non-monotone function of a numeric signal, would
  be detected (something would be significant) but mis-described.
- The inventory effect is modelled as a slope. GhostCart caps it at ±10%;
  the linear fit slightly over-extrapolates at the extremes (−11.3% vs the
  true −10% at inventory 100). Fine for a *lawful* finding; a numeric
  *individual* signal (account tenure in days, say) would deserve a
  categorical or spline treatment before being flagged on its extremes.
- Effect sizes are relative to the declared reference session. If the
  reference itself is personalized (a store that discounts desktop rather
  than marking up mobile), the finding is the same size with the opposite
  sign — the report says "lower", not "higher", and the flag is identical.
- Nothing here is legal advice. The taxonomy tracks how the FTC and New
  York frame the distinction; whether a specific practice is unlawful
  depends on disclosure, jurisdiction and facts the audit does not see.
