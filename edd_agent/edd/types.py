"""Small typed helpers for EDD report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RiskFinding:
    rule_id: str
    severity: str
    score: int
    reason: str
    evidence_count: int = 0
    evidence_type: str = "derived_metric"
    evidence_ref: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Recommendation:
    risk_level: str
    text: str
