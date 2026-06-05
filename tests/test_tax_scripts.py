from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from subprocess import run

import pytest
import yaml
from pypdf import PdfReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
TAX_SKILL = ROOT / "us-tax-return-prep"
TAX_SCRIPTS = TAX_SKILL / "scripts"
REGEN_SKILL = ROOT / "regenerate-tax-pdfs"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_script(script: Path, *args: str):
    return run([sys.executable, "-B", str(script), *args], check=True, text=True, capture_output=True)


def create_fillable_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    form = pdf.acroForm
    form.textfield(name="full_name", x=100, y=700, width=250, height=20)
    form.textfield(name="address", x=100, y=670, width=300, height=20)
    form.textfield(name="ssn_last4", x=100, y=640, width=80, height=20)
    form.textfield(name="line_1a", x=100, y=610, width=80, height=20)
    form.checkbox(name="single_box", x=100, y=580, buttonStyle="check", checked=False)
    pdf.showPage()
    pdf.save()


def create_fillable_pdf_with_fields(path: Path, field_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    form = pdf.acroForm
    y = 720
    for name in field_names:
        form.textfield(name=name, x=100, y=y, width=120, height=20)
        y -= 30
        if y < 80:
            pdf.showPage()
            y = 720
    pdf.showPage()
    pdf.save()


def test_prepare_tax_workspace_creates_layout_and_classifies_sources(tmp_path: Path):
    (tmp_path / "summary.md").write_text("Name: Ada Lovelace\n", encoding="utf-8")
    (tmp_path / "1099-B-brokerage.pdf").write_bytes(b"%PDF-1.4\n")
    itemized_dir = tmp_path / "itemized"
    itemized_dir.mkdir()
    (itemized_dir / "charity-receipt.pdf").write_bytes(b"%PDF-1.4\n")
    (itemized_dir / "mortgage-interest-1098.pdf").write_bytes(b"%PDF-1.4\n")
    rental_dir = tmp_path / "rental"
    rental_dir.mkdir()
    (rental_dir / "2025-property-tax-bill.pdf").write_bytes(b"%PDF-1.4\n")
    (rental_dir / "rent-ledger.csv").write_text("month,rent\nJan,1000\n", encoding="utf-8")

    run_script(TAX_SCRIPTS / "prepare_tax_workspace.py", str(tmp_path), "--tax-year", "2025")

    tax_forms = tmp_path / "tax_forms"
    assert (tmp_path / "itemized").is_dir()
    itemized_intake = tmp_path / "itemized" / "itemized_intake.md"
    assert itemized_intake.exists()
    itemized_text = itemized_intake.read_text(encoding="utf-8")
    assert "## Deduction Choice" in itemized_text
    assert "Choose one: standard / itemized / unsure" in itemized_text
    assert (tmp_path / "rental").is_dir()
    rental_intake = tmp_path / "rental" / "rental_intake.md"
    assert rental_intake.exists()
    assert "## Rental Property 1" in rental_intake.read_text(encoding="utf-8")
    assert "Land value or land percentage" in rental_intake.read_text(encoding="utf-8")
    assert "California building basis" in rental_intake.read_text(encoding="utf-8")
    assert (tax_forms / "extracted_tax_data.yaml").exists()
    assert (tax_forms / "required_irs_forms.yaml").exists()
    assert (tax_forms / "required_state_forms.yaml").exists()
    assert (tax_forms / "workpapers" / "blank_forms" / "irs").is_dir()
    assert (tax_forms / "workpapers" / "blank_forms" / "ca").is_dir()
    assert (tax_forms / "workpapers" / "field_maps").is_dir()
    assert (tax_forms / "workpapers" / "field_maps" / "ca").is_dir()

    manifest = read_yaml(tax_forms / "source_manifest.yaml")
    by_path = {doc["path"]: doc for doc in manifest["documents"]}
    assert by_path["summary.md"]["document_type"] == "summary"
    assert by_path["1099-B-brokerage.pdf"]["document_type"] == "1099-B"
    assert by_path["itemized/itemized_intake.md"]["document_type"] == "itemized_intake"
    assert by_path["itemized/charity-receipt.pdf"]["document_type"] == "itemized_charity_cash"
    assert by_path["itemized/mortgage-interest-1098.pdf"]["document_type"] == "itemized_mortgage_interest"
    assert by_path["rental/rental_intake.md"]["document_type"] == "rental_intake"
    assert by_path["rental/2025-property-tax-bill.pdf"]["document_type"] == "rental_property_tax"
    assert by_path["rental/rent-ledger.csv"]["document_type"] == "rental_lease_or_ledger"

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    assert data["tax_year"] == "2025"
    assert data["required_irs_forms"]["status"] == "not_inferred"
    assert data["required_state_forms"]["status"] == "not_inferred"
    assert data["filled_pdfs"]["status"] == "not_generated"
    assert data["calculation"]["status"] == "not_calculated"
    assert data["validation"]["status"] == "not_validated"
    assert data["review_report"]["status"] == "not_generated"


def test_prepare_tax_workspace_classifies_common_rental_documents(tmp_path: Path):
    rental_dir = tmp_path / "rental"
    rental_dir.mkdir()
    samples = {
        "mortgage-interest-1098.pdf": "rental_mortgage_interest",
        "landlord-insurance.pdf": "rental_insurance",
        "hoa-statement.pdf": "rental_hoa",
        "repair-invoice.pdf": "rental_repairs",
        "utility-water.pdf": "rental_utilities",
        "depreciation-schedule.xlsx": "rental_depreciation",
        "closing-statement.pdf": "rental_closing_statement",
    }
    for filename in samples:
        (rental_dir / filename).write_bytes(b"%PDF-1.4\n")

    run_script(TAX_SCRIPTS / "prepare_tax_workspace.py", str(tmp_path), "--tax-year", "2025")

    manifest = read_yaml(tmp_path / "tax_forms" / "source_manifest.yaml")
    by_path = {doc["path"]: doc["document_type"] for doc in manifest["documents"]}
    for filename, document_type in samples.items():
        assert by_path[f"rental/{filename}"] == document_type


def test_prepare_tax_workspace_classifies_common_itemized_documents(tmp_path: Path):
    itemized_dir = tmp_path / "itemized"
    itemized_dir.mkdir()
    samples = {
        "medical-receipts.pdf": "itemized_medical",
        "home-property-tax-bill.pdf": "itemized_property_tax",
        "mortgage-interest-1098.pdf": "itemized_mortgage_interest",
        "goodwill-noncash-donation.pdf": "itemized_charity_noncash",
        "church-donation-receipt.pdf": "itemized_charity_cash",
        "state-tax-estimated-payment.pdf": "itemized_state_tax",
        "dmv-registration.pdf": "itemized_vehicle_tax",
        "fema-disaster-casualty.pdf": "itemized_casualty",
        "margin-investment-interest.pdf": "itemized_investment_interest",
    }
    for filename in samples:
        (itemized_dir / filename).write_bytes(b"%PDF-1.4\n")

    run_script(TAX_SCRIPTS / "prepare_tax_workspace.py", str(tmp_path), "--tax-year", "2025")

    manifest = read_yaml(tmp_path / "tax_forms" / "source_manifest.yaml")
    by_path = {doc["path"]: doc["document_type"] for doc in manifest["documents"]}
    for filename, document_type in samples.items():
        assert by_path[f"itemized/{filename}"] == document_type


def test_infer_required_irs_forms_adds_schedule_d_and_8949(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "income": {"capital_gains": []},
        },
    )
    write_yaml(
        tax_forms / "source_manifest.yaml",
        {
            "schema_version": "0.1",
            "documents": [
                {"id": "doc_001", "path": "brokerage_1099-B.pdf", "document_type": "1099-B"}
            ],
        },
    )

    run_script(TAX_SCRIPTS / "infer_required_irs_forms.py", str(tmp_path))

    plan = read_yaml(tax_forms / "required_irs_forms.yaml")
    statuses = {form["form_id"]: form["status"] for form in plan["forms"]}
    assert statuses["f1040"] == "required"
    assert statuses["f1040sd"] == "required"
    assert statuses["f8949"] == "required"

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    assert data["required_irs_forms"]["status"] == "needs_review"


