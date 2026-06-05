#!/usr/bin/env python3
"""Calculate California resident return line values from extracted YAML using OTS math."""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc

from ots_math import OTSMathError, apply_ca_outputs, evaluate_federal_and_ca, write_report_fields


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}
ENGINE_VERSION = "0.2"

CA_STANDARD_DEDUCTION_2025 = {
    "single": Decimal("5706"),
    "married_filing_separately": Decimal("5706"),
    "married_rdp_filing_separately": Decimal("5706"),
    "married_filing_jointly": Decimal("11412"),
    "married_rdp_filing_jointly": Decimal("11412"),
    "head_of_household": Decimal("11412"),
    "qualifying_surviving_spouse": Decimal("11412"),
    "qualifying_surviving_spouse_rdp": Decimal("11412"),
}


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"YAML file not found: {path}")
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


def money(value: Any) -> Decimal:
    if is_unknown(value):
        return Decimal("0")
    text = str(value).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def money_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if is_unknown(value):
        return []
    return [value]


def entries(data: dict[str, Any], dotted_path: str) -> list[dict[str, Any]]:
    return [item for item in as_list(get_path(data, dotted_path)) if isinstance(item, dict)]


def first_amount(item: dict[str, Any], keys: list[str]) -> Decimal:
    for key in keys:
        if key in item and not is_unknown(item.get(key)):
            return money(item.get(key))
    return Decimal("0")


def total_entries(items: list[dict[str, Any]], keys: list[str]) -> Decimal:
    return sum((first_amount(item, keys) for item in items), Decimal("0"))


def normalize_state(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"CALIFORNIA", "CA"}:
        return "CA"
    return text


def filing_status(data: dict[str, Any]) -> str:
    return str(get_path(data, "taxpayer.filing_status") or "unknown").strip().lower()


def add_review(review_items: list[dict[str, str]], topic: str, message: str, severity: str = "review") -> None:
    review_items.append({"severity": severity, "topic": topic, "message": message})


def set_line(lines: dict[str, str], line: str, value: Decimal) -> None:
    lines[line] = money_string(value)


def ca_w2_values(data: dict[str, Any]) -> tuple[Decimal, Decimal]:
    wages = Decimal("0")
    withholding = Decimal("0")
    for wage in entries(data, "income.wages"):
        for state_item in as_list(wage.get("state_items")):
            if not isinstance(state_item, dict) or normalize_state(state_item.get("state")) != "CA":
                continue
            wages += first_amount(state_item, ["state_wages_box_16", "wages", "amount"])
            withholding += first_amount(state_item, ["state_income_tax_box_17", "withholding", "amount"])
    return wages, withholding


def ca_payment_total(data: dict[str, Any], path: str) -> Decimal:
    total = Decimal("0")
    for payment in entries(data, path):
        if normalize_state(payment.get("state")) == "CA":
            total += first_amount(payment, ["amount", "payment_amount", "withholding"])
    return total


def federal_line(data: dict[str, Any], line: str) -> Decimal:
    return money(get_path(data, f"calculated.form_line_values.f1040.{line}"))


def explicit_ca_amount(data: dict[str, Any], key: str) -> Decimal:
    return money(get_path(data, f"state_adjustments.ca.{key}"))


def explicit_or_federal(data: dict[str, Any], ca_key: str, federal_line_name: str) -> Decimal:
    explicit = get_path(data, f"state_adjustments.ca.{ca_key}")
    if not is_unknown(explicit):
        return money(explicit)
    return federal_line(data, federal_line_name)


def ca_standard_deduction(data: dict[str, Any], review_items: list[dict[str, str]]) -> tuple[Decimal, bool]:
    explicit = get_path(data, "state_adjustments.ca.standard_deduction")
    if not is_unknown(explicit):
        return money(explicit), True
    tax_year = str(data.get("tax_year") or "unknown")
    if tax_year != "2025":
        add_review(
            review_items,
            "ca_standard_deduction",
            "California standard deduction constants are bundled only for tax year 2025. Provide state_adjustments.ca.standard_deduction for this tax year.",
            "error",
        )
        return Decimal("0"), False
    status = filing_status(data)
    if status in CA_STANDARD_DEDUCTION_2025:
        return CA_STANDARD_DEDUCTION_2025[status], True
    add_review(
        review_items,
        "ca_standard_deduction",
        "California standard deduction was not calculated because filing status is missing or unsupported.",
    )
    return Decimal("0"), False


