from datetime import datetime, timezone

from audit_engine import AuditEngine, RiskSeverity, SignalType, build_report, render_html
from demo_store import DemoStore
from probing import Prober


def _findings():
    store = DemoStore(noise_pct=0.005, seed=1)
    run = Prober(store, sessions_per_variant=5).run()
    eng = AuditEngine()
    eng.add_observations(run.observations)
    return eng.run_audit(include_clean=True), run


def test_report_payload_shape():
    findings, run = _findings()
    report = build_report(
        findings,
        store_name="Test store",
        sessions_per_variant=run.sessions_per_variant,
        observation_count=run.session_count,
        products=run.products_probed,
        signals_tested=[SignalType(s) for s in run.signals_probed],
        generated_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
    )
    assert report["generated_at"] == "2026-09-14T12:00:00+00:00"
    assert report["store"] == "Test store"
    assert report["probe"] == {"sessions_per_variant": 5, "observation_count": run.session_count}

    s = report["summary"]
    assert s["highest_severity"] == "high"
    assert s["flagged_finding_count"] == len(report["findings"])
    assert sum(s["flagged_by_severity"].values()) == s["flagged_finding_count"]
    assert set(s["clean_individual_signals"]) == {"ip_isp", "logged_in_state", "account_tenure"}
    assert len(s["signals_tested"]) == len(SignalType)
    assert "Personalized pricing detected" in s["headline"]
    assert "cart abandonment" in s["headline"]

    assert all(f["severity"] in ("high", "moderate", "low") for f in report["findings"])
    assert all(f["severity"] == "lawful" for f in report["lawful_dynamic"])
    assert all(f["severity"] == "none" for f in report["clean"])
    assert report["findings"][0]["severity"] == "high"   # most severe first


def test_report_is_json_serialisable():
    import json
    findings, _ = _findings()
    json.dumps(build_report(findings))


def test_clean_store_headline():
    store = DemoStore(rules=[], noise_pct=0.002, seed=3)
    run = Prober(store, sessions_per_variant=5).run(product_ids=["SKU-1001"])
    eng = AuditEngine()
    eng.add_observations(run.observations)
    report = build_report(eng.run_audit(include_clean=True))
    assert report["summary"]["highest_severity"] == "none"
    assert report["findings"] == []
    assert report["summary"]["headline"].startswith("No personalized pricing detected")


def test_html_render_contains_key_content_and_escapes():
    findings, _ = _findings()
    report = build_report(findings, store_name="<Evil & Co>")
    html = render_html(report)
    assert html.startswith("<!doctype html>")
    assert "&lt;Evil &amp; Co&gt;" in html
    assert "<Evil" not in html
    assert report["summary"]["headline"].replace('"', "&quot;") in html
    assert "cart abandonment" in html
    assert "ip isp" in html                       # clean signals listed
    assert html.count('class="badge"') == len(report["findings"]) + len(report["lawful_dynamic"])
