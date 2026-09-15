"""Sample product catalog for the demo storefront."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    base_price: float
    inventory: int          # default stock level; a session may observe a different one
    category: str

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "base_price": self.base_price,
            "inventory": self.inventory,
            "category": self.category,
        }


CATALOG: List[Product] = [
    Product("SKU-1001", "Wireless Noise-Cancelling Headphones", 54.99, 40, "electronics"),
    Product("SKU-2002", "Adjustable Standing Desk", 349.00, 12, "furniture"),
    Product("SKU-3003", "Trail Running Shoes", 119.00, 60, "apparel"),
    Product("SKU-4004", "Espresso Machine", 229.00, 8, "kitchen"),
]

_BY_ID: Dict[str, Product] = {p.product_id: p for p in CATALOG}


def get_product(product_id: str) -> Product:
    try:
        return _BY_ID[product_id]
    except KeyError:
        raise KeyError(f"unknown product_id {product_id!r}") from None
