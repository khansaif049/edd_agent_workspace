"""FastAPI application factory for the FinAgent UI/API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from edd_agent.api.schemas import AlertDispositionRequest, ReportRequest, TmRunRequest
from edd_agent.core.llm import enrich_report_with_groq, groq_configured
from edd_agent.database.connection import DEFAULT_DB_PATH
from edd_agent.database.models import Account, EddReport, make_session_factory
from edd_agent.edd.repository import load_account_context_orm, sample_accounts_orm
from edd_agent.edd.reporter import build_report, save_report_orm
from edd_agent.edd.rules import calculate_score, evaluate, recommendation, risk_level
from edd_agent.tm.service import add_alert_disposition, get_tm_alert_detail, list_tm_alerts, run_tm_scan


ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_UI_DIR = ROOT / "ui"
FRONTEND_DIST = ROOT / "frontend" / "dist"


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    session_factory = make_session_factory(db_path)

    def session_dependency():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI(title="FinAgent Financial Crime API", version="0.1.0")

    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    elif LEGACY_UI_DIR.exists():
        app.mount("/ui", StaticFiles(directory=LEGACY_UI_DIR), name="ui")

    @app.get("/")
    def index():
        dist_index = FRONTEND_DIST / "index.html"
        if dist_index.exists():
            return FileResponse(dist_index)
        return FileResponse(LEGACY_UI_DIR / "index.html")

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "backend": "fastapi",
            "orm": "sqlalchemy",
            "llm_provider": "groq",
            "llm_configured": groq_configured(),
        }

    @app.get("/api/sample-accounts")
    def sample_accounts(session: Session = Depends(session_dependency)):
        return sample_accounts_orm(session)

    @app.get("/api/reports")
    def saved_reports(session: Session = Depends(session_dependency)):
        rows = session.execute(
            select(
                EddReport.report_id,
                EddReport.account_id,
                EddReport.risk_score,
                EddReport.risk_level,
                EddReport.final_recommendation,
                EddReport.created_at,
                Account.entity_name,
                Account.bank_name,
            )
            .join(Account, Account.account_id == EddReport.account_id, isouter=True)
            .order_by(desc(EddReport.report_id))
            .limit(100)
        ).mappings()
        return [dict(row) for row in rows]

    @app.get("/api/reports/{report_id}")
    def saved_report_detail(report_id: int, session: Session = Depends(session_dependency)):
        report_row = session.get(EddReport, report_id)
        if not report_row:
            raise HTTPException(status_code=404, detail="Report not found")
        if report_row.report_json:
            try:
                payload = json.loads(report_row.report_json)
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = {}
        payload.update(
            {
                "report_id": report_row.report_id,
                "account_id": report_row.account_id,
                "risk_score": report_row.risk_score,
                "risk_level": report_row.risk_level,
                "edd_summary": report_row.edd_summary,
                "final_recommendation": report_row.final_recommendation,
                "created_at": report_row.created_at,
            }
        )
        return payload

    @app.post("/api/report")
    def report(payload: ReportRequest, session: Session = Depends(session_dependency)):
        account_id = payload.account_id.strip()
        if not account_id:
            raise HTTPException(status_code=400, detail="account_id is required")
        try:
            context = load_account_context_orm(session, account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        findings = evaluate(context)
        score = calculate_score(findings)
        level = risk_level(score, findings)
        rec = recommendation(level)
        report_payload = build_report(context, findings, score, level, rec.text)
        if payload.deep_review and payload.use_llm:
            report_payload = enrich_report_with_groq(report_payload)
        if payload.save:
            report_payload["report_id"] = save_report_orm(session, report_payload)
        return report_payload

    @app.post("/api/tm/run")
    def run_transaction_monitoring(payload: TmRunRequest, session: Session = Depends(session_dependency)):
        limit = max(1, min(payload.limit, 100))
        account_id = payload.account_id.strip() if payload.account_id else None
        return run_tm_scan(session, limit=limit, account_id=account_id)

    @app.get("/api/tm/alerts")
    def tm_alerts(session: Session = Depends(session_dependency)):
        return list_tm_alerts(session)

    @app.get("/api/tm/alerts/{alert_id}")
    def tm_alert_detail(alert_id: int, session: Session = Depends(session_dependency)):
        alert = get_tm_alert_detail(session, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="TM alert not found")
        return alert

    @app.post("/api/tm/alerts/{alert_id}/disposition")
    def tm_alert_disposition(
        alert_id: int,
        payload: AlertDispositionRequest,
        session: Session = Depends(session_dependency),
    ):
        alert = add_alert_disposition(
            session,
            alert_id,
            payload.disposition,
            payload.notes,
            payload.analyst,
        )
        if not alert:
            raise HTTPException(status_code=404, detail="TM alert not found")
        return alert

    return app