def test_infer_ca_state_forms_adds_resident_forms(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "return_scope": {"federal": True, "states": [{"state": "CA", "residency_status": "full_year_resident"}]},
            "taxpayer": {
                "address": {"state": "CA"},
                "filing_status": "married_filing_jointly",
            },
            "state_adjustments": {
                "ca": {
                    "residency_status": "unknown",
                    "reviewed_no_adjustments": False,
                    "subtractions_total": "unknown",
                    "additions_total": "unknown",
                    "itemized_deduction_total": "unknown",
                }
            },
            "income": {
                "wages": [
                    {
                        "source_document_id": "w2_001",
                        "state_items": [
                            {
                                "state": "CA",
                                "state_wages_box_16": "50000.00",
                                "state_income_tax_box_17": "2500.00",
                            }
                        ],
                    }
                ],
                "capital_gains": [{"term": "long", "gain_or_loss": "100.00"}],
            },
        },
    )

    run_script(TAX_SCRIPTS / "infer_ca_state_forms.py", str(tmp_path))

    plan = read_yaml(tax_forms / "required_state_forms.yaml")
    statuses = {form["form_id"]: form["status"] for form in plan["forms"]}
    assert statuses["ca540"] == "required"
    assert statuses["ca540ca"] == "review"
    assert statuses["ca540d"] == "review"
    ca540 = next(form for form in plan["forms"] if form["form_id"] == "ca540")
    assert ca540["pdf"] == "2025-540.pdf"
    assert ca540["blank_dir"] == "tax_forms/workpapers/blank_forms/ca"

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    assert data["required_state_forms"]["status"] == "needs_review"


def test_download_irs_forms_uses_plan_and_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = TAX_SCRIPTS / "download_irs_forms.py"
    module = load_module(script, "download_irs_forms_test")
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f1040",
                    "title": "Form 1040",
                    "status": "required",
                    "pdf": "f1040.pdf",
                    "instruction_pdf": "i1040gi.pdf",
                },
                {
                    "form_id": "f8949",
                    "title": "Form 8949",
                    "status": "review",
                    "pdf": "f8949.pdf",
                },
            ],
        },
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"%PDF-1.4\nfake\n"

    requested_urls: list[str] = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            str(tmp_path),
            "--include-review",
            "--include-instructions",
            "--overwrite",
        ],
    )

    assert module.main() == 0
    assert (tax_forms / "workpapers" / "blank_forms" / "irs" / "f1040.pdf").exists()
    assert (tax_forms / "workpapers" / "blank_forms" / "irs" / "i1040gi.pdf").exists()
    assert (tax_forms / "workpapers" / "blank_forms" / "irs" / "f8949.pdf").exists()
    assert requested_urls == [
        "https://www.irs.gov/pub/irs-pdf/f1040.pdf",
        "https://www.irs.gov/pub/irs-pdf/i1040gi.pdf",
        "https://www.irs.gov/pub/irs-pdf/f8949.pdf",
    ]
    manifest = read_yaml(tax_forms / "workpapers" / "blank_forms" / "irs" / "download_manifest.yaml")
    assert len(manifest["downloads"]) == 3


def test_download_ca_forms_uses_state_plan_and_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = TAX_SCRIPTS / "download_ca_forms.py"
    module = load_module(script, "download_ca_forms_test")
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "required_state_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "ca540",
                    "jurisdiction": "CA",
                    "title": "California Form 540",
                    "status": "required",
                    "pdf": "2025-540.pdf",
                    "url": "https://www.ftb.ca.gov/forms/2025/2025-540.pdf",
                },
                {
                    "form_id": "ca540ca",
                    "jurisdiction": "CA",
                    "title": "Schedule CA (540)",
                    "status": "review",
                    "pdf": "2025-540-ca.pdf",
                },
            ],
        },
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"%PDF-1.4\nfake\n"

    requested_urls: list[str] = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            str(tmp_path),
            "--include-review",
            "--overwrite",
        ],
    )

    assert module.main() == 0
    assert (tax_forms / "workpapers" / "blank_forms" / "ca" / "2025-540.pdf").exists()
    assert (tax_forms / "workpapers" / "blank_forms" / "ca" / "2025-540-ca.pdf").exists()
    assert requested_urls == [
        "https://www.ftb.ca.gov/forms/2025/2025-540.pdf",
        "https://www.ftb.ca.gov/forms/2025/2025-540-ca.pdf",
    ]
    manifest = read_yaml(tax_forms / "workpapers" / "blank_forms" / "ca" / "download_manifest.yaml")
    assert len(manifest["downloads"]) == 2


