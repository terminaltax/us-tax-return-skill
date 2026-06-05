#!/usr/bin/env python3
"""Infer California resident state forms indicated by extracted tax data."""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


FORM_ORDER = ["ca540", "ca540ca", "ca540d"]
REQUIRED_RANK = {"not_needed": 0, "review": 1, "required": 2}


def form_catalog(tax_year: str) -> dict[str, dict[str, Any]]:
    year = tax_year if tax_year.isdigit() else "unknown"
    base = f"https://www.ftb.ca.gov/forms/{year}" if tax_year.isdigit() else None
    return {
        "ca540": {
            "title": "California Form 540",
            "pdf": f"{year}-540.pdf",
            "url": f"{base}/{year}-540.pdf" if base else None,
            "instruction_url": f"{base}/{year}-540-booklet.html" if base else None,
            "calculation_coverage": "resident_common_lines_partial",
        },
        "ca540ca": {
            "title": "Schedule CA (540)",
            "pdf": f"{year}-540-ca.pdf",
            "url": f"{base}/{year}-540-ca.pdf" if base else None,
            "instruction_url": f"{base}/{year}-540-ca-instructions.html" if base else None,
            "calculation_coverage": "federal_amounts_and_review_adjustments",
        },
        "ca540d": {
            "title": "Schedule D (540)",
            "pdf": f"{year}-540-d.pdf",
            "url": f"{base}/{year}-540-d.pdf" if base else None,
            "instruction_url": f"{base}/{year}-540-d-instructions.html" if base else None,
            "calculation_coverage": "review_required",
        },
    }


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if loaded is not None else {}


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def is_unknown(value: Any) -> bool:
    return value in (None, "", "unknown", "not_inferred", "needs_review")


