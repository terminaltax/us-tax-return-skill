#!/usr/bin/env python3
"""Calculate Form 8582 passive activity loss limits for direct rental real estate."""

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
MAX_SPECIAL_ALLOWANCE = Decimal("25000")
MFS_MAX_SPECIAL_ALLOWANCE = Decimal("12500")
PHASEOUT_BASE = Decimal("150000")
MFS_PHASEOUT_BASE = Decimal("75000")
PHASEOUT_RATE = Decimal("0.50")
PROPERTY_COLUMNS = ["a", "b", "c"]


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


def ratio_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0000"), rounding=ROUND_HALF_UP))


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
    return money(first_value(item, keys))


def total_entries(items: list[dict[str, Any]], keys: list[str]) -> Decimal:
    return sum((first_amount(item, keys) for item in items), Decimal("0"))


def nested_dict(item: dict[str, Any], key: str) -> dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def filing_status(data: dict[str, Any]) -> str:
    return str(get_path(data, "taxpayer.filing_status") or "unknown").strip().lower()


def truthy(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "checked", "x", "on"}


def add_review(review_items: list[dict[str, str]], topic: str, message: str, severity: str = "review") -> None:
    review_items.append({"severity": severity, "topic": topic, "message": message})


def activity_name(item: dict[str, Any], index: int) -> str:
    for key in ["property_id", "property_description", "activity_name", "description"]:
        value = item.get(key)
        if meaningful(value):
            return str(value)
    address = item.get("property_address") or item.get("address")
    if isinstance(address, dict):
        line1 = address.get("line1")
        if meaningful(line1):
            return str(line1)
    if meaningful(address):
        return str(address)
    return f"Rental property {index + 1}"


def schedule_e_line21(data: dict[str, Any], index: int) -> Decimal:
    column = PROPERTY_COLUMNS[index] if index < len(PROPERTY_COLUMNS) else None
    if column:
        value = get_path(
            data,
            f"calculated.form_line_values.f1040se.part_i.properties.{column}.line_21_income_or_loss",
        )
        if not is_unknown(value):
            return money(value)
    items = entries(data, "income.rentals_royalties_partnerships")
    if index < len(items):
        return first_amount(items[index], ["income_loss", "net_income_loss", "rental_real_estate_income_loss"])
    return Decimal("0")


def rental_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    rentals = []
    for item in entries(data, "income.rentals_royalties_partnerships"):
        marker = " ".join(
            str(item.get(key, "")).lower()
            for key in ["activity_type", "type", "property_description"]
        )
        if "rental" in marker or meaningful(item.get("property_address")) or meaningful(item.get("gross_rents")):
            rentals.append(item)
    return rentals


def estimate_magi(data: dict[str, Any], review_items: list[dict[str, str]]) -> Decimal:
    explicit_paths = [
        "taxpayer.modified_adjusted_gross_income_for_form_8582",
        "taxpayer.passive_activity_magi",
        "calculated.passive_activity.modified_adjusted_gross_income",
        "calculated.form_line_values.f8582.part_ii.line_6_modified_adjusted_gross_income",
    ]
    for path in explicit_paths:
        value = get_path(data, path)
        if not is_unknown(value):
            return max(Decimal("0"), money(value))

    wages = entries(data, "income.wages")
    interest = entries(data, "income.interest")
    dividends = entries(data, "income.dividends")
    retirement = entries(data, "income.retirement_distributions")
    business = entries(data, "income.business_or_1099_income")
    other_income = entries(data, "income.other_income")
    capital_gain = money(get_path(data, "calculated.form_line_values.f1040.line_7"))
    if capital_gain == 0:
        capital_gain = money(get_path(data, "calculated.form_line_values.f1040sd.line_21_to_form_1040"))

    rental_income = Decimal("0")
    for index, _item in enumerate(rental_items(data)):
        line21 = schedule_e_line21(data, index)
        if line21 > 0:
            rental_income += line21

    magi = (
        total_entries(wages, ["wages_box_1", "wages", "amount"])
        + total_entries(interest, ["interest_income_box_1", "taxable_interest", "amount"])
        + total_entries(dividends, ["ordinary_dividends_box_1a", "ordinary_dividends", "amount"])
        + total_entries(retirement, ["taxable_amount_box_2a", "taxable_amount"])
        + total_entries(business, ["net_profit", "schedule_c_net_profit", "net_income"])
        + total_entries(other_income, ["amount", "income", "taxable_amount"])
        + capital_gain
        + rental_income
    )

    adjustments = get_path(data, "adjustments")
    if meaningful(adjustments):
        add_review(
            review_items,
            "form_8582_magi_review",
            "Form 8582 line 6 MAGI was estimated from common income fields. Review it because adjustments or exclusions may change the official MAGI worksheet.",
        )
    return max(Decimal("0"), magi)


