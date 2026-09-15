"""GhostCart target: ``POST /api/persona-price`` over HTTP.

Built against docs/ghostcart-persona-price-contract.md (GhostCart v0.6,
finalized 2026-09-15). GhostCart is the only remote target this project
will ever have; it is a storefront Julian owns, and the endpoint is a side
channel real visitors never see.

Gating: the route 404s with an empty body unless the server has
``PERSONA_PRICING_ENABLED=true`` *and* the request carries
``X-PriceIntegrity-Probe: <secret>``. The secret lives in this project's
``.env`` as ``GHOSTCART_PROBE_SECRET`` and is never committed.

Signal mapping (taxonomy → wire): the four names are identical
(``device_type``, ``cart_abandonment``, ``referrer_source``,
``inventory_level``). Values differ from the demo store's — GhostCart's
cart_abandonment is a boolean and its referrers include ``email`` — so
the space below is GhostCart's, not ``SIGNAL_VARIANTS``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional

import httpx

from audit_engine.models import SignalType
from audit_engine.rigorous import SignalValue

from .targets import SignalSpace

DEFAULT_BASE_URL = "https://ghostcart-ten.vercel.app"
PROBE_HEADER = "X-PriceIntegrity-Probe"
ENDPOINT = "/api/persona-price"

# The contract's signal space. Inventory is numeric (0–100000 accepted); the
# rule is ±0.2%/unit around 50, capped at ±10%, so 1…100 spans the whole
# effect and the engine models it as a slope through the reference of 50.
GHOSTCART_SIGNAL_SPACE: SignalSpace = {
    SignalType.DEVICE_TYPE: ["desktop", "mobile", "tablet"],
    SignalType.CART_ABANDONMENT: [False, True],
    SignalType.REFERRER_SOURCE: ["direct", "search", "social", "email"],
    SignalType.INVENTORY_LEVEL: [1, 10, 25, 40, 50, 60, 80, 100],
}

GHOSTCART_REFERENCE_LEVELS: Dict[SignalType, SignalValue] = {
    SignalType.DEVICE_TYPE: "desktop",
    SignalType.CART_ABANDONMENT: False,
    SignalType.REFERRER_SOURCE: "direct",
    SignalType.INVENTORY_LEVEL: 50,
}

# Static copy of the audit-enabled subset, used if the listing call fails.
GHOSTCART_AUDIT_PRODUCTS: List[Dict[str, Any]] = [
    {"productId": "GC-0001", "slug": "wireless-noise-cancelling-headphones-0", "basePrice": 89.99, "inventory": 40},
    {"productId": "GC-0002", "slug": "cast-iron-skillet-12-17", "basePrice": 32.50, "inventory": 62},
    {"productId": "GC-0003", "slug": "weighted-blanket-15lb-11", "basePrice": 54.99, "inventory": 35},
    {"productId": "GC-0004", "slug": "robot-vacuum-with-mapping-6", "basePrice": 219.00, "inventory": 4},
    {"productId": "GC-0005", "slug": "trail-running-shoes-72", "basePrice": 79.99, "inventory": 58},
    {"productId": "GC-0006", "slug": "merino-wool-crewneck-38", "basePrice": 78.00, "inventory": 27},
    {"productId": "GC-0007", "slug": "adjustable-dumbbell-set-5-52lb-60", "basePrice": 299.00, "inventory": 12},
    {"productId": "GC-0008", "slug": "boucl-accent-chair-24", "basePrice": 449.00, "inventory": 9},
    {"productId": "GC-0009", "slug": "kettle-cooked-sea-salt-chips-6-pack-88", "basePrice": 18.00, "inventory": 80},
    {"productId": "GC-0010", "slug": "swiss-automatic-chronograph-41", "basePrice": 6800.00, "inventory": 1},
]


class GhostCartError(RuntimeError):
    """A probe the endpoint rejected or that never got a usable price."""


class GhostCartTarget:
    name = "GhostCart"

    def __init__(
        self,
        secret: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 15.0,
        retries: int = 3,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not secret:
            raise ValueError("GhostCart probe secret is required (GHOSTCART_PROBE_SECRET)")
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={PROBE_HEADER: secret, "Content-Type": "application/json"},
            timeout=timeout,
        )
        self._products: Optional[List[str]] = None

    # -- PricingTarget ------------------------------------------------------

    def product_ids(self) -> List[str]:
        if self._products is None:
            self._products = [p["productId"] for p in self.list_products()]
        return self._products

    def signal_space(self) -> SignalSpace:
        return {k: list(v) for k, v in GHOSTCART_SIGNAL_SPACE.items()}

    def reference_levels(self) -> Dict[SignalType, SignalValue]:
        return dict(GHOSTCART_REFERENCE_LEVELS)

    def quote(self, product_id: str, signals: Mapping[SignalType, SignalValue]) -> float:
        return self.quote_full(product_id, signals)["price"]

    # -- HTTP -------------------------------------------------------------

    def quote_full(self, product_id: str, signals: Mapping[SignalType, SignalValue]) -> Dict[str, Any]:
        """The endpoint's whole response (``price``, ``basePrice``,
        ``appliedRules``). The prober only uses ``price``; ``appliedRules``
        is the store's own answer key and the audit must never read it."""
        body = {"productId": product_id, "signals": {s.value: v for s, v in signals.items()}}
        resp = self._request("POST", ENDPOINT, json=body)
        if resp.status_code == 200:
            data = resp.json()
            if not isinstance(data.get("price"), (int, float)) or data["price"] <= 0:
                raise GhostCartError(f"malformed price in response: {data!r}")
            return data
        raise GhostCartError(_explain(resp))

    def list_products(self) -> List[Dict[str, Any]]:
        """``GET /api/persona-price`` → the audit-enabled subset. Falls
        back to the contract's static table if the call fails."""
        try:
            resp = self._request("GET", ENDPOINT)
        except GhostCartError:
            return list(GHOSTCART_AUDIT_PRODUCTS)
        if resp.status_code != 200:
            return list(GHOSTCART_AUDIT_PRODUCTS)
        data = resp.json()
        items = data.get("products", data) if isinstance(data, dict) else data
        products = [
            {"productId": it, "basePrice": None, "inventory": None} if isinstance(it, str) else it
            for it in items
        ]
        return products or list(GHOSTCART_AUDIT_PRODUCTS)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                last = exc
            else:
                if resp.status_code < 500:
                    return resp
                last = GhostCartError(f"HTTP {resp.status_code} from {path}")
            time.sleep(0.5 * (2**attempt))
        raise GhostCartError(f"{path} failed after {self.retries} attempts: {last}")

    def close(self) -> None:
        self._client.close()


def _explain(resp: httpx.Response) -> str:
    if resp.status_code == 404 and not resp.content:
        return (
            "404 with empty body: gating failed. Check PERSONA_PRICING_ENABLED on "
            "GhostCart and that GHOSTCART_PROBE_SECRET matches PERSONA_PRICING_SECRET."
        )
    try:
        detail = resp.json()
    except ValueError:
        detail = resp.text[:200]
    return f"HTTP {resp.status_code}: {detail}"
