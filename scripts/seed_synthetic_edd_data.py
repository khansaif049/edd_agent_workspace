#!/usr/bin/env python3
"""Seed synthetic EDD/KYC data into the local AML SQLite database.

The generator is deterministic: the same account_id always gets the same
profile attributes. Existing transaction/account data is preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


DB_PATH = Path("db/finagent_aml.db")
BATCH_SIZE = 5_000

COUNTRIES = [
    ("United States", "North America", "USD", "low"),
    ("United Kingdom", "Europe", "GBP", "low"),
    ("Canada", "North America", "CAD", "low"),
    ("Germany", "Europe", "EUR", "low"),
    ("United Arab Emirates", "Middle East", "AED", "medium"),
    ("Singapore", "Asia Pacific", "SGD", "low"),
    ("India", "Asia Pacific", "INR", "medium"),
    ("Brazil", "Latin America", "BRL", "medium"),
    ("Turkey", "Middle East", "TRY", "medium"),
    ("Mexico", "Latin America", "MXN", "medium"),
    ("China", "Asia Pacific", "CNY", "medium"),
    ("South Africa", "Africa", "ZAR", "medium"),
    ("Panama", "Latin America", "USD", "high"),
    ("Cyprus", "Europe", "EUR", "medium"),
    ("Nigeria", "Africa", "NGN", "high"),
    ("Russia", "Europe", "RUB", "high"),
    ("Iran", "Middle East", "IRR", "high"),
]

INDUSTRIES = [
    ("Retail", "sales revenue", 80_000, 1_200_000),
    ("Import Export", "trade finance proceeds", 250_000, 8_000_000),
    ("Real Estate", "property sale proceeds", 500_000, 15_000_000),
    ("Professional Services", "client payments", 60_000, 1_800_000),
    ("Hospitality", "operating revenue", 40_000, 900_000),
    ("Manufacturing", "commercial revenue", 200_000, 6_000_000),
    ("Crypto Services", "digital asset liquidity", 150_000, 10_000_000),
    ("Money Services Business", "customer remittances", 300_000, 12_000_000),
    ("Charity / NGO", "donations and grants", 30_000, 800_000),
    ("Investment Holding", "investment income", 500_000, 25_000_000),
    ("Government Entity", "public funds", 1_000_000, 50_000_000),
    ("Personal Banking", "salary and savings", 3_000, 60_000),
]

PAYMENT_FORMATS = ["ACH", "Cheque", "Credit Card", "Wire", "Cash", "Bitcoin", "Reinvestment"]
KYC_STATUSES = ["verified", "verified", "verified", "pending_refresh", "enhanced_review"]
ANALYSTS = ["analyst_01", "analyst_02", "analyst_03", "aml_lead", "edd_queue"]
RISK_RULES = [
    ("KNOWN_LAUNDERING_LABEL", "Ground-truth AML label present in transaction history.", "critical", 35, 1),
    ("HIGH_VALUE_ACTIVITY", "Observed movement exceeds expected profile or high-value percentile.", "high", 20, 1),
    ("STRUCTURING_BELOW_THRESHOLD", "Repeated payments just below reporting threshold.", "high", 18, 1),
    ("FAN_OUT", "Funds sent to unusually many unique counterparties.", "high", 15, 1),
    ("FAN_IN", "Funds received from unusually many unique counterparties.", "medium", 10, 1),
    ("RAPID_IN_OUT_MOVEMENT", "Incoming and outgoing movement occurs within a short window.", "high", 18, 1),
    ("KYC_BEHAVIOR_MISMATCH", "Actual behavior materially deviates from expected KYC profile.", "high", 16, 1),
    ("HIGH_RISK_JURISDICTION", "Customer or counterparty exposure to high-risk jurisdiction.", "high", 14, 1),
    ("WATCHLIST_OR_PEP_MATCH", "Potential sanctions, watchlist, or PEP exposure.", "critical", 30, 1),
    ("ADVERSE_MEDIA", "Negative media associated with customer or related party.", "medium", 8, 1),
]


def stable_int(value: str, modulo: int | None = None) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    number = int(digest[:16], 16)
    return number % modulo if modulo else number


def rng_for(value: str) -> random.Random:
    return random.Random(stable_int(value))


def infer_customer_type(entity_name: str) -> str:
    if entity_name.startswith("Corporation"):
        return "corporate"
    if entity_name.startswith("Partnership"):
        return "partnership"
    if entity_name.startswith("Sole Proprietorship"):
        return "sole_proprietor"
    if entity_name.startswith("Individual"):
        return "individual"
    if entity_name.startswith("Country") or entity_name.startswith("Direct"):
        return "institutional"
    return "business"


def choose_profile(account_id: str, entity_name: str, risky: bool) -> dict:
    rnd = rng_for(account_id)
    customer_type = infer_customer_type(entity_name)
    country = rnd.choice(COUNTRIES)
    industry = rnd.choice(INDUSTRIES)

    if customer_type == "individual":
        industry = ("Personal Banking", "salary and savings", 3_000, 60_000)
    elif customer_type == "institutional":
        industry = ("Government Entity", "public funds", 1_000_000, 50_000_000)

    expected_min, expected_max = industry[2], industry[3]
    expected_volume = round(rnd.uniform(expected_min, expected_max), 2)
    expected_txn_count = rnd.randint(8, 280)
    if customer_type in {"corporate", "partnership", "institutional"}:
        expected_txn_count = rnd.randint(80, 2_400)
    if industry[0] in {"Money Services Business", "Crypto Services", "Import Export"}:
        expected_txn_count *= rnd.randint(2, 5)

    expected_currencies = [country[2], "USD"]
    if rnd.random() < 0.45:
        expected_currencies.append(rnd.choice(["EUR", "GBP", "CNY", "AED", "INR"]))
    if industry[0] == "Crypto Services":
        expected_currencies.append("BTC")

    expected_formats = rnd.sample(PAYMENT_FORMATS, k=rnd.randint(2, 4))
    if industry[0] == "Crypto Services" and "Bitcoin" not in expected_formats:
        expected_formats.append("Bitcoin")
    if customer_type == "individual":
        expected_formats = ["ACH", "Credit Card", "Cheque"]

    country_risk = country[3]
    risk_rating = "low"
    if country_risk == "high" or industry[0] in {"Money Services Business", "Crypto Services"}:
        risk_rating = "high"
    elif country_risk == "medium" or industry[0] in {"Import Export", "Real Estate", "Investment Holding"}:
        risk_rating = "medium"
    if risky:
        risk_rating = "high"

    onboarding = date(2018, 1, 1) + timedelta(days=rnd.randint(0, 2_200))
    last_review = date(2026, 1, 1) - timedelta(days=rnd.randint(1, 540))
    next_review = last_review + timedelta(days=365 if risk_rating == "low" else 180)

    return {
        "account_id": account_id,
        "customer_type": customer_type,
        "legal_name": entity_name,
        "country": country[0],
        "region": country[1],
        "industry": industry[0],
        "onboarding_date": onboarding.isoformat(),
        "expected_monthly_volume": expected_volume,
        "expected_monthly_txn_count": expected_txn_count,
        "expected_currencies": json.dumps(sorted(set(expected_currencies))),
        "expected_payment_formats": json.dumps(sorted(set(expected_formats))),
        "expected_counterparty_countries": json.dumps(
            sorted({country[0], rnd.choice(COUNTRIES)[0], rnd.choice(COUNTRIES)[0]})
        ),
        "source_of_funds": industry[1],
        "annual_revenue": round(expected_volume * rnd.uniform(8, 18), 2),
        "employee_count": rnd.randint(1, 18) if customer_type in {"individual", "sole_proprietor"} else rnd.randint(12, 4_500),
        "risk_rating": risk_rating,
        "kyc_status": "enhanced_review" if risky and rnd.random() < 0.55 else rnd.choice(KYC_STATUSES),
        "last_review_date": last_review.isoformat(),
        "next_review_date": next_review.isoformat(),
    }


def create_schema(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS customer_kyc (
            account_id TEXT PRIMARY KEY,
            customer_type TEXT NOT NULL,
            legal_name TEXT NOT NULL,
            country TEXT NOT NULL,
            region TEXT NOT NULL,
            industry TEXT NOT NULL,
            onboarding_date TEXT NOT NULL,
            expected_monthly_volume REAL NOT NULL,
            expected_monthly_txn_count INTEGER NOT NULL,
            expected_currencies TEXT NOT NULL,
            expected_payment_formats TEXT NOT NULL,
            expected_counterparty_countries TEXT NOT NULL,
            source_of_funds TEXT NOT NULL,
            annual_revenue REAL,
            employee_count INTEGER,
            risk_rating TEXT NOT NULL,
            kyc_status TEXT NOT NULL,
            last_review_date TEXT NOT NULL,
            next_review_date TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        );

        CREATE TABLE IF NOT EXISTS beneficial_owners (
            owner_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            nationality TEXT NOT NULL,
            ownership_pct REAL NOT NULL,
            is_pep INTEGER NOT NULL DEFAULT 0,
            date_of_birth TEXT,
            id_doc_type TEXT,
            screening_status TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        );

        CREATE TABLE IF NOT EXISTS watchlists (
            watchlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            list_type TEXT NOT NULL,
            full_name TEXT NOT NULL,
            country TEXT,
            risk_category TEXT NOT NULL,
            reason TEXT NOT NULL,
            active_since TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS screening_matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            watchlist_id INTEGER NOT NULL,
            matched_name TEXT NOT NULL,
            match_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            disposition TEXT NOT NULL,
            screened_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id),
            FOREIGN KEY (watchlist_id) REFERENCES watchlists(watchlist_id)
        );

        CREATE TABLE IF NOT EXISTS adverse_media (
            media_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            headline TEXT NOT NULL,
            source TEXT NOT NULL,
            published_at TEXT NOT NULL,
            risk_topic TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            summary TEXT NOT NULL,
            url TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        );

        CREATE TABLE IF NOT EXISTS risk_rules (
            rule_id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            score_weight INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS edd_cases (
            case_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            trigger_reason TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            assigned_to TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            FOREIGN KEY (account_id) REFERENCES accounts(account_id)
        );

        CREATE TABLE IF NOT EXISTS edd_evidence (
            evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            account_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            evidence_ref TEXT,
            evidence_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES edd_cases(case_id),
            FOREIGN KEY (account_id) REFERENCES accounts(account_id),
            FOREIGN KEY (rule_id) REFERENCES risk_rules(rule_id)
        );

        CREATE TABLE IF NOT EXISTS agent_audit_logs (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            account_id TEXT,
            action TEXT NOT NULL,
            details_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_customer_kyc_risk ON customer_kyc(risk_rating);
        CREATE INDEX IF NOT EXISTS idx_beneficial_owners_account ON beneficial_owners(account_id);
        CREATE INDEX IF NOT EXISTS idx_screening_matches_account ON screening_matches(account_id);
        CREATE INDEX IF NOT EXISTS idx_adverse_media_account ON adverse_media(account_id);
        CREATE INDEX IF NOT EXISTS idx_edd_cases_account ON edd_cases(account_id);
        CREATE INDEX IF NOT EXISTS idx_edd_evidence_account ON edd_evidence(account_id);
        """
    )


