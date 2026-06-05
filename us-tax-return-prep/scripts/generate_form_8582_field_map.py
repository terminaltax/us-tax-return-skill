#!/usr/bin/env python3
"""Generate a Form 8582 field map for the current IRS fillable PDF field names."""

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


PAGE1 = "topmostSubform[0].Page1[0]"
PAGE2 = "topmostSubform[0].Page2[0]"
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


def ratio(path: str) -> dict[str, str]:
    return {"path": path, "format": "text"}


def f8582_path(path: str) -> str:
    return f"calculated.form_line_values.f8582.{path}"


def add_part_iv(fields: dict[str, Any]) -> None:
    base_numbers = [20, 26, 32, 38, 44]
    for index, base in enumerate(base_numbers):
        row_path = f"part_iv.activities[{index}]"
        for offset, key in enumerate(
            [
                "name",
                "net_income",
                "net_loss",
                "prior_year_unallowed_loss",
                "overall_gain",
                "overall_loss",
            ]
        ):
            spec = text(f8582_path(f"{row_path}.{key}")) if key == "name" else money(f8582_path(f"{row_path}.{key}"))
            fields[f"{PAGE1}.Table_Part4[0].Row{index + 1}[0].f1_{base + offset}[0]"] = spec
    for field_number, key in [
        (50, "net_income"),
        (51, "net_loss"),
        (52, "prior_year_unallowed_loss"),
        (53, "overall_gain"),
        (54, "overall_loss"),
    ]:
        fields[f"{PAGE1}.Table_Part4[0].Row6[0].f1_{field_number}[0]"] = money(
            f8582_path(f"part_iv.totals.{key}")
        )


def add_allocation_table(
    fields: dict[str, Any],
    *,
    table_name: str,
    row_prefix: str,
    start_numbers: list[int],
    part_path: str,
    amount_keys: list[str],
) -> None:
    for index, base in enumerate(start_numbers):
        row_path = f"{part_path}.activities[{index}]"
        fields[f"{PAGE2}.{table_name}[0].Row{index + 1}[0].{row_prefix}_{base}[0]"] = text(
            f8582_path(f"{row_path}.name")
        )
        fields[f"{PAGE2}.{table_name}[0].Row{index + 1}[0].{row_prefix}_{base + 1}[0]"] = text(
            f8582_path(f"{row_path}.form_or_schedule_line")
        )
        for offset, key in enumerate(amount_keys, start=2):
            spec = ratio(f8582_path(f"{row_path}.{key}")) if key == "ratio" else money(f8582_path(f"{row_path}.{key}"))
            fields[f"{PAGE2}.{table_name}[0].Row{index + 1}[0].{row_prefix}_{base + offset}[0]"] = spec


