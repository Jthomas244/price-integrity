"""FactorialProber: randomized factorial sessions for the regression engine.

The one-at-a-time ``Prober`` varies a single signal against a fixed control
session. That is easy to read but it can't see interactions, and against a
store whose rules compound (mobile × abandoned cart) it under-measures.

This prober assigns *every* signal a value in *every* session:

  - ``full`` design: the Cartesian product of every level of every signal,
    repeated ``replicates`` times. Balanced and orthogonal, so each effect
    is estimated with maximum precision for the number of sessions. Used
    for GhostCart (4 signals, 192 cells).
  - ``random`` design: ``n_sessions`` sessions with each signal drawn
    uniformly and independently. Used when the full factorial is too big
    (the demo store's 13 signals).

Either way the assignment is randomized, so the data is a randomized
experiment and the engine's coefficients are causal effects of each signal.

Session order is shuffled so a target whose prices drift over time can't
confound a signal that happened to be probed late.
"""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product as cartesian
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from audit_engine.models import SignalType
from audit_engine.rigorous import SessionObservation, SignalValue

from .targets import PricingTarget


@dataclass
class ProbeFailure:
    product_id: str
    signals: Dict[str, SignalValue]
    error: str


@dataclass
class FactorialRun:
    target: str
    design: str
    observations: List[SessionObservation] = field(default_factory=list)
    failures: List[ProbeFailure] = field(default_factory=list)
    products_probed: List[str] = field(default_factory=list)
    signals_probed: List[str] = field(default_factory=list)
    signal_space: Dict[str, List[SignalValue]] = field(default_factory=dict)
    reference_levels: Dict[str, SignalValue] = field(default_factory=dict)
    cells: int = 0                 # distinct signal combinations per product
    replicates: int = 1
    started_at: str = ""
    finished_at: str = ""

    @property
    def session_count(self) -> int:
        return len(self.observations)

    @property
    def sessions_per_product(self) -> int:
        return self.cells * self.replicates

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "design": self.design,
            "products_probed": list(self.products_probed),
            "signals_probed": list(self.signals_probed),
            "signal_space": {k: list(v) for k, v in self.signal_space.items()},
            "reference_levels": dict(self.reference_levels),
            "cells_per_product": self.cells,
            "replicates": self.replicates,
            "sessions_per_product": self.sessions_per_product,
            "session_count": self.session_count,
            "failure_count": len(self.failures),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class FactorialProber:
    def __init__(
        self,
        target: PricingTarget,
        *,
        design: str = "full",
        replicates: int = 1,
        n_sessions: Optional[int] = None,
        seed: int = 42,
        concurrency: int = 1,
    ) -> None:
        if design not in ("full", "random"):
            raise ValueError("design must be 'full' or 'random'")
        if design == "random" and not n_sessions:
            raise ValueError("random design needs n_sessions")
        if replicates < 1:
            raise ValueError("replicates must be >= 1")
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.target = target
        self.design = design
        self.replicates = replicates
        self.n_sessions = n_sessions
        self.seed = seed
        self.concurrency = concurrency

    # -- design ------------------------------------------------------------

    def sessions_for(self, rng: random.Random) -> List[Dict[SignalType, SignalValue]]:
        """The signal assignments for one product, in shuffled order."""
        space = self.target.signal_space()
        signals = sorted(space, key=lambda s: s.value)
        if self.design == "full":
            cells = [dict(zip(signals, combo)) for combo in cartesian(*(space[s] for s in signals))]
            sessions = [dict(c) for c in cells for _ in range(self.replicates)]
        else:
            assert self.n_sessions is not None
            sessions = [{s: rng.choice(space[s]) for s in signals} for _ in range(self.n_sessions)]
        rng.shuffle(sessions)
        return sessions

    def cell_count(self) -> int:
        space = self.target.signal_space()
        if self.design == "full":
            n = 1
            for levels in space.values():
                n *= len(levels)
            return n
        assert self.n_sessions is not None
        return self.n_sessions

    # -- execution ---------------------------------------------------------

    def run(self, product_ids: Optional[Iterable[str]] = None) -> FactorialRun:
        products = list(product_ids) if product_ids is not None else self.target.product_ids()
        space = self.target.signal_space()
        run = FactorialRun(
            target=self.target.name,
            design=self.design,
            products_probed=products,
            signals_probed=[s.value for s in sorted(space, key=lambda s: s.value)],
            signal_space={s.value: list(v) for s, v in space.items()},
            reference_levels={s.value: v for s, v in self.target.reference_levels().items()},
            cells=self.cell_count(),
            replicates=self.replicates if self.design == "full" else 1,
            started_at=_now(),
        )

        rng = random.Random(self.seed)
        jobs: List[Tuple[str, Dict[SignalType, SignalValue]]] = [
            (pid, session) for pid in products for session in self.sessions_for(rng)
        ]

        if self.concurrency == 1:
            results = [self._probe(pid, s) for pid, s in jobs]
        else:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                results = list(pool.map(lambda j: self._probe(*j), jobs))

        for item in results:
            (run.observations if isinstance(item, SessionObservation) else run.failures).append(item)
        run.finished_at = _now()
        return run

    def _probe(self, product_id: str, signals: Mapping[SignalType, SignalValue]):
        try:
            price = self.target.quote(product_id, signals)
            return SessionObservation(product_id=product_id, price=price, signals=dict(signals), timestamp=_now())
        except Exception as exc:  # a failed session is recorded, never fabricated
            return ProbeFailure(product_id, {s.value: v for s, v in signals.items()}, f"{type(exc).__name__}: {exc}")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