def test_calculate_tax_lines_common_federal_values(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {"filing_status": "single"},
            "income": {
                "wages": [
                    {
                        "wages_box_1": "50000.00",
                        "federal_income_tax_withheld_box_2": "5000.00",
                    }
                ],
                "interest": [{"interest_income_box_1": "100.00"}],
                "dividends": [
                    {
                        "ordinary_dividends_box_1a": "200.00",
                        "qualified_dividends_box_1b": "150.00",
                        "capital_gain_distributions_box_2a": "25.00",
                    }
                ],
                "capital_gains": [
                    {"term": "short", "gain_or_loss": "-4000.00"},
                    {"term": "long", "gain_or_loss": "1000.00"},
                ],
                "retirement_distributions": [],
                "social_security": [],
                "business_or_1099_income": [],
                "rentals_royalties_partnerships": [],
                "other_income": [],
            },
            "deductions": {"selected_deduction_amount": "13850.00"},
            "payments": {"estimated_tax_payments": [{"amount": "1000.00"}]},
        },
    )

    run_script(TAX_SCRIPTS / "calculate_tax_lines.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    f1040 = data["calculated"]["form_line_values"]["f1040"]
    schedule_d = data["calculated"]["form_line_values"]["f1040sd"]
    assert f1040["line_1a"] == "50000.00"
    assert f1040["line_2b"] == "100.00"
    assert f1040["line_3a"] == "150.00"
    assert schedule_d["line_16"] == "-2975.00"
    assert f1040["line_7"] == "-2975.00"
    assert f1040["line_9_total_income"] == "47325.00"
    assert f1040["line_11_adjusted_gross_income"] == "47325.00"
    assert f1040["line_12_standard_or_itemized_deduction"] == "15750.00"
    assert f1040["line_15_taxable_income"] == "31575.00"
    assert f1040["line_16_tax"] == "3533.00"
    assert f1040["line_24_total_tax"] == "3533.00"
    assert f1040["line_25a_federal_income_tax_withheld_from_w2"] == "5000.00"
    assert f1040["line_26_estimated_tax_payments"] == "1000.00"
    assert f1040["line_33_total_payments"] == "6000.00"
    assert data["calculated"]["scope"] == "federal_common_lines_with_ots"
    assert data["calculated"]["math_engine"]["wrapper"] == "tenforty.otslib"
    assert not any(item["topic"] == "line_16_tax" for item in data["calculated"]["review_items"])
    assert (tax_forms / "workpapers" / "calculation_report.yaml").exists()


def test_calculate_ca_lines_common_resident_values(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "return_scope": {"federal": True, "states": [{"state": "CA", "residency_status": "full_year_resident"}]},
            "taxpayer": {"filing_status": "married_filing_jointly", "address": {"state": "CA"}},
            "income": {
                "wages": [
                    {
                        "state_items": [
                            {
                                "state": "CA",
                                "state_wages_box_16": "50000.00",
                                "state_income_tax_box_17": "2500.00",
                            }
                        ]
                    }
                ]
            },
            "deductions": {"standard_or_itemized": "standard"},
            "payments": {
                "state_withholding": [{"state": "CA", "amount": "2500.00"}],
                "state_estimated_payments": [{"state": "CA", "amount": "1000.00"}],
            },
            "state_adjustments": {"ca": {"reviewed_no_adjustments": True}},
            "calculated": {
                "form_line_values": {
                    "f1040": {
                        "line_1a": "50000.00",
                        "line_2b": "100.00",
                        "line_3b": "200.00",
                        "line_7": "300.00",
                        "line_8": "0.00",
                        "line_11_adjusted_gross_income": "50600.00",
                    }
                },
                "review_items": [],
            },
        },
    )

    run_script(TAX_SCRIPTS / "calculate_ca_lines.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    ca540 = data["calculated"]["form_line_values"]["ca540"]
    ca540ca = data["calculated"]["form_line_values"]["ca540ca"]
    assert ca540["line_12_state_wages"] == "50000.00"
    assert ca540["line_13_federal_agi"] == "50600.00"
    assert ca540["line_18_standard_or_itemized_deduction"] == "11412.00"
    assert ca540["line_19_taxable_income"] == "39188.00"
    assert ca540["line_31_tax"] == "562.00"
    assert ca540["line_64_total_tax"] == "256.00"
    assert ca540["line_71_ca_income_tax_withheld"] == "2500.00"
    assert ca540["line_72_ca_estimated_tax_payments"] == "1000.00"
    assert ca540ca["part_i_line_1a_federal_wages"] == "50000.00"
    assert data["calculated"]["state"]["ca"]["scope"] == "ca_resident_lines_with_ots"
    assert data["calculated"]["state"]["ca"]["math_engine"]["wrapper"] == "tenforty.otslib"
    assert not any(item["topic"] == "ca_line_31_tax" for item in data["calculated"]["state"]["ca"]["review_items"])
    assert (tax_forms / "workpapers" / "ca_calculation_report.yaml").exists()


def test_validate_tax_data_checks_required_facts_field_maps_and_pdfs(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "irs"
    field_map_dir = tax_forms / "workpapers" / "field_maps"
    create_fillable_pdf(blank_dir / "f1040.pdf")
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {
                    "line1": "1 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94105",
                },
                "filing_status": "single",
            },
            "income": {"wages": [{"wages_box_1": "100.00"}]},
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f1040",
                    "title": "Form 1040",
                    "status": "required",
                    "pdf": "f1040.pdf",
                    "output_dir": "tax_forms/federal",
                }
            ],
        },
    )
    write_yaml(
        field_map_dir / "f1040_field_map.yaml",
        {
            "schema_version": "0.1",
            "form_id": "f1040",
            "fields": {"full_name": {"path": "taxpayer.primary.full_name"}},
        },
    )

    run_script(TAX_SCRIPTS / "validate_tax_data.py", str(tmp_path))

    report = read_yaml(tax_forms / "workpapers" / "validation_report.yaml")
    assert report["status"] == "passed"
    assert report["error_count"] == 0


def test_validate_tax_data_accepts_state_forms_plan(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "ca"
    field_map_dir = tax_forms / "workpapers" / "field_maps" / "ca"
    create_fillable_pdf_with_fields(blank_dir / "2025-540.pdf", ["line_12"])
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {
                    "line1": "1 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94105",
                },
                "filing_status": "single",
            },
            "income": {"wages": [{"wages_box_1": "100.00"}]},
        },
    )
    write_yaml(
        tax_forms / "required_state_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "states": [{"state": "CA"}],
            "forms": [
                {
                    "form_id": "ca540",
                    "jurisdiction": "CA",
                    "title": "California Form 540",
                    "status": "required",
                    "pdf": "2025-540.pdf",
                    "output_dir": "tax_forms/state/ca",
                    "blank_dir": "tax_forms/workpapers/blank_forms/ca",
                    "field_map_dir": "tax_forms/workpapers/field_maps/ca",
                }
            ],
        },
    )
    write_yaml(
        field_map_dir / "ca540_field_map.yaml",
        {
            "schema_version": "0.1",
            "form_id": "ca540",
            "fields": {"line_12": {"path": "calculated.form_line_values.ca540.line_12_state_wages"}},
        },
    )

    run_script(
        TAX_SCRIPTS / "validate_tax_data.py",
        str(tmp_path),
        "--forms-plan",
        str(tax_forms / "required_state_forms.yaml"),
        "--blank-dir",
        str(blank_dir),
        "--field-map-dir",
        str(field_map_dir),
    )

    report = read_yaml(tax_forms / "workpapers" / "validation_report.yaml")
    assert report["status"] == "passed"
    assert report["error_count"] == 0


def test_validate_tax_data_warns_for_incomplete_rental_property(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {
                    "line1": "1 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94105",
                },
                "filing_status": "single",
            },
            "income": {
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "property_id": "rental_001",
                        "gross_rents": "12000.00",
                    }
                ]
            },
        },
    )

    run_script(TAX_SCRIPTS / "validate_tax_data.py", str(tmp_path))

    report = read_yaml(tax_forms / "workpapers" / "validation_report.yaml")
    assert report["status"] == "passed"
    codes = [issue["code"] for issue in report["issues"]]
    assert "incomplete_rental_property" in codes
    assert "rental_missing_source_refs" in codes


