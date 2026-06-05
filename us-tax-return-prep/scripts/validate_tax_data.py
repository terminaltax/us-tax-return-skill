#!/usr/bin/env python3
"""Validate extracted tax data, form plans, blank PDFs, and field maps."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc

try:
    from pypdf import PdfReader
except ImportError as exc:
    raise SystemExit(
        "pypdf is required. Install it in the local environment with: uv pip install pypdf"
    ) from exc


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}
MONEY_KEYWORDS = (
    "amount",
    "wages",
    "withheld",
    "withholding",
    "income",
    "tax",
    "basis",
    "proceeds",
    "dividend",
    "interest",
    "gross",
    "net",
    "deduction",
    "credit",
    "payment",
    "distribution",
    "benefit",
    "loss",
    "gain",
)


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


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


def is_unknown(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in UNKNOWN_VALUES:
        return True
    return False


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def add_issue(
    issues: list[dict[str, str]],
    severity: str,
    code: str,
    message: str,
    path: str | None = None,
) -> None:
    issue = {"severity": severity, "code": code, "message": message}
    if path:
        issue["path"] = path
    issues.append(issue)


def parse_money(value: Any) -> bool:
    if is_unknown(value):
        return True
    text = str(value).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        Decimal(text)
    except InvalidOperation:
        return False
    return True


def looks_like_money_key(key: str) -> bool:
    normalized = key.lower()
    return any(keyword in normalized for keyword in MONEY_KEYWORDS)


def validate_money_values(data: Any, issues: list[dict[str, str]], path: str = "") -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, (dict, list)):
                validate_money_values(value, issues, child_path)
            elif looks_like_money_key(str(key)) and not parse_money(value):
                add_issue(
                    issues,
                    "error",
                    "invalid_money",
                    f"Expected a decimal-compatible money value, got {value!r}.",
                    child_path,
                )
    elif isinstance(data, list):
        for index, value in enumerate(data):
            validate_money_values(value, issues, f"{path}[{index}]")


def candidate_field_maps(field_map_dir: Path, form: dict[str, Any], tax_year: str) -> list[Path]:
    form_id = str(form.get("form_id", ""))
    pdf_stem = Path(str(form.get("pdf", form_id))).stem
    candidates = [
        field_map_dir / f"{tax_year}_{form_id}_field_map.yaml",
        field_map_dir / f"{form_id}_field_map.yaml",
        field_map_dir / f"{tax_year}_{pdf_stem}_field_map.yaml",
        field_map_dir / f"{pdf_stem}_field_map.yaml",
    ]
    unique = []
    seen = set()
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def resolve_root_path(root: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else root / path


def load_pdf_fields(path: Path) -> set[str]:
    reader = PdfReader(str(path))
    return set((reader.get_fields() or {}).keys())


def validate_taxpayer(data: dict[str, Any], issues: list[dict[str, str]]) -> None:
    required_paths = [
        "taxpayer.primary.full_name",
        "taxpayer.primary.ssn",
        "taxpayer.address.line1",
        "taxpayer.address.city",
        "taxpayer.address.state",
        "taxpayer.address.zip",
        "taxpayer.filing_status",
    ]
    for dotted_path in required_paths:
        if is_unknown(get_path(data, dotted_path)):
            add_issue(issues, "error", "missing_required_fact", "Required taxpayer fact is missing.", dotted_path)

    ssn = get_path(data, "taxpayer.primary.ssn")
    if not is_unknown(ssn):
        digits = re.sub(r"\D", "", str(ssn))
        if len(digits) != 9:
            add_issue(issues, "error", "invalid_ssn", "Primary taxpayer SSN must contain 9 digits.", "taxpayer.primary.ssn")


def meaningful(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    return True


def rental_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    entries = get_path(data, "income.rentals_royalties_partnerships")
    if not isinstance(entries, list):
        return []
    rentals = []
    rental_markers = {
        "property_address",
        "property_type",
        "rental_income",
        "gross_rents",
        "days_rented",
        "personal_use_days",
        "fair_rental_days",
        "expenses",
        "depreciation",
        "passive_activity",
    }
    for item in entries:
        if not isinstance(item, dict):
            continue
        activity = str(item.get("activity_type") or item.get("type") or "").strip().lower()
        if "rental" in activity or any(key in item for key in rental_markers):
            rentals.append(item)
    return rentals


def first_meaningful(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if meaningful(value):
            return value
    return None


def validate_rental_entries(data: dict[str, Any], issues: list[dict[str, str]]) -> None:
    for index, rental in enumerate(rental_entries(data)):
        base = f"income.rentals_royalties_partnerships[{index}]"
        required_groups = [
            (
                "property_address",
                ["property_address", "address"],
                "Rental property address is missing. Fill rental/rental_intake.md or add source-backed property address data.",
            ),
            (
                "gross_rents",
                ["gross_rents", "rental_income", "rents_received"],
                "Gross rents are missing. Schedule E needs rental income before the rental result can be trusted.",
            ),
            (
                "days_rented",
                ["days_rented", "fair_rental_days"],
                "Rental days or fair-rental days are missing. Fill rental/rental_intake.md for Schedule E use questions.",
            ),
            (
                "personal_use_days",
                ["personal_use_days"],
                "Personal-use days are missing. Fill rental/rental_intake.md even if the value is zero.",
            ),
            (
                "expenses",
                ["expenses", "total_expenses", "expense_total", "income_loss"],
                "Rental expenses or a reviewed net income/loss amount are missing.",
            ),
        ]
        for fact, keys, message in required_groups:
            if first_meaningful(rental, keys) is None:
                add_issue(
                    issues,
                    "warning",
                    "incomplete_rental_property",
                    message,
                    f"{base}.{fact}",
                )
        if not meaningful(rental.get("source_refs")):
            add_issue(
                issues,
                "warning",
                "rental_missing_source_refs",
                "Rental property data has no source_refs. Use rental/rental_intake.md and supporting docs in rental/ to source material numbers.",
                base,
            )
        depreciation = rental.get("depreciation") if isinstance(rental.get("depreciation"), dict) else {}
        if depreciation:
            if first_meaningful(rental, ["placed_in_service_date", "date_placed_in_service"]) is None and first_meaningful(
                depreciation, ["placed_in_service_date"]
            ) is None:
                add_issue(
                    issues,
                    "warning",
                    "incomplete_rental_depreciation",
                    "Rental depreciation needs the date placed in service as a rental.",
                    f"{base}.depreciation.placed_in_service_date",
                )
            if first_meaningful(depreciation, ["building_basis", "depreciable_basis", "federal_building_basis"]) is None:
                add_issue(
                    issues,
                    "warning",
                    "incomplete_rental_depreciation",
                    "Rental depreciation needs building value/depreciable basis excluding land.",
                    f"{base}.depreciation.building_basis",
                )
            if first_meaningful(depreciation, ["land_value", "federal_land_value"]) is None:
                add_issue(
                    issues,
                    "warning",
                    "incomplete_rental_depreciation",
                    "Rental depreciation needs land value or land allocation because land is not depreciable.",
                    f"{base}.depreciation.land_value",
                )


def validate_itemized_deductions(data: dict[str, Any], issues: list[dict[str, str]]) -> None:
    deductions = data.get("deductions")
    if not isinstance(deductions, dict):
        add_issue(
            issues,
            "warning",
            "deduction_choice_missing",
            "Choose standard, itemized, or unsure in itemized/itemized_intake.md.",
            "deductions.standard_or_itemized",
        )
        return

    method = str(deductions.get("standard_or_itemized") or "").strip().lower()
    if method in {"", "unknown", "not_inferred", "needs_review"}:
        add_issue(
            issues,
            "warning",
            "deduction_choice_missing",
            "Choose standard, itemized, or unsure in itemized/itemized_intake.md.",
            "deductions.standard_or_itemized",
        )
        return

    if method not in {"standard", "itemized", "unsure"}:
        add_issue(
            issues,
            "warning",
            "deduction_choice_invalid",
            "Deduction choice should be standard, itemized, or unsure.",
            "deductions.standard_or_itemized",
        )
        return

    if method == "itemized":
        has_total = meaningful(deductions.get("itemized_deduction_total")) or meaningful(
            deductions.get("selected_deduction_amount")
        )
        has_categories = meaningful(deductions.get("itemized"))
        if not has_total and not has_categories:
            add_issue(
                issues,
                "warning",
                "incomplete_itemized_deductions",
                "Itemized deductions are selected, but no Schedule A categories or total are populated. Fill itemized/itemized_intake.md or add supporting documents in itemized/.",
                "deductions.itemized",
            )


def validate_forms(
    plan: dict[str, Any],
    tax_year: str,
    blank_dir: Path,
    field_map_dir: Path,
    root: Path,
    issues: list[dict[str, str]],
    require_f1040: bool = True,
) -> None:
    forms = plan.get("forms")
    if not isinstance(forms, list) or not forms:
        add_issue(issues, "warning", "no_required_forms", "No forms are listed in the forms plan.")
        return

    form_ids = {form.get("form_id") for form in forms if isinstance(form, dict)}
    if require_f1040 and "f1040" not in form_ids:
        add_issue(issues, "error", "missing_f1040", "Form 1040 is not listed in the federal forms plan.")

    for index, form in enumerate(forms):
        if not isinstance(form, dict):
            add_issue(issues, "error", "invalid_form_entry", "Form plan entry must be a mapping.", f"forms[{index}]")
            continue
        form_path = f"forms[{index}]"
        form_id = str(form.get("form_id") or "")
        status = form.get("status")
        pdf = form.get("pdf")
        if not form_id:
            add_issue(issues, "error", "missing_form_id", "Form entry is missing form_id.", form_path)
        if status not in {"required", "review", "not_needed"}:
            add_issue(issues, "error", "invalid_form_status", "Form status must be required, review, or not_needed.", f"{form_path}.status")
        if status != "not_needed" and not pdf:
            add_issue(issues, "error", "missing_form_pdf", "Form entry is missing pdf.", f"{form_path}.pdf")
            continue
        if status != "required":
            continue

        form_blank_dir = resolve_root_path(root, form.get("blank_dir")) if form.get("blank_dir") else blank_dir
        form_field_map_dir = resolve_root_path(root, form.get("field_map_dir")) if form.get("field_map_dir") else field_map_dir
        blank_pdf = form_blank_dir / str(pdf)
        if not blank_pdf.exists():
            add_issue(
                issues,
                "warning",
                "missing_blank_pdf",
                f"Blank PDF is not present: {blank_pdf.relative_to(root) if blank_pdf.is_relative_to(root) else blank_pdf}",
                f"{form_path}.pdf",
            )
            continue

        field_map_path = first_existing(candidate_field_maps(form_field_map_dir, form, tax_year))
        if not field_map_path:
            add_issue(
                issues,
                "warning",
                "missing_field_map",
                f"No field map found for required form {form_id}.",
                form_path,
            )
            continue

        field_map = load_yaml(field_map_path)
        fields = field_map.get("fields") if isinstance(field_map, dict) else None
        if not isinstance(fields, dict):
            add_issue(issues, "error", "invalid_field_map", "Field map must contain a fields mapping.", str(field_map_path))
            continue

        try:
            pdf_fields = load_pdf_fields(blank_pdf)
        except Exception as exc:
            add_issue(issues, "error", "pdf_read_error", f"Could not inspect blank PDF: {exc}", str(blank_pdf))
            continue
        missing_fields = sorted(set(fields.keys()) - pdf_fields)
        if missing_fields:
            add_issue(
                issues,
                "error",
                "field_map_pdf_mismatch",
                f"Field map references fields not present in PDF: {', '.join(missing_fields[:10])}",
                str(field_map_path),
            )


def validate_filled_manifest(manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    results = manifest.get("results")
    if not results:
        return
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        if result.get("status") == "error":
            add_issue(
                issues,
                "error",
                "filled_pdf_error",
                "; ".join(str(error) for error in result.get("errors", [])) or "Filled PDF manifest contains an error.",
                f"filled_pdf_manifest.results[{index}]",
            )


def is_state_plan(plan: dict[str, Any]) -> bool:
    if plan.get("states"):
        return True
    for form in plan.get("forms", []):
        if isinstance(form, dict) and form.get("jurisdiction"):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate extracted tax data, required forms, blank PDFs, field maps, and filled PDF manifests."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--forms-plan", help="Path to required_irs_forms.yaml.")
    parser.add_argument("--state-forms-plan", help="Path to required_state_forms.yaml.")
    parser.add_argument("--blank-dir", help="Directory containing blank PDFs for --forms-plan.")
    parser.add_argument("--field-map-dir", help="Directory containing field maps.")
    parser.add_argument("--state-blank-dir", help="Directory containing blank state PDFs.")
    parser.add_argument("--state-field-map-dir", help="Directory containing state field maps.")
    parser.add_argument("--skip-state-forms", action="store_true", help="Do not validate required_state_forms.yaml.")
    parser.add_argument("--filled-manifest", help="Path to filled_pdf_manifest.yaml.")
    parser.add_argument("--output", help="Path for validation_report.yaml.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    forms_plan_path = (
        Path(args.forms_plan).expanduser().resolve()
        if args.forms_plan
        else tax_forms / "required_irs_forms.yaml"
    )
    state_forms_plan_path = (
        Path(args.state_forms_plan).expanduser().resolve()
        if args.state_forms_plan
        else tax_forms / "required_state_forms.yaml"
    )
    blank_dir = (
        Path(args.blank_dir).expanduser().resolve()
        if args.blank_dir
        else tax_forms / "workpapers" / "blank_forms" / "irs"
    )
    field_map_dir = (
        Path(args.field_map_dir).expanduser().resolve()
        if args.field_map_dir
        else tax_forms / "workpapers" / "field_maps"
    )
    state_blank_dir = (
        Path(args.state_blank_dir).expanduser().resolve()
        if args.state_blank_dir
        else tax_forms / "workpapers" / "blank_forms" / "ca"
    )
    state_field_map_dir = (
        Path(args.state_field_map_dir).expanduser().resolve()
        if args.state_field_map_dir
        else tax_forms / "workpapers" / "field_maps" / "ca"
    )
    filled_manifest_path = (
        Path(args.filled_manifest).expanduser().resolve()
        if args.filled_manifest
        else tax_forms / "workpapers" / "filled_pdf_manifest.yaml"
    )
    output_path = Path(args.output).expanduser().resolve() if args.output else tax_forms / "workpapers" / "validation_report.yaml"

    issues: list[dict[str, str]] = []
    data = load_yaml(data_path)
    plan = load_yaml(forms_plan_path)
    state_plan = load_yaml(state_forms_plan_path)
    filled_manifest = load_yaml(filled_manifest_path)

    if not isinstance(data, dict) or not data:
        add_issue(issues, "error", "missing_data", f"Missing or invalid data YAML: {data_path}")
    else:
        if is_unknown(data.get("tax_year")):
            add_issue(issues, "error", "missing_tax_year", "tax_year is missing.", "tax_year")
        validate_taxpayer(data, issues)
        validate_rental_entries(data, issues)
        validate_itemized_deductions(data, issues)
        validate_money_values(data, issues)
        if not data.get("source_documents") and not (tax_forms / "source_manifest.yaml").exists():
            add_issue(issues, "warning", "no_source_documents", "No source documents are recorded.")

    tax_year = str(data.get("tax_year", "unknown")) if isinstance(data, dict) else "unknown"
    if isinstance(plan, dict) and plan:
        validate_forms(plan, tax_year, blank_dir, field_map_dir, root, issues, require_f1040=not is_state_plan(plan))
    else:
        add_issue(issues, "warning", "missing_forms_plan", f"Missing or invalid forms plan: {forms_plan_path}")

    if not args.skip_state_forms and isinstance(state_plan, dict) and state_plan:
        should_validate_state = bool(state_plan.get("forms")) or state_plan.get("status") not in {None, "not_inferred"}
        if should_validate_state:
            validate_forms(
                state_plan,
                tax_year,
                state_blank_dir,
                state_field_map_dir,
                root,
                issues,
                require_f1040=False,
            )

    if isinstance(filled_manifest, dict):
        validate_filled_manifest(filled_manifest, issues)

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    report = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "failed" if error_count else "passed",
        "error_count": error_count,
        "warning_count": warning_count,
        "inputs": {
            "data": str(data_path),
            "forms_plan": str(forms_plan_path),
            "state_forms_plan": str(state_forms_plan_path),
            "blank_dir": str(blank_dir),
            "field_map_dir": str(field_map_dir),
            "state_blank_dir": str(state_blank_dir),
            "state_field_map_dir": str(state_field_map_dir),
            "filled_manifest": str(filled_manifest_path),
        },
        "issues": issues,
    }
    dump_yaml(report, output_path)
    print(f"Validation report: {output_path}")
    print(f"Errors: {error_count}; warnings: {warning_count}")
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