def calculate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    totals: dict[str, str] = {}
    ca540: dict[str, str] = {}
    ca540ca: dict[str, str] = {}

    federal_agi_raw = get_path(data, "calculated.form_line_values.f1040.line_11_adjusted_gross_income")
    federal_agi = money(federal_agi_raw)
    if is_unknown(federal_agi_raw):
        add_review(
            review_items,
            "ca_federal_agi",
            "Form 540 line 13 needs federal Form 1040 line 11 AGI before California taxable income can be trusted.",
            "error",
        )

    ca_state_wages, w2_state_withholding = ca_w2_values(data)
    payment_state_withholding = ca_payment_total(data, "payments.state_withholding")
    ca_withholding = payment_state_withholding if payment_state_withholding else w2_state_withholding
    ca_estimated_payments = ca_payment_total(data, "payments.state_estimated_payments")
    ca_extension_payments = ca_payment_total(data, "payments.state_extension_payments")

    ca_subtractions = explicit_ca_amount(data, "subtractions_total")
    ca_additions = explicit_ca_amount(data, "additions_total")
    ca_rental_depreciation_addition = explicit_ca_amount(data, "rental_depreciation_addition")
    ca_rental_depreciation_subtraction = explicit_ca_amount(data, "rental_depreciation_subtraction")
    ca_additions += ca_rental_depreciation_addition
    ca_subtractions += ca_rental_depreciation_subtraction
    no_adjustments_confirmed = get_path(data, "state_adjustments.ca.reviewed_no_adjustments") is True
    if not no_adjustments_confirmed and ca_subtractions == 0 and ca_additions == 0:
        add_review(
            review_items,
            "ca_schedule_ca_adjustments",
            "Review Schedule CA (540) for California/federal differences; this engine assumes zero adjustments only when reviewed_no_adjustments is true.",
        )

    set_line(ca540, "line_12_state_wages", ca_state_wages)
    set_line(ca540, "line_13_federal_agi", federal_agi)
    set_line(ca540, "line_14_ca_adjustments_subtractions", ca_subtractions)
    line_15 = federal_agi - ca_subtractions
    set_line(ca540, "line_15_subtotal", line_15)
    set_line(ca540, "line_16_ca_adjustments_additions", ca_additions)
    ca_agi = line_15 + ca_additions
    set_line(ca540, "line_17_ca_adjusted_gross_income", ca_agi)

    deduction_method = str(get_path(data, "deductions.standard_or_itemized") or "").strip().lower()
    deduction_known = False
    if deduction_method == "itemized":
        itemized = get_path(data, "state_adjustments.ca.itemized_deduction_total")
        if is_unknown(itemized):
            deduction = Decimal("0")
            add_review(
                review_items,
                "ca_itemized_deduction",
                "California itemized deduction total is not calculated. Provide state_adjustments.ca.itemized_deduction_total or use the standard deduction.",
                "error",
            )
        else:
            deduction = money(itemized)
            deduction_known = True
    else:
        deduction, deduction_known = ca_standard_deduction(data, review_items)
        if get_path(data, "taxpayer.can_be_claimed_as_dependent") is True:
            add_review(
                review_items,
                "ca_dependent_standard_deduction",
                "Taxpayer can be claimed as a dependent; review the modified California standard deduction rules.",
            )

    set_line(ca540, "line_18_standard_or_itemized_deduction", deduction)
    if deduction_known:
        set_line(ca540, "line_19_taxable_income", max(Decimal("0"), ca_agi - deduction))

    set_line(ca540, "line_71_ca_income_tax_withheld", ca_withholding)
    set_line(ca540, "line_72_ca_estimated_tax_payments", ca_estimated_payments)
    if ca_extension_payments:
        set_line(ca540, "line_72_ca_extension_payments", ca_extension_payments)

    set_line(ca540ca, "part_i_line_1a_federal_wages", federal_line(data, "line_1a"))
    set_line(ca540ca, "part_i_line_2b_federal_taxable_interest", federal_line(data, "line_2b"))
    set_line(ca540ca, "part_i_line_3b_federal_ordinary_dividends", federal_line(data, "line_3b"))
    set_line(ca540ca, "part_i_line_7_federal_capital_gain_or_loss", federal_line(data, "line_7"))
    set_line(ca540ca, "part_i_line_8_federal_additional_income", federal_line(data, "line_8"))
    set_line(ca540ca, "part_i_line_27_subtractions_total", ca_subtractions)
    set_line(ca540ca, "part_i_line_27_additions_total", ca_additions)

    for topic, message in [
        (
            "ca_line_31_tax",
            "Form 540 line 31 tax requires OpenTaxSolver evaluation; this review item is cleared when OTS succeeds.",
        ),
        (
            "ca_exemption_credits",
            "Form 540 exemption credits require OpenTaxSolver evaluation; this review item is cleared when OTS succeeds.",
        ),
        (
            "ca_use_tax_and_voluntary_contributions",
            "California use tax, special credits, voluntary contributions, penalties, and direct deposit/payment instructions require user review.",
        ),
        (
            "ca_amt_and_mental_health_services_tax",
            "California AMT and Behavioral Health Services Tax require reviewed inputs; OTS carries them through when supplied.",
        ),
    ]:
        add_review(review_items, topic, message)

    totals.update(
        {
            "ca_state_wages_w2_box_16": money_string(ca_state_wages),
            "ca_federal_agi": money_string(federal_agi),
            "ca_adjustments_subtractions": money_string(ca_subtractions),
            "ca_adjustments_additions": money_string(ca_additions),
            "ca_rental_depreciation_addition": money_string(ca_rental_depreciation_addition),
            "ca_rental_depreciation_subtraction": money_string(ca_rental_depreciation_subtraction),
            "ca_adjusted_gross_income": money_string(ca_agi),
            "ca_income_tax_withheld": money_string(ca_withholding),
            "ca_estimated_tax_payments": money_string(ca_estimated_payments),
        }
    )

    calculated = data.setdefault("calculated", {})
    calculated.setdefault("form_line_values", {})
    calculated["form_line_values"]["ca540"] = ca540
    calculated["form_line_values"]["ca540ca"] = ca540ca
    ots_result: dict[str, Any] | None = None
    try:
        ots_result = evaluate_federal_and_ca(data)
    except OTSMathError as exc:
        add_review(review_items, "ca_ots_math_engine", str(exc), "error")
    else:
        apply_ca_outputs(calculated["form_line_values"], totals, review_items, ots_result)
        ca540 = calculated["form_line_values"]["ca540"]

    state_calculated = calculated.setdefault("state", {})
    state_calculated["ca"] = {
        "engine_version": ENGINE_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "ca_resident_lines_with_ots",
        "totals": totals,
        "forms": ["ca540", "ca540ca"],
        "review_items": review_items,
        "math_engine": ots_result["engine"] if ots_result else None,
        "official_sources": [
            {
                "agency": "California Franchise Tax Board",
                "url": "https://www.ftb.ca.gov/forms/2025/2025-540.pdf",
                "notes": "Form 540 lines 12-19 and 71-72 mapping.",
            },
            {
                "agency": "California Franchise Tax Board",
                "url": "https://www.ftb.ca.gov/forms/2025/2025-540-es-instructions.html",
                "notes": "Standard deduction reference; OTS supplies supported-year deduction math.",
            },
        ],
    }
    ca_topics = {item["topic"] for item in review_items}
    existing_review_items = calculated.setdefault("review_items", [])
    calculated["review_items"] = [
        item
        for item in existing_review_items
        if not (
            isinstance(item, dict)
            and item.get("topic") in ca_topics
            and str(item.get("message", "")).startswith("California:")
        )
    ]
    calculated["review_items"].extend(
        {"severity": item["severity"], "topic": item["topic"], "message": f"California: {item['message']}"}
        for item in review_items
    )
    data["review_status"] = "calculated_needs_review"

    report = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "generated_at": calculated["state"]["ca"]["generated_at"],
        "scope": "ca_resident_lines_with_ots",
        "totals": totals,
        "forms": ["ca540", "ca540ca"],
        "review_items": review_items,
    }
    if ots_result:
        write_report_fields(report, ots_result, state=True)
    return data, report


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate California resident line values from extracted_tax_data.yaml using OpenTaxSolver where supported."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for updated extracted tax data. Defaults to overwriting --data.")
    parser.add_argument(
        "--report",
        help="Path for California calculation report. Defaults to tax_forms/workpapers/ca_calculation_report.yaml.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else data_path
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else tax_forms / "workpapers" / "ca_calculation_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")

    updated_data, report = calculate(data)
    dump_yaml(updated_data, output_path)
    dump_yaml(report, report_path)

    print(f"Updated data: {relative_to_root(output_path, root)}")
    print(f"California calculation report: {relative_to_root(report_path, root)}")
    print(f"Review items: {len(report['review_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
