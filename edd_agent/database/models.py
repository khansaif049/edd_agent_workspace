"""SQLAlchemy ORM models and session helpers for the AML database."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import Float, ForeignKey, Integer, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .connection import DEFAULT_DB_PATH


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    bank_id: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    entity_name: Mapped[str | None] = mapped_column(Text)
    is_placeholder: Mapped[int] = mapped_column(Integer, default=0)

    kyc: Mapped["CustomerKyc | None"] = relationship(back_populates="account", uselist=False)


class CustomerKyc(Base):
    __tablename__ = "customer_kyc"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), primary_key=True)
    customer_type: Mapped[str] = mapped_column(Text)
    legal_name: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(Text)
    onboarding_date: Mapped[str] = mapped_column(Text)
    expected_monthly_volume: Mapped[float] = mapped_column(Float)
    expected_monthly_txn_count: Mapped[int] = mapped_column(Integer)
    expected_currencies: Mapped[str] = mapped_column(Text)
    expected_payment_formats: Mapped[str] = mapped_column(Text)
    expected_counterparty_countries: Mapped[str] = mapped_column(Text)
    source_of_funds: Mapped[str] = mapped_column(Text)
    annual_revenue: Mapped[float | None] = mapped_column(Float)
    employee_count: Mapped[int | None] = mapped_column(Integer)
    risk_rating: Mapped[str] = mapped_column(Text)
    kyc_status: Mapped[str] = mapped_column(Text)
    last_review_date: Mapped[str] = mapped_column(Text)
    next_review_date: Mapped[str] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="kyc")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[str] = mapped_column(Text)
    from_bank: Mapped[str | None] = mapped_column(Text)
    from_account: Mapped[str] = mapped_column(Text)
    to_bank: Mapped[str | None] = mapped_column(Text)
    to_account: Mapped[str] = mapped_column(Text)
    amount_received: Mapped[float] = mapped_column(Float)
    receiving_currency: Mapped[str | None] = mapped_column(Text)
    amount_paid: Mapped[float] = mapped_column(Float)
    payment_currency: Mapped[str | None] = mapped_column(Text)
    payment_format: Mapped[str | None] = mapped_column(Text)
    is_laundering: Mapped[int] = mapped_column(Integer, default=0)


class BeneficialOwner(Base):
    __tablename__ = "beneficial_owners"

    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    owner_name: Mapped[str] = mapped_column(Text)
    nationality: Mapped[str] = mapped_column(Text)
    ownership_pct: Mapped[float] = mapped_column(Float)
    is_pep: Mapped[int] = mapped_column(Integer, default=0)
    date_of_birth: Mapped[str | None] = mapped_column(Text)
    id_doc_type: Mapped[str | None] = mapped_column(Text)
    screening_status: Mapped[str] = mapped_column(Text)


class Watchlist(Base):
    __tablename__ = "watchlists"

    watchlist_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    list_type: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    risk_category: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    active_since: Mapped[str] = mapped_column(Text)


class ScreeningMatch(Base):
    __tablename__ = "screening_matches"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.watchlist_id"))
    matched_name: Mapped[str] = mapped_column(Text)
    match_type: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    disposition: Mapped[str] = mapped_column(Text)
    screened_at: Mapped[str] = mapped_column(Text)

    watchlist: Mapped[Watchlist] = relationship()


class AdverseMedia(Base):
    __tablename__ = "adverse_media"

    media_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    headline: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str] = mapped_column(Text)
    risk_topic: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)


class EddCase(Base):
    __tablename__ = "edd_cases"

    case_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    trigger_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[str] = mapped_column(Text)
    closed_at: Mapped[str | None] = mapped_column(Text)


class EddReport(Base):
    __tablename__ = "edd_reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(Text)
    edd_summary: Mapped[str] = mapped_column(Text)
    final_recommendation: Mapped[str] = mapped_column(Text)
    report_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class EddEvidence(Base):
    __tablename__ = "edd_evidence"

    evidence_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("edd_cases.case_id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    rule_id: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class AgentAuditLog(Base):
    __tablename__ = "agent_audit_logs"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class TmScenario(Base):
    __tablename__ = "tm_scenarios"

    scenario_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    threshold_json: Mapped[str] = mapped_column(Text)
    enabled: Mapped[int] = mapped_column(Integer, default=1)


class TmAlert(Base):
    __tablename__ = "tm_alerts"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    scenario_id: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")
    risk_score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class TmAlertEvidence(Base):
    __tablename__ = "tm_alert_evidence"

    evidence_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("tm_alerts.alert_id"))
    evidence_type: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class AlertDisposition(Base):
    __tablename__ = "alert_dispositions"

    disposition_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("tm_alerts.alert_id"))
    disposition: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    analyst: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


def make_engine(db_path: str | Path = DEFAULT_DB_PATH):
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


def make_session_factory(db_path: str | Path = DEFAULT_DB_PATH) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(db_path), autoflush=False, expire_on_commit=False)


SessionLocal = make_session_factory()


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
