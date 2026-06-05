#!/usr/bin/env python3
"""Calculate Schedule E Part I rental and royalty line values from extracted YAML."""

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
PROPERTY_COLUMNS = ["a", "b", "c"]

PROPERTY_TYPE_CODES = {
    "single family residence": "1",
    "single-family residence": "1",
    "single_family_residence": "1",
    "single family": "1",
    "multi-family residence": "2",
    "multi family residence": "2",
    "multi_family_residence": "2",
    "vacation/short-term rental": "3",
    "vacation rental": "3",
    "short-term rental": "3",
    "short_term_rental": "3",
    "commercial": "4",
    "land": "5",
    "royalties": "6",
    "royalty": "6",
    "self-rental": "7",
    "self rental": "7",
    "self_rental": "7",
    "other": "8",
}

EXPENSE_LINES = [
    ("line_5_advertising", ["advertising"]),
    ("line_6_auto_and_travel", ["auto_and_travel", "auto_travel", "travel"]),
    ("line_7_cleaning_and_maintenance", ["cleaning_and_maintenance", "cleaning", "maintenance"]),
    ("line_8_commissions", ["commissions"]),
    ("line_9_insurance", ["insurance"]),
    ("line_10_legal_and_professional_fees", ["legal_and_professional", "legal_professional", "professional_fees"]),
    ("line_11_management_fees", ["management_fees", "management"]),
    ("line_12_mortgage_interest", ["mortgage_interest", "mortgage_interest_paid_to_banks"]),
    ("line_13_other_interest", ["other_interest"]),
    ("line_14_repairs", ["repairs"]),
    ("line_15_supplies", ["supplies"]),
    ("line_16_taxes", ["taxes", "real_estate_taxes", "property_taxes"]),
    ("line_17_utilities", ["utilities"]),
    ("line_18_depreciation_or_depletion", ["depreciation", "depletion", "current_depreciation"]),
]


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


def entries(data: dict[str, Any], dotted_path: str) -> list[dict[str, Any]]:
    return [item for item in as_list(get_path(data, dotted_path)) if isinstance(item, dict)]


