"""ORM-backed account investigation queries."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import case, desc, distinct, func, or_, select
from sqlalchemy.orm import Session

from edd_agent.database.models import (
    Account,
    AdverseMedia,
    BeneficialOwner,
    CustomerKyc,
    EddCase,
    ScreeningMatch,
    Transaction,
    Watchlist,
)


def model_to_dict(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


def load_account_context_orm(session: Session, account_id: str) -> dict[str, Any]:
    account_row = session.execute(
        select(Account, CustomerKyc)
        .join(CustomerKyc, CustomerKyc.account_id == Account.account_id, isouter=True)
        .where(Account.account_id == account_id)
    ).one_or_none()
    if not account_row:
        raise ValueError(f"Account not found: {account_id}")

    account, kyc = account_row
    account_dict = {
        "account_id": account.account_id,
        "bank_id": account.bank_id,
        "bank_name": account.bank_name,
        "entity_id": account.entity_id,
        "entity_name": account.entity_name,
        "is_placeholder": account.is_placeholder,
    }
    if kyc:
        account_dict.update(
            {
                "customer_type": kyc.customer_type,
                "country": kyc.country,
                "region": kyc.region,
                "industry": kyc.industry,
                "onboarding_date": kyc.onboarding_date,
                "expected_monthly_volume": kyc.expected_monthly_volume,
                "expected_monthly_txn_count": kyc.expected_monthly_txn_count,
                "expected_currencies": load_json_list(kyc.expected_currencies),
                "expected_payment_formats": load_json_list(kyc.expected_payment_formats),
                "expected_counterparty_countries": load_json_list(kyc.expected_counterparty_countries),
                "source_of_funds": kyc.source_of_funds,
                "annual_revenue": kyc.annual_revenue,
                "employee_count": kyc.employee_count,
                "kyc_risk_rating": kyc.risk_rating,
                "kyc_status": kyc.kyc_status,
                "last_review_date": kyc.last_review_date,
                "next_review_date": kyc.next_review_date,
            }
        )

    return {
        "account": account_dict,
        "beneficial_owners": load_beneficial_owners(session, account_id),
        "screening_matches": load_screening_matches(session, account_id),
        "adverse_media": load_adverse_media(session, account_id),
        "existing_cases": load_cases(session, account_id),
        "transaction_metrics": load_transaction_metrics_orm(session, account_id),
        "sample_transactions": load_sample_transactions_orm(session, account_id),
    }


def load_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else [str(data)]
    except json.JSONDecodeError:
        return [value]


def load_beneficial_owners(session: Session, account_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(BeneficialOwner)
        .where(BeneficialOwner.account_id == account_id)
        .order_by(desc(BeneficialOwner.ownership_pct), BeneficialOwner.owner_id)
        .limit(20)
    ).all()
    fields = [
        "owner_id",
        "owner_name",
        "nationality",
        "ownership_pct",
        "is_pep",
        "date_of_birth",
        "id_doc_type",
        "screening_status",
    ]
    return [model_to_dict(row, fields) for row in rows]


def load_screening_matches(session: Session, account_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ScreeningMatch, Watchlist)
        .join(Watchlist, Watchlist.watchlist_id == ScreeningMatch.watchlist_id)
        .where(ScreeningMatch.account_id == account_id)
        .order_by(desc(ScreeningMatch.confidence), ScreeningMatch.match_id)
        .limit(20)
    ).all()
    output = []
    for match, watchlist in rows:
        output.append(
            {
                "match_id": match.match_id,
                "matched_name": match.matched_name,
                "match_type": match.match_type,
                "confidence": match.confidence,
                "disposition": match.disposition,
                "screened_at": match.screened_at,
                "watchlist_id": watchlist.watchlist_id,
                "source": watchlist.source,
                "list_type": watchlist.list_type,
                "watchlist_name": watchlist.full_name,
                "country": watchlist.country,
                "risk_category": watchlist.risk_category,
                "reason": watchlist.reason,
            }
        )
    return output


def load_adverse_media(session: Session, account_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AdverseMedia)
        .where(AdverseMedia.account_id == account_id)
        .order_by(desc(AdverseMedia.published_at), AdverseMedia.media_id)
        .limit(20)
    ).all()
    fields = ["media_id", "headline", "source", "published_at", "risk_topic", "sentiment", "summary", "url"]
    return [model_to_dict(row, fields) for row in rows]


def load_cases(session: Session, account_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(EddCase)
        .where(EddCase.account_id == account_id)
        .order_by(desc(EddCase.opened_at), desc(EddCase.case_id))
        .limit(10)
    ).all()
    fields = ["case_id", "trigger_reason", "status", "priority", "assigned_to", "opened_at", "closed_at"]
    return [model_to_dict(row, fields) for row in rows]


def load_transaction_metrics_orm(session: Session, account_id: str) -> dict[str, Any]:
    stmt = select(
        func.count().label("total_transactions"),
        func.sum(case((Transaction.to_account == account_id, 1), else_=0)).label("incoming_transactions"),
        func.sum(case((Transaction.from_account == account_id, 1), else_=0)).label("outgoing_transactions"),
        func.coalesce(
            func.sum(case((Transaction.to_account == account_id, Transaction.amount_received), else_=0)),
            0,
        ).label("total_incoming_amount"),
        func.coalesce(
            func.sum(case((Transaction.from_account == account_id, Transaction.amount_paid), else_=0)),
            0,
        ).label("total_outgoing_amount"),
        func.max(
            case(
                (Transaction.from_account == account_id, Transaction.amount_paid),
                (Transaction.to_account == account_id, Transaction.amount_received),
                else_=0,
            )
        ).label("max_transaction_amount"),
        func.count(distinct(case((Transaction.to_account == account_id, Transaction.from_account)))).label(
            "unique_incoming_counterparties"
        ),
        func.count(distinct(case((Transaction.from_account == account_id, Transaction.to_account)))).label(
            "unique_outgoing_counterparties"
        ),
        func.count(
            distinct(
                case(
                    (Transaction.from_account == account_id, Transaction.to_bank),
                    (Transaction.to_account == account_id, Transaction.from_bank),
                )
            )
        ).label("unique_banks_touched"),
        func.sum(case((Transaction.is_laundering == 1, 1), else_=0)).label("labelled_laundering_transactions"),
        func.min(Transaction.timestamp).label("first_seen"),
        func.max(Transaction.timestamp).label("last_seen"),
    ).where(or_(Transaction.from_account == account_id, Transaction.to_account == account_id))

    row = session.execute(stmt).mappings().one()
    metrics = dict(row)
    metrics["unique_counterparties"] = (
        metrics.get("unique_incoming_counterparties") or 0
    ) + (metrics.get("unique_outgoing_counterparties") or 0)
    metrics["currencies"] = load_currencies(session, account_id)
    metrics["payment_formats"] = load_payment_formats(session, account_id)
    metrics["structuring_days"] = load_structuring_days(session, account_id)
    metrics["rapid_in_out_windows"] = load_rapid_in_out_count(session, account_id)
    return metrics


def load_currencies(session: Session, account_id: str) -> list[str]:
    incoming = session.scalars(
        select(distinct(Transaction.receiving_currency))
        .where(Transaction.to_account == account_id, Transaction.receiving_currency.is_not(None))
    ).all()
    outgoing = session.scalars(
        select(distinct(Transaction.payment_currency))
        .where(Transaction.from_account == account_id, Transaction.payment_currency.is_not(None))
    ).all()
    return sorted({value for value in [*incoming, *outgoing] if value})


def load_payment_formats(session: Session, account_id: str) -> list[str]:
    rows = session.scalars(
        select(distinct(Transaction.payment_format))
        .where(
            or_(Transaction.from_account == account_id, Transaction.to_account == account_id),
            Transaction.payment_format.is_not(None),
        )
        .order_by(Transaction.payment_format)
    ).all()
    return [row for row in rows if row]


def load_structuring_days(session: Session, account_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            func.date(Transaction.timestamp).label("day"),
            func.count().label("txn_count"),
            func.round(func.sum(Transaction.amount_paid), 2).label("total_amount"),
        )
        .where(
            Transaction.from_account == account_id,
            Transaction.amount_paid.between(9000, 10000),
        )
        .group_by(func.date(Transaction.timestamp))
        .having(func.count() >= 5)
        .order_by(desc("txn_count"))
        .limit(10)
    ).mappings()
    return [dict(row) for row in rows]


def load_rapid_in_out_count(session: Session, account_id: str) -> int:
    incoming = session.scalars(
        select(Transaction.timestamp).where(Transaction.to_account == account_id).limit(250)
    ).all()
    outgoing = session.scalars(
        select(Transaction.timestamp).where(Transaction.from_account == account_id).limit(250)
    ).all()
    incoming_dt = [parse_timestamp(value) for value in incoming]
    outgoing_dt = [parse_timestamp(value) for value in outgoing]
    return sum(
        1
        for in_time in incoming_dt
        for out_time in outgoing_dt
        if in_time and out_time and abs((out_time - in_time).total_seconds()) <= 86_400
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def load_sample_transactions_orm(session: Session, account_id: str) -> list[dict[str, Any]]:
    amount_sort = case(
        (Transaction.from_account == account_id, Transaction.amount_paid),
        else_=Transaction.amount_received,
    )
    rows = session.scalars(
        select(Transaction)
        .where(or_(Transaction.from_account == account_id, Transaction.to_account == account_id))
        .order_by(desc(Transaction.is_laundering), desc(amount_sort))
        .limit(15)
    ).all()
    fields = [
        "transaction_id",
        "timestamp",
        "from_account",
        "to_account",
        "amount_paid",
        "payment_currency",
        "amount_received",
        "receiving_currency",
        "payment_format",
        "is_laundering",
    ]
    return [model_to_dict(row, fields) for row in rows]


def sample_accounts_orm(session: Session) -> list[dict[str, Any]]:
    case_rows = session.execute(
        select(
            Account.account_id,
            Account.entity_name,
            Account.bank_name,
            CustomerKyc.country,
            CustomerKyc.industry,
            CustomerKyc.risk_rating,
            func.count(EddCase.case_id).label("case_count"),
        )
        .join(CustomerKyc, CustomerKyc.account_id == Account.account_id)
        .join(EddCase, EddCase.account_id == Account.account_id)
        .group_by(Account.account_id)
        .order_by(desc("case_count"), Account.account_id)
        .limit(12)
    ).mappings()
    samples = [dict(row) for row in case_rows]
    seen = {row["account_id"] for row in samples}
    if len(samples) >= 12:
        return samples

    high_risk_rows = session.execute(
        select(
            Account.account_id,
            Account.entity_name,
            Account.bank_name,
            CustomerKyc.country,
            CustomerKyc.industry,
            CustomerKyc.risk_rating,
        )
        .join(CustomerKyc, CustomerKyc.account_id == Account.account_id)
        .where(CustomerKyc.risk_rating == "high")
        .order_by(Account.account_id)
        .limit(24)
    ).mappings()
    for row in high_risk_rows:
        item = dict(row)
        if item["account_id"] in seen:
            continue
        item["case_count"] = 0
        samples.append(item)
        if len(samples) == 12:
            break
    return samples
