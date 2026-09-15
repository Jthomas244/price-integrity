"""Audit engine: classifies observed price variance as market-based
(lawful dynamic pricing) or individual-based (personalized/surveillance
pricing risk)."""

from .models import (
    AuditConfig,
    AuditFinding,
    Category,
    INDIVIDUAL_BASED_SIGNALS,
    MARKET_BASED_SIGNALS,
    ProbeObservation,
    RiskSeverity,
    SignalType,
)
from .engine import AuditEngine
from .rigorous import RegressionDiagnostics, RigorousAuditEngine, SessionObservation
from .report import METHODOLOGY_NOTE, REGRESSION_METHODOLOGY_NOTE, build_report, render_html

__all__ = [
    "AuditConfig",
    "AuditEngine",
    "AuditFinding",
    "Category",
    "INDIVIDUAL_BASED_SIGNALS",
    "METHODOLOGY_NOTE",
    "REGRESSION_METHODOLOGY_NOTE",
    "MARKET_BASED_SIGNALS",
    "ProbeObservation",
    "RegressionDiagnostics",
    "RigorousAuditEngine",
    "SessionObservation",
    "RiskSeverity",
    "SignalType",
    "build_report",
    "render_html",
]
