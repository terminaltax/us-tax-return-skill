#!/usr/bin/env python3
"""Calculate common Schedule A itemized deduction lines from extracted YAML."""

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


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}
ENGINE_VERSION = "0.1"
SUPPORTED_TAX_YEAR = "2025"

FEDERAL_STANDARD_DEDUCTION_2025 = {
    "single": Decimal("15750"),
    "married_filing_jointly": Decimal("31500"),
    "qualifying_surviving_spouse": Decimal("31500"),
    "surviving_spouse": Decimal("31500"),
    "married_filing_separately": Decimal("15750"),
    "head_of_household": Decimal("23625"),
}

CA_STANDARD_DEDUCTION_2025 = {
    "single": Decimal("5706"),
    "married_filing_jointly": Decimal("11412"),
    "qualifying_surviving_spouse": Decimal("11412"),
    "surviving_spouse": Decimal("11412"),
    "married_filing_separately": Decimal("5706"),
    "head_of_household": Decimal("11412"),
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


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    current = data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def entries(data: dict[str, Any], dotted_path: str) -> list[dict[str, Any]]:
    return [item for item in as_list(get_path(data, dotted_path)) if isinstance(item, dict)]


def first_value(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and not is_unknown(item.get(key)):
            return item.get(key)
    return None


def first_amount(item: dict[str, Any], keys: list[str]) -> Decimal:
    return money(first_value(item, keys))


def amount_entries(items: list[dict[str, Any]], keys: list[str]) -> Decimal:
    return sum((first_amount(item, keys) for item in items), Decimal("0"))


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "y", "1"}
    return False


def filing_status(data: dict[str, Any]) -> str:
    return str(get_path(data, "taxpayer.filing_status") or "").strip().lower()


def add_review(review_items: list[dict[str, str]], topic: str, message: str) -> None:
    review_items.append({"severity": "review", "topic": topic, "message": message})


def agi_amount(data: dict[str, Any]) -> Decimal:
    for path in [
        "calculated.form_line_values.f1040.line_11_adjusted_gross_income",
        "calculated.totals.adjusted_gross_income",
        "income.adjusted_gross_income",
    ]:
        value = get_path(data, path)
        if not is_unknown(value):
            return money(value)
    return Decimal("0")


def standard_deduction(data: dict[str, Any], review_items: list[dict[str, str]]) -> Decimal:
    explicit = get_path(data, "deductions.standard_deduction")
    if not is_unknown(explicit):
        return money(explicit)
    if str(data.get("tax_year")) != SUPPORTED_TAX_YEAR:
        add_review(
            review_items,
            "schedule_a_standard_deduction",
            "Federal standard deduction constants are bundled only for tax year 2025. Provide deductions.standard_deduction for this tax year.",
        )
        return Decimal("0")
    status = filing_status(data)
    if status in FEDERAL_STANDARD_DEDUCTION_2025:
        return FEDERAL_STANDARD_DEDUCTION_2025[status]
    add_review(
        review_items,
        "schedule_a_standard_deduction",
        "Filing status is missing or unsupported, so the federal standard deduction was not calculated.",
    )
    return Decimal("0")


def ca_standard_deduction(data: dict[str, Any], review_items: list[dict[str, str]]) -> Decimal:
    explicit = get_path(data, "state_adjustments.ca.standard_deduction")
    if not is_unknown(explicit):
        return money(explicit)
    if str(data.get("tax_year")) != SUPPORTED_TAX_YEAR:
        return Decimal("0")
    return CA_STANDARD_DEDUCTION_2025.get(filing_status(data), Decimal("0"))


def schedule_a_entries(data: dict[str, Any], category: str) -> list[dict[str, Any]]:
    return entries(data, f"deductions.itemized.{category}")


def medical_total(data: dict[str, Any]) -> Decimal:
    total = Decimal("0")
    for item in schedule_a_entries(data, "medical"):
        gross = first_amount(item, ["allowable_amount", "amount", "expense_amount", "paid_amount"])
        reimbursements = first_amount(item, ["reimbursed_amount", "reimbursements"])
        total += max(Decimal("0"), gross - reimbursements)
    return total


def tax_totals(data: dict[str, Any]) -> dict[str, Decimal]:
    income_or_sales = Decimal("0")
    real_estate = Decimal("0")
    personal_property = Decimal("0")
    other = Decimal("0")
    for item in schedule_a_entries(data, "taxes_paid"):
        amount = first_amount(item, ["allowable_amount", "amount", "tax_amount", "paid_amount"])
        tax_type = str(first_value(item, ["type", "tax_type", "description"]) or "").lower()
        if any(token in tax_type for token in ["sales"]):
            income_or_sales += amount
        elif any(token in tax_type for token in ["real_estate", "real estate", "property_tax", "property tax"]):
            real_estate += amount
        elif any(token in tax_type for token in ["personal_property", "personal property", "vehicle", "dmv"]):
            personal_property += amount
        elif any(token in tax_type for token in ["state_income", "state income", "local_income", "local income", "estimated", "balance"]):
            income_or_sales += amount
        else:
            other += amount
    return {
        "income_or_sales": income_or_sales,
        "real_estate": real_estate,
        "personal_property": personal_property,
        "other": other,
    }


def salt_cap(data: dict[str, Any], agi: Decimal, review_items: list[dict[str, str]]) -> Decimal:
    status = filing_status(data)
    mfs = status == "married_filing_separately"
    base_cap = Decimal("20000") if mfs else Decimal("40000")
    floor = Decimal("5000") if mfs else Decimal("10000")
    phaseout_threshold = Decimal("250000") if mfs else Decimal("500000")
    if bool_value(get_path(data, "deductions.itemized_salt_requires_worksheet")):
        add_review(
            review_items,
            "schedule_a_salt_worksheet",
            "SALT limit may require the IRS worksheet because Form 2555, Form 4563, or Puerto Rico excluded income is present.",
        )
    if agi <= phaseout_threshold:
        return base_cap
    reduction = (agi - phaseout_threshold) * Decimal("0.30")
    return max(floor, base_cap - reduction)


def interest_totals(data: dict[str, Any], review_items: list[dict[str, str]]) -> dict[str, Decimal]:
    line_8a = Decimal("0")
    line_8b = Decimal("0")
    line_8c = Decimal("0")
    line_8d = Decimal("0")
    line_9 = Decimal("0")
    has_limit_review = False
    for item in schedule_a_entries(data, "interest_paid"):
        amount = first_amount(item, ["allowable_amount", "amount", "interest_amount", "paid_amount"])
        interest_type = str(first_value(item, ["type", "interest_type", "description"]) or "").lower()
        form_1098 = bool_value(item.get("form_1098")) or "1098" in interest_type
        if "investment" in interest_type or "margin" in interest_type:
            line_9 += amount
            if not bool_value(item.get("form_4952_not_required")) and is_unknown(item.get("form_4952_allowed_amount")):
                has_limit_review = True
            continue
        if "point" in interest_type and not form_1098:
            line_8c += amount
        elif form_1098:
            line_8a += amount
        else:
            line_8b += amount
        if any(
            bool_value(item.get(key))
            for key in [
                "limited_home_mortgage_interest",
                "proceeds_not_used_to_buy_build_improve",
                "debt_exceeds_limit",
                "home_equity_not_used_to_improve_home",
            ]
        ):
            has_limit_review = True
    if has_limit_review:
        add_review(
            review_items,
            "schedule_a_interest_limit",
            "Mortgage or investment interest may require Pub. 936 or Form 4952 limits. Use allowable_amount or form_4952_allowed_amount when available.",
        )
    return {"8a": line_8a, "8b": line_8b, "8c": line_8c, "8d": line_8d, "9": line_9}


def charity_totals(data: dict[str, Any], agi: Decimal, review_items: list[dict[str, str]]) -> dict[str, Decimal]:
    cash = Decimal("0")
    noncash = Decimal("0")
    carryover = Decimal("0")
    needs_limit_review = False
    for item in schedule_a_entries(data, "gifts_to_charity"):
        amount = first_amount(item, ["allowable_amount", "amount", "gift_amount", "paid_amount"])
        goods = first_amount(item, ["goods_or_services_received", "benefit_value"])
        deductible = max(Decimal("0"), amount - goods)
        gift_type = str(first_value(item, ["type", "gift_type", "description"]) or "").lower()
        if "carry" in gift_type:
            carryover += deductible
        elif "noncash" in gift_type or "property" in gift_type or "goods" in gift_type:
            noncash += deductible
        else:
            cash += deductible
        limit_pct = first_value(item, ["agi_limit_percentage", "limit_percentage"])
        if meaningful(limit_pct) and money(limit_pct) not in {Decimal("60"), Decimal("50")}:
            needs_limit_review = True
    if cash > agi * Decimal("0.60"):
        add_review(
            review_items,
            "schedule_a_charity_limit",
            "Cash charitable gifts exceed the common 60% of AGI limit. Review Pub. 526 and any carryover worksheet before relying on Schedule A.",
        )
    if noncash > agi * Decimal("0.50") or carryover:
        needs_limit_review = True
    if needs_limit_review:
        add_review(
            review_items,
            "schedule_a_charity_limit",
            "Charitable gifts may require separate 50%, 30%, 20%, noncash, or carryover limit calculations. Use allowable_amount when already reviewed.",
        )
    return {"11": cash, "12": noncash, "13": carryover}


def casualty_total(data: dict[str, Any], review_items: list[dict[str, str]]) -> Decimal:
    total = Decimal("0")
    for item in schedule_a_entries(data, "casualty_theft"):
        amount = first_amount(item, ["form_4684_line_18", "allowable_amount", "amount", "loss_amount"])
        if not bool_value(item.get("federally_declared_disaster")) and is_unknown(item.get("form_4684_line_18")):
            add_review(
                review_items,
                "schedule_a_casualty_limit",
                "Casualty/theft losses generally require a federally declared disaster and Form 4684. Use form_4684_line_18 when available.",
            )
            continue
        total += amount
    return total


def other_total(data: dict[str, Any], review_items: list[dict[str, str]]) -> tuple[Decimal, str]:
    total = Decimal("0")
    labels = []
    for item in schedule_a_entries(data, "other"):
        amount = first_amount(item, ["allowable_amount", "amount", "deduction_amount"])
        other_type = str(first_value(item, ["type", "description"]) or "Other itemized deduction")
        if "gambling" in other_type.lower():
            winnings = first_amount(item, ["gambling_winnings", "winnings"])
            if winnings:
                amount = min(amount, winnings)
            else:
                add_review(
                    review_items,
                    "schedule_a_gambling_loss_limit",
                    "Gambling losses are deductible only up to gambling winnings. Provide gambling_winnings or allowable_amount.",
                )
        total += amount
        if amount:
            labels.append(other_type)
    return total, ", ".join(labels[:3])


def ca_itemized_total(data: dict[str, Any], federal_total: Decimal, charity: dict[str, Decimal], agi: Decimal) -> Decimal:
    explicit = get_path(data, "state_adjustments.ca.itemized_deduction_total")
    if not is_unknown(explicit):
        return money(explicit)
    adjustments = get_path(data, "state_adjustments.ca.itemized_adjustments")
    if isinstance(adjustments, dict):
        additions = amount_entries(as_list(adjustments.get("additions")), ["amount", "adjustment_amount"])
        subtractions = amount_entries(as_list(adjustments.get("subtractions")), ["amount", "adjustment_amount"])
        return max(Decimal("0"), federal_total + additions - subtractions)
    cash = charity["11"]
    cash_limit = agi * Decimal("0.50")
    if cash > cash_limit:
        return max(Decimal("0"), federal_total - (cash - cash_limit))
    return federal_total


def calculate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    agi = agi_amount(data)
    if agi == 0 and is_unknown(get_path(data, "calculated.form_line_values.f1040.line_11_adjusted_gross_income")):
        add_review(
            review_items,
            "schedule_a_agi",
            "AGI is missing. Medical, SALT, charitable, and casualty limits may be incomplete until Form 1040 line 11 is calculated or supplied.",
        )

    medical = medical_total(data)
    line_2 = agi * Decimal("0.075")
    line_4 = max(Decimal("0"), medical - line_2)

    taxes = tax_totals(data)
    line_5a = taxes["income_or_sales"]
    line_5b = taxes["real_estate"]
    line_5c = taxes["personal_property"]
    line_5d = line_5a + line_5b + line_5c
    line_5e = min(line_5d, salt_cap(data, agi, review_items))
    line_6 = taxes["other"]
    line_7 = line_5e + line_6

    interest = interest_totals(data, review_items)
    line_10 = interest["8a"] + interest["8b"] + interest["8c"] + interest["8d"] + interest["9"]

    charity = charity_totals(data, agi, review_items)
    line_14 = charity["11"] + charity["12"] + charity["13"]

    line_15 = casualty_total(data, review_items)
    line_16, line_16_label = other_total(data, review_items)
    line_17 = line_4 + line_7 + line_10 + line_14 + line_15 + line_16

    f1040sa = {
        "line_1_medical_and_dental_expenses": money_string(medical),
        "line_2_adjusted_gross_income": money_string(agi),
        "line_3_medical_threshold_7_5_percent": money_string(line_2),
        "line_4_medical_deduction": money_string(line_4),
        "line_5a_state_local_income_or_sales_taxes": money_string(line_5a),
        "line_5a_general_sales_tax_elected": bool_value(get_path(data, "deductions.itemized.sales_tax_elected")),
        "line_5b_real_estate_taxes": money_string(line_5b),
        "line_5c_personal_property_taxes": money_string(line_5c),
        "line_5d_total_taxes_before_limit": money_string(line_5d),
        "line_5e_state_and_local_tax_deduction": money_string(line_5e),
        "line_6_other_taxes": money_string(line_6),
        "line_6_other_taxes_description": "Other taxes" if line_6 else "",
        "line_7_total_taxes": money_string(line_7),
        "line_8_home_mortgage_interest_not_all_proceeds_used": bool_value(
            get_path(data, "deductions.itemized.mortgage_proceeds_not_all_used_to_buy_build_improve")
        ),
        "line_8a_home_mortgage_interest_form_1098": money_string(interest["8a"]),
        "line_8b_home_mortgage_interest_not_form_1098": money_string(interest["8b"]),
        "line_8b_recipient": str(get_path(data, "deductions.itemized.mortgage_interest_recipient") or ""),
        "line_8c_points_not_reported_on_1098": money_string(interest["8c"]),
        "line_8d_reserved": money_string(interest["8d"]),
        "line_8e_total_home_mortgage_interest": money_string(interest["8a"] + interest["8b"] + interest["8c"] + interest["8d"]),
        "line_9_investment_interest": money_string(interest["9"]),
        "line_10_total_interest": money_string(line_10),
        "line_11_gifts_by_cash_or_check": money_string(charity["11"]),
        "line_12_other_than_cash_or_check": money_string(charity["12"]),
        "line_13_carryover_from_prior_year": money_string(charity["13"]),
        "line_14_total_gifts_to_charity": money_string(line_14),
        "line_15_casualty_and_theft_loss": money_string(line_15),
        "line_16_other_itemized_deductions": money_string(line_16),
        "line_16_other_itemized_deductions_description": line_16_label,
        "line_17_total_itemized_deductions": money_string(line_17),
        "line_18_itemizing_elected": True,
    }

    deductions = data.setdefault("deductions", {})
    method = str(deductions.get("standard_or_itemized") or "").strip().lower()
    standard = standard_deduction(data, review_items)
    deductions["standard_deduction"] = money_string(standard) if standard else deductions.get("standard_deduction", "unknown")
    deductions["itemized_deduction_total"] = money_string(line_17)
    if method in {"itemized", "standard"}:
        selected_method = method
    else:
        selected_method = "itemized" if line_17 > standard else "standard"
        deductions["standard_or_itemized"] = selected_method
    selected_amount = line_17 if selected_method == "itemized" else standard
    if selected_amount:
        deductions["selected_deduction_amount"] = money_string(selected_amount)

    if selected_method == "standard" and line_17 > standard:
        add_review(
            review_items,
            "schedule_a_standard_vs_itemized",
            "Standard deduction is selected, but calculated itemized deductions are larger. Confirm deduction choice.",
        )
    elif selected_method == "itemized" and standard > line_17:
        add_review(
            review_items,
            "schedule_a_standard_vs_itemized",
            "Itemized deduction is selected, but the standard deduction is larger. Confirm deduction choice.",
        )

    calculated = data.setdefault("calculated", {})
    form_line_values = calculated.setdefault("form_line_values", {})
    form_line_values["f1040sa"] = f1040sa
    form_line_values.setdefault("f1040", {})["line_12_standard_or_itemized_deduction"] = money_string(selected_amount)

    ca_scope = get_path(data, "return_scope.states")
    has_ca = any(
        isinstance(item, dict) and str(item.get("state", "")).upper() == "CA"
        for item in as_list(ca_scope)
    )
    if has_ca or get_path(data, "state_adjustments.ca") is not None:
        ca_total = ca_itemized_total(data, line_17, charity, agi)
        ca_standard = ca_standard_deduction(data, review_items)
        ca_selected = ca_total if ca_total > ca_standard else ca_standard
        set_path(data, "state_adjustments.ca.itemized_deduction_total", money_string(ca_total))
        if ca_standard:
            set_path(data, "state_adjustments.ca.standard_deduction", money_string(ca_standard))
        set_path(data, "calculated.form_line_values.ca540.line_18_standard_or_itemized_deduction", money_string(ca_selected))
        if charity["11"] > agi * Decimal("0.50"):
            add_review(
                review_items,
                "ca_itemized_charity_limit",
                "California cash charitable deduction can differ from federal when gifts exceed 50% of federal AGI. Review Schedule CA Part II.",
            )

    calculated.setdefault("worksheets", [])
    calculated.setdefault("review_items", [])
    existing_topics = {item.get("topic") for item in review_items}
    calculated["review_items"] = [
        item
        for item in calculated["review_items"]
        if not (isinstance(item, dict) and item.get("topic") in existing_topics)
    ]
    calculated["review_items"].extend(review_items)

    report = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "scope": "schedule_a_common_itemized_deductions",
        "f1040sa": f1040sa,
        "standard_deduction": money_string(standard),
        "selected_method": selected_method,
        "selected_deduction_amount": money_string(selected_amount),
        "review_items": review_items,
    }
    return data, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate common Schedule A itemized deduction lines.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for schedule_a_report.yaml.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else tax_forms / "workpapers" / "schedule_a_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit("extracted_tax_data.yaml must contain a mapping.")
    updated, report = calculate(data)
    dump_yaml(updated, data_path)
    dump_yaml(report, output_path)
    print(f"Wrote {data_path}")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
