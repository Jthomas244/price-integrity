"""Turns a list of AuditFindings into a report payload (dict, JSON-ready)
and renders that payload as a standalone HTML page.

The report is written for a non-technical reader: a plain-English
headline first, then per-signal detail for anyone who wants it.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from .models import AuditFinding, Category, RiskSeverity, SignalType

METHODOLOGY_NOTE = (
    "Every pricing signal is placed in one of two buckets. Market-based "
    "signals (inventory, time of day, day of week, seasonal demand) describe "
    "conditions that apply equally to every shopper; variance driven by them "
    "is conventional dynamic pricing and is surfaced for visibility only. "
    "Individual-based signals (device, operating system, location, ISP, "
    "browsing and cart history, referrer, login state, account tenure) "
    "describe the shopper rather than the market; variance driven by them is "
    "personalized or 'surveillance' pricing, which regulators increasingly "
    "require merchants to disclose. The audit varies one signal at a time "
    "against an otherwise identical control session and measures the "
    "worst-case price difference each signal produces."
)

REGRESSION_METHODOLOGY_NOTE = (
    "Every pricing signal is placed in one of two buckets. Market-based "
    "signals (inventory, time of day, day of week, seasonal demand) describe "
    "conditions that apply equally to every shopper; variance driven by them "
    "is conventional dynamic pricing and is surfaced for visibility only. "
    "Individual-based signals (device, operating system, location, ISP, "
    "browsing and cart history, referrer, login state, account tenure) "
    "describe the shopper rather than the market; variance driven by them is "
    "personalized or 'surveillance' pricing, which regulators increasingly "
    "require merchants to disclose. The audit runs a randomized factorial "
    "experiment: every synthetic session is assigned a value for every "
    "signal at random, so each signal's effect can be estimated while holding "
    "all the others constant. For each product, log(price) is fit by robust "
    "(Huber) regression on all signals at once plus every pairwise "
    "interaction between individual-based signals. Each effect is reported "
    "as a percentage with a 95% confidence interval and a p-value corrected "
    "for multiple comparisons (Benjamini-Hochberg, false discovery rate 5%). "
    "A signal is flagged only if its effect is statistically significant "
    "after correction and at least 3% in size; smaller or non-significant "
    "effects are reported as clean."
)

_SEVERITY_ORDER = [RiskSeverity.HIGH, RiskSeverity.MODERATE, RiskSeverity.LOW]


def build_report(
    findings: Sequence[AuditFinding],
    *,
    store_name: str = "Demo storefront",
    sessions_per_variant: Optional[int] = None,
    observation_count: Optional[int] = None,
    products: Optional[Sequence[str]] = None,
    signals_tested: Optional[Sequence[SignalType]] = None,
    generated_at: Optional[datetime] = None,
    methodology_note: Optional[str] = None,
    probe: Optional[dict] = None,
    diagnostics: Optional[Sequence[object]] = None,
) -> dict:
    """Assemble the JSON-serialisable report payload.

    ``probe`` is free-form metadata about how the sessions were collected
    (e.g. ``FactorialRun.to_dict()``); ``diagnostics`` the regression
    engine's per-product fit summaries. ``methodology_note`` defaults to
    the one-at-a-time note; pass ``REGRESSION_METHODOLOGY_NOTE`` for the
    regression engine.
    """
    generated_at = generated_at or datetime.now(timezone.utc)

    flagged = [f for f in findings if f.severity.is_flagged]
    lawful = [f for f in findings if f.severity is RiskSeverity.LAWFUL_DYNAMIC]
    clean = [f for f in findings if f.severity is RiskSeverity.NONE]

    by_severity = Counter(f.severity for f in flagged)
    flagged_signals = sorted({f.signal_type for f in flagged}, key=lambda s: s.value)
    tested_signals = list(signals_tested) if signals_tested is not None else sorted(
        {f.signal_type for f in findings}, key=lambda s: s.value
    )
    individual_tested = [s for s in tested_signals if s.category is Category.INDIVIDUAL_BASED]
    clean_individual = [s for s in individual_tested if s not in flagged_signals]

    worst = flagged[0] if flagged else None   # findings arrive sorted most-severe first
    interactions = [f for f in flagged if f.is_interaction]

    summary = {
        "headline": _headline(flagged, by_severity, worst),
        "highest_severity": worst.severity.value if worst else RiskSeverity.NONE.value,
        "flagged_finding_count": len(flagged),
        "flagged_by_severity": {s.value: by_severity.get(s, 0) for s in _SEVERITY_ORDER},
        "flagged_signals": [s.value for s in flagged_signals],
        "clean_individual_signals": [s.value for s in clean_individual],
        "lawful_dynamic_finding_count": len(lawful),
        "interaction_finding_count": len(interactions),
        "signals_tested": [s.value for s in tested_signals],
        "products_tested": list(products) if products is not None else sorted({f.product_id for f in findings}),
    }

    return {
        "generated_at": generated_at.replace(microsecond=0).isoformat(),
        "store": store_name,
        "probe": {
            "sessions_per_variant": sessions_per_variant,
            "observation_count": observation_count,
            **(probe or {}),
        },
        "summary": summary,
        "findings": [f.to_dict() for f in flagged],
        "lawful_dynamic": [f.to_dict() for f in lawful],
        "clean": [f.to_dict() for f in clean],
        "diagnostics": [_diag_dict(d) for d in (diagnostics or [])],
        "methodology_note": methodology_note or METHODOLOGY_NOTE,
    }


def _diag_dict(d: object) -> dict:
    return dict(vars(d)) if hasattr(d, "__dict__") else dict(d)  # dataclass or already a dict


def _variant_phrase(f: AuditFinding) -> str:
    """'device type = "mobile"' for threshold findings; the regression
    engine's driving_variant already reads 'device type = mobile' (and
    'cart abandonment = True × device type = mobile' for interactions)."""
    if f.p_value_corrected is not None:
        return f.driving_variant or f.term
    return f"{f.signal_type.label} = \"{f.driving_variant}\""


def _headline(flagged: List[AuditFinding], by_severity: Counter, worst: Optional[AuditFinding]) -> str:
    if not flagged:
        return (
            "No personalized pricing detected. Every price difference observed "
            "was explained by market conditions."
        )
    parts = [f"{by_severity[s]} {s.value}" for s in _SEVERITY_ORDER if by_severity.get(s)]
    n_signals = len({s for f in flagged for s in f.signals})
    n_products = len({f.product_id for f in flagged})
    signal_word = "signal" if n_signals == 1 else "signals"
    product_word = "product" if n_products == 1 else "products"
    finding_word = "finding" if len(flagged) == 1 else "findings"
    assert worst is not None
    verb = "more" if worst.direction == "markup" else "less"
    n_interactions = sum(1 for f in flagged if f.is_interaction)
    interaction_note = ""
    if n_interactions:
        interaction_note = (
            f" {n_interactions} of these are compounding effects between two "
            f"individual-based signals."
        )
    return (
        f"Personalized pricing detected on {n_signals} individual-based {signal_word} "
        f"across {n_products} {product_word} — {len(flagged)} {finding_word} "
        f"({', '.join(parts)}). Worst case: shoppers with {_variant_phrase(worst)} "
        f"pay {worst.variance_pct:.1f}% {verb} for {worst.product_id}.{interaction_note}"
    )


# --- HTML rendering -------------------------------------------------------

_SEVERITY_COLORS: Dict[str, str] = {
    "high": "#b42318",
    "moderate": "#b54708",
    "low": "#7a5c00",
    "lawful": "#027a48",
    "none": "#475467",
}

_CSS = """
:root { color-scheme: light; }
body { margin: 0; padding: 2rem 1.25rem 4rem; background: #f8f8f7; color: #1d1d1b;
       font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 860px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2.25rem 0 .75rem; border-bottom: 1px solid #e4e4e1; padding-bottom: .35rem; }
.meta { color: #667085; font-size: .9rem; margin-bottom: 1.5rem; }
.headline { background: #fff; border: 1px solid #e4e4e1; border-left: 5px solid var(--accent, #475467);
            border-radius: 6px; padding: 1rem 1.25rem; font-size: 1.05rem; }
.counts { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
.count { background: #fff; border: 1px solid #e4e4e1; border-radius: 6px; padding: .6rem .9rem; min-width: 7rem; }
.count b { display: block; font-size: 1.4rem; line-height: 1.2; }
.count span { color: #667085; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }
.finding { background: #fff; border: 1px solid #e4e4e1; border-radius: 6px; padding: 1rem 1.25rem; margin-bottom: .9rem; }
.finding header { display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem; margin-bottom: .4rem; }
.badge { display: inline-block; color: #fff; font-size: .72rem; font-weight: 600; letter-spacing: .05em;
         text-transform: uppercase; padding: .15rem .5rem; border-radius: 999px; }
.finding h3 { margin: 0; font-size: 1rem; }
.finding .sku { color: #667085; font-size: .85rem; }
.finding p { margin: .35rem 0 .6rem; }
.breakdown { width: 100%; border-collapse: collapse; font-size: .88rem; }
.breakdown th, .breakdown td { text-align: left; padding: .3rem .5rem; border-top: 1px solid #f0f0ee; }
.breakdown th { color: #667085; font-weight: 500; border-top: 0; }
.breakdown td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pos { color: #b42318; } .neg { color: #027a48; }
.clean-list { display: flex; flex-wrap: wrap; gap: .5rem; padding: 0; list-style: none; }
.clean-list li { background: #ecfdf3; color: #027a48; border-radius: 999px; padding: .2rem .7rem; font-size: .85rem; }
.method { color: #475467; font-size: .92rem; }
.stats { color: #667085; font-size: .85rem; font-variant-numeric: tabular-nums; }
.kind { color: #667085; font-size: .8rem; border: 1px solid #e4e4e1; border-radius: 4px; padding: 0 .4rem; }
.sig { color: #027a48; font-weight: 600; }
.wrap { overflow-x: auto; }
"""


def render_html(report: dict) -> str:
    """Render a report payload from ``build_report`` as a standalone HTML page."""
    s = report["summary"]
    accent = _SEVERITY_COLORS.get(s["highest_severity"], _SEVERITY_COLORS["none"])
    counts = s["flagged_by_severity"]
    probe = report.get("probe") or {}

    out: List[str] = []
    out.append("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    out.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    out.append(f"<title>Pricing audit — {_e(report['store'])}</title>")
    out.append(f"<style>{_CSS}</style></head><body><main>")
    out.append(f"<h1>Pricing compliance audit</h1>")
    meta_bits = [_e(report["store"]), f"generated {_e(report['generated_at'])}"]
    if probe.get("observation_count"):
        meta_bits.append(f"{probe['observation_count']:,} synthetic sessions")
    if probe.get("sessions_per_variant"):
        meta_bits.append(f"{probe['sessions_per_variant']} sessions per variant")
    if probe.get("sessions_per_product"):
        meta_bits.append(f"{probe['sessions_per_product']} sessions per product ({probe.get('design', 'factorial')} factorial design)")
    out.append(f"<div class=\"meta\">{' · '.join(meta_bits)}</div>")

    out.append(f"<div class=\"headline\" style=\"--accent:{accent}\">{_e(s['headline'])}</div>")
    out.append("<div class=\"counts\">")
    for sev in ("high", "moderate", "low"):
        out.append(f"<div class=\"count\"><b style=\"color:{_SEVERITY_COLORS[sev]}\">{counts.get(sev, 0)}</b><span>{sev} risk</span></div>")
    out.append(f"<div class=\"count\"><b style=\"color:{_SEVERITY_COLORS['lawful']}\">{s['lawful_dynamic_finding_count']}</b><span>lawful dynamic</span></div>")
    out.append(f"<div class=\"count\"><b>{len(s['signals_tested'])}</b><span>signals tested</span></div>")
    if s.get("interaction_finding_count"):
        out.append(f"<div class=\"count\"><b style=\"color:{_SEVERITY_COLORS['moderate']}\">{s['interaction_finding_count']}</b><span>compounding</span></div>")
    out.append("</div>")

    out.append("<h2>Personalized pricing findings</h2>")
    if report["findings"]:
        out.extend(_finding_card(f) for f in report["findings"])
    else:
        out.append("<p>None. No individual-based signal moved the price beyond the detection threshold.</p>")

    out.append("<h2>Individual-based signals that came back clean</h2>")
    if s["clean_individual_signals"]:
        out.append("<ul class=\"clean-list\">")
        out.extend(f"<li>{_e(_label(v))}</li>" for v in s["clean_individual_signals"])
        out.append("</ul>")
    else:
        out.append("<p>None — every individual-based signal tested produced a flagged finding.</p>")

    out.append("<h2>Market-based (lawful dynamic) pricing observed</h2>")
    if report["lawful_dynamic"]:
        out.extend(_finding_card(f) for f in report["lawful_dynamic"])
    else:
        out.append("<p>No market-driven price variance observed.</p>")

    out.append("<h2>Methodology</h2>")
    out.append(f"<p class=\"method\">{_e(report['methodology_note'])}</p>")
    out.append("</main></body></html>")
    return "".join(out)


def _finding_card(f: dict) -> str:
    sev = f["severity"]
    color = _SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["none"])
    regression = f.get("p_value_corrected") is not None
    significant = set(f.get("significant_variants") or [])
    rows = "".join(
        f"<tr><td>{_e(value)}{' <span class=sig title=\"significant after FDR correction\">✓</span>' if value in significant else ''}</td>"
        f"<td class=\"num {'pos' if pct > 0 else 'neg' if pct < 0 else ''}\">{pct:+.2f}%</td></tr>"
        for value, pct in f["variant_breakdown"].items()
    )
    title = f.get("term") or _label(f["signal_type"])
    kind = " <span class=\"kind\">interaction</span>" if f.get("effect_type") == "interaction" else ""
    stats = ""
    if regression and f.get("driving_variant"):
        stats = (
            f"<p class=\"stats\">95% CI {f['ci_low_pct']:+.2f}% to {f['ci_high_pct']:+.2f}% · "
            f"FDR-corrected p = {f['p_value_corrected']:.4f}</p>"
        )
    return (
        "<article class=\"finding\"><header>"
        f"<span class=\"badge\" style=\"background:{color}\">{_e(sev)}</span>"
        f"<h3>{_e(title)}</h3>{kind}"
        f"<span class=\"sku\">{_e(f['product_id'])} · n={f['sample_size']}</span>"
        "</header>"
        f"<p>{_e(f['detail'])}</p>{stats}"
        "<div class=\"wrap\"><table class=\"breakdown\"><thead><tr><th>Signal value</th>"
        f"<th style=\"text-align:right\">{'Effect vs. control' if regression else 'Price vs. control'}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "</article>"
    )


def _label(signal_value: str) -> str:
    return signal_value.replace("_", " ")


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)