def reset_synthetic_tables(cur: sqlite3.Cursor) -> None:
    for table in [
        "agent_audit_logs",
        "edd_evidence",
        "edd_cases",
        "adverse_media",
        "screening_matches",
        "watchlists",
        "beneficial_owners",
        "customer_kyc",
        "risk_rules",
    ]:
        cur.execute(f"DELETE FROM {table}")


def risky_accounts(cur: sqlite3.Cursor, limit: int) -> set[str]:
    rows = cur.execute(
        """
        SELECT account_id
        FROM (
            SELECT from_account AS account_id, COUNT(*) AS c
            FROM transactions
            WHERE is_laundering = 1
            GROUP BY from_account
            UNION ALL
            SELECT to_account AS account_id, COUNT(*) AS c
            FROM transactions
            WHERE is_laundering = 1
            GROUP BY to_account
        )
        GROUP BY account_id
        ORDER BY SUM(c) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return {row[0] for row in rows}


def seed_risk_rules(cur: sqlite3.Cursor) -> None:
    cur.executemany(
        """
        INSERT OR REPLACE INTO risk_rules
            (rule_id, description, severity, score_weight, enabled)
        VALUES (?, ?, ?, ?, ?)
        """,
        RISK_RULES,
    )


def seed_kyc_and_owners(cur: sqlite3.Cursor, risky: set[str]) -> None:
    kyc_batch = []
    owner_batch = []
    owner_first = ["Aarav", "Nora", "Liam", "Sofia", "Omar", "Maya", "Ethan", "Zara", "Leo", "Iris"]
    owner_last = ["Kapoor", "Stone", "Haddad", "Chen", "Patel", "Reed", "Khan", "Rossi", "Silva", "Morgan"]
    read_cur = cur.connection.cursor()

    rows = read_cur.execute("SELECT account_id, entity_name FROM accounts ORDER BY account_id")
    for account_id, entity_name in rows:
        profile = choose_profile(account_id, entity_name or "Unknown Entity", account_id in risky)
        kyc_batch.append(tuple(profile.values()))

        rnd = rng_for(f"owner:{account_id}")
        customer_type = profile["customer_type"]
        owner_count = 0
        if customer_type in {"corporate", "partnership"}:
            owner_count = rnd.randint(1, 4)
        elif customer_type == "sole_proprietor":
            owner_count = 1
        elif customer_type == "individual":
            owner_count = 1

        remaining_pct = 100.0
        for idx in range(owner_count):
            if idx == owner_count - 1:
                pct = remaining_pct
            else:
                pct = round(rnd.uniform(10, max(10.0, remaining_pct - 10)), 2)
                remaining_pct = round(remaining_pct - pct, 2)
            name = f"{rnd.choice(owner_first)} {rnd.choice(owner_last)}"
            nationality = rnd.choice(COUNTRIES)[0]
            dob = date(1950, 1, 1) + timedelta(days=rnd.randint(0, 20_000))
            is_pep = 1 if (account_id in risky and rnd.random() < 0.12) or rnd.random() < 0.006 else 0
            owner_batch.append(
                (
                    account_id,
                    name,
                    nationality,
                    pct,
                    is_pep,
                    dob.isoformat(),
                    rnd.choice(["passport", "national_id", "tax_id"]),
                    "potential_match" if is_pep else "clear",
                )
            )

        if len(kyc_batch) >= BATCH_SIZE:
            insert_kyc(cur, kyc_batch)
            kyc_batch.clear()
        if len(owner_batch) >= BATCH_SIZE:
            insert_owners(cur, owner_batch)
            owner_batch.clear()

    insert_kyc(cur, kyc_batch)
    insert_owners(cur, owner_batch)


def insert_kyc(cur: sqlite3.Cursor, rows: list[tuple]) -> None:
    if not rows:
        return
    cur.executemany(
        """
        INSERT INTO customer_kyc (
            account_id, customer_type, legal_name, country, region, industry,
            onboarding_date, expected_monthly_volume, expected_monthly_txn_count,
            expected_currencies, expected_payment_formats, expected_counterparty_countries,
            source_of_funds, annual_revenue, employee_count, risk_rating, kyc_status,
            last_review_date, next_review_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_owners(cur: sqlite3.Cursor, rows: list[tuple]) -> None:
    if not rows:
        return
    cur.executemany(
        """
        INSERT INTO beneficial_owners (
            account_id, owner_name, nationality, ownership_pct, is_pep,
            date_of_birth, id_doc_type, screening_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def seed_watchlists(cur: sqlite3.Cursor) -> list[int]:
    sources = ["OFAC_SYNTH", "UN_SYNTH", "PEP_SYNTH", "INTERNAL_AML_LIST"]
    list_types = ["sanctions", "pep", "law_enforcement", "internal_watchlist"]
    reasons = [
        "Alleged money laundering facilitation",
        "Politically exposed person",
        "Trade-based money laundering concern",
        "Sanctions evasion typology",
        "Fraud and corruption investigation",
    ]
    names = ["Northbridge", "Al Safa", "Meridian", "Blue Harbor", "Eastern Star", "Silverline", "Cedar", "Atlas"]
    rows = []
    for idx in range(80):
        rnd = rng_for(f"watchlist:{idx}")
        country = rnd.choice(COUNTRIES)[0]
        rows.append(
            (
                rnd.choice(sources),
                rnd.choice(list_types),
                f"{rnd.choice(names)} Subject {idx + 1}",
                country,
                rnd.choice(["high", "critical"]),
                rnd.choice(reasons),
                (date(2019, 1, 1) + timedelta(days=rnd.randint(0, 2_200))).isoformat(),
            )
        )
    cur.executemany(
        """
        INSERT INTO watchlists
            (source, list_type, full_name, country, risk_category, reason, active_since)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return [row[0] for row in cur.execute("SELECT watchlist_id FROM watchlists ORDER BY watchlist_id")]


def seed_matches_media_cases(cur: sqlite3.Cursor, risky: set[str], watchlist_ids: list[int]) -> None:
    selected = list(risky)
    extra = [
        row[0]
        for row in cur.execute(
            """
            SELECT account_id FROM customer_kyc
            WHERE risk_rating = 'high'
            ORDER BY account_id
            LIMIT 500
            """
        )
    ]
    selected = list(dict.fromkeys(selected + extra))[:1_200]

    match_rows = []
    media_rows = []
    case_rows = []
    now = datetime(2026, 5, 10, 10, 0, 0)
    topics = ["sanctions evasion", "fraud allegations", "corruption inquiry", "shell company network", "crypto mixing"]
    sources = ["Global Risk Daily", "Financial Crime Monitor", "Trade Watch Briefing", "Compliance Newswire"]

    for idx, account_id in enumerate(selected):
        rnd = rng_for(f"risk_artifacts:{account_id}")
        if rnd.random() < 0.55:
            match_rows.append(
                (
                    account_id,
                    rnd.choice(watchlist_ids),
                    account_id,
                    rnd.choice(["name_fuzzy", "owner_pep", "jurisdictional", "internal_entity"]),
                    round(rnd.uniform(0.72, 0.98), 3),
                    rnd.choice(["unresolved", "true_positive", "needs_review"]),
                    (now - timedelta(days=rnd.randint(0, 180))).isoformat(timespec="seconds"),
                )
            )
        if rnd.random() < 0.45:
            topic = rnd.choice(topics)
            media_rows.append(
                (
                    account_id,
                    f"Compliance review flags {account_id} for {topic}",
                    rnd.choice(sources),
                    (date(2024, 1, 1) + timedelta(days=rnd.randint(0, 850))).isoformat(),
                    topic,
                    rnd.choice(["negative", "negative", "mixed"]),
                    f"Synthetic adverse media record referencing {topic} indicators for account {account_id}.",
                    f"https://synthetic.local/adverse-media/{account_id}",
                )
            )

        priority = "critical" if idx < 150 else rnd.choice(["high", "high", "medium"])
        case_rows.append(
            (
                account_id,
                rnd.choice(
                    [
                        "Known laundering transaction label",
                        "Watchlist or PEP screening hit",
                        "High-risk jurisdiction and behavior mismatch",
                        "Adverse media requiring EDD review",
                    ]
                ),
                rnd.choice(["open", "in_review", "escalated", "closed"]),
                priority,
                rnd.choice(ANALYSTS),
                (now - timedelta(days=rnd.randint(0, 120))).isoformat(timespec="seconds"),
                None,
            )
        )

    cur.executemany(
        """
        INSERT INTO screening_matches
            (account_id, watchlist_id, matched_name, match_type, confidence, disposition, screened_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        match_rows,
    )
    cur.executemany(
        """
        INSERT INTO adverse_media
            (account_id, headline, source, published_at, risk_topic, sentiment, summary, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        media_rows,
    )
    cur.executemany(
        """
        INSERT INTO edd_cases
            (account_id, trigger_reason, status, priority, assigned_to, opened_at, closed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        case_rows,
    )

    evidence_rows = []
    cases = cur.execute("SELECT case_id, account_id, priority, trigger_reason FROM edd_cases").fetchall()
    for case_id, account_id, priority, trigger_reason in cases:
        severity = "critical" if priority == "critical" else "high"
        rule_id = "KNOWN_LAUNDERING_LABEL" if "laundering" in trigger_reason.lower() else "WATCHLIST_OR_PEP_MATCH"
        evidence_rows.append(
            (
                case_id,
                account_id,
                rule_id,
                severity,
                "synthetic_case_trigger",
                str(case_id),
                json.dumps({"trigger_reason": trigger_reason, "priority": priority}),
            )
        )
    cur.executemany(
        """
        INSERT INTO edd_evidence
            (case_id, account_id, rule_id, severity, evidence_type, evidence_ref, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        evidence_rows,
    )


def print_summary(cur: sqlite3.Cursor) -> None:
    print("Synthetic EDD data seeded.")
    for table in [
        "customer_kyc",
        "beneficial_owners",
        "risk_rules",
        "watchlists",
        "screening_matches",
        "adverse_media",
        "edd_cases",
        "edd_evidence",
        "agent_audit_logs",
    ]:
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count}")
    print("risk_rating:")
    for row in cur.execute("SELECT risk_rating, COUNT(*) FROM customer_kyc GROUP BY risk_rating ORDER BY risk_rating"):
        print(f"  {row[0]}: {row[1]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--reset", action="store_true", help="Clear synthetic tables before seeding")
    parser.add_argument("--risky-limit", type=int, default=2_000, help="Accounts linked to laundering labels to emphasize")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    cur = con.cursor()

    create_schema(cur)
    if args.reset:
        reset_synthetic_tables(cur)
    seed_risk_rules(cur)
    risky = risky_accounts(cur, args.risky_limit)
    seed_kyc_and_owners(cur, risky)
    watchlist_ids = seed_watchlists(cur)
    seed_matches_media_cases(cur, risky, watchlist_ids)

    con.commit()
    print_summary(cur)


if __name__ == "__main__":
    main()