def meaningful(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    return True


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if is_unknown(value):
        return []
    return [value]


def normalize_state(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"CALIFORNIA", "CA"}:
        return "CA"
    return text


def return_scope_states(data: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    for item in as_list(get_path(data, "return_scope.states")):
        if isinstance(item, dict):
            code = normalize_state(item.get("state") or item.get("code"))
            if code:
                states.append({**item, "state": code})
        else:
            code = normalize_state(item)
            if code:
                states.append({"state": code})
    return states


def ca_scope_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    for state in return_scope_states(data):
        if state.get("state") == "CA":
            return state
    return None


def user_requested_ca(data: dict[str, Any]) -> bool:
    entry = ca_scope_entry(data)
    if entry is not None:
        return True
    if get_path(data, "user_review.state_return_requested") is True:
        return True
    ca_requested = get_path(data, "state_returns.ca.requested")
    return ca_requested is True


def ca_residency_status(data: dict[str, Any]) -> str:
    candidates = [
        get_path(data, "state_returns.ca.residency_status"),
        get_path(data, "taxpayer.residency.ca.status"),
        get_path(data, "taxpayer.ca_residency_status"),
        get_path(data, "taxpayer.residency_status"),
        get_path(data, "taxpayer.residency_state"),
        (ca_scope_entry(data) or {}).get("residency_status") if ca_scope_entry(data) else None,
    ]
    for candidate in candidates:
        text = str(candidate or "").strip().lower()
        if text:
            return text
    return "unknown"


def is_ca_full_year_resident(data: dict[str, Any]) -> bool:
    status = ca_residency_status(data)
    return status in {"resident", "full_year_resident", "full-year resident", "full year resident"}


def has_ca_indicators(data: dict[str, Any]) -> bool:
    if normalize_state(get_path(data, "taxpayer.address.state")) == "CA":
        return True
    if user_requested_ca(data):
        return True
    for wage in as_list(get_path(data, "income.wages")):
        if not isinstance(wage, dict):
            continue
        for state_item in as_list(wage.get("state_items")):
            if isinstance(state_item, dict) and normalize_state(state_item.get("state")) == "CA":
                return True
    for path in ["payments.state_withholding", "payments.state_estimated_payments"]:
        for payment in as_list(get_path(data, path)):
            if isinstance(payment, dict) and normalize_state(payment.get("state")) == "CA":
                return True
    return False


def has_entries(data: dict[str, Any], dotted_path: str) -> bool:
    return meaningful(get_path(data, dotted_path))


def nonzero_amount(value: Any) -> bool:
    if is_unknown(value):
        return False
    text = str(value).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text) != 0
    except InvalidOperation:
        return True


def source_refs_for_ca_w2(data: dict[str, Any], label: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen = set()
    for wage in as_list(get_path(data, "income.wages")):
        if not isinstance(wage, dict):
            continue
        if not any(
            isinstance(item, dict) and normalize_state(item.get("state")) == "CA"
            for item in as_list(wage.get("state_items"))
        ):
            continue
        doc_id = wage.get("source_document_id")
        if doc_id and doc_id not in seen:
            refs.append({"document_id": str(doc_id), "label": label})
            seen.add(doc_id)
    return refs


class FormPlan:
    def __init__(self, tax_year: str) -> None:
        self.forms: dict[str, dict[str, Any]] = {}
        self.catalog = form_catalog(tax_year)

    def add(
        self,
        form_id: str,
        status: str,
        reason: str,
        source_refs: list[dict[str, str]] | None = None,
    ) -> None:
        catalog = self.catalog[form_id]
        existing = self.forms.get(form_id)
        if not existing:
            existing = {
                "form_id": form_id,
                "jurisdiction": "CA",
                "agency": "California Franchise Tax Board",
                "title": catalog["title"],
                "status": status,
                "pdf": catalog["pdf"],
                "url": catalog["url"],
                "instruction_url": catalog["instruction_url"],
                "output_dir": "tax_forms/state/ca",
                "blank_dir": "tax_forms/workpapers/blank_forms/ca",
                "field_map_dir": "tax_forms/workpapers/field_maps/ca",
                "calculation_coverage": catalog["calculation_coverage"],
                "reasons": [],
                "source_refs": [],
            }
            self.forms[form_id] = existing
        if REQUIRED_RANK[status] > REQUIRED_RANK[existing["status"]]:
            existing["status"] = status
        if reason not in existing["reasons"]:
            existing["reasons"].append(reason)
        if source_refs:
            seen = {(ref.get("document_id"), ref.get("label")) for ref in existing["source_refs"]}
            for ref in source_refs:
                key = (ref.get("document_id"), ref.get("label"))
                if key not in seen:
                    existing["source_refs"].append(ref)
                    seen.add(key)

    def ordered(self) -> list[dict[str, Any]]:
        order = {form_id: index for index, form_id in enumerate(FORM_ORDER)}
        return sorted(self.forms.values(), key=lambda form: order.get(form["form_id"], 999))


def ca_adjustments_present(data: dict[str, Any]) -> bool:
    if has_entries(data, "calculated.form_line_values.ca540ca"):
        return True
    ca_adjustments = get_path(data, "state_adjustments.ca")
    if isinstance(ca_adjustments, dict):
        if nonzero_amount(ca_adjustments.get("subtractions_total")):
            return True
        if nonzero_amount(ca_adjustments.get("additions_total")):
            return True
        if nonzero_amount(ca_adjustments.get("itemized_deduction_total")):
            return True
    if str(get_path(data, "deductions.standard_or_itemized") or "").lower() == "itemized":
        return True
    if has_entries(data, "adjustments.hsa"):
        return True
    for wage in as_list(get_path(data, "income.wages")):
        if not isinstance(wage, dict):
            continue
        for box14 in as_list(wage.get("box_14")):
            label = str((box14 or {}).get("label", "")).lower() if isinstance(box14, dict) else ""
            if label in {"casdi", "sdi", "vpdi"}:
                return True
    return False


def ca_capital_review_present(data: dict[str, Any]) -> bool:
    return (
        has_entries(data, "income.capital_gains")
        or has_entries(data, "state_adjustments.ca.capital_gains")
        or has_entries(data, "calculated.form_line_values.ca540d")
        or has_entries(data, "carryovers_and_prior_year.ca_capital_loss_carryover")
    )


def infer_forms(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    tax_year = str(data.get("tax_year") or "unknown")
    plan = FormPlan(tax_year)
    open_questions: list[str] = []

    if not has_ca_indicators(data):
        return [], ["No California indicators found. Add CA to return_scope.states before preparing California forms."]

    resident = is_ca_full_year_resident(data)
    requested = user_requested_ca(data)
    form_540_status = "required" if requested and resident else "review"
    refs = source_refs_for_ca_w2(data, "California W-2 state wages/withholding")
    plan.add(
        "ca540",
        form_540_status,
        "California indicators are present; Form 540 is used for California full-year resident individual returns.",
        refs,
    )

    if not requested:
        open_questions.append("Confirm that a California state return is requested by adding CA to return_scope.states.")
    if not resident:
        open_questions.append(
            "Confirm California residency status. This module currently targets full-year resident Form 540 returns only."
        )

    if ca_adjustments_present(data):
        plan.add(
            "ca540ca",
            "required",
            "California/federal adjustment indicators are present; Schedule CA (540) should be prepared for review.",
            refs,
        )
    else:
        plan.add(
            "ca540ca",
            "review",
            "Review whether any California/federal income or deduction adjustments are needed.",
            refs,
        )

    if ca_capital_review_present(data):
        status = "required" if has_entries(data, "state_adjustments.ca.capital_gains") or has_entries(data, "calculated.form_line_values.ca540d") else "review"
        plan.add(
            "ca540d",
            status,
            "Capital gain/loss activity is present; review whether California Schedule D (540) is required.",
        )

    return plan.ordered(), open_questions


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Infer California state forms from extracted_tax_data.yaml."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for required_state_forms.yaml.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else tax_forms / "required_state_forms.yaml"

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")

    forms, open_questions = infer_forms(data)
    result = {
        "schema_version": "0.1",
        "tax_year": data.get("tax_year", "unknown"),
        "status": "needs_review" if forms else "not_inferred",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_from": relative_to_root(data_path, root),
        "states": [{"state": "CA", "module": "california_resident"}] if forms else [],
        "forms": forms,
        "open_questions": open_questions,
        "official_sources": [
            {
                "agency": "California Franchise Tax Board",
                "url": "https://www.ftb.ca.gov/forms/",
                "notes": "Use current-year official FTB forms and instructions before finalizing California calculations.",
            }
        ],
    }
    dump_yaml(result, output_path)

    data["required_state_forms"] = {
        "status": result["status"],
        "file": relative_to_root(output_path, root),
    }
    dump_yaml(data, data_path)

    required_count = sum(1 for form in forms if form["status"] == "required")
    review_count = sum(1 for form in forms if form["status"] == "review")
    print(f"Wrote {output_path}")
    print(f"California forms: {required_count} required, {review_count} review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
