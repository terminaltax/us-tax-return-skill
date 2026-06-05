#!/usr/bin/env python3
"""Generate a Schedule A field map for the current IRS fillable PDF field names."""

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


PAGE1 = "form1[0].Page1[0]"
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


def checkbox(path: str) -> dict[str, str]:
    return {
        "path": path,
        "type": "checkbox",
        "checked_value": "/1",
        "unchecked_value": "/Off",
    }


def sa_path(path: str) -> str:
    return f"calculated.form_line_values.f1040sa.{path}"


def schedule_a_field_map(tax_year: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        f"{PAGE1}.f1_1[0]": {
            "join": {"paths": ["taxpayer.primary.full_name", "taxpayer.spouse.full_name"], "separator": " & "},
            "format": "text",
        },
        f"{PAGE1}.f1_2[0]": {"path": "taxpayer.primary.ssn", "format": "digits"},
        f"{PAGE1}.f1_3[0]": money(sa_path("line_1_medical_and_dental_expenses")),
        f"{PAGE1}.Line2_ReadOrder[0].f1_4[0]": money(sa_path("line_2_adjusted_gross_income")),
        f"{PAGE1}.f1_5[0]": money(sa_path("line_3_medical_threshold_7_5_percent")),
        f"{PAGE1}.f1_6[0]": money(sa_path("line_4_medical_deduction")),
        f"{PAGE1}.c1_1[0]": checkbox(sa_path("line_5a_general_sales_tax_elected")),
        f"{PAGE1}.f1_7[0]": money(sa_path("line_5a_state_local_income_or_sales_taxes")),
        f"{PAGE1}.f1_8[0]": money(sa_path("line_5b_real_estate_taxes")),
        f"{PAGE1}.f1_9[0]": money(sa_path("line_5c_personal_property_taxes")),
        f"{PAGE1}.f1_10[0]": money(sa_path("line_5d_total_taxes_before_limit")),
        f"{PAGE1}.f1_11[0]": money(sa_path("line_5e_state_and_local_tax_deduction")),
        f"{PAGE1}.f1_12[0]": text(sa_path("line_6_other_taxes_description")),
        f"{PAGE1}.f1_13[0]": money(sa_path("line_6_other_taxes")),
        f"{PAGE1}.f1_14[0]": money(sa_path("line_7_total_taxes")),
        f"{PAGE1}.Line8_ReadOrder[0].c1_2[0]": checkbox(sa_path("line_8_home_mortgage_interest_not_all_proceeds_used")),
        f"{PAGE1}.f1_15[0]": money(sa_path("line_8a_home_mortgage_interest_form_1098")),
        f"{PAGE1}.Line8b_ReadOrder[0].f1_16[0]": text(sa_path("line_8b_recipient")),
        f"{PAGE1}.f1_17[0]": money(sa_path("line_8b_home_mortgage_interest_not_form_1098")),
        f"{PAGE1}.f1_18[0]": money(sa_path("line_8c_points_not_reported_on_1098")),
        f"{PAGE1}.f1_19[0]": money(sa_path("line_8d_reserved")),
        f"{PAGE1}.f1_20[0]": money(sa_path("line_8e_total_home_mortgage_interest")),
        f"{PAGE1}.f1_21[0]": money(sa_path("line_9_investment_interest")),
        f"{PAGE1}.f1_22[0]": money(sa_path("line_10_total_interest")),
        f"{PAGE1}.f1_23[0]": money(sa_path("line_11_gifts_by_cash_or_check")),
        f"{PAGE1}.f1_24[0]": money(sa_path("line_12_other_than_cash_or_check")),
        f"{PAGE1}.f1_25[0]": money(sa_path("line_13_carryover_from_prior_year")),
        f"{PAGE1}.f1_26[0]": money(sa_path("line_14_total_gifts_to_charity")),
        f"{PAGE1}.f1_27[0]": money(sa_path("line_15_casualty_and_theft_loss")),
        f"{PAGE1}.f1_28[0]": text(sa_path("line_16_other_itemized_deductions_description")),
        f"{PAGE1}.f1_29[0]": money(sa_path("line_16_other_itemized_deductions")),
        f"{PAGE1}.f1_30[0]": money(sa_path("line_17_total_itemized_deductions")),
        f"{PAGE1}.Line18_ReadOrder[0].c1_3[0]": checkbox(sa_path("line_18_itemizing_elected")),
    }
    return {
        "schema_version": "0.1",
        "form_id": "f1040sa",
        "pdf": "f1040sa.pdf",
        "output_pdf": f"{tax_year}_f1040sa_draft.pdf",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "notes": [
            "Maps common 2025 Schedule A itemized deduction fields from calculated.form_line_values.f1040sa.",
            "Run validate_tax_data.py after downloading the blank PDF to catch IRS field-name revisions.",
        ],
        "fields": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a default Schedule A field map.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--tax-year", default="2025", help="Tax year used in output_pdf name.")
    parser.add_argument("--output", help="Output field map path.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing field map.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else root / "tax_forms" / "workpapers" / "field_maps" / "f1040sa_field_map.yaml"
    )
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Field map already exists: {output}. Use --overwrite to replace it.")
    dump_yaml(schedule_a_field_map(args.tax_year), output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
