"""Pydantic request schemas for the FastAPI backend."""

from __future__ import annotations

from pydantic import BaseModel


class ReportRequest(BaseModel):
    account_id: str
    save: bool = False
    deep_review: bool = True
    use_llm: bool = True


class TmRunRequest(BaseModel):
    limit: int = 25
    account_id: str | None = None


class AlertDispositionRequest(BaseModel):
    disposition: str
    notes: str | None = None
    analyst: str | None = "analyst_ui"