def special_allowance_limits(data: dict[str, Any], review_items: list[dict[str, str]]) -> tuple[Decimal, Decimal, bool]:
    status = filing_status(data)
    lived_with_spouse = truthy(get_path(data, "taxpayer.lived_with_spouse_any_time_during_year"))
    if status == "married_filing_separately":
        if lived_with_spouse:
            add_review(
                review_items,
                "form_8582_mfs_no_special_allowance",
                "Married filing separately taxpayer lived with spouse during the year, so the active-participation special allowance is not available.",
            )
            return MFS_PHASEOUT_BASE, Decimal("0"), False
        return MFS_PHASEOUT_BASE, MFS_MAX_SPECIAL_ALLOWANCE, True
    return PHASEOUT_BASE, MAX_SPECIAL_ALLOWANCE, True


def decimal_min(*values: Decimal) -> Decimal:
    return min(values) if values else Decimal("0")


def make_row(
    name: str,
    form_line: str,
    loss: Decimal,
    ratio: Decimal,
    allowed_or_unallowed: Decimal,
    remainder: Decimal | None = None,
) -> dict[str, str]:
    row = {
        "name": name,
        "form_or_schedule_line": form_line,
        "loss": money_string(loss),
        "ratio": ratio_string(ratio),
    }
    if remainder is None:
        row["amount"] = money_string(allowed_or_unallowed)
    else:
        row["special_allowance"] = money_string(allowed_or_unallowed)
        row["remaining_unallowed_loss"] = money_string(remainder)
    return row


