"""Deterministic risk rules for EDD investigations."""

from __future__ import annotations

from typing import Any

from .types import Recommendation, RiskFinding


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
CURRENCY_ALIASES = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "UK Pound",
    "CNY": "Yuan",
    "INR": "Rupee",
    "RUB": "Ruble",
    "BTC": "Bitcoin",
}


def evaluate(context: dict[str, Any]) -> list[RiskFinding]:
    account = context["account"]
    metrics = context["transaction_metrics"]
    findings: list[RiskFinding] = []

    labelled = int(metrics.get("labelled_laundering_transactions") or 0)
    if labelled:
        findings.append(
            RiskFinding(
                "KNOWN_LAUNDERING_LABEL",
                "critical",
                35,
                f"{labelled} transactions carry a laundering label in the dataset.",
                labelled,
                "transaction_label",
                details={"labelled_laundering_transactions": labelled},
            )
        )

    expected_volume = float(account.get("expected_monthly_volume") or 0)
    actual_volume = float(metrics.get("total_incoming_amount") or 0) + float(metrics.get("total_outgoing_amount") or 0)
    if expected_volume and actual_volume > expected_volume * 5:
        findings.append(
            RiskFinding(
                "KYC_BEHAVIOR_MISMATCH",
                "high",
                16,
                f"Actual observed value {actual_volume:,.2f} is more than 5x expected monthly volume {expected_volume:,.2f}.",
                1,
                "kyc_metric",
                details={"actual_value": round(actual_volume, 2), "expected_monthly_volume": expected_volume},
            )
        )

    max_amount = float(metrics.get("max_transaction_amount") or 0)
    if max_amount >= max(1_000_000, expected_volume * 2 if expected_volume else 1_000_000):
        findings.append(
            RiskFinding(
                "HIGH_VALUE_ACTIVITY",
                "high",
                20,
                f"Maximum transaction amount reached {max_amount:,.2f}.",
                1,
                "transaction_metric",
                details={"max_transaction_amount": round(max_amount, 2)},
            )
        )

    structuring = metrics.get("structuring_days") or []
    if structuring:
        top = structuring[0]
        findings.append(
            RiskFinding(
                "STRUCTURING_BELOW_THRESHOLD",
                "high",
                18,
                f"{top['txn_count']} outgoing transactions between 9,000 and 10,000 occurred on {top['day']}.",
                int(top["txn_count"]),
                "transaction_pattern",
                details={"days": structuring},
            )
        )

    outgoing_counterparties = int(metrics.get("unique_outgoing_counterparties") or 0)
    if outgoing_counterparties >= 250:
        findings.append(
            RiskFinding(
                "FAN_OUT",
                "high",
                15,
                f"Funds were sent to {outgoing_counterparties:,} unique counterparties.",
                outgoing_counterparties,
                "network_pattern",
                details={"unique_outgoing_counterparties": outgoing_counterparties},
            )
        )

    incoming_counterparties = int(metrics.get("unique_incoming_counterparties") or 0)
    if incoming_counterparties >= 250:
        findings.append(
            RiskFinding(
                "FAN_IN",
                "medium",
                10,
                f"Funds were received from {incoming_counterparties:,} unique counterparties.",
                incoming_counterparties,
                "network_pattern",
                details={"unique_incoming_counterparties": incoming_counterparties},
            )
        )

    rapid = int(metrics.get("rapid_in_out_windows") or 0)
    if rapid:
        findings.append(
            RiskFinding(
                "RAPID_IN_OUT_MOVEMENT",
                "high",
                18,
                "Incoming and outgoing activity occurred within 24-hour windows.",
                rapid,
                "temporal_pattern",
                details={"rapid_in_out_windows": rapid},
            )
        )

    expected_currencies = {CURRENCY_ALIASES.get(value, value) for value in account.get("expected_currencies") or []}
    unexpected_currencies = sorted(set(metrics.get("currencies") or []) - expected_currencies)
    if unexpected_currencies:
        score = 14 if {"Bitcoin", "Ruble"} & set(unexpected_currencies) else 8
        severity = "high" if score >= 14 else "medium"
        findings.append(
            RiskFinding(
                "KYC_BEHAVIOR_MISMATCH",
                severity,
                score,
                f"Observed currencies outside KYC expectation: {', '.join(unexpected_currencies[:6])}.",
                len(unexpected_currencies),
                "kyc_metric",
                details={"unexpected_currencies": unexpected_currencies},
            )
        )

    if account.get("kyc_risk_rating") == "high" or account.get("country") in {"Iran", "Russia", "Nigeria", "Panama"}:
        findings.append(
            RiskFinding(
                "HIGH_RISK_JURISDICTION",
                "high",
                14,
                f"KYC profile is high risk for country/rating: {account.get('country')} / {account.get('kyc_risk_rating')}.",
                1,
                "kyc_profile",
                details={"country": account.get("country"), "kyc_risk_rating": account.get("kyc_risk_rating")},
            )
        )

    pep_owners = [owner for owner in context["beneficial_owners"] if owner.get("is_pep")]
    screening = context["screening_matches"]
    if screening or pep_owners:
        findings.append(
            RiskFinding(
                "WATCHLIST_OR_PEP_MATCH",
                "critical" if screening else "high",
                30 if screening else 18,
                f"{len(screening)} screening matches and {len(pep_owners)} PEP owner flags found.",
                len(screening) + len(pep_owners),
                "screening",
                details={"screening_matches": screening[:5], "pep_owners": pep_owners[:5]},
            )
        )

    media = context["adverse_media"]
    if media:
        findings.append(
            RiskFinding(
                "ADVERSE_MEDIA",
                "medium",
                8,
                f"{len(media)} adverse media records found.",
                len(media),
                "adverse_media",
                details={"adverse_media": media[:5]},
            )
        )

    return sorted(findings, key=lambda item: (-SEVERITY_RANK[item.severity], -item.score, item.rule_id))


def calculate_score(findings: list[RiskFinding]) -> int:
    return min(100, sum(finding.score for finding in findings))


def risk_level(score: int, findings: list[RiskFinding]) -> str:
    if any(f.severity == "critical" for f in findings) or score >= 80:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def recommendation(level: str) -> Recommendation:
    mapping = {
        "critical": "Escalate to AML investigator and prepare SAR/STR review.",
        "high": "Open enhanced review, obtain supporting documents, and increase monitoring.",
        "medium": "Continue monitoring and refresh KYC at the next review checkpoint.",
        "low": "No immediate EDD escalation required; keep standard monitoring active.",
    }
    return Recommendation(level, mapping[level])