def first_value(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and not is_unknown(item.get(key)):
            return item.get(key)
    return None


def first_amount(item: dict[str, Any], keys: list[str]) -> Decimal:
    value = first_value(item, keys)
    return money(value)


def expense_data(item: dict[str, Any]) -> dict[str, Any]:
    expenses = item.get("expenses")
    return expenses if isinstance(expenses, dict) else {}


def expense_amount(item: dict[str, Any], keys: list[str]) -> Decimal:
    expenses = expense_data(item)
    return first_amount(expenses, keys) + first_amount(item, keys)


def nested_amount(item: dict[str, Any], dotted_path: str) -> Decimal:
    value = get_path(item, dotted_path)
    return money(value)


def other_expenses(item: dict[str, Any]) -> tuple[Decimal, str]:
    expenses = expense_data(item)
    total = Decimal("0")
    labels = []
    for key in ["hoa_dues", "other_expenses", "other"]:
        value = expenses.get(key, item.get(key))
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    total += first_amount(entry, ["amount", "expense_amount"])
                    label = entry.get("description") or entry.get("label")
                    if label:
                        labels.append(str(label))
                else:
                    total += money(entry)
        elif isinstance(value, dict):
            total += first_amount(value, ["amount", "expense_amount"])
            label = value.get("description") or value.get("label")
            if label:
                labels.append(str(label))
        else:
            total += money(value)
            if meaningful(value):
                labels.append(key.replace("_", " "))
    return total, ", ".join(labels[:3]) or "Other rental expenses"


def property_address(item: dict[str, Any]) -> str:
    value = item.get("property_address") or item.get("address")
    if isinstance(value, dict):
        parts = [
            value.get("line1"),
            value.get("city"),
            value.get("state"),
            value.get("zip"),
        ]
        return ", ".join(str(part) for part in parts if meaningful(part))
    if meaningful(value):
        return str(value)
    return ""


def property_type_code(item: dict[str, Any]) -> str:
    explicit = first_value(item, ["property_type_code", "schedule_e_property_type_code"])
    if meaningful(explicit):
        return str(explicit)
    raw_type = first_value(item, ["property_type", "property_description", "activity_type"])
    normalized = str(raw_type or "").strip().lower()
    return PROPERTY_TYPE_CODES.get(normalized, "8" if meaningful(raw_type) else "")


def line_22_allowed_loss(item: dict[str, Any], line_21: Decimal, review_items: list[dict[str, str]], index: int) -> Decimal:
    if line_21 >= 0:
        return Decimal("0")
    explicit = first_value(
        item,
        [
            "deductible_rental_real_estate_loss_after_limitation",
            "form_8582_allowed_loss",
            "allowed_loss",
        ],
    )
    if explicit is None:
        passive = item.get("passive_activity") if isinstance(item.get("passive_activity"), dict) else {}
        explicit = first_value(passive, ["current_year_allowed_loss", "allowed_loss"])
    if explicit is not None:
        allowed = money(explicit)
        return -abs(allowed) if allowed > 0 else allowed
    review_items.append(
        {
            "severity": "review",
            "topic": "schedule_e_passive_loss_limitation",
            "message": f"Rental property {index + 1} has a loss, but deductible loss after Form 8582/passive-loss limitation is not provided.",
        }
    )
    return Decimal("0")


def calculate_property(item: dict[str, Any], column: str, index: int, review_items: list[dict[str, str]]) -> dict[str, str]:
    lines: dict[str, str] = {}
    lines["line_1a_physical_address"] = property_address(item)
    lines["line_1b_type_of_property"] = property_type_code(item)
    lines["line_2_fair_rental_days"] = str(first_value(item, ["fair_rental_days", "days_rented"]) or "")
    lines["line_2_personal_use_days"] = str(first_value(item, ["personal_use_days"]) or "")
    lines["line_2_qualified_joint_venture"] = bool(first_value(item, ["qualified_joint_venture", "qjv"]) is True)

    rents = first_amount(item, ["gross_rents", "rental_income", "rents_received"])
    royalties = first_amount(item, ["royalties_received", "royalty_income"])
    if rents == 0 and str(item.get("activity_type", "")).lower() == "royalty":
        royalties = first_amount(item, ["amount", "income_loss"])
    lines["line_3_rents_received"] = money_string(rents)
    lines["line_4_royalties_received"] = money_string(royalties)

    total_expenses = Decimal("0")
    for line_name, keys in EXPENSE_LINES:
        if line_name == "line_18_depreciation_or_depletion":
            amount = expense_amount(item, keys) + nested_amount(item, "depreciation.current_depreciation")
        else:
            amount = expense_amount(item, keys)
        lines[line_name] = money_string(amount)
        total_expenses += amount

    other_total, other_label = other_expenses(item)
    lines["line_19_other_description"] = other_label if other_total else ""
    lines["line_19_other"] = money_string(other_total)
    total_expenses += other_total
    lines["line_20_total_expenses"] = money_string(total_expenses)

    line_21 = rents + royalties - total_expenses
    lines["line_21_income_or_loss"] = money_string(line_21)
    line_22 = line_22_allowed_loss(item, line_21, review_items, index)
    lines["line_22_deductible_rental_real_estate_loss_after_limitation"] = money_string(line_22)
    return lines


def decimal_line(lines: dict[str, str], key: str) -> Decimal:
    return money(lines.get(key))


def calculate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    rental_items = [
        item
        for item in entries(data, "income.rentals_royalties_partnerships")
        if "rental" in str(item.get("activity_type", item.get("type", ""))).lower()
        or "royalt" in str(item.get("activity_type", item.get("type", ""))).lower()
        or meaningful(item.get("property_address"))
        or meaningful(item.get("gross_rents"))
    ]

    f1040se: dict[str, Any] = {"part_i": {"properties": {}}}
    properties = f1040se["part_i"]["properties"]
    for index, item in enumerate(rental_items[:3]):
        column = PROPERTY_COLUMNS[index]
        properties[column] = calculate_property(item, column, index, review_items)

    if len(rental_items) > 3:
        review_items.append(
            {
                "severity": "review",
                "topic": "schedule_e_property_limit",
                "message": "Schedule E Part I has three property columns. Add a continuation workflow before filling more than three rental/royalty activities.",
            }
        )

    line_23a = sum((decimal_line(lines, "line_3_rents_received") for lines in properties.values()), Decimal("0"))
    line_23b = sum((decimal_line(lines, "line_4_royalties_received") for lines in properties.values()), Decimal("0"))
    line_23c = sum((decimal_line(lines, "line_12_mortgage_interest") for lines in properties.values()), Decimal("0"))
    line_23d = sum((decimal_line(lines, "line_18_depreciation_or_depletion") for lines in properties.values()), Decimal("0"))
    line_23e = sum((decimal_line(lines, "line_20_total_expenses") for lines in properties.values()), Decimal("0"))
    line_24 = sum(
        (max(Decimal("0"), decimal_line(lines, "line_21_income_or_loss")) for lines in properties.values()),
        Decimal("0"),
    )
    line_25 = sum(
        (
            decimal_line(lines, "line_22_deductible_rental_real_estate_loss_after_limitation")
            if decimal_line(lines, "line_21_income_or_loss") < 0
            else Decimal("0")
            for lines in properties.values()
        ),
        Decimal("0"),
    )
    line_26 = line_24 + line_25

    part_i = f1040se["part_i"]
    for key, value in [
        ("line_23a_total_rents", line_23a),
        ("line_23b_total_royalties", line_23b),
        ("line_23c_total_mortgage_interest", line_23c),
        ("line_23d_total_depreciation", line_23d),
        ("line_23e_total_expenses", line_23e),
        ("line_24_income", line_24),
        ("line_25_losses", line_25),
        ("line_26_total_rental_real_estate_and_royalty_income_or_loss", line_26),
    ]:
        part_i[key] = money_string(value)

    f1040se["line_41_total_income_or_loss"] = money_string(line_26)
    f1040se["total_income_or_loss"] = money_string(line_26)
    f1040se["line_26_total_rental_real_estate_and_royalty_income_or_loss"] = money_string(line_26)

    calculated = data.setdefault("calculated", {})
    form_line_values = calculated.setdefault("form_line_values", {})
    form_line_values["f1040se"] = f1040se
    form_line_values.setdefault("f1040s1", {})["line_5_rental_royalty_partnerships_estates_trusts"] = money_string(line_26)

    calculated.setdefault("worksheets", [])
    calculated.setdefault("review_items", [])
    existing_topics = {item.get("topic") for item in review_items}
    calculated["review_items"] = [
        item
        for item in calculated["review_items"]
        if not (isinstance(item, dict) and item.get("topic") in existing_topics)
    ]
    calculated["review_items"].extend(review_items)
    data["review_status"] = "calculated_needs_review" if calculated["review_items"] else "calculated"

    report = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "schedule_e_part_i_rental_royalty_lines",
        "forms": ["f1040se", "f1040s1"],
        "property_count": len(rental_items),
        "included_property_count": min(len(rental_items), 3),
        "form_line_values": {"f1040se": f1040se},
        "review_items": review_items,
    }
    return data, report


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate Schedule E Part I rental and royalty line values.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for updated extracted tax data. Defaults to overwriting --data.")
    parser.add_argument(
        "--report",
        help="Path for Schedule E calculation report. Defaults to tax_forms/workpapers/schedule_e_report.yaml.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else data_path
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else tax_forms / "workpapers" / "schedule_e_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")

    updated_data, report = calculate(data)
    dump_yaml(updated_data, output_path)
    dump_yaml(report, report_path)

    print(f"Updated data: {relative_to_root(output_path, root)}")
    print(f"Schedule E report: {relative_to_root(report_path, root)}")
    print(f"Review items: {len(report['review_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
