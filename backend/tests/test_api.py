import pytest
from fastapi.testclient import TestClient

from api.main import app
from audit_engine import SignalType


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_catalog(client):
    body = client.get("/catalog").json()
    assert len(body["products"]) >= 3
    assert {"product_id", "name", "base_price", "inventory"} <= set(body["products"][0])


def test_signals_taxonomy(client):
    body = client.get("/signals").json()
    assert {s["signal_type"] for s in body["signals"]} == {s.value for s in SignalType}
    assert {s["category"] for s in body["signals"]} == {"market_based", "individual_based"}
    assert all(s["probe_variants"] for s in body["signals"])


def test_rules_answer_key(client):
    body = client.get("/rules").json()
    assert {r["category"] for r in body["rules"]} == {"market_based", "individual_based"}


def test_audit_defaults(client):
    r = client.post("/audit", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["probe"]["sessions_per_variant"] == 5
    assert body["summary"]["highest_severity"] == "high"
    assert body["findings"]


def test_audit_is_reproducible_for_a_seed(client):
    a = client.post("/audit", json={"seed": 9}).json()
    b = client.post("/audit", json={"seed": 9}).json()
    assert a["findings"] == b["findings"]


def test_audit_subset(client):
    r = client.post(
        "/audit",
        json={"product_ids": ["SKU-1001"], "signal_types": ["device_type", "ip_isp"], "sessions_per_variant": 5},
    )
    body = r.json()
    assert body["summary"]["products_tested"] == ["SKU-1001"]
    assert body["summary"]["signals_tested"] == ["device_type", "ip_isp"]
    assert [f["signal_type"] for f in body["findings"]] == ["device_type"]
    assert body["summary"]["clean_individual_signals"] == ["ip_isp"]


def test_audit_min_sample_size_suppresses_findings(client):
    r = client.post("/audit", json={"sessions_per_variant": 1, "min_sample_size": 100})
    body = r.json()
    assert body["findings"] == [] and body["clean"] == [] and body["lawful_dynamic"] == []


def test_audit_validation(client):
    assert client.post("/audit", json={"product_ids": ["NOPE"]}).status_code == 422
    assert client.post("/audit", json={"product_ids": []}).status_code == 422
    assert client.post("/audit", json={"signal_types": ["hair_colour"]}).status_code == 422
    assert client.post("/audit", json={"sessions_per_variant": 0}).status_code == 422
    assert client.post("/audit", json={"noise_pct": 0.5}).status_code == 422


def test_audit_html(client):
    r = client.post("/audit/html", json={"sessions_per_variant": 2})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Pricing compliance audit" in r.text


# --- regression engine over the demo store ---------------------------------

def test_audit_regression_engine(client):
    r = client.post("/audit", json={
        "engine": "regression", "n_sessions": 800, "seed": 1,
        "signal_types": ["device_type", "cart_abandonment", "referrer_source", "inventory_level"],
        "product_ids": ["SKU-1001"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["probe"]["design"] == "random"
    assert body["probe"]["session_count"] == 800
    assert body["diagnostics"][0]["fitted"] is True
    assert "Benjamini-Hochberg" in body["methodology_note"]
    flagged = {(f["signal_type"], f["effect_type"]) for f in body["findings"]}
    # the demo store's -18% cart win-back and +10% coupon-site rules
    assert ("cart_abandonment", "main_effect") in flagged
    assert ("referrer_source", "main_effect") in flagged
    for f in body["findings"]:
        assert f["p_value_corrected"] is not None
        assert f["ci_low_pct"] <= f["ci_high_pct"]


def test_audit_regression_html(client):
    r = client.post("/audit/html", json={
        "engine": "regression", "n_sessions": 600, "seed": 1,
        "signal_types": ["device_type", "cart_abandonment"], "product_ids": ["SKU-1001"],
    })
    assert r.status_code == 200
    assert "FDR-corrected" in r.text


# --- GhostCart endpoints ----------------------------------------------------

def test_ghostcart_info_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GHOSTCART_PROBE_SECRET", raising=False)
    monkeypatch.setattr("api.main.ghostcart_secret", lambda: None)
    r = client.get("/ghostcart")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["cells_per_product"] == 192
    assert body["signal_space"]["cart_abandonment"] == [False, True]


def test_audit_ghostcart_unconfigured_is_503(client, monkeypatch):
    monkeypatch.setattr("api.main.ghostcart_secret", lambda: None)
    r = client.post("/audit/ghostcart", json={})
    assert r.status_code == 503
    assert "GHOSTCART_PROBE_SECRET" in r.json()["detail"]


def test_audit_ghostcart_against_fake(client, monkeypatch):
    import httpx
    from tests.test_factorial import SECRET, FakeGhostCart
    from probing.ghostcart import PROBE_HEADER
    from probing import GhostCartTarget

    fake = FakeGhostCart()

    def fake_target():
        c = httpx.Client(base_url="https://ghostcart.test", transport=httpx.MockTransport(fake.handler),
                         headers={PROBE_HEADER: SECRET})
        return GhostCartTarget(SECRET, base_url="https://ghostcart.test", client=c)

    monkeypatch.setattr("api.main._ghostcart_target", fake_target)
    r = client.post("/audit/ghostcart", json={"product_ids": ["GC-0001", "GC-0004"], "concurrency": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["store"].startswith("GhostCart")
    assert body["probe"]["session_count"] == 384
    assert body["summary"]["highest_severity"] == "moderate"
    assert body["summary"]["clean_individual_signals"] == ["referrer_source"]
    assert body["summary"]["interaction_finding_count"] == 2
    assert any(f["effect_type"] == "interaction" for f in body["findings"])

    r = client.post("/audit/ghostcart", json={"product_ids": ["GC-0001", "GC-9999"]})
    assert r.status_code == 422

    r = client.post("/audit/ghostcart/html", json={"product_ids": ["GC-0001"]})
    assert r.status_code == 200 and "compounding" in r.text
