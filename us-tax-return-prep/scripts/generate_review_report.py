#!/usr/bin/env python3
"""Generate a human-readable review report for a tax packet."""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if loaded is not None else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def count_entries(data: dict[str, Any], paths: list[str]) -> dict[str, int]:
    counts = {}
    for path in paths:
        value = get_path(data, path)
        if isinstance(value, list):
            counts[path] = len(value)
        elif value:
            counts[path] = 1
        else:
            counts[path] = 0
    return counts


def source_document_summary(data: dict[str, Any], manifest: dict[str, Any]) -> tuple[int, Counter]:
    docs = []
    if isinstance(manifest.get("documents"), list):
        docs.extend(manifest["documents"])
    if isinstance(data.get("source_documents"), list):
        docs.extend(data["source_documents"])
    types = Counter()
    for doc in docs:
        if isinstance(doc, dict):
            types[str(doc.get("document_type") or doc.get("type") or "unknown")] += 1
    return len(docs), types


def append_issue_section(lines: list[str], title: str, issues: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    if not issues:
        lines.append("")
        lines.append("None recorded.")
        lines.append("")
        return
    lines.append("")
    for issue in issues:
        severity = issue.get("severity", "review")
        topic = issue.get("topic") or issue.get("code") or issue.get("path") or "review"
        message = issue.get("message", "")
        lines.append(f"- **{severity}** `{topic}`: {message}")
    lines.append("")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate tax_forms/review_report.md.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--forms-plan", help="Path to required_irs_forms.yaml.")
    parser.add_argument("--state-forms-plan", help="Path to required_state_forms.yaml.")
    parser.add_argument("--source-manifest", help="Path to source_manifest.yaml.")
    parser.add_argument("--calculation-report", help="Path to calculation_report.yaml.")
    parser.add_argument("--validation-report", help="Path to validation_report.yaml.")
    parser.add_argument("--filled-manifest", help="Path to filled_pdf_manifest.yaml.")
    parser.add_argument("--output", help="Path for review_report.md.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    forms_plan_path = Path(args.forms_plan).expanduser().resolve() if args.forms_plan else tax_forms / "required_irs_forms.yaml"
    state_forms_plan_path = (
        Path(args.state_forms_plan).expanduser().resolve()
        if args.state_forms_plan
        else tax_forms / "required_state_forms.yaml"
    )
    source_manifest_path = (
        Path(args.source_manifest).expanduser().resolve()
        if args.source_manifest
        else tax_forms / "source_manifest.yaml"
    )
    calculation_report_path = (
        Path(args.calculation_report).expanduser().resolve()
        if args.calculation_report
        else tax_forms / "workpapers" / "calculation_report.yaml"
    )
    validation_report_path = (
        Path(args.validation_report).expanduser().resolve()
        if args.validation_report
        else tax_forms / "workpapers" / "validation_report.yaml"
    )
    filled_manifest_path = (
        Path(args.filled_manifest).expanduser().resolve()
        if args.filled_manifest
        else tax_forms / "workpapers" / "filled_pdf_manifest.yaml"
    )
    output_path = Path(args.output).expanduser().resolve() if args.output else tax_forms / "review_report.md"

    data = load_yaml(data_path)
    plan = load_yaml(forms_plan_path)
    state_plan = load_yaml(state_forms_plan_path)
    manifest = load_yaml(source_manifest_path)
    calculation = load_yaml(calculation_report_path)
    validation = load_yaml(validation_report_path)
    filled = load_yaml(filled_manifest_path)

    if not isinstance(data, dict):
        data = {}
    if not isinstance(plan, dict):
        plan = {}
    if not isinstance(state_plan, dict):
        state_plan = {}

    doc_count, doc_types = source_document_summary(data, manifest if isinstance(manifest, dict) else {})
    income_counts = count_entries(
        data,
        [
            "income.wages",
            "income.interest",
            "income.dividends",
            "income.capital_gains",
            "income.retirement_distributions",
            "income.social_security",
            "income.business_or_1099_income",
            "income.rentals_royalties_partnerships",
            "income.other_income",
        ],
    )

    forms = [form for form in as_list(plan.get("forms")) if isinstance(form, dict)]
    state_forms = [form for form in as_list(state_plan.get("forms")) if isinstance(form, dict)]
    filled_results = [result for result in as_list(filled.get("results")) if isinstance(result, dict)]
    generated_pdfs = [result for result in filled_results if result.get("status") == "filled"]

    lines = [
        "# Tax Return Review Report",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "## Scope",
        "",
        f"- Tax year: `{data.get('tax_year', 'unknown')}`",
        f"- Review status: `{data.get('review_status', 'unknown')}`",
        f"- Source documents recorded: `{doc_count}`",
        f"- Inferred federal forms: `{len(forms)}`",
        f"- Inferred state forms: `{len(state_forms)}`",
        f"- Generated PDFs: `{len(generated_pdfs)}`",
        "",
        "## Source Documents",
        "",
    ]
    if doc_types:
        for document_type, count in sorted(doc_types.items()):
            lines.append(f"- `{document_type}`: {count}")
    else:
        lines.append("None recorded.")
    lines.extend(["", "## Extracted Data Counts", ""])
    for path, count in income_counts.items():
        lines.append(f"- `{path}`: {count}")

    lines.extend(["", "## Required IRS Forms", ""])
    if forms:
        for form in forms:
            lines.append(f"- `{form.get('form_id')}` {form.get('title', '')}: `{form.get('status')}`")
    else:
        lines.append("None recorded.")

    lines.extend(["", "## Required State Forms", ""])
    if state_forms:
        for form in state_forms:
            jurisdiction = form.get("jurisdiction", "state")
            lines.append(f"- `{form.get('form_id')}` {jurisdiction} {form.get('title', '')}: `{form.get('status')}`")
    else:
        lines.append("None recorded.")

    lines.extend(["", "## Calculation Summary", ""])
    totals = get_path(data, "calculated.totals") or {}
    if isinstance(totals, dict) and totals:
        for key, value in totals.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("No calculated totals recorded.")
    ca_totals = get_path(data, "calculated.state.ca.totals") or {}
    if isinstance(ca_totals, dict) and ca_totals:
        lines.append("")
        lines.append("California:")
        for key, value in ca_totals.items():
            lines.append(f"- `{key}`: `{value}`")

    calculation_review_items = [
        item
        for item in as_list(get_path(data, "calculated.review_items"))
        if not (isinstance(item, dict) and str(item.get("message", "")).startswith("California:"))
    ]
    append_issue_section(lines, "Calculation Review Items", calculation_review_items)
    append_issue_section(lines, "California Review Items", as_list(get_path(data, "calculated.state.ca.review_items")))
    validation_issues = as_list(validation.get("issues")) if isinstance(validation, dict) else []
    append_issue_section(lines, "Validation Issues", validation_issues)

    lines.append("## Filled PDFs")
    lines.append("")
    if generated_pdfs:
        for result in generated_pdfs:
            lines.append(f"- `{result.get('form_id')}`: `{result.get('output_pdf')}`")
    else:
        lines.append("None generated.")
    lines.append("")

    open_questions = as_list(data.get("open_questions"))
    open_questions.extend(as_list(state_plan.get("open_questions")))
    lines.append("## Open Questions")
    lines.append("")
    if open_questions:
        for question in open_questions:
            lines.append(f"- {question}")
    else:
        lines.append("None recorded.")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
