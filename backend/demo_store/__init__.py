"""A fully-controlled demo storefront with deliberately variable pricing.

Some rules are market-based, some are individual-based — on purpose.
That's what makes the demo honest: the audit engine has something real
to find, and some signals it should correctly report as clean.
"""

from .catalog import CATALOG, Product, get_product
from .pricing_rules import DEFAULT_RULES, DemoStore, PricingRule, Quote, SessionContext

__all__ = [
    "CATALOG",
    "DEFAULT_RULES",
    "DemoStore",
    "PricingRule",
    "Product",
    "Quote",
    "SessionContext",
    "get_product",
]