def test_validate_tax_data_warns_for_incomplete_rental_depreciation(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "income": {
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "property_address": "1 Rental St",
                        "gross_rents": "12000.00",
                        "fair_rental_days": "365",
                        "personal_use_days": "0",
                        "expenses": {"repairs": "100.00"},
                        "depreciation": {"current_depreciation": "unknown"},
                    }
                ]
            },
        },
    )

    run([sys.executable, "-B", str(TAX_SCRIPTS / "validate_tax_data.py"), str(tmp_path)], check=False)

    report = read_yaml(tax_forms / "workpapers" / "validation_report.yaml")
    codes = [issue["code"] for issue in report["issues"]]
    assert "incomplete_rental_depreciation" in codes


def test_validate_tax_data_warns_for_incomplete_itemized_deductions(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {
                    "line1": "1 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94105",
                },
                "filing_status": "single",
            },
            "deductions": {
                "standard_or_itemized": "itemized",
                "itemized_deduction_total": "unknown",
                "itemized": {
                    "medical": [],
                    "taxes_paid": [],
                    "interest_paid": [],
                    "gifts_to_charity": [],
                    "casualty_theft": [],
                    "other": [],
                },
            },
        },
    )

    run_script(TAX_SCRIPTS / "validate_tax_data.py", str(tmp_path))

    report = read_yaml(tax_forms / "workpapers" / "validation_report.yaml")
    assert report["status"] == "passed"
    codes = [issue["code"] for issue in report["issues"]]
    assert "incomplete_itemized_deductions" in codes


