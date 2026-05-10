"""Groq LLM integration for EDD report narrative drafting."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def groq_configured() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def enrich_report_with_groq(report: dict[str, Any]) -> dict[str, Any]:
    result = generate_groq_narrative(report)
    report["llm"] = {
        "provider": "groq",
        "model": result["model"],
        "status": result["status"],
        "error": result.get("error"),
    }
    if result["status"] == "success":
        report["ai_narrative"] = result["narrative"]
        report["investigation_events"].append(
            {
                "stage": "llm_drafting",
                "status": "completed",
                "message": "Groq LLM generated the EDD narrative from structured investigation context.",
                "details": {"provider": "groq", "model": result["model"]},
            }
        )
    else:
        report["investigation_events"].append(
            {
                "stage": "llm_drafting",
                "status": "skipped" if result["status"] == "not_configured" else "fallback",
                "message": result.get("error") or "Groq LLM was not configured; structured narrative retained.",
                "details": {"provider": "groq", "model": result["model"]},
            }
        )
    return report


def generate_groq_narrative(report: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    if not api_key:
        return {
            "status": "not_configured",
            "model": model,
            "error": "GROQ_API_KEY is not set in .env.",
        }

    base_url = os.getenv("GROQ_API_BASE", DEFAULT_GROQ_BASE).rstrip("/")
    timeout = float(os.getenv("GROQ_TIMEOUT_SECONDS", "25"))
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 900,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an AML Enhanced Due Diligence analyst. "
                    "Write concise, evidence-backed report language. "
                    "Do not invent facts beyond the provided JSON. "
                    "Return only valid JSON with keys: executive_summary, risk_rationale, "
                    "confidence_note, recommended_next_steps."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(compact_report_context(report), default=str),
            },
        ],
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        narrative = parse_narrative_json(content)
        return {"status": "success", "model": model, "narrative": narrative}
    except Exception as exc:
        return {
            "status": "error",
            "model": model,
            "error": f"Groq narrative generation failed: {exc}",
        }


def compact_report_context(report: dict[str, Any]) -> dict[str, Any]:
    account = report["customer_profile"]
    metrics = report["transaction_metrics"]
    return {
        "account": {
            "account_id": report["account_id"],
            "entity_name": account.get("entity_name"),
            "bank_name": account.get("bank_name"),
            "customer_type": account.get("customer_type"),
            "country": account.get("country"),
            "industry": account.get("industry"),
            "kyc_risk_rating": account.get("kyc_risk_rating"),
            "kyc_status": account.get("kyc_status"),
            "expected_monthly_volume": account.get("expected_monthly_volume"),
        },
        "transaction_metrics": {
            "total_transactions": metrics.get("total_transactions"),
            "incoming_transactions": metrics.get("incoming_transactions"),
            "outgoing_transactions": metrics.get("outgoing_transactions"),
            "total_incoming_amount": metrics.get("total_incoming_amount"),
            "total_outgoing_amount": metrics.get("total_outgoing_amount"),
            "max_transaction_amount": metrics.get("max_transaction_amount"),
            "unique_incoming_counterparties": metrics.get("unique_incoming_counterparties"),
            "unique_outgoing_counterparties": metrics.get("unique_outgoing_counterparties"),
            "labelled_laundering_transactions": metrics.get("labelled_laundering_transactions"),
            "currencies": metrics.get("currencies"),
            "payment_formats": metrics.get("payment_formats"),
        },
        "risk": {
            "risk_score": report["risk_score"],
            "risk_level": report["risk_level"],
            "final_recommendation": report["final_recommendation"],
            "confidence": report.get("confidence"),
        },
        "findings": [
            {
                "rule_id": item["rule_id"],
                "severity": item["severity"],
                "reason": item["reason"],
                "evidence_count": item.get("evidence_count"),
            }
            for item in report.get("risk_findings", [])[:10]
        ],
        "screening_matches": report.get("screening_matches", [])[:5],
        "adverse_media": report.get("adverse_media", [])[:5],
        "analyst_questions": report.get("analyst_questions", []),
    }


def parse_narrative_json(content: str) -> dict[str, str]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.removeprefix("json").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(content[start : end + 1])
    required = ["executive_summary", "risk_rationale", "confidence_note", "recommended_next_steps"]
    return {key: str(data.get(key, "")).strip() for key in required}
