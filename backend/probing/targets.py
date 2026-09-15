"""Pricing targets the factorial prober can run against.

A target describes *what can be varied* (its signal space and the control
level of each signal) and *how to get a price* for one fully-specified
session. The prober never learns anything about the target beyond that,
which is the point: it has to infer the pricing rules from prices alone.

Only two targets exist and only two are meant to: GhostCart, a storefront
Julian owns, and the in-process demo store used by the test suite.
Pointing this at a third-party retailer is out of scope (see PICLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Protocol, Sequence

from audit_engine.models import SignalType
from audit_engine.rigorous import SignalValue

SignalSpace = Dict[SignalType, List[SignalValue]]


class PricingTarget(Protocol):
    """What the factorial prober needs from a store."""

    name: str

    def product_ids(self) -> List[str]: ...

    def signal_space(self) -> SignalSpace:
        """Every level of every signal the prober should randomize over."""
        ...

    def reference_levels(self) -> Dict[SignalType, SignalValue]:
        """The control level of each signal — what "no personalization"
        looks like, and what every other level is compared against."""
        ...

    def quote(self, product_id: str, signals: Mapping[SignalType, SignalValue]) -> float:
        """Price for one session. Must be safe to call from several threads
        if the prober is run with ``concurrency > 1``."""
        ...


# --- Demo store (in-process, for tests) --------------------------------

@dataclass
class DemoStoreTarget:
    """Adapts ``demo_store.DemoStore`` to the target protocol.

    ``signals`` restricts the space (the full 13-signal factorial is far
    too large; the demo store is probed with a random design instead).
    """

    store: object                                   # demo_store.DemoStore
    signals: Optional[Sequence[SignalType]] = None
    name: str = "PriceIntegrity demo storefront"
    _space: SignalSpace = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        from probing.prober import SIGNAL_VARIANTS  # local import: avoids a cycle at package import

        chosen = list(self.signals) if self.signals is not None else list(SIGNAL_VARIANTS)
        self._space = {sig: list(SIGNAL_VARIANTS[sig]) for sig in chosen}

    def product_ids(self) -> List[str]:
        return [p.product_id for p in self.store.catalog]

    def signal_space(self) -> SignalSpace:
        return {k: list(v) for k, v in self._space.items()}

    def reference_levels(self) -> Dict[SignalType, SignalValue]:
        # SIGNAL_VARIANTS lists the control level first for every signal.
        return {sig: levels[0] for sig, levels in self._space.items()}

    def quote(self, product_id: str, signals: Mapping[SignalType, SignalValue]) -> float:
        from demo_store import SessionContext

        ctx = SessionContext()
        for sig, value in signals.items():
            ctx = ctx.with_signal(sig, str(value))
        return self.store.quote(product_id, ctx).price