def form_8582_field_map(tax_year: str) -> dict[str, Any]:
    fields: dict[str, Any] = {
        f"{PAGE1}.f1_01[0]": {
            "join": {"paths": ["taxpayer.primary.full_name", "taxpayer.spouse.full_name"], "separator": " & "},
            "format": "text",
        },
        f"{PAGE1}.f1_02[0]": {"path": "taxpayer.primary.ssn", "format": "digits"},
        f"{PAGE1}.f1_03[0]": money(f8582_path("part_i.line_1a_active_rental_net_income")),
        f"{PAGE1}.f1_04[0]": money(f8582_path("part_i.line_1b_active_rental_net_loss")),
        f"{PAGE1}.f1_05[0]": money(f8582_path("part_i.line_1c_active_rental_prior_year_unallowed_loss")),
        f"{PAGE1}.f1_06[0]": money(f8582_path("part_i.line_1d_active_rental_combined")),
        f"{PAGE1}.f1_07[0]": money(f8582_path("part_i.line_2a_other_passive_net_income")),
        f"{PAGE1}.f1_08[0]": money(f8582_path("part_i.line_2b_other_passive_net_loss")),
        f"{PAGE1}.f1_09[0]": money(f8582_path("part_i.line_2c_other_passive_prior_year_unallowed_loss")),
        f"{PAGE1}.f1_10[0]": money(f8582_path("part_i.line_2d_other_passive_combined")),
        f"{PAGE1}.f1_11[0]": money(f8582_path("part_i.line_3_total_passive_activity_loss")),
        f"{PAGE1}.f1_12[0]": money(f8582_path("part_ii.line_4_smaller_loss")),
        f"{PAGE1}.f1_13[0]": money(f8582_path("part_ii.line_5_phaseout_base")),
        f"{PAGE1}.f1_14[0]": money(f8582_path("part_ii.line_6_modified_adjusted_gross_income")),
        f"{PAGE1}.f1_15[0]": money(f8582_path("part_ii.line_7_phaseout_difference")),
        f"{PAGE1}.f1_16[0]": money(f8582_path("part_ii.line_8_special_allowance_limit")),
        f"{PAGE1}.f1_17[0]": money(f8582_path("part_ii.line_9_special_allowance")),
        f"{PAGE1}.f1_18[0]": money(f8582_path("part_iii.line_10_passive_activity_income")),
        f"{PAGE1}.f1_19[0]": money(f8582_path("part_iii.line_11_total_losses_allowed")),
    }
    add_part_iv(fields)
    add_allocation_table(
        fields,
        table_name="Table_Part6",
        row_prefix="f2",
        start_numbers=[36, 42, 48, 54, 60],
        part_path="part_vi",
        amount_keys=["loss", "ratio", "special_allowance", "remaining_unallowed_loss"],
    )
    add_allocation_table(
        fields,
        table_name="Table_Part7",
        row_prefix="f2",
        start_numbers=[70, 75, 80, 85, 90],
        part_path="part_vii",
        amount_keys=["loss", "ratio", "amount"],
    )
    add_allocation_table(
        fields,
        table_name="Table_PartVIII",
        row_prefix="f2",
        start_numbers=[98, 103, 108, 113, 118],
        part_path="part_viii",
        amount_keys=["loss", "unallowed_loss", "allowed_loss"],
    )
    fields[f"{PAGE2}.f2_66[0]"] = money(f8582_path("part_vi.total_loss"))
    fields[f"{PAGE2}.f2_68[0]"] = {"value": "1.00", "format": "text"}
    fields[f"{PAGE2}.f2_69[0]"] = money(f8582_path("part_ii.line_9_special_allowance"))
    fields[f"{PAGE2}.f2_95[0]"] = money(f8582_path("part_vii.total_loss"))
    fields[f"{PAGE2}.f2_97[0]"] = money(f8582_path("part_vii.total_unallowed_loss"))
    fields[f"{PAGE2}.f2_123[0]"] = money(f8582_path("part_viii.total_loss"))
    fields[f"{PAGE2}.f2_124[0]"] = money(f8582_path("part_viii.total_unallowed_loss"))
    fields[f"{PAGE2}.f2_125[0]"] = money(f8582_path("part_viii.total_allowed_loss"))

    return {
        "schema_version": "0.1",
        "form_id": "f8582",
        "pdf": "f8582.pdf",
        "output_pdf": f"{tax_year}_f8582_draft.pdf",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "notes": [
            "Maps Form 8582 Parts I-IV and VI-VIII for direct rental real estate passive loss limitations.",
            "Parts V and IX require manual/agent mapping for non-rental passive activities, PTPs, CRD, or losses reported on multiple forms.",
            "Run validate_tax_data.py after downloading the blank PDF to catch IRS field-name revisions.",
        ],
        "fields": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a default Form 8582 field map.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--tax-year", default="2025", help="Tax year used in output_pdf name.")
    parser.add_argument("--output", help="Output field map path.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing field map.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else root / "tax_forms" / "workpapers" / "field_maps" / "f8582_field_map.yaml"
    )
    if output.exists() and not args.overwrite:
        raise SystemExit(f"Field map already exists: {output}. Use --overwrite to replace it.")
    dump_yaml(form_8582_field_map(args.tax_year), output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
