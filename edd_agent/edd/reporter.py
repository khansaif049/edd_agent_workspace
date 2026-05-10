"""Report assembly and persistence for the EDD agent."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from typing import Any

from .types import RiskFinding
from edd_agent.database.models import AgentAuditLog, EddEvidence, EddReport


def build_report(context: dict[str, Any], findings: list[RiskFinding], score: int, level: str, recommendation: str) -> dict[str, Any]:
    account = context["account"]
    metrics = context["transaction_metrics"]
    rule_ids = [finding.rule_id for finding in findings]
    summary = (
        f"Account {account['account_id']} ({account.get('entity_name')}, {account.get('bank_name')}) "
        f"has {metrics.get('total_transactions', 0):,} transactions, "
        f"{float(metrics.get('total_incoming_amount') or 0):,.2f} incoming value, and "
        f"{float(metrics.get('total_outgoing_amount') or 0):,.2f} outgoing value. "
        f"Risk rules identified: {', '.join(rule_ids) if rule_ids else 'none'}. "
        f"Overall risk score is {score}/100. Recommendation: {recommendation}"
    )
    confidence = confidence_assessment(context, findings)
    narrative = build_narrative(account, metrics, findings, level, recommendation, confidence)
    questions = analyst_questions(context, findings, level)
    events = investigation_events(context, findings, score, level)
    return {
        "run_id": str(uuid.uuid4()),
        "account_id": account["account_id"],
        "customer_profile": account,
        "beneficial_owners": context["beneficial_owners"],
        "transaction_metrics": metrics,
        "screening_matches": context["screening_matches"],
        "adverse_media": context["adverse_media"],
        "existing_cases": context["existing_cases"],
        "risk_findings": [asdict(finding) for finding in findings],
        "sample_transactions": context["sample_transactions"],
        "risk_score": score,
        "risk_level": level,
        "confidence": confidence,
        "investigation_events": events,
        "ai_narrative": narrative,
        "analyst_questions": questions,
        "edd_summary": summary,
        "final_recommendation": recommendation,
    }


def confidence_assessment(context: dict[str, Any], findings: list[RiskFinding]) -> dict[str, Any]:
    metrics = context["transaction_metrics"]
    evidence_points = sum(1 for finding in findings if finding.evidence_count)
    data_sources = [
        "account_profile",
        "kyc_profile",
        "transactions",
        "beneficial_owners",
    ]
    if context["screening_matches"]:
        data_sources.append("screening_matches")
    if context["adverse_media"]:
        data_sources.append("adverse_media")
    if context["existing_cases"]:
        data_sources.append("case_history")

    txn_count = int(metrics.get("total_transactions") or 0)
    confidence = 50
    confidence += min(25, len(data_sources) * 3)
    confidence += min(20, evidence_points * 3)
    confidence += 10 if txn_count >= 100 else 0
    confidence = min(96, confidence)
    if not findings:
        confidence = min(confidence, 72)

    return {
        "score": confidence,
        "level": "high" if confidence >= 80 else "medium" if confidence >= 60 else "low",
        "basis": [
            f"{txn_count:,} transactions reviewed",
            f"{len(data_sources)} data sources used",
            f"{evidence_points} evidence-backed findings",
        ],
        "limitations": [
            "Synthetic KYC, watchlist, and adverse media are used for demonstration.",
            "Narrative is generated from structured rules unless an external LLM provider is later connected.",
        ],
    }


def build_narrative(
    account: dict[str, Any],
    metrics: dict[str, Any],
    findings: list[RiskFinding],
    level: str,
    recommendation: str,
    confidence: dict[str, Any],
) -> dict[str, str]:
    top_findings = ", ".join(f.rule_id for f in findings[:4]) if findings else "no material rule hits"
    return {
        "executive_summary": (
            f"The investigation rates {account.get('entity_name')} as {level.upper()} risk. "
            f"The primary drivers are {top_findings}. The account shows "
            f"{int(metrics.get('total_transactions') or 0):,} observed transactions with "
            f"{float(metrics.get('total_outgoing_amount') or 0):,.2f} outgoing value."
        ),
        "risk_rationale": (
            "The score is based on structured AML typologies, KYC-to-behavior comparison, "
            "network movement patterns, screening indicators, and adverse media where present."
        ),
        "confidence_note": (
            f"Assessment confidence is {confidence['level']} ({confidence['score']}/100) because "
            f"{'; '.join(confidence['basis'])}."
        ),
        "recommended_next_steps": recommendation,
    }


def analyst_questions(context: dict[str, Any], findings: list[RiskFinding], level: str) -> list[str]:
    rule_ids = {finding.rule_id for finding in findings}
    questions = []
    if "KYC_BEHAVIOR_MISMATCH" in rule_ids:
        questions.append("Can the customer provide documents explaining the gap between expected and observed activity?")
    if "FAN_OUT" in rule_ids or "FAN_IN" in rule_ids:
        questions.append("Are the high-volume counterparties related parties, customers, vendors, or unknown third parties?")
    if "WATCHLIST_OR_PEP_MATCH" in rule_ids:
        questions.append("Has the screening match been dispositioned as true positive, false positive, or unresolved?")
    if "STRUCTURING_BELOW_THRESHOLD" in rule_ids:
        questions.append("Is there a legitimate business reason for repeated transactions near reporting thresholds?")
    if context["adverse_media"]:
        questions.append("Has adverse media been independently validated and linked to the customer or owner?")
    if level in {"critical", "high"}:
        questions.append("Should the case be escalated for SAR/STR assessment and enhanced monitoring?")
    return questions[:6]


def investigation_events(context: dict[str, Any], findings: list[RiskFinding], score: int, level: str) -> list[dict[str, Any]]:
    metrics = context["transaction_metrics"]
    return [
        {
            "stage": "planning",
            "status": "completed",
            "message": "Investigation plan created from account ID and EDD scope.",
            "details": {"account_id": context["account"]["account_id"]},
        },
        {
            "stage": "querying",
            "status": "completed",
            "message": "Profile, KYC, ownership, screening, media, cases, and transaction metrics loaded with ORM queries.",
            "details": {
                "transactions": metrics.get("total_transactions", 0),
                "owners": len(context["beneficial_owners"]),
                "screening_matches": len(context["screening_matches"]),
                "adverse_media": len(context["adverse_media"]),
            },
        },
        {
            "stage": "analyzing",
            "status": "completed",
            "message": f"{len(findings)} risk findings generated from deterministic EDD rules.",
            "details": {"risk_score": score, "risk_level": level},
        },
        {
            "stage": "drafting",
            "status": "completed",
            "message": "EDD narrative, recommendation, confidence note, and analyst questions drafted.",
            "details": {"mode": "structured-ai-narrative"},
        },
    ]


def save_report(con: sqlite3.Connection, report: dict[str, Any]) -> int:
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO edd_reports
            (account_id, risk_score, risk_level, edd_summary, final_recommendation, report_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            report["account_id"],
            report["risk_score"],
            report["risk_level"],
            report["edd_summary"],
            report["final_recommendation"],
            json.dumps(report, default=str),
        ),
    )
    report_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO agent_audit_logs (run_id, account_id, action, details_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            report["run_id"],
            report["account_id"],
            "edd_report_saved",
            json.dumps({"report_id": report_id, "risk_score": report["risk_score"], "risk_level": report["risk_level"]}),
        ),
    )
    con.commit()
    return report_id


def save_report_orm(session, report: dict[str, Any]) -> int:
    edd_report = EddReport(
        account_id=report["account_id"],
        risk_score=report["risk_score"],
        risk_level=report["risk_level"],
        edd_summary=report["edd_summary"],
        final_recommendation=report["final_recommendation"],
        report_json=json.dumps(report, default=str),
    )
    session.add(edd_report)
    session.flush()
    for finding in report.get("risk_findings", []):
        session.add(
            EddEvidence(
                case_id=None,
                account_id=report["account_id"],
                rule_id=finding["rule_id"],
                severity=finding["severity"],
                evidence_type=finding.get("evidence_type") or "derived_metric",
                evidence_ref=finding.get("evidence_ref"),
                evidence_json=json.dumps(
                    {
                        "report_id": edd_report.report_id,
                        "reason": finding["reason"],
                        "evidence_count": finding.get("evidence_count", 0),
                        "details": finding.get("details", {}),
                    },
                    default=str,
                ),
            )
        )
    session.add(
        AgentAuditLog(
            run_id=report["run_id"],
            account_id=report["account_id"],
            action="edd_report_saved",
            details_json=json.dumps(
                {
                    "report_id": edd_report.report_id,
                    "risk_score": report["risk_score"],
                    "risk_level": report["risk_level"],
                }
            ),
        )
    )
    for event in report.get("investigation_events", []):
        session.add(
            AgentAuditLog(
                run_id=report["run_id"],
                account_id=report["account_id"],
                action=f"investigation_{event['stage']}",
                details_json=json.dumps(event, default=str),
            )
        )
    session.commit()
    return int(edd_report.report_id)


def format_text_report(report: dict[str, Any]) -> str:
    account = report["customer_profile"]
    metrics = report["transaction_metrics"]
    lines = [
        "EDD Investigation Report",
        "=" * 24,
        f"Account ID: {report['account_id']}",
        f"Entity: {account.get('entity_name')}",
        f"Bank: {account.get('bank_name')}",
        f"KYC: {account.get('customer_type')} | {account.get('country')} | {account.get('industry')} | {account.get('kyc_risk_rating')}",
        f"Risk: {report['risk_score']}/100 ({report['risk_level']})",
        f"Recommendation: {report['final_recommendation']}",
        "",
        "Transaction Snapshot",
        f"- Total transactions: {metrics.get('total_transactions', 0):,}",
        f"- Incoming value: {float(metrics.get('total_incoming_amount') or 0):,.2f}",
        f"- Outgoing value: {float(metrics.get('total_outgoing_amount') or 0):,.2f}",
        f"- Incoming counterparties: {metrics.get('unique_incoming_counterparties', 0):,}",
        f"- Outgoing counterparties: {metrics.get('unique_outgoing_counterparties', 0):,}",
        f"- Labelled laundering txns: {metrics.get('labelled_laundering_transactions', 0):,}",
        "",
        "Findings",
    ]
    if not report["risk_findings"]:
        lines.append("- No material EDD red flags found.")
    for finding in report["risk_findings"]:
        lines.append(
            f"- [{finding['severity']}] {finding['rule_id']}: {finding['reason']} "
            f"(score +{finding['score']}, evidence {finding['evidence_count']})"
        )
    lines.extend(["", "Summary", report["edd_summary"]])
    return "\n".join(lines)
