#!/usr/bin/env python3
"""Calculate common residential rental depreciation for Schedule E and CA review."""

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
RESIDENTIAL_RECOVERY_YEARS = Decimal("27.5")
NONRESIDENTIAL_RECOVERY_YEARS = Decimal("39")
CA_REVIEW_TOPICS = {
    "ca_depreciation_difference",
    "ca_depreciation_review",
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


def meaningful(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    return True


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


def parse_date(value: Any) -> dt.date | None:
    if is_unknown(value):
        return None
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def property_id(item: dict[str, Any], index: int) -> str:
    value = item.get("property_id") or item.get("activity_id")
    return str(value) if meaningful(value) else f"rental_{index + 1:03d}"


def depreciation_data(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("depreciation")
    if isinstance(value, dict):
        return value
    value = {}
    item["depreciation"] = value
    return value


def property_type(item: dict[str, Any]) -> str:
    return str(item.get("property_type") or item.get("property_description") or "").strip().lower()


def default_recovery_years(item: dict[str, Any]) -> Decimal:
    kind = property_type(item)
    if "commercial" in kind or "nonresidential" in kind:
        return NONRESIDENTIAL_RECOVERY_YEARS
    return RESIDENTIAL_RECOVERY_YEARS


def allowed_months_for_year(
    placed_in_service: dt.date,
    tax_year: int,
    recovery_years: Decimal,
    disposed: dt.date | None = None,
) -> Decimal:
    if tax_year < placed_in_service.year:
        return Decimal("0")
    if disposed and tax_year > disposed.year:
        return Decimal("0")

    recovery_months = recovery_years * Decimal("12")
    used_months = Decimal("0")
    current_months = Decimal("0")
    for year in range(placed_in_service.year, tax_year + 1):
        if disposed and year > disposed.year:
            break
        if year == placed_in_service.year and disposed and year == disposed.year:
            months = Decimal(max(0, disposed.month - placed_in_service.month))
        elif year == placed_in_service.year:
            months = Decimal("12.5") - Decimal(placed_in_service.month)
        elif disposed and year == disposed.year:
            months = Decimal(disposed.month) - Decimal("0.5")
        else:
            months = Decimal("12")
        if used_months >= recovery_months:
            months = Decimal("0")
        elif used_months + months > recovery_months:
            months = recovery_months - used_months
        used_months += months
        if year == tax_year:
            current_months = months
    return max(Decimal("0"), current_months)


def depreciation_for_year(
    basis: Decimal,
    recovery_years: Decimal,
    placed_in_service: dt.date,
    tax_year: int,
    prior_depreciation: Decimal = Decimal("0"),
    disposed: dt.date | None = None,
) -> tuple[Decimal, Decimal]:
    if basis <= 0:
        return Decimal("0"), Decimal("0")
    months = allowed_months_for_year(placed_in_service, tax_year, recovery_years, disposed)
    recovery_months = recovery_years * Decimal("12")
    current = (basis / recovery_months) * months
    remaining = max(Decimal("0"), basis - prior_depreciation)
    return min(current, remaining), months


def rental_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    rentals = []
    for item in entries(data, "income.rentals_royalties_partnerships"):
        marker = " ".join(
            str(item.get(key, "")).lower()
            for key in ["activity_type", "type", "property_description", "property_type"]
        )
        if "rental" in marker or meaningful(item.get("property_address")) or meaningful(item.get("gross_rents")):
            rentals.append(item)
    return rentals


def add_review(review_items: list[dict[str, str]], topic: str, message: str, severity: str = "review") -> None:
    review_items.append({"severity": severity, "topic": topic, "message": message})


def calculate_property_depreciation(
    item: dict[str, Any],
    index: int,
    tax_year: int,
    overwrite: bool,
    review_items: list[dict[str, str]],
) -> dict[str, Any]:
    dep = depreciation_data(item)
    pid = property_id(item, index)
    placed = parse_date(first_value(item, ["placed_in_service_date", "date_placed_in_service"]) or dep.get("placed_in_service_date"))
    disposed = parse_date(first_value(item, ["date_sold_or_stopped_rental", "disposed_date", "date_sold"]) or dep.get("disposed_date"))
    if placed is None:
        add_review(
            review_items,
            "rental_depreciation_missing_placed_in_service",
            f"{pid} needs a placed-in-service date before depreciation can be calculated.",
        )
        return {"property_id": pid, "status": "needs_review"}

    land = first_amount(dep, ["land_value", "federal_land_value"])
    building_basis = first_amount(dep, ["building_basis", "depreciable_basis", "federal_building_basis"])
    if building_basis == 0:
        purchase_price = first_amount(dep, ["purchase_price", "original_purchase_price", "cost_basis"])
        adjusted_basis = first_amount(dep, ["adjusted_basis"])
        conversion_fmv = first_amount(dep, ["fair_market_value_at_conversion", "fmv_at_conversion"])
        gross_basis = adjusted_basis or purchase_price
        if conversion_fmv and gross_basis:
            gross_basis = min(gross_basis, conversion_fmv)
        if gross_basis and land:
            building_basis = max(Decimal("0"), gross_basis - land)

    if building_basis <= 0:
        add_review(
            review_items,
            "rental_depreciation_missing_building_basis",
            f"{pid} needs building value/depreciable basis. Land is not depreciable, so the land/building split must be supplied or inferred from source documents.",
        )
        return {"property_id": pid, "status": "needs_review", "land_value": money_string(land)}

    recovery_years = money(dep.get("federal_recovery_period_years")) or default_recovery_years(item)
    prior = first_amount(dep, ["prior_depreciation", "federal_prior_depreciation"])
    federal_current, federal_months = depreciation_for_year(
        building_basis,
        recovery_years,
        placed,
        tax_year,
        prior,
        disposed,
    )

    ca_land = money(dep.get("ca_land_value")) if meaningful(dep.get("ca_land_value")) else land
    ca_basis = money(dep.get("ca_building_basis")) if meaningful(dep.get("ca_building_basis")) else building_basis
    ca_recovery_years = money(dep.get("ca_recovery_period_years")) if meaningful(dep.get("ca_recovery_period_years")) else recovery_years
    ca_prior = money(dep.get("ca_prior_depreciation")) if meaningful(dep.get("ca_prior_depreciation")) else prior
    ca_current, ca_months = depreciation_for_year(ca_basis, ca_recovery_years, placed, tax_year, ca_prior, disposed)

    if int(placed.year) < 1987 or meaningful(dep.get("bonus_depreciation")) or meaningful(dep.get("section_179")):
        add_review(
            review_items,
            "ca_depreciation_review",
            f"{pid} may need California depreciation review because pre-1987 property, bonus depreciation, section 179, special credits, or accelerated write-offs can create federal/California differences.",
        )
    if ca_current != federal_current or ca_basis != building_basis or ca_recovery_years != recovery_years:
        add_review(
            review_items,
            "ca_depreciation_difference",
            f"{pid} has a California depreciation difference. Use Schedule CA and Form FTB 3885A review for the rental adjustment.",
        )

    dep.update(
        {
            "land_value": money_string(land),
            "building_basis": money_string(building_basis),
            "federal_recovery_period_years": money_string(recovery_years),
            "federal_method": "straight_line",
            "federal_convention": "mid_month",
            "federal_current_depreciation": money_string(federal_current),
            "federal_depreciation_months": str(federal_months.normalize()),
            "ca_land_value": money_string(ca_land),
            "ca_building_basis": money_string(ca_basis),
            "ca_recovery_period_years": money_string(ca_recovery_years),
            "ca_method": "straight_line",
            "ca_convention": "mid_month",
            "ca_current_depreciation": money_string(ca_current),
            "ca_depreciation_months": str(ca_months.normalize()),
        }
    )
    if is_unknown(dep.get("current_depreciation")) or overwrite:
        dep["current_depreciation"] = money_string(federal_current)

    return {
        "property_id": pid,
        "status": "calculated",
        "placed_in_service_date": placed.isoformat(),
        "disposed_date": disposed.isoformat() if disposed else None,
        "land_value": money_string(land),
        "building_basis": money_string(building_basis),
        "federal_current_depreciation": money_string(federal_current),
        "ca_current_depreciation": money_string(ca_current),
        "ca_adjustment": money_string(federal_current - ca_current),
    }


def calculate(data: dict[str, Any], overwrite: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    review_items: list[dict[str, str]] = []
    try:
        tax_year = int(str(data.get("tax_year") or "").strip())
    except ValueError as exc:
        raise SystemExit("tax_year must be numeric before calculating rental depreciation.") from exc

    results = [
        calculate_property_depreciation(item, index, tax_year, overwrite, review_items)
        for index, item in enumerate(rental_items(data))
    ]
    federal_total = sum((money(result.get("federal_current_depreciation")) for result in results), Decimal("0"))
    ca_total = sum((money(result.get("ca_current_depreciation")) for result in results), Decimal("0"))
    ca_adjustment = federal_total - ca_total

    calculated = data.setdefault("calculated", {})
    rental_depreciation = calculated.setdefault("rental_depreciation", {})
    rental_depreciation.update(
        {
            "engine_version": ENGINE_VERSION,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "scope": "residential_rental_straight_line_mid_month_with_ca_review",
            "properties": results,
            "federal_current_depreciation_total": money_string(federal_total),
            "ca_current_depreciation_total": money_string(ca_total),
            "ca_adjustment_federal_minus_ca": money_string(ca_adjustment),
        }
    )

    ca_state = data.setdefault("state_adjustments", {}).setdefault("ca", {})
    ca_state["rental_depreciation_federal_total"] = money_string(federal_total)
    ca_state["rental_depreciation_ca_total"] = money_string(ca_total)
    ca_state["rental_depreciation_adjustment_total"] = money_string(ca_adjustment)
    ca_state["rental_depreciation_addition"] = money_string(max(Decimal("0"), ca_adjustment))
    ca_state["rental_depreciation_subtraction"] = money_string(max(Decimal("0"), -ca_adjustment))

    existing_review_items = calculated.setdefault("review_items", [])
    existing_review_items = [
        item
        for item in existing_review_items
        if not (isinstance(item, dict) and item.get("topic") in CA_REVIEW_TOPICS | {
            "rental_depreciation_missing_placed_in_service",
            "rental_depreciation_missing_building_basis",
        })
    ]
    existing_review_items.extend(review_items)
    calculated["review_items"] = existing_review_items
    data["review_status"] = "calculated_needs_review" if existing_review_items else "calculated"

    report = {
        "schema_version": "0.1",
        "engine_version": ENGINE_VERSION,
        "generated_at": rental_depreciation["generated_at"],
        "scope": rental_depreciation["scope"],
        "properties": results,
        "federal_current_depreciation_total": money_string(federal_total),
        "ca_current_depreciation_total": money_string(ca_total),
        "ca_adjustment_federal_minus_ca": money_string(ca_adjustment),
        "review_items": review_items,
        "sources": [
            {
                "agency": "IRS",
                "title": "Publication 527, Residential Rental Property",
                "url": "https://www.irs.gov/publications/p527",
            },
            {
                "agency": "California Franchise Tax Board",
                "title": "Rental income type guidance",
                "url": "https://www.ftb.ca.gov/file/personal/income-types/rental.html",
            },
            {
                "agency": "California Franchise Tax Board",
                "title": "Form FTB 3885A instructions",
                "url": "https://www.ftb.ca.gov/forms/2025/2025-3885a-instructions.html",
            },
        ],
    }
    return data, report


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate common residential rental depreciation.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--output", help="Path for updated extracted tax data. Defaults to overwriting --data.")
    parser.add_argument(
        "--report",
        help="Path for depreciation report. Defaults to tax_forms/workpapers/rental_depreciation_report.yaml.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite depreciation.current_depreciation.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else data_path
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else tax_forms / "workpapers" / "rental_depreciation_report.yaml"
    )

    data = load_yaml(data_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")
    updated_data, report = calculate(data, overwrite=args.overwrite)
    dump_yaml(updated_data, output_path)
    dump_yaml(report, report_path)

    print(f"Updated data: {relative_to_root(output_path, root)}")
    print(f"Rental depreciation report: {relative_to_root(report_path, root)}")
    print(f"Review items: {len(report['review_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
