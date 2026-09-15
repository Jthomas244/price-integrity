#!/usr/bin/env python
"""Run the full audit against live GhostCart and write the report.

    backend/.venv/bin/python scripts/audit_ghostcart.py [--products GC-0001,GC-0002]
        [--replicates 1] [--concurrency 8] [--seed 42] [--out ../reports]

Needs GHOSTCART_PROBE_SECRET in the project's .env (or the environment).
Writes ghostcart-<timestamp>.json / .html plus ghostcart-latest.json / .html.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from audit_engine import (  # noqa: E402
    REGRESSION_METHODOLOGY_NOTE,
    AuditConfig,
    RigorousAuditEngine,
    SignalType,
    build_report,
    render_html,
)
from probing import FactorialProber, GhostCartTarget  # noqa: E402
from settings import REPORTS_DIR, ghostcart_base_url, ghostcart_secret  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", help="comma-separated GC- ids; default: everything the endpoint lists")
    ap.add_argument("--replicates", type=int, default=1, help="repeats of the 192-cell design per product (the endpoint is deterministic, so 1 is enough)")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=REPORTS_DIR)
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    secret = ghostcart_secret()
    if not secret:
        print("GHOSTCART_PROBE_SECRET is not set. Put it in price-integrity/.env "
              "(vercel env pull from the ghostcart repo).", file=sys.stderr)
        return 2

    target = GhostCartTarget(secret, base_url=args.base_url or ghostcart_base_url())
    products = args.products.split(",") if args.products else target.product_ids()
    prober = FactorialProber(target, replicates=args.replicates, seed=args.seed, concurrency=args.concurrency)
    print(f"Probing {target.base_url} — {len(products)} products × {prober.cell_count() * args.replicates} sessions "
          f"({prober.cell_count()} cells × {args.replicates}) at concurrency {args.concurrency}")

    t0 = time.time()
    run = prober.run(products)
    print(f"{run.session_count} sessions, {len(run.failures)} failures in {time.time() - t0:.1f}s")
    if run.failures:
        print("  first failure:", run.failures[0].error, file=sys.stderr)
    if not run.observations:
        return 1

    engine = RigorousAuditEngine(AuditConfig(alpha=args.alpha), reference_levels=target.reference_levels())
    engine.add_observations(run.observations)
    findings = engine.run_audit(include_clean=True)

    report = build_report(
        findings,
        store_name=f"GhostCart ({target.base_url})",
        observation_count=run.session_count,
        products=run.products_probed,
        signals_tested=[SignalType(s) for s in run.signals_probed],
        methodology_note=REGRESSION_METHODOLOGY_NOTE,
        probe=run.to_dict(),
        diagnostics=engine.diagnostics,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name in (f"ghostcart-{stamp}", "ghostcart-latest"):
        (args.out / f"{name}.json").write_text(json.dumps(report, indent=2))
        (args.out / f"{name}.html").write_text(render_html(report))

    print()
    print(report["summary"]["headline"])
    print()
    for f in findings:
        if f.severity.value == "none":
            continue
        print(f"[{f.severity.value.upper():8}] {f.product_id}  {f.term:38} {f.variance_pct:+7.2f}%  "
              f"CI [{f.ci_low_pct:+.2f}, {f.ci_high_pct:+.2f}]  q={f.p_value_corrected}")
    print(f"\nwrote {args.out / 'ghostcart-latest.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
