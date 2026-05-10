"""Collect account, KYC, transaction, screening, and media context."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from edd_agent.database.connection import row_to_dict, rows_to_dicts


def load_account_context(con: sqlite3.Connection, account_id: str) -> dict[str, Any]:
    account = row_to_dict(
        con.execute(
            """
            SELECT a.*, k.customer_type, k.country, k.region, k.industry,
                   k.onboarding_date, k.expected_monthly_volume,
                   k.expected_monthly_txn_count, k.expected_currencies,
                   k.expected_payment_formats, k.expected_counterparty_countries,
                   k.source_of_funds, k.annual_revenue, k.employee_count,
                   k.risk_rating AS kyc_risk_rating, k.kyc_status,
                   k.last_review_date, k.next_review_date
            FROM accounts a
            LEFT JOIN customer_kyc k ON k.account_id = a.account_id
            WHERE a.account_id = ?
            """,
            (account_id,),
        ).fetchone()
    )
    if not account:
        raise ValueError(f"Account not found: {account_id}")

    owners = rows_to_dicts(
        con.execute(
            """
            SELECT owner_id, owner_name, nationality, ownership_pct, is_pep,
                   date_of_birth, id_doc_type, screening_status
            FROM beneficial_owners
            WHERE account_id = ?
            ORDER BY ownership_pct DESC, owner_id
            LIMIT 20
            """,
            (account_id,),
        ).fetchall()
    )
    screening = rows_to_dicts(
        con.execute(
            """
            SELECT sm.match_id, sm.matched_name, sm.match_type, sm.confidence,
                   sm.disposition, sm.screened_at, w.watchlist_id, w.source,
                   w.list_type, w.full_name AS watchlist_name, w.country,
                   w.risk_category, w.reason
            FROM screening_matches sm
            JOIN watchlists w ON w.watchlist_id = sm.watchlist_id
            WHERE sm.account_id = ?
            ORDER BY sm.confidence DESC, sm.match_id
            LIMIT 20
            """,
            (account_id,),
        ).fetchall()
    )
    media = rows_to_dicts(
        con.execute(
            """
            SELECT media_id, headline, source, published_at, risk_topic,
                   sentiment, summary, url
            FROM adverse_media
            WHERE account_id = ?
            ORDER BY published_at DESC, media_id
            LIMIT 20
            """,
            (account_id,),
        ).fetchall()
    )
    cases = rows_to_dicts(
        con.execute(
            """
            SELECT case_id, trigger_reason, status, priority, assigned_to,
                   opened_at, closed_at
            FROM edd_cases
            WHERE account_id = ?
            ORDER BY opened_at DESC, case_id DESC
            LIMIT 10
            """,
            (account_id,),
        ).fetchall()
    )

    return {
        "account": normalize_json_fields(account),
        "beneficial_owners": owners,
        "screening_matches": screening,
        "adverse_media": media,
        "existing_cases": cases,
        "transaction_metrics": load_transaction_metrics(con, account_id),
        "sample_transactions": load_sample_transactions(con, account_id),
    }


def normalize_json_fields(account: dict[str, Any]) -> dict[str, Any]:
    for key in ["expected_currencies", "expected_payment_formats", "expected_counterparty_countries"]:
        value = account.get(key)
        if isinstance(value, str):
            try:
                account[key] = json.loads(value)
            except json.JSONDecodeError:
                account[key] = [value]
    return account


def load_transaction_metrics(con: sqlite3.Connection, account_id: str) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS total_transactions,
            SUM(CASE WHEN to_account = ? THEN 1 ELSE 0 END) AS incoming_transactions,
            SUM(CASE WHEN from_account = ? THEN 1 ELSE 0 END) AS outgoing_transactions,
            COALESCE(SUM(CASE WHEN to_account = ? THEN amount_received ELSE 0 END), 0) AS total_incoming_amount,
            COALESCE(SUM(CASE WHEN from_account = ? THEN amount_paid ELSE 0 END), 0) AS total_outgoing_amount,
            MAX(CASE
                WHEN from_account = ? THEN amount_paid
                WHEN to_account = ? THEN amount_received
                ELSE 0
            END) AS max_transaction_amount,
            COUNT(DISTINCT CASE WHEN to_account = ? THEN from_account END) AS unique_incoming_counterparties,
            COUNT(DISTINCT CASE WHEN from_account = ? THEN to_account END) AS unique_outgoing_counterparties,
            COUNT(DISTINCT CASE
                WHEN from_account = ? THEN to_bank
                WHEN to_account = ? THEN from_bank
            END) AS unique_banks_touched,
            SUM(CASE WHEN is_laundering = 1 THEN 1 ELSE 0 END) AS labelled_laundering_transactions,
            MIN(timestamp) AS first_seen,
            MAX(timestamp) AS last_seen
        FROM transactions
        WHERE from_account = ? OR to_account = ?
        """,
        (
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
            account_id,
        ),
    ).fetchone()
    metrics = row_to_dict(row) or {}
    metrics["unique_counterparties"] = (
        metrics.get("unique_incoming_counterparties") or 0
    ) + (metrics.get("unique_outgoing_counterparties") or 0)
    metrics["currencies"] = distinct_values(con, account_id, "currency")
    metrics["payment_formats"] = distinct_values(con, account_id, "payment_format")
    metrics["structuring_days"] = structuring_days(con, account_id)
    metrics["rapid_in_out_windows"] = rapid_in_out_count(con, account_id)
    return metrics


