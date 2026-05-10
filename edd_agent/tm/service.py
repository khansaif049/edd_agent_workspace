"""Transaction Monitoring agent services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, func, literal, select, union_all
from sqlalchemy.orm import Session

from edd_agent.database.models import (
    Account,
    AlertDisposition,
    Base,
    TmAlert,
    TmAlertEvidence,
    TmScenario,
    Transaction,
)
from edd_agent.edd.repository import load_account_context_orm


SCENARIOS = [
    (
        "KNOWN_LAUNDERING_LABEL",
        "Known laundering label",
        "Ground-truth laundering-labelled transactions are present.",
        "critical",
        {"min_labelled_transactions": 1},
    ),
    (
        "HIGH_VALUE_ACTIVITY",
        "High value activity",
        "Maximum observed transaction exceeds high value threshold or KYC expectation.",
        "high",
        {"min_amount": 1_000_000, "expected_volume_multiplier": 2},
    ),
    (
        "STRUCTURING_BELOW_THRESHOLD",
        "Structuring below threshold",
        "Multiple outgoing transactions occur just below a reporting threshold.",
        "high",
        {"min_daily_count": 5, "min_amount": 9000, "max_amount": 10000},
    ),
    (
        "FAN_OUT",
        "Fan-out distribution",
        "Funds are sent to unusually many unique counterparties.",
        "high",
        {"min_unique_outgoing_counterparties": 250},
    ),
    (
        "FAN_IN",
        "Fan-in aggregation",
        "Funds are received from unusually many unique counterparties.",
        "medium",
        {"min_unique_incoming_counterparties": 250},
    ),
    (
        "RAPID_IN_OUT_MOVEMENT",
        "Rapid in-out movement",
        "Incoming and outgoing activity occurs inside a short window.",
        "high",
        {"window_hours": 24},
    ),
    (
        "CASH_OR_CRYPTO_HEAVY",
        "Cash or crypto exposure",
        "Cash or Bitcoin activity appears in account transaction formats.",
        "medium",
        {"payment_formats": ["Cash", "Bitcoin"]},
    ),
]


@dataclass(frozen=True)
class CandidateAlert:
    scenario_id: str
    priority: str
    risk_score: int
    reason: str
    evidence_type: str
    evidence: dict[str, Any]


def init_tm_schema(session: Session) -> None:
    Base.metadata.create_all(
        bind=session.get_bind(),
        tables=[
            TmScenario.__table__,
            TmAlert.__table__,
            TmAlertEvidence.__table__,
            AlertDisposition.__table__,
        ],
    )
    seed_tm_scenarios(session)


def seed_tm_scenarios(session: Session) -> None:
    for scenario_id, name, description, severity, thresholds in SCENARIOS:
        existing = session.get(TmScenario, scenario_id)
        if existing:
            continue
        session.add(
            TmScenario(
                scenario_id=scenario_id,
                name=name,
                description=description,
                severity=severity,
                threshold_json=json.dumps(thresholds),
                enabled=1,
            )
        )
    session.commit()


def top_active_accounts(session: Session, limit: int) -> list[str]:
    outgoing = select(
        Transaction.from_account.label("account_id"),
        func.count().label("txn_count"),
    ).group_by(Transaction.from_account)
    incoming = select(
        Transaction.to_account.label("account_id"),
        func.count().label("txn_count"),
    ).group_by(Transaction.to_account)
    combined = union_all(outgoing, incoming).subquery()
    rows = session.execute(
        select(combined.c.account_id, func.sum(combined.c.txn_count).label("total_count"))
        .group_by(combined.c.account_id)
        .order_by(desc("total_count"))
        .limit(limit)
    ).all()
    return [row.account_id for row in rows]


def run_tm_scan(session: Session, limit: int = 25, account_id: str | None = None) -> dict[str, Any]:
    init_tm_schema(session)
    accounts = [account_id] if account_id else top_active_accounts(session, limit)
    created_alerts = []
    skipped_duplicates = 0
    scanned = 0
    for acct in accounts:
        if not acct:
            continue
        try:
            context = load_account_context_orm(session, acct)
        except ValueError:
            continue
        scanned += 1
        for candidate in evaluate_tm_scenarios(context):
            if open_alert_exists(session, acct, candidate.scenario_id):
                skipped_duplicates += 1
                continue
            alert = create_tm_alert(session, acct, candidate)
            created_alerts.append(alert)
    session.commit()
    return {
        "scanned_accounts": scanned,
        "created_alerts": len(created_alerts),
        "skipped_duplicates": skipped_duplicates,
        "alerts": created_alerts,
    }


def evaluate_tm_scenarios(context: dict[str, Any]) -> list[CandidateAlert]:
    account = context["account"]
    metrics = context["transaction_metrics"]
    alerts: list[CandidateAlert] = []

    labelled = int(metrics.get("labelled_laundering_transactions") or 0)
    if labelled:
        alerts.append(
            CandidateAlert(
                "KNOWN_LAUNDERING_LABEL",
                "critical",
                95,
                f"{labelled} transactions are labelled as laundering.",
                "transaction_label",
                {"labelled_laundering_transactions": labelled},
            )
        )

    max_amount = float(metrics.get("max_transaction_amount") or 0)
    expected_volume = float(account.get("expected_monthly_volume") or 0)
    high_value_threshold = max(1_000_000, expected_volume * 2 if expected_volume else 1_000_000)
    if max_amount >= high_value_threshold:
        alerts.append(
            CandidateAlert(
                "HIGH_VALUE_ACTIVITY",
                "high",
                82,
                f"Maximum transaction amount {max_amount:,.2f} exceeds threshold {high_value_threshold:,.2f}.",
                "transaction_metric",
                {"max_transaction_amount": max_amount, "threshold": high_value_threshold},
            )
        )

    structuring_days = metrics.get("structuring_days") or []
    if structuring_days:
        top_day = structuring_days[0]
        alerts.append(
            CandidateAlert(
                "STRUCTURING_BELOW_THRESHOLD",
                "high",
                86,
                f"{top_day['txn_count']} outgoing transactions between 9,000 and 10,000 on {top_day['day']}.",
                "transaction_pattern",
                {"structuring_days": structuring_days},
            )
        )

    fan_out = int(metrics.get("unique_outgoing_counterparties") or 0)
    if fan_out >= 250:
        alerts.append(
            CandidateAlert(
                "FAN_OUT",
                "high",
                85,
                f"Account sent funds to {fan_out:,} unique counterparties.",
                "network_pattern",
                {"unique_outgoing_counterparties": fan_out},
            )
        )

    fan_in = int(metrics.get("unique_incoming_counterparties") or 0)
    if fan_in >= 250:
        alerts.append(
            CandidateAlert(
                "FAN_IN",
                "medium",
                68,
                f"Account received funds from {fan_in:,} unique counterparties.",
                "network_pattern",
                {"unique_incoming_counterparties": fan_in},
            )
        )

    rapid = int(metrics.get("rapid_in_out_windows") or 0)
    if rapid:
        alerts.append(
            CandidateAlert(
                "RAPID_IN_OUT_MOVEMENT",
                "high",
                80,
                "Incoming and outgoing movement was observed within 24-hour windows.",
                "temporal_pattern",
                {"rapid_in_out_windows": rapid},
            )
        )

    formats = set(metrics.get("payment_formats") or [])
    risky_formats = sorted(formats & {"Cash", "Bitcoin"})
    if risky_formats and int(metrics.get("total_transactions") or 0) >= 100:
        alerts.append(
            CandidateAlert(
                "CASH_OR_CRYPTO_HEAVY",
                "medium",
                62,
                f"Observed payment formats include {', '.join(risky_formats)}.",
                "payment_format",
                {"payment_formats": sorted(formats), "risky_formats": risky_formats},
            )
        )

    return alerts


def open_alert_exists(session: Session, account_id: str, scenario_id: str) -> bool:
    return bool(
        session.scalar(
            select(TmAlert.alert_id)
            .where(
                TmAlert.account_id == account_id,
                TmAlert.scenario_id == scenario_id,
                TmAlert.status.in_(["open", "in_review", "escalated"]),
            )
            .limit(1)
        )
    )


def create_tm_alert(session: Session, account_id: str, candidate: CandidateAlert) -> dict[str, Any]:
    alert = TmAlert(
        account_id=account_id,
        scenario_id=candidate.scenario_id,
        priority=candidate.priority,
        status="open",
        risk_score=candidate.risk_score,
        reason=candidate.reason,
    )
    session.add(alert)
    session.flush()
    session.add(
        TmAlertEvidence(
            alert_id=alert.alert_id,
            evidence_type=candidate.evidence_type,
            evidence_json=json.dumps(candidate.evidence, default=str),
        )
    )
    return alert_summary(alert)


def alert_summary(alert: TmAlert, account: Account | None = None) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "account_id": alert.account_id,
        "scenario_id": alert.scenario_id,
        "priority": alert.priority,
        "status": alert.status,
        "risk_score": alert.risk_score,
        "reason": alert.reason,
        "created_at": alert.created_at,
        "entity_name": account.entity_name if account else None,
        "bank_name": account.bank_name if account else None,
    }


def list_tm_alerts(session: Session, limit: int = 100) -> list[dict[str, Any]]:
    init_tm_schema(session)
    rows = session.execute(
        select(TmAlert, Account)
        .join(Account, Account.account_id == TmAlert.account_id, isouter=True)
        .order_by(desc(TmAlert.alert_id))
        .limit(limit)
    ).all()
    return [alert_summary(alert, account) for alert, account in rows]


def get_tm_alert_detail(session: Session, alert_id: int) -> dict[str, Any] | None:
    init_tm_schema(session)
    row = session.execute(
        select(TmAlert, Account)
        .join(Account, Account.account_id == TmAlert.account_id, isouter=True)
        .where(TmAlert.alert_id == alert_id)
    ).one_or_none()
    if not row:
        return None
    alert, account = row
    evidence = session.scalars(
        select(TmAlertEvidence)
        .where(TmAlertEvidence.alert_id == alert_id)
        .order_by(TmAlertEvidence.evidence_id)
    ).all()
    dispositions = session.scalars(
        select(AlertDisposition)
        .where(AlertDisposition.alert_id == alert_id)
        .order_by(desc(AlertDisposition.disposition_id))
    ).all()
    detail = alert_summary(alert, account)
    detail["evidence"] = [
        {
            "evidence_id": item.evidence_id,
            "evidence_type": item.evidence_type,
            "evidence_json": json.loads(item.evidence_json),
            "created_at": item.created_at,
        }
        for item in evidence
    ]
    detail["dispositions"] = [
        {
            "disposition_id": item.disposition_id,
            "disposition": item.disposition,
            "notes": item.notes,
            "analyst": item.analyst,
            "created_at": item.created_at,
        }
        for item in dispositions
    ]
    detail["recommended_action"] = recommended_action(alert)
    return detail


def recommended_action(alert: TmAlert) -> str:
    if alert.priority == "critical" or alert.risk_score >= 90:
        return "Escalate to EDD and SAR/STR review."
    if alert.priority == "high" or alert.risk_score >= 75:
        return "Assign analyst review and gather transaction support."
    return "Monitor, document rationale, and close if business activity is explained."


def add_alert_disposition(
    session: Session,
    alert_id: int,
    disposition: str,
    notes: str | None,
    analyst: str | None,
) -> dict[str, Any] | None:
    init_tm_schema(session)
    alert = session.get(TmAlert, alert_id)
    if not alert:
        return None
    session.add(
        AlertDisposition(
            alert_id=alert_id,
            disposition=disposition,
            notes=notes,
            analyst=analyst,
        )
    )
    alert.status = "closed" if disposition in {"false_positive", "explained", "closed"} else "escalated"
    session.commit()
    return get_tm_alert_detail(session, alert_id)
