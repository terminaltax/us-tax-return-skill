"""OpenTaxSolver-backed math helpers using tenforty's low-level OTS wrapper."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib import metadata
from typing import Any


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}
SUPPORTED_OTS_YEARS = set(range(2018, 2026))


class OTSMathError(RuntimeError):
    """Raised when the OTS math engine cannot evaluate a return."""


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


def money_string(value: Any) -> str:
    amount = money(value) if not isinstance(value, Decimal) else value
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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


def calculated_line(data: dict[str, Any], form_id: str, line: str) -> Decimal:
    return money(get_path(data, f"calculated.form_line_values.{form_id}.{line}"))


def tax_year(data: dict[str, Any]) -> int:
    try:
        year = int(str(data.get("tax_year") or "").strip())
    except ValueError as exc:
        raise OTSMathError("OTS requires a numeric tax_year from 2018 through 2025.") from exc
    if year not in SUPPORTED_OTS_YEARS:
        raise OTSMathError(f"OTS does not support tax year {year}; supported years are 2018 through 2025.")
    return year


def filing_status(data: dict[str, Any]) -> str:
    raw = str(get_path(data, "taxpayer.filing_status") or "").strip().lower()
    mapping = {
        "single": "Single",
        "married_filing_jointly": "Married/Joint",
        "married_joint": "Married/Joint",
        "married_rdp_filing_jointly": "Married/Joint",
        "married_filing_separately": "Married/Sep",
        "married_sep": "Married/Sep",
        "married_rdp_filing_separately": "Married/Sep",
        "head_of_household": "Head_of_House",
        "head_of_house": "Head_of_House",
        "qualifying_surviving_spouse": "Widow(er)",
        "qualifying_surviving_spouse_rdp": "Widow(er)",
        "widow": "Widow(er)",
        "widower": "Widow(er)",
        "widow(er)": "Widow(er)",
    }
    status = mapping.get(raw)
    if status is None:
        raise OTSMathError("OTS requires taxpayer.filing_status to be reviewed and supported.")
    return status


def dependents_count(data: dict[str, Any]) -> int:
    dependents = get_path(data, "taxpayer.dependents")
    if isinstance(dependents, list):
        return len(dependents)
    raw_count = get_path(data, "taxpayer.num_dependents")
    if is_unknown(raw_count):
        return 0
    try:
        return int(raw_count)
    except (TypeError, ValueError):
        return 0


def yes_no(value: Any) -> str | None:
    if is_unknown(value):
        return None
    if isinstance(value, bool):
        return "Y" if value else "N"
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return "Y"
    if text in {"false", "no", "n", "0"}:
        return "N"
    return None


def set_amount(values: dict[str, Any], key: str, amount: Decimal, *, include_zero: bool = False) -> None:
    if include_zero or amount != 0:
        values[key] = money_string(amount)


def set_flag(values: dict[str, Any], key: str, value: Any) -> None:
    flag = yes_no(value)
    if flag is not None:
        values[key] = flag


def normalize_state(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"CALIFORNIA", "CA"}:
        return "CA"
    return text


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


def _fallback(primary: Decimal, data: dict[str, Any], form_id: str, line: str) -> Decimal:
    if primary != 0:
        return primary
    return calculated_line(data, form_id, line)


def federal_ots_input(data: dict[str, Any]) -> dict[str, Any]:
    wages = entries(data, "income.wages")
    interest = entries(data, "income.interest")
    dividends = entries(data, "income.dividends")
    capital_items = entries(data, "income.capital_gains")
    retirement = entries(data, "income.retirement_distributions")
    social_security = entries(data, "income.social_security")
    business = entries(data, "income.business_or_1099_income")
    rentals = entries(data, "income.rentals_royalties_partnerships")
    other_income = entries(data, "income.other_income")

    wage_income = _fallback(total_entries(wages, ["wages_box_1", "wages", "amount"]), data, "f1040", "line_1a")
    w2_withholding = _fallback(
        total_entries(wages, ["federal_income_tax_withheld_box_2", "federal_withholding"]),
        data,
        "f1040",
        "line_25a_federal_income_tax_withheld_from_w2",
    )
    taxable_interest = _fallback(
        total_entries(interest, ["interest_income_box_1", "taxable_interest", "amount"]),
        data,
        "f1040",
        "line_2b",
    )
    tax_exempt_interest = _fallback(
        total_entries(interest, ["tax_exempt_interest_box_8", "tax_exempt_interest"]),
        data,
        "f1040",
        "line_2a",
    )
    interest_withholding = total_entries(interest, ["federal_income_tax_withheld_box_4", "federal_withholding"])
    ordinary_dividends = _fallback(
        total_entries(dividends, ["ordinary_dividends_box_1a", "ordinary_dividends", "amount"]),
        data,
        "f1040",
        "line_3b",
    )
    qualified_dividends = _fallback(
        total_entries(dividends, ["qualified_dividends_box_1b", "qualified_dividends"]),
        data,
        "f1040",
        "line_3a",
    )
    capital_gain_distributions = total_entries(dividends, ["capital_gain_distributions_box_2a", "capital_gain_distributions"])
    dividend_withholding = total_entries(dividends, ["federal_income_tax_withheld_box_4", "federal_withholding"])

    ira_items, pension_items = classify_retirement_items(retirement)
    ira_gross = _fallback(total_entries(ira_items, ["gross_distribution_box_1", "gross_distribution", "amount"]), data, "f1040", "line_4a")
    ira_taxable = _fallback(total_entries(ira_items, ["taxable_amount_box_2a", "taxable_amount"]), data, "f1040", "line_4b")
    pension_gross = _fallback(total_entries(pension_items, ["gross_distribution_box_1", "gross_distribution", "amount"]), data, "f1040", "line_5a")
    pension_taxable = _fallback(total_entries(pension_items, ["taxable_amount_box_2a", "taxable_amount"]), data, "f1040", "line_5b")
    retirement_withholding = total_entries(retirement, ["federal_income_tax_withheld_box_4", "federal_withholding"])

    ss_benefits = _fallback(total_entries(social_security, ["net_benefits_box_5", "benefits", "amount"]), data, "f1040", "line_6a")
    ss_withholding = total_entries(social_security, ["federal_income_tax_withheld", "federal_withholding"])

    short_capital = sum((capital_gain_or_loss(item) for item in capital_items if is_short_term(item)), Decimal("0"))
    long_capital = sum((capital_gain_or_loss(item) for item in capital_items if is_long_term(item)), Decimal("0"))
    unknown_capital_total = sum(
        (
            capital_gain_or_loss(item)
            for item in capital_items
            if not is_short_term(item) and not is_long_term(item)
        ),
        Decimal("0"),
    )
    if short_capital == 0 and unknown_capital_total == 0:
        short_capital = calculated_line(data, "f1040sd", "line_7")
    if long_capital == 0 and capital_gain_distributions == 0:
        long_capital = calculated_line(data, "f1040sd", "line_15")
    if short_capital == 0 and long_capital == 0 and capital_gain_distributions == 0:
        form1040_capital = calculated_line(data, "f1040", "line_7")
        if form1040_capital < 0:
            short_capital = form1040_capital
        else:
            long_capital = form1040_capital
    short_capital += unknown_capital_total

    business_net = _fallback(
        total_entries(business, ["net_profit", "schedule_c_net_profit", "net_income"]),
        data,
        "f1040s1",
        "line_3_business_income_or_loss",
    )
    business_withholding = total_entries(business, ["federal_income_tax_withheld", "backup_withholding"])
    rental_total = _fallback(
        total_entries(
            rentals,
            ["income_loss", "ordinary_business_income_loss", "rental_real_estate_income_loss", "amount"],
        ),
        data,
        "f1040s1",
        "line_5_rental_royalty_partnerships_estates_trusts",
    )
    other_income_total = _fallback(
        total_entries(other_income, ["amount", "income", "taxable_amount"]),
        data,
        "f1040s1",
        "line_8z_other_income",
    )

    adjustments = get_path(data, "adjustments") or {}
    adjustment_total = Decimal("0")
    if isinstance(adjustments, dict):
        for value in adjustments.values():
            for item in as_list(value):
                if isinstance(item, dict):
                    adjustment_total += first_amount(item, ["deduction_amount", "amount", "allowable_amount"])
    adjustment_total = _fallback(adjustment_total, data, "f1040s1", "line_26_adjustments_to_income")

    credits = get_path(data, "credits") or {}
    child_credit_total = Decimal("0")
    schedule3_credit_total = Decimal("0")
    if isinstance(credits, dict):
        child_credit_total = total_entries(entries(data, "credits.child_and_dependent"), ["credit_amount", "amount"])
        for section, value in credits.items():
            for item in as_list(value):
                if isinstance(item, dict):
                    amount = first_amount(item, ["credit_amount", "amount", "allowable_amount"])
                    if section in {"education", "foreign_tax", "retirement_saver", "energy", "premium_tax_credit", "other"}:
                        schedule3_credit_total += amount

    payments = get_path(data, "payments") or {}
    estimated_payments = Decimal("0")
    extension_payments = Decimal("0")
    refundable_credits = Decimal("0")
    other_federal_withholding = Decimal("0")
    if isinstance(payments, dict):
        estimated_payments = _fallback(
            total_entries(entries(data, "payments.estimated_tax_payments"), ["amount"]),
            data,
            "f1040",
            "line_26_estimated_tax_payments",
        )
        extension_payments = total_entries(entries(data, "payments.extension_payments"), ["amount"])
        refundable_credits = total_entries(entries(data, "payments.refundable_credits"), ["amount", "credit_amount"])
        other_federal_withholding = total_entries(entries(data, "payments.federal_withholding"), ["amount"])
    form1099_withholding = _fallback(
        interest_withholding + dividend_withholding + retirement_withholding + ss_withholding + business_withholding,
        data,
        "f1040",
        "line_25b_federal_income_tax_withheld_from_1099",
    )

    values: dict[str, Any] = {
        "Status": filing_status(data),
        "Dependents": str(dependents_count(data)),
    }
    for source_path, ots_key in [
        ("taxpayer.primary.age_65_or_over", "You_65+Over?"),
        ("taxpayer.primary.is_65_or_older", "You_65+Over?"),
        ("taxpayer.primary.blind", "You_Blind?"),
        ("taxpayer.spouse.age_65_or_over", "Spouse_65+Over?"),
        ("taxpayer.spouse.is_65_or_older", "Spouse_65+Over?"),
        ("taxpayer.spouse.blind", "Spouse_Blind?"),
        ("taxpayer.virtual_currency", "VirtCurr?"),
    ]:
        if ots_key not in values:
            set_flag(values, ots_key, get_path(data, source_path))

    for key, amount in [
        ("L1a", wage_income),
        ("L2a", tax_exempt_interest),
        ("L2b", taxable_interest),
        ("L3a", qualified_dividends),
        ("L3b", ordinary_dividends),
        ("L4a", ira_gross),
        ("L4b", ira_taxable),
        ("L5a", pension_gross),
        ("L5b", pension_taxable),
        ("L6a", ss_benefits),
        ("D1ad", short_capital),
        ("D8ad", long_capital),
        ("D13", capital_gain_distributions),
        ("S1_3", business_net),
        ("S1_5", rental_total),
        ("S1_8z", other_income_total),
        ("S1_24z", adjustment_total),
        ("L19", child_credit_total),
        ("S3_6z", schedule3_credit_total),
        ("L25a", w2_withholding),
        ("L25b", form1099_withholding),
        ("L25c", other_federal_withholding),
        ("L26", estimated_payments),
        ("S3_10", extension_payments),
        ("L27", refundable_credits),
    ]:
        set_amount(values, key, amount)

    deductions = get_path(data, "deductions") or {}
    if isinstance(deductions, dict):
        method = str(deductions.get("standard_or_itemized") or "").strip().lower()
        if method == "itemized":
            itemized = Decimal("0")
            for key in ["itemized_deduction_total", "selected_deduction_amount"]:
                if key in deductions and not is_unknown(deductions.get(key)):
                    itemized = money(deductions[key])
                    break
            set_amount(values, "A6", itemized)
            values["A18"] = "Y"
        elif method == "standard":
            values["A18"] = "N"
        elif not is_unknown(deductions.get("itemized_deduction_total")):
            set_amount(values, "A6", money(deductions["itemized_deduction_total"]))

    qbi_value = get_path(data, "deductions.qbi_deduction")
    if not is_unknown(qbi_value):
        set_amount(values, "L13a", money(qbi_value))

    schedule2_tax_total = Decimal("0")
    if isinstance(get_path(data, "taxes"), dict):
        schedule2_tax_total = total_entries(entries(data, "taxes.additional_taxes"), ["amount", "tax_amount"])
    set_amount(values, "S2_17z", schedule2_tax_total)

    return values


def ca_w2_values(data: dict[str, Any]) -> tuple[Decimal, Decimal]:
    wages = Decimal("0")
    withholding = Decimal("0")
    for wage in entries(data, "income.wages"):
        for state_item in as_list(wage.get("state_items")):
            if not isinstance(state_item, dict) or normalize_state(state_item.get("state")) != "CA":
                continue
            wages += first_amount(state_item, ["state_wages_box_16", "wages", "amount"])
            withholding += first_amount(state_item, ["state_income_tax_box_17", "withholding", "amount"])
    wages = _fallback(wages, data, "ca540", "line_12_state_wages")
    withholding = _fallback(withholding, data, "ca540", "line_71_ca_income_tax_withheld")
    return wages, withholding


def ca_payment_total(data: dict[str, Any], path: str) -> Decimal:
    total = Decimal("0")
    for payment in entries(data, path):
        if normalize_state(payment.get("state")) == "CA":
            total += first_amount(payment, ["amount", "payment_amount", "withholding"])
    return total


def ca_ots_input(data: dict[str, Any]) -> dict[str, Any]:
    ca_state_wages, w2_state_withholding = ca_w2_values(data)
    payment_state_withholding = ca_payment_total(data, "payments.state_withholding")
    ca_withholding = payment_state_withholding if payment_state_withholding else w2_state_withholding
    ca_estimated_payments = ca_payment_total(data, "payments.state_estimated_payments")
    ca_extension_payments = ca_payment_total(data, "payments.state_extension_payments")

    values: dict[str, Any] = {
        "L10": str(dependents_count(data)),
    }
    set_amount(values, "L12", ca_state_wages, include_zero=True)
    set_amount(values, "L71", ca_withholding)
    set_amount(values, "L72", ca_estimated_payments)
    set_amount(values, "L73", ca_extension_payments)
    set_amount(values, "CA540_Subtr_B8z", money(get_path(data, "state_adjustments.ca.subtractions_total")))
    set_amount(values, "CA540_Addit_B8z", money(get_path(data, "state_adjustments.ca.additions_total")))

    itemized = get_path(data, "state_adjustments.ca.itemized_deduction_total")
    if not is_unknown(itemized):
        # OTS uses Schedule CA part II line 20/21 values to select the larger
        # California deduction against the standard deduction it computes.
        set_amount(values, "CA540_P2_20", money(itemized))

    return values


def _tenforty_evaluate_form():
    try:
        from tenforty.core import evaluate_form
    except Exception as exc:  # pragma: no cover - exercised through script tests when missing
        raise OTSMathError(
            "tenforty is required for OTS math. Install it with: uv pip install --python .venv/bin/python tenforty"
        ) from exc
    return evaluate_form


def tenforty_version() -> str:
    try:
        return metadata.version("tenforty")
    except metadata.PackageNotFoundError:
        return "unknown"


def evaluate_federal(data: dict[str, Any]) -> dict[str, Any]:
    year = tax_year(data)
    evaluate_form = _tenforty_evaluate_form()
    fed_values = federal_ots_input(data)
    try:
        outputs = evaluate_form(year, federal_form_values=fed_values, on_error="raise")
    except Exception as exc:
        raise OTSMathError(f"OTS federal calculation failed: {exc}") from exc
    return {
        "engine": math_engine_metadata(["US_1040"]),
        "year": year,
        "federal_input_keys": sorted(fed_values.keys()),
        "federal": outputs["federal"],
    }


def evaluate_federal_and_ca(data: dict[str, Any]) -> dict[str, Any]:
    year = tax_year(data)
    evaluate_form = _tenforty_evaluate_form()
    fed_values = federal_ots_input(data)
    state_values = ca_ots_input(data)
    try:
        outputs = evaluate_form(
            year,
            state_form_id="CA_540",
            federal_form_values=fed_values,
            state_form_values=state_values,
            on_error="raise",
        )
    except Exception as exc:
        raise OTSMathError(f"OTS California calculation failed: {exc}") from exc
    return {
        "engine": math_engine_metadata(["US_1040", "CA_540"]),
        "year": year,
        "federal_input_keys": sorted(fed_values.keys()),
        "state_input_keys": sorted(state_values.keys()),
        "federal": outputs["federal"],
        "state": outputs["state"],
    }


def math_engine_metadata(form_ids: list[str]) -> dict[str, Any]:
    return {
        "name": "OpenTaxSolver",
        "wrapper": "tenforty.otslib",
        "tenforty_version": tenforty_version(),
        "form_ids": form_ids,
    }


FEDERAL_1040_LINES = {
    "L1a": "line_1a",
    "L1z": "line_1z",
    "L2a": "line_2a",
    "L2b": "line_2b",
    "L3a": "line_3a",
    "L3b": "line_3b",
    "L4a": "line_4a",
    "L4b": "line_4b",
    "L5a": "line_5a",
    "L5b": "line_5b",
    "L6a": "line_6a",
    "L6b": "line_6b",
    "L7": "line_7",
    "L8": "line_8",
    "L9": "line_9_total_income",
    "L10": "line_10_adjustments_to_income",
    "L11": "line_11_adjusted_gross_income",
    "L11b": "line_11_adjusted_gross_income",
    "L12": "line_12_standard_or_itemized_deduction",
    "L13a": "line_13_qualified_business_income_deduction",
    "L14": "line_14_total_deductions",
    "L15": "line_15_taxable_income",
    "L16": "line_16_tax",
    "L19": "line_19_child_tax_credit_or_credit_for_other_dependents",
    "L20": "line_20_schedule_3_line_8",
    "L22": "line_22_tax_after_credits",
    "L23": "line_23_other_taxes",
    "L24": "line_24_total_tax",
    "L25a": "line_25a_federal_income_tax_withheld_from_w2",
    "L25b": "line_25b_federal_income_tax_withheld_from_1099",
    "L25c": "line_25c_other_federal_income_tax_withheld",
    "L25d": "line_25d_total_federal_income_tax_withheld",
    "L26": "line_26_estimated_tax_payments",
    "L31": "line_31_other_payments_and_refundable_credits",
    "L33": "line_33_total_payments",
    "L34": "line_34_overpaid",
    "L37": "line_37_amount_owed",
    "L38": "line_38_estimated_tax_penalty",
}

FEDERAL_SCHEDULE_1_LINES = {
    "S1_3": "line_3_business_income_or_loss",
    "S1_5": "line_5_rental_royalty_partnerships_estates_trusts",
    "S1_8z": "line_8z_other_income",
    "S1_10": "line_10_additional_income_total",
    "S1_26": "line_26_adjustments_to_income",
}

FEDERAL_SCHEDULE_2_LINES = {
    "S2_21": "line_21_total_other_taxes",
}

FEDERAL_SCHEDULE_3_LINES = {
    "S3_8": "line_8_total_other_credits",
    "S3_10": "line_10_amount_paid_with_extension",
}

FEDERAL_SCHEDULE_D_LINES = {
    "D7": "line_7",
    "D15": "line_15",
    "D16": "line_16",
    "D21": "line_21_to_form_1040",
}

CA_540_LINES = {
    "L12": "line_12_state_wages",
    "L13": "line_13_federal_agi",
    "L14": "line_14_ca_adjustments_subtractions",
    "L15": "line_15_subtotal",
    "L16": "line_16_ca_adjustments_additions",
    "L17": "line_17_ca_adjusted_gross_income",
    "L18": "line_18_standard_or_itemized_deduction",
    "L19": "line_19_taxable_income",
    "L31": "line_31_tax",
    "L32": "line_32_exemption_credits",
    "L35": "line_35_tax_after_exemption_credits",
    "L48": "line_48_total_nonrefundable_credits",
    "L61": "line_61_alternative_minimum_tax",
    "L62": "line_62_mental_health_services_tax",
    "L63": "line_63_other_taxes_and_credit_recapture",
    "L64": "line_64_total_tax",
    "L71": "line_71_ca_income_tax_withheld",
    "L72": "line_72_ca_estimated_tax_payments",
    "L73": "line_73_extension_payment",
}


def _apply_lines(lines: dict[str, str], output: dict[str, Any], mapping: dict[str, str]) -> None:
    for ots_key, line_name in mapping.items():
        value = output.get(ots_key)
        if isinstance(value, (int, float, Decimal)):
            lines[line_name] = money_string(Decimal(str(value)))


def apply_federal_outputs(
    form_line_values: dict[str, dict[str, str]],
    totals: dict[str, str],
    review_items: list[dict[str, str]],
    result: dict[str, Any],
) -> None:
    fed = result["federal"]
    _apply_lines(form_line_values.setdefault("f1040", {}), fed, FEDERAL_1040_LINES)
    if any(key in fed for key in FEDERAL_SCHEDULE_1_LINES):
        _apply_lines(form_line_values.setdefault("f1040s1", {}), fed, FEDERAL_SCHEDULE_1_LINES)
    if any(key in fed for key in FEDERAL_SCHEDULE_2_LINES):
        _apply_lines(form_line_values.setdefault("f1040s2", {}), fed, FEDERAL_SCHEDULE_2_LINES)
    if any(key in fed for key in FEDERAL_SCHEDULE_3_LINES):
        _apply_lines(form_line_values.setdefault("f1040s3", {}), fed, FEDERAL_SCHEDULE_3_LINES)
    if any(key in fed for key in FEDERAL_SCHEDULE_D_LINES):
        _apply_lines(form_line_values.setdefault("f1040sd", {}), fed, FEDERAL_SCHEDULE_D_LINES)

    for ots_key, total_key in [
        ("L9", "total_income"),
        ("L11b", "adjusted_gross_income"),
        ("L15", "taxable_income"),
        ("L16", "federal_income_tax"),
        ("L24", "federal_total_tax"),
        ("L25d", "federal_withholding"),
        ("L33", "total_payments"),
    ]:
        if isinstance(fed.get(ots_key), (int, float, Decimal)):
            totals[total_key] = money_string(Decimal(str(fed[ots_key])))

    resolved_topics = set()
    if isinstance(fed.get("L12"), (int, float, Decimal)) and isinstance(fed.get("L15"), (int, float, Decimal)):
        resolved_topics.add("deduction_amount")
    if isinstance(fed.get("L16"), (int, float, Decimal)):
        resolved_topics.add("line_16_tax")
    if isinstance(fed.get("L6b"), (int, float, Decimal)):
        resolved_topics.add("social_security_taxable_amount")
    review_items[:] = [item for item in review_items if item.get("topic") not in resolved_topics]


def apply_ca_outputs(
    form_line_values: dict[str, dict[str, str]],
    totals: dict[str, str],
    review_items: list[dict[str, str]],
    result: dict[str, Any],
) -> None:
    state = result["state"] or {}
    _apply_lines(form_line_values.setdefault("ca540", {}), state, CA_540_LINES)
    for ots_key, total_key in [
        ("L17", "ca_adjusted_gross_income"),
        ("L19", "ca_taxable_income"),
        ("L31", "ca_tax"),
        ("L32", "ca_exemption_credits"),
        ("L64", "ca_total_tax"),
        ("L71", "ca_income_tax_withheld"),
        ("L72", "ca_estimated_tax_payments"),
    ]:
        if isinstance(state.get(ots_key), (int, float, Decimal)):
            totals[total_key] = money_string(Decimal(str(state[ots_key])))

    resolved_topics = set()
    if isinstance(state.get("L13"), (int, float, Decimal)):
        resolved_topics.add("ca_federal_agi")
    if isinstance(state.get("L18"), (int, float, Decimal)):
        resolved_topics.add("ca_standard_deduction")
    if isinstance(state.get("L31"), (int, float, Decimal)):
        resolved_topics.add("ca_line_31_tax")
    if isinstance(state.get("L32"), (int, float, Decimal)) or isinstance(state.get("L35"), (int, float, Decimal)):
        resolved_topics.add("ca_exemption_credits")
    review_items[:] = [item for item in review_items if item.get("topic") not in resolved_topics]


def report_output_subset(output: dict[str, Any], keys: list[str]) -> dict[str, str]:
    subset: dict[str, str] = {}
    for key in keys:
        value = output.get(key)
        if isinstance(value, (int, float, Decimal)):
            subset[key] = money_string(Decimal(str(value)))
    return subset


def write_report_fields(report: dict[str, Any], result: dict[str, Any], *, state: bool = False) -> None:
    report["math_engine"] = result["engine"]
    report["ots_input_keys"] = {"federal": result.get("federal_input_keys", [])}
    report["ots_outputs"] = {
        "federal": report_output_subset(
            result["federal"],
            ["L9", "L11", "L11b", "L12", "L15", "L16", "L24", "L25d", "L33"],
        )
    }
    if state:
        report["ots_input_keys"]["state"] = result.get("state_input_keys", [])
        report["ots_outputs"]["state"] = report_output_subset(
            result["state"] or {},
            ["L13", "L17", "L18", "L19", "L31", "L32", "L35", "L64", "L71", "L72", "L73"],
        )