def test_calculate_schedule_a_common_lines_and_selects_itemized(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "return_scope": {"federal": True, "states": [{"state": "CA"}]},
            "taxpayer": {"filing_status": "married_filing_jointly"},
            "calculated": {
                "form_line_values": {"f1040": {"line_11_adjusted_gross_income": "600000.00"}},
                "review_items": [],
            },
            "deductions": {
                "standard_or_itemized": "unsure",
                "itemized": {
                    "medical": [{"amount": "50000.00", "reimbursed_amount": "0.00"}],
                    "taxes_paid": [
                        {"type": "state_income_tax_estimated_payment", "amount": "45000.00"},
                        {"type": "real_estate_tax", "amount": "20000.00"},
                        {"type": "personal_property_tax", "amount": "1000.00"},
                    ],
                    "interest_paid": [{"type": "home_mortgage_interest", "amount": "30000.00", "form_1098": True}],
                    "gifts_to_charity": [
                        {"type": "cash", "amount": "5000.00"},
                        {"type": "noncash", "amount": "1000.00"},
                    ],
                    "casualty_theft": [{"form_4684_line_18": "2000.00"}],
                    "other": [{"type": "gambling_losses", "amount": "1000.00", "gambling_winnings": "400.00"}],
                },
            },
            "state_adjustments": {"ca": {}},
        },
    )

    run_script(TAX_SCRIPTS / "calculate_schedule_a.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    schedule_a = data["calculated"]["form_line_values"]["f1040sa"]
    assert schedule_a["line_1_medical_and_dental_expenses"] == "50000.00"
    assert schedule_a["line_3_medical_threshold_7_5_percent"] == "45000.00"
    assert schedule_a["line_4_medical_deduction"] == "5000.00"
    assert schedule_a["line_5d_total_taxes_before_limit"] == "66000.00"
    assert schedule_a["line_5e_state_and_local_tax_deduction"] == "10000.00"
    assert schedule_a["line_10_total_interest"] == "30000.00"
    assert schedule_a["line_14_total_gifts_to_charity"] == "6000.00"
    assert schedule_a["line_15_casualty_and_theft_loss"] == "2000.00"
    assert schedule_a["line_16_other_itemized_deductions"] == "400.00"
    assert schedule_a["line_17_total_itemized_deductions"] == "53400.00"
    assert data["deductions"]["standard_or_itemized"] == "itemized"
    assert data["deductions"]["standard_deduction"] == "31500.00"
    assert data["deductions"]["selected_deduction_amount"] == "53400.00"
    assert data["calculated"]["form_line_values"]["f1040"]["line_12_standard_or_itemized_deduction"] == "53400.00"
    assert data["state_adjustments"]["ca"]["itemized_deduction_total"] == "53400.00"
    assert data["calculated"]["form_line_values"]["ca540"]["line_18_standard_or_itemized_deduction"] == "53400.00"
    assert (tax_forms / "workpapers" / "schedule_a_report.yaml").exists()


def test_calculate_schedule_e_part_i_and_federal_passthrough(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {"line1": "1 Main St", "city": "San Francisco", "state": "CA", "zip": "94105"},
                "filing_status": "single",
            },
            "income": {
                "wages": [{"wages_box_1": "50000.00", "federal_income_tax_withheld_box_2": "5000.00"}],
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "property_address": {
                            "line1": "1 Rental St",
                            "city": "Sacramento",
                            "state": "CA",
                            "zip": "95814",
                        },
                        "property_type": "single family residence",
                        "fair_rental_days": "365",
                        "personal_use_days": "0",
                        "gross_rents": "30000.00",
                        "expenses": {
                            "advertising": "100.00",
                            "cleaning_and_maintenance": "1200.00",
                            "insurance": "900.00",
                            "management_fees": "1800.00",
                            "mortgage_interest": "8000.00",
                            "repairs": "1500.00",
                            "real_estate_taxes": "3600.00",
                            "utilities": "600.00",
                            "hoa_dues": "1200.00",
                        },
                        "depreciation": {"current_depreciation": "5000.00"},
                        "source_refs": [{"document_id": "rental_intake_001", "label": "Rental intake"}],
                    }
                ],
            },
            "deductions": {"standard_deduction": "15000.00"},
        },
    )

    run_script(TAX_SCRIPTS / "calculate_schedule_e.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    part_i = data["calculated"]["form_line_values"]["f1040se"]["part_i"]
    property_a = part_i["properties"]["a"]
    assert property_a["line_1b_type_of_property"] == "1"
    assert property_a["line_20_total_expenses"] == "23900.00"
    assert property_a["line_21_income_or_loss"] == "6100.00"
    assert part_i["line_23a_total_rents"] == "30000.00"
    assert part_i["line_23e_total_expenses"] == "23900.00"
    assert part_i["line_26_total_rental_real_estate_and_royalty_income_or_loss"] == "6100.00"
    assert data["calculated"]["form_line_values"]["f1040s1"]["line_5_rental_royalty_partnerships_estates_trusts"] == "6100.00"

    run_script(TAX_SCRIPTS / "calculate_tax_lines.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    assert data["calculated"]["form_line_values"]["f1040se"]["part_i"]["properties"]["a"]["line_20_total_expenses"] == "23900.00"
    assert data["calculated"]["form_line_values"]["f1040s1"]["line_5_rental_royalty_partnerships_estates_trusts"] == "6100.00"
    assert data["calculated"]["totals"]["rental_royalty_partnership_income_or_loss"] == "6100.00"


def test_calculate_rental_depreciation_updates_schedule_e_and_ca_adjustment(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "income": {
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "property_id": "rental_001",
                        "property_type": "single family residence",
                        "property_address": "1 Rental St",
                        "placed_in_service_date": "2020-06-01",
                        "gross_rents": "24000.00",
                        "fair_rental_days": "365",
                        "personal_use_days": "0",
                        "expenses": {"repairs": "500.00"},
                        "depreciation": {
                            "original_purchase_price": "375000.00",
                            "land_value": "100000.00",
                            "building_basis": "275000.00",
                            "ca_building_basis": "330000.00",
                        },
                    }
                ]
            },
        },
    )

    run_script(TAX_SCRIPTS / "calculate_rental_depreciation.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    dep = data["income"]["rentals_royalties_partnerships"][0]["depreciation"]
    assert dep["federal_method"] == "straight_line"
    assert dep["federal_convention"] == "mid_month"
    assert dep["federal_current_depreciation"] == "10000.00"
    assert dep["current_depreciation"] == "10000.00"
    assert dep["ca_current_depreciation"] == "12000.00"
    assert data["state_adjustments"]["ca"]["rental_depreciation_adjustment_total"] == "-2000.00"
    assert data["state_adjustments"]["ca"]["rental_depreciation_subtraction"] == "2000.00"
    assert (tax_forms / "workpapers" / "rental_depreciation_report.yaml").exists()

    run_script(TAX_SCRIPTS / "calculate_schedule_e.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    schedule_e_property = data["calculated"]["form_line_values"]["f1040se"]["part_i"]["properties"]["a"]
    assert schedule_e_property["line_18_depreciation_or_depletion"] == "10000.00"
    assert schedule_e_property["line_20_total_expenses"] == "10500.00"


def test_calculate_form_8582_limits_active_rental_loss_and_updates_schedule_e(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {"line1": "1 Main St", "city": "San Francisco", "state": "CA", "zip": "94105"},
                "filing_status": "single",
            },
            "income": {
                "wages": [{"wages_box_1": "120000.00", "federal_income_tax_withheld_box_2": "15000.00"}],
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "property_id": "rental_001",
                        "property_address": {
                            "line1": "1 Rental St",
                            "city": "Sacramento",
                            "state": "CA",
                            "zip": "95814",
                        },
                        "property_type": "single family residence",
                        "active_participation": True,
                        "fair_rental_days": "365",
                        "personal_use_days": "0",
                        "gross_rents": "0.00",
                        "expenses": {"repairs": "31000.00"},
                        "source_refs": [{"document_id": "rental_intake_001", "label": "Rental intake"}],
                    }
                ],
            },
            "deductions": {"standard_deduction": "15000.00"},
        },
    )

    run_script(TAX_SCRIPTS / "calculate_schedule_e.py", str(tmp_path))
    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    assert data["calculated"]["form_line_values"]["f1040se"]["part_i"]["properties"]["a"]["line_21_income_or_loss"] == "-31000.00"
    assert any(item["topic"] == "schedule_e_passive_loss_limitation" for item in data["calculated"]["review_items"])

    run_script(TAX_SCRIPTS / "calculate_form_8582.py", str(tmp_path))

    data = read_yaml(tax_forms / "extracted_tax_data.yaml")
    f8582 = data["calculated"]["form_line_values"]["f8582"]
    assert f8582["part_i"]["line_1b_active_rental_net_loss"] == "31000.00"
    assert f8582["part_i"]["line_1d_active_rental_combined"] == "-31000.00"
    assert f8582["part_ii"]["line_6_modified_adjusted_gross_income"] == "120000.00"
    assert f8582["part_ii"]["line_8_special_allowance_limit"] == "15000.00"
    assert f8582["part_ii"]["line_9_special_allowance"] == "15000.00"
    assert f8582["part_iii"]["line_11_total_losses_allowed"] == "15000.00"
    assert f8582["unallowed_losses_by_property_id"]["rental_001"] == "16000.00"
    assert data["income"]["rentals_royalties_partnerships"][0]["passive_activity"]["current_year_allowed_loss"] == "15000.00"
    assert data["income"]["rentals_royalties_partnerships"][0]["passive_activity"]["current_year_unallowed_loss"] == "16000.00"
    schedule_e = data["calculated"]["form_line_values"]["f1040se"]["part_i"]
    assert schedule_e["properties"]["a"]["line_22_deductible_rental_real_estate_loss_after_limitation"] == "-15000.00"
    assert schedule_e["line_25_losses"] == "-15000.00"
    assert schedule_e["line_26_total_rental_real_estate_and_royalty_income_or_loss"] == "-15000.00"
    assert data["calculated"]["form_line_values"]["f1040s1"]["line_5_rental_royalty_partnerships_estates_trusts"] == "-15000.00"
    assert not any(item["topic"] == "schedule_e_passive_loss_limitation" for item in data["calculated"]["review_items"])


def test_infer_required_irs_forms_adds_form_8582_for_rental_loss(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "income": {
                "rentals_royalties_partnerships": [
                    {
                        "activity_type": "rental",
                        "income_loss": "-12000.00",
                        "depreciation": {"building_basis": "275000.00", "land_value": "100000.00"},
                        "passive_activity": {"prior_year_unallowed_loss": "1000.00"},
                    }
                ]
            },
        },
    )
    write_yaml(tax_forms / "source_manifest.yaml", {"documents": []})

    run_script(TAX_SCRIPTS / "infer_required_irs_forms.py", str(tmp_path))

    plan = read_yaml(tax_forms / "required_irs_forms.yaml")
    forms = {form["form_id"]: form for form in plan["forms"]}
    assert forms["f8582"]["pdf"] == "f8582.pdf"
    assert forms["f8582"]["status"] == "review"
    assert forms["f4562"]["status"] == "review"


