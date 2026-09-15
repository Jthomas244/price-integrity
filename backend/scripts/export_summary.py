#!/usr/bin/env python
"""Condense a report into the small per-term summary GhostCart's /audit page
embeds (src/lib/audit-result.json in the ghostcart repo).

    backend/.venv/bin/python scripts/export_summary.py reports/ghostcart-latest.json > audit-result.json

One entry per term (signal or signal pair) with the median effect across
products, the span of the products' 95% CIs, the largest corrected p, and the
plain-English detail — enough to show the result without shipping 100 KB.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from statistics import median


def main(path: str) -> None:
    report = json.load(open(path))
    groups: dict = defaultdict(list)
    for f in report["findings"] + report["lawful_dynamic"] + report["clean"]:
        groups[f["term"]].append(f)

    rank = {"high": 0, "moderate": 1, "low": 2, "lawful": 3, "none": 4}
    terms = []
    for term, fs in groups.items():
        rep = fs[0]
        signed = [(-1 if f["direction"] == "discount" else 1) * f["variance_pct"] for f in fs]
        cis = [f for f in fs if f["ci_low_pct"] is not None]
        terms.append({
            "term": term,
            "effect_type": rep["effect_type"],
            "category": rep["category"],
            "severity": rep["severity"],
            "effect_pct": round(median(signed), 2) if rep["severity"] != "none" else 0.0,
            "ci_low_pct": min(f["ci_low_pct"] for f in cis) if cis and rep["severity"] != "none" else None,
            "ci_high_pct": max(f["ci_high_pct"] for f in cis) if cis and rep["severity"] != "none" else None,
            "p_value_corrected": max(f["p_value_corrected"] for f in fs) if rep["severity"] != "none" else None,
            "driving_variant": rep["driving_variant"],
            "n_products": len(fs),
            "n_sessions_per_product": rep["sample_size"],
            "detail": rep["detail"],
        })
    terms.sort(key=lambda t: (rank[t["severity"]], -abs(t["effect_pct"]), t["term"]))

    s = report["summary"]
    out = {
        "generated_at": report["generated_at"],
        "store": report["store"],
        "session_count": report["probe"].get("session_count"),
        "sessions_per_product": report["probe"].get("sessions_per_product"),
        "design": report["probe"].get("design"),
        "products_tested": s["products_tested"],
        "signals_tested": s["signals_tested"],
        "headline": s["headline"],
        "highest_severity": s["highest_severity"],
        "flagged_finding_count": s["flagged_finding_count"],
        "interaction_finding_count": s["interaction_finding_count"],
        "clean_individual_signals": s["clean_individual_signals"],
        "terms": terms,
    }
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../reports/ghostcart-latest.json")
