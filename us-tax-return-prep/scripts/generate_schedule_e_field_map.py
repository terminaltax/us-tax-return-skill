#!/usr/bin/env python3
"""Generate a Schedule E field map for the current IRS fillable PDF field names."""

from __future__ import annotations

import argparse
import datetime as dt
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


FIELD_PREFIX = "topmostSubform[0].Page1[0]"
PAGE2_PREFIX = "topmostSubform[0].Page2[0]"
PROPERTY_COLUMNS = ["a", "b", "c"]
MONEY_FORMAT = "money_whole_dollars"


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def money(path: str) -> dict[str, str]:
    return {"path": path, "format": MONEY_FORMAT}


def text(path: str) -> dict[str, str]:
    return {"path": path, "format": "text"}


def integer(path: str) -> dict[str, str]:
    return {"path": path, "format": "integer"}


def checkbox(path: str) -> dict[str, str]:
    return {
        "path": path,
        "type": "checkbox",
        "checked_value": "/1",
        "unchecked_value": "/Off",
    }


def property_path(column: str, line: str) -> str:
    return f"calculated.form_line_values.f1040se.part_i.properties.{column}.{line}"


def add_property_fields(fields: dict[str, Any]) -> None:
    for offset, column in enumerate(PROPERTY_COLUMNS):
        fields[f"{FIELD_PREFIX}.Table_Line1a[0].Row{column.upper()}[0].f1_{3 + offset}[0]"] = text(
            property_path(column, "line_1a_physical_address")
        )
        fields[f"{FIELD_PREFIX}.Table_Line1b[0].Row{column.upper()}[0].f1_{6 + offset}[0]"] = text(
            property_path(column, "line_1b_type_of_property")
        )
        base = 9 + (offset * 2)
        fields[f"{FIELD_PREFIX}.Table_Line2[0].Row{column.upper()}[0].f1_{base}[0]"] = integer(
            property_path(column, "line_2_fair_rental_days")
        )
        fields[f"{FIELD_PREFIX}.Table_Line2[0].Row{column.upper()}[0].f1_{base + 1}[0]"] = integer(
            property_path(column, "line_2_personal_use_days")
        )
        fields[f"{FIELD_PREFIX}.Table_Line2[0].Row{column.upper()}[0].c1_{3 + offset}[0]"] = checkbox(
            property_path(column, "line_2_qualified_joint_venture")
        )

    for line_number, line_key, first_field in [
        (3, "line_3_rents_received", 16),
        (4, "line_4_royalties_received", 19),
        (5, "line_5_advertising", 22),
        (6, "line_6_auto_and_travel", 25),
        (7, "line_7_cleaning_and_maintenance", 28),
        (8, "line_8_commissions", 31),
        (9, "line_9_insurance", 34),
        (10, "line_10_legal_and_professional_fees", 37),
        (11, "line_11_management_fees", 40),
        (12, "line_12_mortgage_interest", 43),
        (13, "line_13_other_interest", 46),
        (14, "line_14_repairs", 49),
        (15, "line_15_supplies", 52),
        (16, "line_16_taxes", 55),
        (17, "line_17_utilities", 58),
        (18, "line_18_depreciation_or_depletion", 61),
        (20, "line_20_total_expenses", 68),
        (21, "line_21_income_or_loss", 71),
        (22, "line_22_deductible_rental_real_estate_loss_after_limitation", 74),
    ]:
        for offset, column in enumerate(PROPERTY_COLUMNS):
            table_name = "Table_Income" if line_number in {3, 4} else "Table_Expenses"
            fields[f"{FIELD_PREFIX}.{table_name}[0].Line{line_number}[0].f1_{first_field + offset}[0]"] = money(
                property_path(column, line_key)
            )

    fields[f"{FIELD_PREFIX}.Table_Expenses[0].Line19[0].f1_64[0]"] = text(
        property_path("a", "line_19_other_description")
    )
    for offset, column in enumerate(PROPERTY_COLUMNS):
        fields[f"{FIELD_PREFIX}.Table_Expenses[0].Line19[0].f1_{65 + offset}[0]"] = money(
            property_path(column, "line_19_other")
        )


def schedule_e_field_map(tax_year: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        f"{FIELD_PREFIX}.f1_1[0]": {
            "join": {"paths": ["taxpayer.primary.full_name", "taxpayer.spouse.full_name"], "separator": " & "},
            "format": "text",
        },
        f"{FIELD_PREFIX}.f1_2[0]": {"path": "taxpayer.primary.ssn", "format": "digits"},
        f"{FIELD_PREFIX}.c1_1[0]": checkbox("taxpayer.schedule_e_1099_payments_made"),
        f"{FIELD_PREFIX}.c1_1[1]": {
            "path": "taxpayer.schedule_e_1099_payments_made_no",
            "type": "checkbox",
            "checked_value": "/2",
            "unchecked_value": "/Off",
        },
        f"{FIELD_PREFIX}.c1_2[0]": checkbox("taxpayer.schedule_e_required_1099s_filed"),
        f"{FIELD_PREFIX}.c1_2[1]": {
            "path": "taxpayer.schedule_e_required_1099s_filed_no",
            "type": "checkbox",
            "checked_value": "/2",
            "unchecked_value": "/Off",
        },
    }
    add_property_fields(fields)
    for field_number, line_key in [
        (77, "line_23a_total_rents"),
        (78, "line_23b_total_royalties"),
        (79, "line_23c_total_mortgage_interest"),
        (80, "line_23d_total_depreciation"),
        (81, "line_23e_total_expenses"),
        (82, "line_24_income"),
        (83, "line_25_losses"),
        (84, "line_26_total_rental_real_estate_and_royalty_income_or_loss"),
    ]:
        fields[f"{FIELD_PREFIX}.f1_{field_number}[0]"] = money(f"calculated.form_line_values.f1040se.part_i.{line_key}")

    fields[f"{PAGE2_PREFIX}.f2_1[0]"] = fields[f"{FIELD_PREFIX}.f1_1[0]"]
    fields[f"{PAGE2_PREFIX}.f2_2[0]"] = fields[f"{FIELD_PREFIX}.f1_2[0]"]
    fields[f"{PAGE2_PREFIX}.f2_78[0]"] = money("calculated.form_line_values.f1040se.line_41_total_income_or_loss")

    return {
        "schema_version": "0.1",
        "form_id": "f1040se",
        "pdf": "f1040se.pdf",
        "output_pdf": f"{tax_year}_f1040se_draft.pdf",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "notes": [
            "Maps Schedule E Part I rental/royalty fields and page 2 line 41 for the current IRS fillable f1040se.pdf field names.",
            "Run validate_tax_data.py after downloading the blank PDF to catch IRS field-name revisions.",
        ],
        "fields": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a default Schedule E field map.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--tax-year", default="2025", help="Tax year used in output_pdf name.")
    parser.add_argument("--output", help="Output field map path.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing field map.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else root / "tax_forms" / "workpapers" / "field_maps" / "f1040se_field_map.yaml"
    )
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Field map already exists: {output}. Use --overwrite to replace it.")
    dump_yaml(schedule_e_field_map(args.tax_year), output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