def test_generate_schedule_e_field_map_and_fill_pdf(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "irs"
    target_fields = [
        "topmostSubform[0].Page1[0].Table_Line1a[0].RowA[0].f1_3[0]",
        "topmostSubform[0].Page1[0].Table_Income[0].Line3[0].f1_16[0]",
        "topmostSubform[0].Page1[0].Table_Expenses[0].Line20[0].f1_68[0]",
        "topmostSubform[0].Page1[0].f1_84[0]",
    ]
    create_fillable_pdf_with_fields(blank_dir / "f1040se.pdf", target_fields)
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {"primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"}},
            "calculated": {
                "form_line_values": {
                    "f1040se": {
                        "part_i": {
                            "properties": {
                                "a": {
                                    "line_1a_physical_address": "1 Rental St, Sacramento, CA 95814",
                                    "line_3_rents_received": "30000.00",
                                    "line_20_total_expenses": "23400.00",
                                }
                            },
                            "line_26_total_rental_real_estate_and_royalty_income_or_loss": "6600.00",
                        }
                    }
                }
            },
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f1040se",
                    "title": "Schedule E",
                    "status": "required",
                    "pdf": "f1040se.pdf",
                    "output_dir": "tax_forms/federal",
                }
            ],
        },
    )

    run_script(TAX_SCRIPTS / "generate_schedule_e_field_map.py", str(tmp_path), "--tax-year", "2025")
    field_map = read_yaml(tax_forms / "workpapers" / "field_maps" / "f1040se_field_map.yaml")
    assert field_map["fields"]["topmostSubform[0].Page1[0].f1_84[0]"]["path"] == (
        "calculated.form_line_values.f1040se.part_i.line_26_total_rental_real_estate_and_royalty_income_or_loss"
    )

    run_script(TAX_SCRIPTS / "regenerate_tax_pdfs.py", str(tmp_path), "--overwrite", "--allow-unmapped-fields")

    output_pdf = tax_forms / "federal" / "2025_f1040se_draft.pdf"
    fields = PdfReader(str(output_pdf)).get_fields() or {}
    assert fields[target_fields[0]]["/V"] == "1 Rental St, Sacramento, CA 95814"
    assert fields[target_fields[1]]["/V"] == "30000"
    assert fields[target_fields[2]]["/V"] == "23400"
    assert fields[target_fields[3]]["/V"] == "6600"


def test_generate_schedule_a_field_map_and_fill_pdf(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "irs"
    target_fields = [
        "form1[0].Page1[0].f1_3[0]",
        "form1[0].Page1[0].f1_11[0]",
        "form1[0].Page1[0].f1_20[0]",
        "form1[0].Page1[0].f1_26[0]",
        "form1[0].Page1[0].f1_30[0]",
    ]
    create_fillable_pdf_with_fields(blank_dir / "f1040sa.pdf", target_fields)
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {"primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"}},
            "calculated": {
                "form_line_values": {
                    "f1040sa": {
                        "line_1_medical_and_dental_expenses": "50000.00",
                        "line_5e_state_and_local_tax_deduction": "10000.00",
                        "line_8e_total_home_mortgage_interest": "30000.00",
                        "line_14_total_gifts_to_charity": "6000.00",
                        "line_17_total_itemized_deductions": "53400.00",
                    }
                }
            },
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f1040sa",
                    "title": "Schedule A",
                    "status": "required",
                    "pdf": "f1040sa.pdf",
                    "output_dir": "tax_forms/federal",
                }
            ],
        },
    )

    run_script(TAX_SCRIPTS / "generate_schedule_a_field_map.py", str(tmp_path), "--tax-year", "2025")
    field_map = read_yaml(tax_forms / "workpapers" / "field_maps" / "f1040sa_field_map.yaml")
    assert field_map["fields"]["form1[0].Page1[0].f1_30[0]"]["path"] == (
        "calculated.form_line_values.f1040sa.line_17_total_itemized_deductions"
    )

    run_script(TAX_SCRIPTS / "regenerate_tax_pdfs.py", str(tmp_path), "--overwrite", "--allow-unmapped-fields")

    output_pdf = tax_forms / "federal" / "2025_f1040sa_draft.pdf"
    fields = PdfReader(str(output_pdf)).get_fields() or {}
    assert fields[target_fields[0]]["/V"] == "50000"
    assert fields[target_fields[1]]["/V"] == "10000"
    assert fields[target_fields[2]]["/V"] == "30000"
    assert fields[target_fields[3]]["/V"] == "6000"
    assert fields[target_fields[4]]["/V"] == "53400"


def test_generate_form_8582_field_map_and_fill_pdf(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "irs"
    target_fields = [
        "topmostSubform[0].Page1[0].f1_04[0]",
        "topmostSubform[0].Page1[0].f1_14[0]",
        "topmostSubform[0].Page1[0].f1_17[0]",
        "topmostSubform[0].Page1[0].Table_Part4[0].Row1[0].f1_20[0]",
        "topmostSubform[0].Page2[0].Table_PartVIII[0].Row1[0].f2_102[0]",
    ]
    create_fillable_pdf_with_fields(blank_dir / "f8582.pdf", target_fields)
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {"primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"}},
            "calculated": {
                "form_line_values": {
                    "f8582": {
                        "part_i": {"line_1b_active_rental_net_loss": "31000.00"},
                        "part_ii": {
                            "line_6_modified_adjusted_gross_income": "120000.00",
                            "line_9_special_allowance": "15000.00",
                        },
                        "part_iv": {
                            "activities": [{"name": "rental_001", "net_loss": "31000.00"}],
                            "totals": {},
                        },
                        "part_viii": {
                            "activities": [{"allowed_loss": "15000.00"}],
                        },
                    }
                }
            },
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f8582",
                    "title": "Form 8582",
                    "status": "required",
                    "pdf": "f8582.pdf",
                    "output_dir": "tax_forms/federal",
                }
            ],
        },
    )

    run_script(TAX_SCRIPTS / "generate_form_8582_field_map.py", str(tmp_path), "--tax-year", "2025")
    field_map = read_yaml(tax_forms / "workpapers" / "field_maps" / "f8582_field_map.yaml")
    assert field_map["fields"]["topmostSubform[0].Page1[0].f1_17[0]"]["path"] == (
        "calculated.form_line_values.f8582.part_ii.line_9_special_allowance"
    )

    run_script(TAX_SCRIPTS / "regenerate_tax_pdfs.py", str(tmp_path), "--overwrite", "--allow-unmapped-fields")

    output_pdf = tax_forms / "federal" / "2025_f8582_draft.pdf"
    fields = PdfReader(str(output_pdf)).get_fields() or {}
    assert fields[target_fields[0]]["/V"] == "31000"
    assert fields[target_fields[1]]["/V"] == "120000"
    assert fields[target_fields[2]]["/V"] == "15000"
    assert fields[target_fields[3]]["/V"] == "rental_001"
    assert fields[target_fields[4]]["/V"] == "15000"


def test_inspect_pdf_fields_generates_skeleton_field_map(tmp_path: Path):
    pdf_path = tmp_path / "f1040.pdf"
    output_path = tmp_path / "f1040_field_map.yaml"
    create_fillable_pdf(pdf_path)

    run_script(
        TAX_SCRIPTS / "inspect_pdf_fields.py",
        str(pdf_path),
        "--form-id",
        "f1040",
        "--tax-year",
        "2025",
        "--output",
        str(output_path),
    )

    field_map = read_yaml(output_path)
    assert field_map["form_id"] == "f1040"
    assert field_map["pdf"] == "f1040.pdf"
    assert "full_name" in field_map["fields"]
    assert field_map["fields"]["single_box"]["type"] == "checkbox"
    assert "semantic_path_suggestions" in field_map
    assert field_map["semantic_path_suggestions"]["line_1a"]["path"] == "calculated.form_line_values.f1040.line_1a"


