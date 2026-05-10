"""Command line entrypoint for the EDD agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .database.connection import DEFAULT_DB_PATH, connect
from .edd.sqlite_investigator import load_account_context
from .edd.reporter import build_report, format_text_report, save_report
from .edd.rules import calculate_score, evaluate, recommendation, risk_level


def generate_report(account_id: str, db_path: str | Path, save: bool, output_json: bool) -> int:
    con = connect(db_path)
    context = load_account_context(con, account_id)
    findings = evaluate(context)
    score = calculate_score(findings)
    level = risk_level(score, findings)
    rec = recommendation(level)
    report = build_report(context, findings, score, level, rec.text)
    if save:
        report["report_id"] = save_report(con, report)
    if output_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_text_report(report))
        if save:
            print(f"\nSaved report_id: {report['report_id']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinAgent EDD investigation agent")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="Generate an EDD report for one account")
    report.add_argument("--account-id", required=True, help="Account ID to investigate")
    report.add_argument("--save", action="store_true", help="Persist report and audit log to the database")
    report.add_argument("--json", action="store_true", help="Print full JSON report")

    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            return generate_report(args.account_id, args.db, args.save, args.json)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