def calculate(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    items = rental_items(data)
    status = filing_status(data)
    phaseout_base, allowance_cap, can_use_part_ii = special_allowance_limits(data, review_items)
    magi = estimate_magi(data, review_items)

    activities: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        passive = nested_dict(item, "passive_activity")
        if passive.get("is_publicly_traded_partnership") is True or item.get("source_document_type") == "K-1":
            add_review(
                review_items,
                "form_8582_unsupported_passive_activity",
                f"{activity_name(item, index)} looks like a pass-through or PTP activity. This script covers direct rental real estate activities only.",
                "error",
            )
            continue
        active_participation = first_value(item, ["active_participation"])
        if active_participation is None:
            active_participation = first_value(passive, ["active_participation"])
        if active_participation is not True:
            add_review(
                review_items,
                "form_8582_active_participation_missing",
                f"{activity_name(item, index)} does not have active_participation: true. Treating its loss as not eligible for the active-participation special allowance.",
            )
        line21 = schedule_e_line21(data, index)
        prior_unallowed = first_amount(
            passive,
            ["prior_year_unallowed_loss", "prior_year_unallowed_passive_loss", "prior_year_disallowed_loss"],
        )
        current_income = max(Decimal("0"), line21)
        current_loss = abs(min(Decimal("0"), line21))
        total_loss = current_loss + prior_unallowed
        overall = current_income - total_loss
        activities.append(
            {
                "index": index,
                "property_id": item.get("property_id") or f"rental_{index + 1:03d}",
                "name": activity_name(item, index),
                "schedule_line": "Schedule E, line 22",
                "active_participation": active_participation is True and can_use_part_ii,
                "current_income": current_income,
                "current_loss": current_loss,
                "prior_unallowed": prior_unallowed,
                "total_loss": total_loss,
                "overall_gain": max(Decimal("0"), overall),
                "overall_loss": abs(min(Decimal("0"), overall)),
                "allowed_loss": Decimal("0"),
                "current_year_unallowed_loss": Decimal("0"),
            }
        )

    part_iv_activities = [activity for activity in activities if activity["active_participation"]]
    part_v_activities = [activity for activity in activities if not activity["active_participation"]]
    if part_v_activities:
        add_review(
            review_items,
            "form_8582_part_v_review",
            "One or more passive activities do not qualify for the active-participation rental real estate allowance. Part V allocation is marked for review.",
        )

    line_1a = sum((activity["current_income"] for activity in part_iv_activities), Decimal("0"))
    line_1b = sum((activity["current_loss"] for activity in part_iv_activities), Decimal("0"))
    line_1c = sum((activity["prior_unallowed"] for activity in part_iv_activities), Decimal("0"))
    line_1d = line_1a - line_1b - line_1c
    line_2a = sum((activity["current_income"] for activity in part_v_activities), Decimal("0"))
    line_2b = sum((activity["current_loss"] for activity in part_v_activities), Decimal("0"))
    line_2c = sum((activity["prior_unallowed"] for activity in part_v_activities), Decimal("0"))
    line_2d = line_2a - line_2b - line_2c
    line_3 = line_1d + line_2d

    line_4 = Decimal("0")
    line_5 = phaseout_base
    line_6 = magi
    line_7 = Decimal("0")
    line_8 = Decimal("0")
    line_9 = Decimal("0")
    if line_3 < 0 and line_1d < 0 and can_use_part_ii:
        line_4 = decimal_min(abs(line_1d), abs(line_3))
        if line_6 < line_5:
            line_7 = line_5 - line_6
            line_8 = min(allowance_cap, line_7 * PHASEOUT_RATE)
            line_9 = decimal_min(line_4, line_8)

    line_10 = line_1a + line_2a
    line_11 = line_9 + line_10

    overall_loss_activities = [activity for activity in activities if activity["overall_loss"] > 0]
    total_overall_loss = sum((activity["overall_loss"] for activity in overall_loss_activities), Decimal("0"))
    total_unallowed = Decimal("0")
    if line_3 < 0:
        total_unallowed = max(Decimal("0"), abs(line_3) - line_9)

    for activity in activities:
        if activity["overall_gain"] > 0:
            activity["allowed_loss"] = activity["total_loss"]
            continue
        if total_overall_loss == 0:
            activity["allowed_loss"] = activity["total_loss"]
            continue
        ratio = activity["overall_loss"] / total_overall_loss
        unallowed = (total_unallowed * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        activity["current_year_unallowed_loss"] = min(activity["total_loss"], unallowed)
        activity["allowed_loss"] = max(Decimal("0"), activity["total_loss"] - activity["current_year_unallowed_loss"])

    if line_3 >= 0:
        for activity in activities:
            activity["allowed_loss"] = activity["total_loss"]
            activity["current_year_unallowed_loss"] = Decimal("0")

    if sum((activity["current_year_unallowed_loss"] for activity in activities), Decimal("0")) != total_unallowed:
        remainder = total_unallowed - sum((activity["current_year_unallowed_loss"] for activity in activities), Decimal("0"))
        for activity in reversed(overall_loss_activities):
            if remainder == 0:
                break
            adjusted = activity["current_year_unallowed_loss"] + remainder
            if adjusted >= 0:
                activity["current_year_unallowed_loss"] = adjusted
                activity["allowed_loss"] = max(Decimal("0"), activity["total_loss"] - adjusted)
                remainder = Decimal("0")

    part_iv_rows = []
    for activity in part_iv_activities[:5]:
        part_iv_rows.append(
            {
                "name": activity["name"],
                "net_income": money_string(activity["current_income"]),
                "net_loss": money_string(activity["current_loss"]),
                "prior_year_unallowed_loss": money_string(activity["prior_unallowed"]),
                "overall_gain": money_string(activity["overall_gain"]),
                "overall_loss": money_string(activity["overall_loss"]),
            }
        )
    if len(part_iv_activities) > 5:
        add_review(
            review_items,
            "form_8582_additional_part_iv_rows",
            "Form 8582 Part IV has five visible rows. Attach a continuation schedule for additional active-participation rentals.",
        )

    part_vi_rows = []
    part_vii_rows = []
    part_viii_rows = []
    if line_9 > 0 and total_overall_loss > 0:
        for activity in overall_loss_activities[:5]:
            ratio = activity["overall_loss"] / total_overall_loss
            special_allowance = (line_9 * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            remaining = max(Decimal("0"), activity["overall_loss"] - special_allowance)
            part_vi_rows.append(make_row(activity["name"], activity["schedule_line"], activity["overall_loss"], ratio, special_allowance, remaining))
    if total_unallowed > 0 and total_overall_loss > 0:
        for activity in overall_loss_activities[:5]:
            ratio = activity["overall_loss"] / total_overall_loss
            part_vii_rows.append(make_row(activity["name"], activity["schedule_line"], activity["overall_loss"], ratio, activity["current_year_unallowed_loss"]))
            part_viii_rows.append(
                {
                    "name": activity["name"],
                    "form_or_schedule_line": activity["schedule_line"],
                    "loss": money_string(activity["total_loss"]),
                    "unallowed_loss": money_string(activity["current_year_unallowed_loss"]),
                    "allowed_loss": money_string(activity["allowed_loss"]),
                }
            )

    f8582 = {
        "form_required": not (
            not part_v_activities
            and line_1d < 0
            and line_2d == 0
            and line_1b <= allowance_cap
            and line_1c == 0
            and line_6 <= (Decimal("100000") if status != "married_filing_separately" else Decimal("50000"))
        ),
        "part_i": {
            "line_1a_active_rental_net_income": money_string(line_1a),
            "line_1b_active_rental_net_loss": money_string(line_1b),
            "line_1c_active_rental_prior_year_unallowed_loss": money_string(line_1c),
            "line_1d_active_rental_combined": money_string(line_1d),
            "line_2a_other_passive_net_income": money_string(line_2a),
            "line_2b_other_passive_net_loss": money_string(line_2b),
            "line_2c_other_passive_prior_year_unallowed_loss": money_string(line_2c),
            "line_2d_other_passive_combined": money_string(line_2d),
            "line_3_total_passive_activity_loss": money_string(line_3),
        },
        "part_ii": {
            "line_4_smaller_loss": money_string(line_4),
            "line_5_phaseout_base": money_string(line_5),
            "line_6_modified_adjusted_gross_income": money_string(line_6),
            "line_7_phaseout_difference": money_string(line_7),
            "line_8_special_allowance_limit": money_string(line_8),
            "line_9_special_allowance": money_string(line_9),
        },
        "part_iii": {
            "line_10_passive_activity_income": money_string(line_10),
            "line_11_total_losses_allowed": money_string(line_11),
        },
        "part_iv": {
            "activities": part_iv_rows,
            "totals": {
                "net_income": money_string(line_1a),
                "net_loss": money_string(line_1b),
                "prior_year_unallowed_loss": money_string(line_1c),
                "overall_gain": money_string(sum((activity["overall_gain"] for activity in part_iv_activities), Decimal("0"))),
                "overall_loss": money_string(sum((activity["overall_loss"] for activity in part_iv_activities), Decimal("0"))),
            },
        },
        "part_vi": {
            "activities": part_vi_rows,
            "total_loss": money_string(sum((money(row.get("loss")) for row in part_vi_rows), Decimal("0"))),
            "total_special_allowance": money_string(sum((money(row.get("special_allowance")) for row in part_vi_rows), Decimal("0"))),
            "total_remaining_unallowed_loss": money_string(sum((money(row.get("remaining_unallowed_loss")) for row in part_vi_rows), Decimal("0"))),
        },
        "part_vii": {
            "activities": part_vii_rows,
            "total_loss": money_string(sum((money(row.get("loss")) for row in part_vii_rows), Decimal("0"))),
            "total_unallowed_loss": money_string(sum((money(row.get("amount")) for row in part_vii_rows), Decimal("0"))),
        },
        "part_viii": {
            "activities": part_viii_rows,
            "total_loss": money_string(sum((money(row.get("loss")) for row in part_viii_rows), Decimal("0"))),
            "total_unallowed_loss": money_string(sum((money(row.get("unallowed_loss")) for row in part_viii_rows), Decimal("0"))),
            "total_allowed_loss": money_string(sum((money(row.get("allowed_loss")) for row in part_viii_rows), Decimal("0"))),
        },
        "allowed_losses_by_property_id": {
            str(activity["property_id"]): money_string(activity["allowed_loss"]) for activity in activities
        },
        "unallowed_losses_by_property_id": {
            str(activity["property_id"]): money_string(activity["current_year_unallowed_loss"]) for activity in activities
        },
    }

    calculated = data.setdefault("calculated", {})
    form_line_values = calculated.setdefault("form_line_values", {})
    form_line_values["f8582"] = f8582

    se = form_line_values.setdefault("f1040se", {})
    part_i = se.setdefault("part_i", {})
    properties = part_i.setdefault("properties", {})
    for activity in activities:
        item = items[activity["index"]]
        passive = item.setdefault("passive_activity", {})
        passive["current_year_allowed_loss"] = money_string(activity["allowed_loss"])
        passive["current_year_unallowed_loss"] = money_string(activity["current_year_unallowed_loss"])
        column = PROPERTY_COLUMNS[activity["index"]] if activity["index"] < len(PROPERTY_COLUMNS) else None
        if column and column in properties:
            properties[column]["line_22_deductible_rental_real_estate_loss_after_limitation"] = money_string(-activity["allowed_loss"])

    line_24 = sum(
        (
            money(lines.get("line_21_income_or_loss"))
            for lines in properties.values()
            if money(lines.get("line_21_income_or_loss")) > 0
        ),
        Decimal("0"),
    )
    line_25 = sum((money(lines.get("line_22_deductible_rental_real_estate_loss_after_limitation")) for lines in properties.values()), Decimal("0"))
    line_26 = line_24 + line_25
    if properties:
        part_i["line_24_income"] = money_string(line_24)
        part_i["line_25_losses"] = money_string(line_25)
        part_i["line_26_total_rental_real_estate_and_royalty_income_or_loss"] = money_string(line_26)
        se["line_41_total_income_or_loss"] = money_string(line_26)
        se["total_income_or_loss"] = money_string(line_26)
        se["line_26_total_rental_real_estate_and_royalty_income_or_loss"] = money_string(line_26)
        form_line_values.setdefault("f1040s1", {})["line_5_rental_royalty_partnerships_estates_trusts"] = money_string(line_26)

    calculated.setdefault("review_items", [])
    calculated["review_items"] = [
        item
        for item in calculated["review_items"]
        if not (
            isinstance(item, dict)
            and item.get("topic") in {"schedule_e_passive_loss_limitation", *{review.get("topic") for review in review_items}}
        )
    ]
    calculated["review_items"].extend(review_items)
    data["review_status"] = "calculated_needs_review" if calculated["review_items"] else "calculated"

    report = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "form_8582_direct_rental_real_estate_active_participation",
        "forms": ["f8582", "f1040se", "f1040s1"],
        "form_line_values": {"f8582": f8582},
        "review_items": review_items,
    }
    return data, report


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate Form 8582 passive activity loss limits for direct rentals.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for updated extracted tax data. Defaults to overwriting --data.")
    parser.add_argument(
        "--report",
        help="Path for Form 8582 calculation report. Defaults to tax_forms/workpapers/form_8582_report.yaml.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else data_path
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else tax_forms / "workpapers" / "form_8582_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")

    updated_data, report = calculate(data)
    dump_yaml(updated_data, output_path)
    dump_yaml(report, report_path)

    print(f"Updated data: {relative_to_root(output_path, root)}")
    print(f"Form 8582 report: {relative_to_root(report_path, root)}")
    print(f"Review items: {len(report['review_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