def test_inspect_pdf_fields_uses_ca_semantic_library(tmp_path: Path):
    pdf_path = tmp_path / "2025-540.pdf"
    output_path = tmp_path / "ca540_field_map.yaml"
    create_fillable_pdf_with_fields(pdf_path, ["line_12"])

    run_script(
        TAX_SCRIPTS / "inspect_pdf_fields.py",
        str(pdf_path),
        "--form-id",
        "ca540",
        "--tax-year",
        "2025",
        "--output",
        str(output_path),
    )

    field_map = read_yaml(output_path)
    assert field_map["form_id"] == "ca540"
    assert field_map["pdf"] == "2025-540.pdf"
    assert field_map["semantic_path_suggestions"]["line_12"]["path"] == "calculated.form_line_values.ca540.line_12_state_wages"


def test_federal_form_coverage_catalog_lists_common_forms():
    catalog = read_yaml(TAX_SKILL / "references" / "federal_form_coverage.yaml")
    forms = catalog["forms"]
    assert forms["f1040"]["pdf"] == "f1040.pdf"
    assert forms["f1040sa"]["calculation_coverage"] == "common_itemized_lines_with_review_items"
    assert forms["f1040sa"]["field_map_coverage"] == "default_current_irs_schedule_a_map_or_manual_review"
    assert forms["f1040sd"]["calculation_coverage"] == "short_long_total_partial"
    assert forms["f1040se"]["calculation_coverage"] == "schedule_e_part_i_rental_royalty_lines_with_passive_loss_review"
    assert forms["f8582"]["calculation_coverage"] == "direct_rental_real_estate_active_participation_special_allowance"
    assert forms["f4562"]["calculation_coverage"] == "common_residential_rental_building_prepass_only"
    assert forms["f8949"]["inference"] == "capital_asset_transaction_reporting"


def test_ca_form_coverage_catalog_lists_resident_forms():
    catalog = read_yaml(TAX_SKILL / "references" / "ca_form_coverage.yaml")
    forms = catalog["forms"]
    assert forms["ca540"]["pdf_pattern"] == "{tax_year}-540.pdf"
    assert forms["ca540ca"]["calculation_coverage"] == "federal_amounts_and_explicit_adjustment_totals"
    assert forms["ca540d"]["inference"] == "california_capital_gain_loss_difference_review"


def test_semantic_field_library_lists_common_yaml_targets():
    library = read_yaml(
        TAX_SKILL / "assets" / "field_maps" / "federal" / "semantic_field_library.yaml"
    )
    suggestions = library["forms"]["f1040"]["targets"]
    assert suggestions["taxpayer_primary_name"]["path"] == "taxpayer.primary.full_name"
    assert suggestions["line_33"]["path"] == "calculated.form_line_values.f1040.line_33_total_payments"
    schedule_a = library["forms"]["f1040sa"]["targets"]
    assert schedule_a["line_17"]["path"] == "calculated.form_line_values.f1040sa.line_17_total_itemized_deductions"
    schedule_e = library["forms"]["f1040se"]["targets"]
    assert schedule_e["property_a_rents"]["path"] == "calculated.form_line_values.f1040se.part_i.properties.a.line_3_rents_received"
    assert schedule_e["line_26"]["path"] == "calculated.form_line_values.f1040se.part_i.line_26_total_rental_real_estate_and_royalty_income_or_loss"
    form_8582 = library["forms"]["f8582"]["targets"]
    assert form_8582["line_9"]["path"] == "calculated.form_line_values.f8582.part_ii.line_9_special_allowance"
    assert form_8582["part_viii_activity_1_allowed_loss"]["path"] == "calculated.form_line_values.f8582.part_viii.activities[0].allowed_loss"


def test_ca_semantic_field_library_lists_common_yaml_targets():
    library = read_yaml(
        TAX_SKILL / "assets" / "field_maps" / "ca" / "semantic_field_library.yaml"
    )
    suggestions = library["forms"]["ca540"]["targets"]
    assert suggestions["line_12"]["path"] == "calculated.form_line_values.ca540.line_12_state_wages"
    assert suggestions["line_71"]["path"] == "calculated.form_line_values.ca540.line_71_ca_income_tax_withheld"


def test_tax_data_schema_documents_rental_property_shape():
    schema = (TAX_SKILL / "references" / "tax_data_schema.md").read_text(encoding="utf-8")
    assert "## Rental Property Example" in schema
    assert "income.rentals_royalties_partnerships" in schema
    assert "property_address" in schema
    assert "passive_activity" in schema
    assert "calculated.form_line_values.f8582" in schema
    assert "current_year_unallowed_loss" in schema
    assert "prior_year_unallowed_loss_source" in schema


def test_tax_data_schema_documents_itemized_deduction_shape():
    schema = (TAX_SKILL / "references" / "tax_data_schema.md").read_text(encoding="utf-8")
    assert "## Itemized Deduction Example" in schema
    assert "itemized/itemized_intake.md" in schema
    assert "standard_or_itemized" in schema
    assert "itemized_deduction_total" in schema


def test_skill_documents_prior_year_passive_loss_extraction():
    skill = (TAX_SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = (TAX_SKILL / "references" / "intake_extraction.md").read_text(encoding="utf-8")
    assert "## Prior-Year Passive Loss Extraction" in skill
    assert "prior_year_unallowed_loss" in skill
    assert "Prior-Year Rental Passive Loss Carryovers" in reference
    assert "do not allocate by assumption" in reference


def test_generate_summary_template_updates_summary_md_with_missing_fields(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    (tmp_path / "summary.md").write_text("# Existing Summary\n\nKeep this.\n", encoding="utf-8")
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "unknown"},
                "address": {"line1": "1 Main St", "city": "unknown", "state": "CA", "zip": "94105"},
                "filing_status": "unknown",
            },
            "open_questions": ["Confirm estimated payments."],
            "calculated": {
                "review_items": [
                    {
                        "severity": "review",
                        "topic": "line_16_tax",
                        "message": "Tax table review required.",
                    }
                ]
            },
        },
    )
    write_yaml(
        tax_forms / "workpapers" / "validation_report.yaml",
        {
            "issues": [
                {
                    "severity": "error",
                    "code": "missing_required_fact",
                    "path": "taxpayer.primary.ssn",
                    "message": "Required taxpayer fact is missing.",
                }
            ]
        },
    )

    run_script(TAX_SCRIPTS / "generate_summary_template.py", str(tmp_path))

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Keep this." in summary
    assert "taxpayer.primary.ssn:" in summary
    assert "taxpayer.filing_status:" in summary
    assert "Confirm estimated payments.:" in summary
    manifest = read_yaml(tax_forms / "workpapers" / "summary_missing_fields_manifest.yaml")
    assert "taxpayer.primary.ssn" in manifest["missing_required_facts"]


