#!/usr/bin/env python3
"""Calculate federal tax return line values from extracted YAML using OTS math."""

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

from ots_math import OTSMathError, apply_federal_outputs, evaluate_federal, write_report_fields


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}
ENGINE_VERSION = "0.2"


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


def meaningful(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    return True


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


def set_line(lines: dict[str, str], line: str, value: Decimal) -> None:
    lines[line] = money_string(value)


def add_review(review_items: list[dict[str, str]], topic: str, message: str, severity: str = "review") -> None:
    review_items.append({"severity": severity, "topic": topic, "message": message})


def filing_status(data: dict[str, Any]) -> str:
    return str(get_path(data, "taxpayer.filing_status") or "unknown").strip().lower()


def capital_loss_limit(data: dict[str, Any]) -> Decimal:
    # This limit has been stable for current individual returns, but keep it
    # isolated so a tax-year ruleset can replace it later.
    return Decimal("1500") if filing_status(data) == "married_filing_separately" else Decimal("3000")


def classify_retirement_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ira_items = []
    pension_items = []
    for item in items:
        marker = " ".join(
            str(item.get(key, "")).lower()
            for key in ["type", "distribution_type", "ira_sep_simple", "source_document_type", "source_document_id"]
        )
        if "ira" in marker or item.get("ira_sep_simple") is True:
            ira_items.append(item)
        else:
            pension_items.append(item)
    return ira_items, pension_items


def capital_gain_or_loss(item: dict[str, Any]) -> Decimal:
    explicit = first_amount(
        item,
        [
            "gain_or_loss",
            "gain_loss",
            "net_gain_loss",
            "capital_gain_or_loss",
            "amount",
        ],
    )
    if explicit:
        return explicit
    proceeds = first_amount(item, ["proceeds", "proceeds_box_1d", "sales_price"])
    basis = first_amount(item, ["cost_basis", "basis_box_1e", "basis"])
    adjustment = first_amount(item, ["adjustment_amount", "wash_sale_disallowed", "adjustments"])
    return proceeds - basis + adjustment


def is_short_term(item: dict[str, Any]) -> bool:
    return str(item.get("term", item.get("holding_period", ""))).strip().lower().startswith("short")


def is_long_term(item: dict[str, Any]) -> bool:
    return str(item.get("term", item.get("holding_period", ""))).strip().lower().startswith("long")


def calculate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    totals: dict[str, str] = {}
    existing_form_line_values = get_path(data, "calculated.form_line_values")
    form_line_values: dict[str, dict[str, Any]] = (
        dict(existing_form_line_values) if isinstance(existing_form_line_values, dict) else {}
    )
    worksheets: list[dict[str, str]] = []

    f1040: dict[str, str] = {}
    s1: dict[str, str] = {}
    s2: dict[str, str] = {}
    s3: dict[str, str] = {}
    sd: dict[str, str] = {}
    sc: dict[str, str] = {}
    se: dict[str, Any] = dict(form_line_values.get("f1040se") or {})

    wages = entries(data, "income.wages")
    interest = entries(data, "income.interest")
    dividends = entries(data, "income.dividends")
    capital_items = entries(data, "income.capital_gains")
    retirement = entries(data, "income.retirement_distributions")
    social_security = entries(data, "income.social_security")
    business = entries(data, "income.business_or_1099_income")
    rentals = entries(data, "income.rentals_royalties_partnerships")
    other_income = entries(data, "income.other_income")

    wage_income = total_entries(wages, ["wages_box_1", "wages", "amount"])
    w2_withholding = total_entries(wages, ["federal_income_tax_withheld_box_2", "federal_withholding"])
    taxable_interest = total_entries(interest, ["interest_income_box_1", "taxable_interest", "amount"])
    tax_exempt_interest = total_entries(interest, ["tax_exempt_interest_box_8", "tax_exempt_interest"])
    interest_withholding = total_entries(interest, ["federal_income_tax_withheld_box_4", "federal_withholding"])
    ordinary_dividends = total_entries(dividends, ["ordinary_dividends_box_1a", "ordinary_dividends", "amount"])
    qualified_dividends = total_entries(dividends, ["qualified_dividends_box_1b", "qualified_dividends"])
    capital_gain_distributions = total_entries(dividends, ["capital_gain_distributions_box_2a", "capital_gain_distributions"])
    dividend_withholding = total_entries(dividends, ["federal_income_tax_withheld_box_4", "federal_withholding"])
    foreign_tax_paid = total_entries(dividends, ["foreign_tax_paid_box_7", "foreign_tax_paid"])

    ira_items, pension_items = classify_retirement_items(retirement)
    ira_gross = total_entries(ira_items, ["gross_distribution_box_1", "gross_distribution", "amount"])
    ira_taxable = total_entries(ira_items, ["taxable_amount_box_2a", "taxable_amount"])
    pension_gross = total_entries(pension_items, ["gross_distribution_box_1", "gross_distribution", "amount"])
    pension_taxable = total_entries(pension_items, ["taxable_amount_box_2a", "taxable_amount"])
    retirement_withholding = total_entries(retirement, ["federal_income_tax_withheld_box_4", "federal_withholding"])

    ss_benefits = total_entries(social_security, ["net_benefits_box_5", "benefits", "amount"])
    ss_taxable = total_entries(social_security, ["taxable_amount", "taxable_benefits"])
    ss_withholding = total_entries(social_security, ["federal_income_tax_withheld", "federal_withholding"])
    if social_security and ss_taxable == 0:
        add_review(
            review_items,
            "social_security_taxable_amount",
            "Social Security benefits are present, but taxable benefits require the IRS worksheet unless taxable_amount is provided.",
        )

    short_capital = sum((capital_gain_or_loss(item) for item in capital_items if is_short_term(item)), Decimal("0"))
    long_capital = sum((capital_gain_or_loss(item) for item in capital_items if is_long_term(item)), Decimal("0"))
    unknown_capital = [item for item in capital_items if not is_short_term(item) and not is_long_term(item)]
    unknown_capital_total = sum((capital_gain_or_loss(item) for item in unknown_capital), Decimal("0"))
    if unknown_capital:
        add_review(
            review_items,
            "capital_gain_term",
            "Some capital gain/loss items do not identify short-term vs long-term holding period.",
        )
    long_capital += capital_gain_distributions
    schedule_d_line_7 = short_capital + unknown_capital_total
    schedule_d_line_15 = long_capital
    schedule_d_line_16 = schedule_d_line_7 + schedule_d_line_15
    form1040_capital = schedule_d_line_16
    if schedule_d_line_16 < 0:
        form1040_capital = max(schedule_d_line_16, -capital_loss_limit(data))

    if capital_items or capital_gain_distributions:
        set_line(sd, "line_7", schedule_d_line_7)
        set_line(sd, "line_15", schedule_d_line_15)
        set_line(sd, "line_16", schedule_d_line_16)
        set_line(sd, "line_21_to_form_1040", form1040_capital)

    business_gross = total_entries(
        business,
        ["gross_receipts", "nonemployee_compensation_box_1", "gross_payment", "amount"],
    )
    business_net = total_entries(business, ["net_profit", "schedule_c_net_profit", "net_income"])
    business_withholding = total_entries(business, ["federal_income_tax_withheld", "backup_withholding"])
    if business and business_net == 0 and business_gross != 0:
        add_review(
            review_items,
            "schedule_c_net_profit",
            "Business income is present. Provide net_profit after expenses before using Schedule C net income on Form 1040.",
        )
    if business_gross:
        set_line(sc, "gross_receipts", business_gross)
    if business_net:
        set_line(sc, "net_profit_or_loss", business_net)
        set_line(s1, "line_3_business_income_or_loss", business_net)
        add_review(
            review_items,
            "self_employment_tax",
            "Schedule SE tax is not calculated by this engine yet; calculate it from reviewed Schedule C/SE data.",
        )

    rental_total = total_entries(
        rentals,
        ["income_loss", "ordinary_business_income_loss", "rental_real_estate_income_loss", "amount"],
    )
    if rental_total == 0:
        rental_total = money(
            get_path(
                data,
                "calculated.form_line_values.f1040se.line_26_total_rental_real_estate_and_royalty_income_or_loss",
            )
        )
    if rental_total:
        set_line(se, "total_income_or_loss", rental_total)
        set_line(s1, "line_5_rental_royalty_partnerships_estates_trusts", rental_total)

    other_income_total = total_entries(other_income, ["amount", "income", "taxable_amount"])
    if other_income_total:
        set_line(s1, "line_8z_other_income", other_income_total)

    additional_income = business_net + rental_total + other_income_total
    if additional_income:
        set_line(s1, "line_10_additional_income_total", additional_income)

    adjustments = get_path(data, "adjustments") or {}
    adjustment_total = Decimal("0")
    if isinstance(adjustments, dict):
        for section, value in adjustments.items():
            if section in {"self_employed"} and meaningful(value):
                add_review(
                    review_items,
                    "self_employed_adjustments",
                    "Self-employed adjustments require current worksheets and are not calculated by this engine yet.",
                )
            for item in as_list(value):
                if isinstance(item, dict):
                    adjustment_total += first_amount(item, ["deduction_amount", "amount", "allowable_amount"])
    if adjustment_total:
        set_line(s1, "line_26_adjustments_to_income", adjustment_total)

    credits = get_path(data, "credits") or {}
    schedule3_credit_total = Decimal("0")
    child_credit_total = Decimal("0")
    if isinstance(credits, dict):
        child_credit_total = total_entries(entries(data, "credits.child_and_dependent"), ["credit_amount", "amount"])
        for section, value in credits.items():
            for item in as_list(value):
                if isinstance(item, dict):
                    amount = first_amount(item, ["credit_amount", "amount", "allowable_amount"])
                    if section in {"education", "foreign_tax", "retirement_saver", "energy", "premium_tax_credit", "other"}:
                        schedule3_credit_total += amount
        if meaningful(credits.get("foreign_tax")) and not schedule3_credit_total:
            add_review(
                review_items,
                "foreign_tax_credit",
                "Foreign tax credit data is present but the allowable credit may require Form 1116 or Schedule 3 review.",
            )
    if schedule3_credit_total:
        set_line(s3, "line_8_total_other_credits", schedule3_credit_total)

    payments = get_path(data, "payments") or {}
    estimated_payments = Decimal("0")
    extension_payments = Decimal("0")
    refundable_credits = Decimal("0")
    other_federal_withholding = Decimal("0")
    if isinstance(payments, dict):
        estimated_payments = total_entries(entries(data, "payments.estimated_tax_payments"), ["amount"])
        extension_payments = total_entries(entries(data, "payments.extension_payments"), ["amount"])
        refundable_credits = total_entries(entries(data, "payments.refundable_credits"), ["amount", "credit_amount"])
        other_federal_withholding = total_entries(entries(data, "payments.federal_withholding"), ["amount"])
    form1099_withholding = interest_withholding + dividend_withholding + retirement_withholding + ss_withholding + business_withholding
    total_withholding = w2_withholding + form1099_withholding + other_federal_withholding

    set_line(f1040, "line_1a", wage_income)
    set_line(f1040, "line_1z", wage_income)
    set_line(f1040, "line_2a", tax_exempt_interest)
    set_line(f1040, "line_2b", taxable_interest)
    set_line(f1040, "line_3a", qualified_dividends)
    set_line(f1040, "line_3b", ordinary_dividends)
    set_line(f1040, "line_4a", ira_gross)
    set_line(f1040, "line_4b", ira_taxable)
    set_line(f1040, "line_5a", pension_gross)
    set_line(f1040, "line_5b", pension_taxable)
    set_line(f1040, "line_6a", ss_benefits)
    if ss_taxable:
        set_line(f1040, "line_6b", ss_taxable)
    set_line(f1040, "line_7", form1040_capital)
    set_line(f1040, "line_8", additional_income)

    total_income = wage_income + taxable_interest + ordinary_dividends + ira_taxable + pension_taxable + ss_taxable + form1040_capital + additional_income
    set_line(f1040, "line_9_total_income", total_income)
    set_line(f1040, "line_10_adjustments_to_income", adjustment_total)
    agi = total_income - adjustment_total
    set_line(f1040, "line_11_adjusted_gross_income", agi)

    deduction_value = Decimal("0")
    deduction_known = False
    deduction_data = get_path(data, "deductions") or {}
    if isinstance(deduction_data, dict):
        for key in ["selected_deduction_amount", "standard_deduction", "itemized_deduction_total"]:
            if key in deduction_data and not is_unknown(deduction_data.get(key)):
                deduction_value = money(deduction_data[key])
                deduction_known = True
                break
    if deduction_known:
        set_line(f1040, "line_12_standard_or_itemized_deduction", deduction_value)
    else:
        add_review(
            review_items,
            "deduction_amount",
            "Provide selected_deduction_amount, standard_deduction, or itemized_deduction_total before calculating taxable income.",
        )

    qbi_deduction = Decimal("0")
    qbi_value = get_path(data, "deductions.qbi_deduction")
    if not is_unknown(qbi_value):
        qbi_deduction = money(qbi_value)
        set_line(f1040, "line_13_qualified_business_income_deduction", qbi_deduction)
    elif business_net or rental_total:
        add_review(
            review_items,
            "qbi_deduction",
            "Business or pass-through income is present. QBI deduction is not calculated unless deductions.qbi_deduction is provided.",
        )

    if deduction_known:
        total_deductions = deduction_value + qbi_deduction
        set_line(f1040, "line_14_total_deductions", total_deductions)
        set_line(f1040, "line_15_taxable_income", max(Decimal("0"), agi - total_deductions))

    tax_line_16 = get_path(data, "calculated.form_line_values.f1040.line_16_tax")
    if not is_unknown(tax_line_16):
        set_line(f1040, "line_16_tax", money(tax_line_16))
    else:
        add_review(
            review_items,
            "line_16_tax",
            "Form 1040 line 16 tax requires OpenTaxSolver evaluation; this review item is cleared when OTS succeeds.",
        )

    if child_credit_total:
        set_line(f1040, "line_19_child_tax_credit_or_credit_for_other_dependents", child_credit_total)
    if schedule3_credit_total:
        set_line(f1040, "line_20_schedule_3_line_8", schedule3_credit_total)

    schedule2_tax_total = Decimal("0")
    if isinstance(get_path(data, "taxes"), dict):
        schedule2_tax_total = total_entries(entries(data, "taxes.additional_taxes"), ["amount", "tax_amount"])
    if schedule2_tax_total:
        set_line(s2, "line_21_total_other_taxes", schedule2_tax_total)
        set_line(f1040, "line_23_other_taxes", schedule2_tax_total)

    set_line(f1040, "line_25a_federal_income_tax_withheld_from_w2", w2_withholding)
    set_line(f1040, "line_25b_federal_income_tax_withheld_from_1099", form1099_withholding)
    set_line(f1040, "line_25c_other_federal_income_tax_withheld", other_federal_withholding)
    set_line(f1040, "line_25d_total_federal_income_tax_withheld", total_withholding)
    set_line(f1040, "line_26_estimated_tax_payments", estimated_payments)
    if extension_payments:
        set_line(s3, "line_10_amount_paid_with_extension", extension_payments)
    if refundable_credits:
        set_line(f1040, "line_31_other_payments_and_refundable_credits", refundable_credits)
    total_payments = total_withholding + estimated_payments + extension_payments + refundable_credits
    set_line(f1040, "line_33_total_payments", total_payments)

    totals.update(
        {
            "wages": money_string(wage_income),
            "taxable_interest": money_string(taxable_interest),
            "tax_exempt_interest": money_string(tax_exempt_interest),
            "ordinary_dividends": money_string(ordinary_dividends),
            "qualified_dividends": money_string(qualified_dividends),
            "capital_gain_distributions": money_string(capital_gain_distributions),
            "capital_gain_or_loss_before_1040_loss_limit": money_string(schedule_d_line_16),
            "business_gross_receipts": money_string(business_gross),
            "business_net_profit": money_string(business_net),
            "rental_royalty_partnership_income_or_loss": money_string(rental_total),
            "additional_income": money_string(additional_income),
            "adjustments_to_income": money_string(adjustment_total),
            "federal_withholding": money_string(total_withholding),
            "estimated_tax_payments": money_string(estimated_payments),
            "total_payments": money_string(total_payments),
            "foreign_tax_paid": money_string(foreign_tax_paid),
        }
    )

    form_line_values["f1040"] = f1040
    if s1:
        form_line_values["f1040s1"] = s1
    if s2:
        form_line_values["f1040s2"] = s2
    if s3:
        form_line_values["f1040s3"] = s3
    if sd:
        form_line_values["f1040sd"] = sd
    if sc:
        form_line_values["f1040sc"] = sc
    if se:
        form_line_values["f1040se"] = se

    calculated = data.setdefault("calculated", {})
    calculated["form_line_values"] = form_line_values
    ots_result: dict[str, Any] | None = None
    try:
        ots_result = evaluate_federal(data)
    except OTSMathError as exc:
        add_review(review_items, "ots_math_engine", str(exc), "error")
    else:
        apply_federal_outputs(form_line_values, totals, review_items, ots_result)

    calculated["engine_version"] = ENGINE_VERSION
    calculated["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    calculated["scope"] = "federal_common_lines_with_ots"
    calculated["totals"] = totals
    calculated["form_line_values"] = form_line_values
    calculated["worksheets"] = worksheets
    calculated["review_items"] = review_items
    if ots_result:
        calculated["math_engine"] = ots_result["engine"]
    data["review_status"] = "calculated_needs_review" if review_items else "calculated"

    report = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "generated_at": calculated["generated_at"],
        "scope": calculated["scope"],
        "totals": totals,
        "forms": sorted(form_line_values.keys()),
        "review_items": review_items,
    }
    if ots_result:
        write_report_fields(report, ots_result)
    return data, report


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate federal line values from extracted_tax_data.yaml using OpenTaxSolver where supported."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for updated extracted tax data. Defaults to overwriting --data.")
    parser.add_argument(
        "--report",
        help="Path for calculation report. Defaults to tax_forms/workpapers/calculation_report.yaml.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else data_path
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else tax_forms / "workpapers" / "calculation_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")

    updated_data, report = calculate(data)
    dump_yaml(updated_data, output_path)
    dump_yaml(report, report_path)

    print(f"Updated data: {relative_to_root(output_path, root)}")
    print(f"Calculation report: {relative_to_root(report_path, root)}")
    print(f"Review items: {len(report['review_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