def distinct_values(con: sqlite3.Connection, account_id: str, value_type: str) -> list[str]:
    if value_type == "currency":
        sql = """
            SELECT value FROM (
                SELECT receiving_currency AS value FROM transactions WHERE to_account = ?
                UNION
                SELECT payment_currency AS value FROM transactions WHERE from_account = ?
            )
            WHERE value IS NOT NULL
            ORDER BY value
        """
    else:
        sql = """
            SELECT DISTINCT payment_format AS value
            FROM transactions
            WHERE (from_account = ? OR to_account = ?) AND payment_format IS NOT NULL
            ORDER BY payment_format
        """
    return [row["value"] for row in con.execute(sql, (account_id, account_id)).fetchall()]


def structuring_days(con: sqlite3.Connection, account_id: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT DATE(timestamp) AS day, COUNT(*) AS txn_count, ROUND(SUM(amount_paid), 2) AS total_amount
        FROM transactions
        WHERE from_account = ? AND amount_paid BETWEEN 9000 AND 10000
        GROUP BY DATE(timestamp)
        HAVING COUNT(*) >= 5
        ORDER BY txn_count DESC
        LIMIT 10
        """,
        (account_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def rapid_in_out_count(con: sqlite3.Connection, account_id: str) -> int:
    row = con.execute(
        """
        WITH incoming AS (
            SELECT timestamp FROM transactions WHERE to_account = ? LIMIT 250
        ),
        outgoing AS (
            SELECT timestamp FROM transactions WHERE from_account = ? LIMIT 250
        )
        SELECT COUNT(*) AS windows
        FROM incoming i
        JOIN outgoing o
          ON ABS(strftime('%s', o.timestamp) - strftime('%s', i.timestamp)) <= 86400
        """,
        (account_id, account_id),
    ).fetchone()
    return int(row["windows"] or 0)


def load_sample_transactions(con: sqlite3.Connection, account_id: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT transaction_id, timestamp, from_account, to_account, amount_paid,
               payment_currency, amount_received, receiving_currency, payment_format,
               is_laundering
        FROM transactions
        WHERE from_account = ? OR to_account = ?
        ORDER BY is_laundering DESC,
                 CASE WHEN from_account = ? THEN amount_paid ELSE amount_received END DESC
        LIMIT 15
        """,
        (account_id, account_id, account_id),
    ).fetchall()
    return rows_to_dicts(rows)