@pytest.mark.parametrize(
    "script",
    [
        TAX_SCRIPTS / "regenerate_tax_pdfs.py",
        REGEN_SKILL / "scripts" / "regenerate_tax_pdfs.py",
    ],
)
def test_regenerate_tax_pdfs_fills_fields_from_yaml(tmp_path: Path, script: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "irs"
    field_map_dir = tax_forms / "workpapers" / "field_maps"
    create_fillable_pdf(blank_dir / "f1040.pdf")
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "taxpayer": {
                "primary": {"full_name": "Ada Lovelace", "ssn": "123-45-6789"},
                "address": {
                    "line1": "1 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94105",
                },
            },
            "income": {"wages": [{"wages_box_1": "1234.56"}, {"wages_box_1": "10.44"}]},
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "forms": [
                {
                    "form_id": "f1040",
                    "title": "Form 1040",
                    "status": "required",
                    "pdf": "f1040.pdf",
                    "output_dir": "tax_forms/federal",
                }
            ],
        },
    )
    write_yaml(
        field_map_dir / "f1040_field_map.yaml",
        {
            "schema_version": "0.1",
            "form_id": "f1040",
            "pdf": "f1040.pdf",
            "output_pdf": "2025_f1040_draft.pdf",
            "fields": {
                "full_name": {"path": "taxpayer.primary.full_name", "required": True},
                "address": {
                    "template": "{taxpayer.address.line1}, {taxpayer.address.city}, {taxpayer.address.state} {taxpayer.address.zip}"
                },
                "ssn_last4": {"path": "taxpayer.primary.ssn", "format": "ssn_last4"},
                "line_1a": {"sum": ["income.wages[].wages_box_1"], "format": "money_whole_dollars"},
                "single_box": {"value": True, "type": "checkbox", "checked_value": "/Yes"},
            },
        },
    )

    run_script(script, str(tmp_path), "--overwrite")

    output_pdf = tax_forms / "federal" / "2025_f1040_draft.pdf"
    fields = PdfReader(str(output_pdf)).get_fields() or {}
    assert fields["full_name"]["/V"] == "Ada Lovelace"
    assert fields["address"]["/V"] == "1 Main St, San Francisco, CA 94105"
    assert fields["ssn_last4"]["/V"] == "6789"
    assert fields["line_1a"]["/V"] == "1245"
    assert fields["single_box"]["/V"] == "/Yes"

    manifest = read_yaml(tax_forms / "workpapers" / "filled_pdf_manifest.yaml")
    assert manifest["workflow"] == "regenerate-tax-pdfs"
    assert manifest["results"][0]["status"] == "filled"


def test_regenerate_tax_pdfs_fills_state_plan_with_per_form_dirs(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    blank_dir = tax_forms / "workpapers" / "blank_forms" / "ca"
    field_map_dir = tax_forms / "workpapers" / "field_maps" / "ca"
    create_fillable_pdf_with_fields(blank_dir / "2025-540.pdf", ["line_12", "line_71"])
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "calculated": {
                "form_line_values": {
                    "ca540": {
                        "line_12_state_wages": "50000.00",
                        "line_71_ca_income_tax_withheld": "2500.00",
                    }
                }
            },
        },
    )
    write_yaml(
        tax_forms / "required_state_forms.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "states": [{"state": "CA"}],
            "forms": [
                {
                    "form_id": "ca540",
                    "jurisdiction": "CA",
                    "title": "California Form 540",
                    "status": "required",
                    "pdf": "2025-540.pdf",
                    "output_dir": "tax_forms/state/ca",
                    "blank_dir": "tax_forms/workpapers/blank_forms/ca",
                    "field_map_dir": "tax_forms/workpapers/field_maps/ca",
                }
            ],
        },
    )
    write_yaml(
        field_map_dir / "ca540_field_map.yaml",
        {
            "schema_version": "0.1",
            "form_id": "ca540",
            "pdf": "2025-540.pdf",
            "output_pdf": "2025_ca540_draft.pdf",
            "fields": {
                "line_12": {
                    "path": "calculated.form_line_values.ca540.line_12_state_wages",
                    "format": "money_whole_dollars",
                },
                "line_71": {
                    "path": "calculated.form_line_values.ca540.line_71_ca_income_tax_withheld",
                    "format": "money_whole_dollars",
                },
            },
        },
    )

    run_script(
        TAX_SCRIPTS / "regenerate_tax_pdfs.py",
        str(tmp_path),
        "--forms-plan",
        str(tax_forms / "required_state_forms.yaml"),
        "--overwrite",
    )

    output_pdf = tax_forms / "state" / "ca" / "2025_ca540_draft.pdf"
    fields = PdfReader(str(output_pdf)).get_fields() or {}
    assert fields["line_12"]["/V"] == "50000"
    assert fields["line_71"]["/V"] == "2500"

    manifest = read_yaml(tax_forms / "workpapers" / "filled_pdf_manifest.yaml")
    assert manifest["results"][0]["blank_pdf"] == "tax_forms/workpapers/blank_forms/ca/2025-540.pdf"
    assert manifest["results"][0]["status"] == "filled"


def test_generate_review_report_summarizes_packet(tmp_path: Path):
    tax_forms = tmp_path / "tax_forms"
    write_yaml(
        tax_forms / "extracted_tax_data.yaml",
        {
            "schema_version": "0.1",
            "tax_year": "2025",
            "review_status": "calculated_needs_review",
            "income": {"wages": [{"wages_box_1": "100.00"}]},
            "calculated": {
                "totals": {"wages": "100.00"},
                "review_items": [
                    {
                        "severity": "review",
                        "topic": "line_16_tax",
                        "message": "Tax table review required.",
                    }
                ],
            },
            "open_questions": ["Confirm filing status."],
        },
    )
    write_yaml(
        tax_forms / "required_irs_forms.yaml",
        {
            "forms": [
                {
                    "form_id": "f1040",
                    "title": "Form 1040",
                    "status": "required",
                }
            ]
        },
    )
    write_yaml(
        tax_forms / "source_manifest.yaml",
        {"documents": [{"id": "doc_001", "document_type": "W-2"}]},
    )
    write_yaml(
        tax_forms / "workpapers" / "validation_report.yaml",
        {"issues": [{"severity": "warning", "code": "example", "message": "Example warning."}]},
    )
    write_yaml(
        tax_forms / "workpapers" / "filled_pdf_manifest.yaml",
        {"results": [{"form_id": "f1040", "status": "filled", "output_pdf": "tax_forms/federal/2025_f1040_draft.pdf"}]},
    )

    run_script(TAX_SCRIPTS / "generate_review_report.py", str(tmp_path))

    report = (tax_forms / "review_report.md").read_text(encoding="utf-8")
    assert "# Tax Return Review Report" in report
    assert "`f1040` Form 1040: `required`" in report
    assert "`line_16_tax`" in report
    assert "Confirm filing status." in report
