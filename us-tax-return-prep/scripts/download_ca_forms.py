#!/usr/bin/env python3
"""Download blank California FTB PDF forms listed in required_state_forms.yaml."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


FTB_BASE = "https://www.ftb.ca.gov/forms"


def load_yaml(path: Path):
    if not path.exists():
        raise SystemExit(f"State forms plan not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return loaded


def dump_yaml(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def ftb_url(filename: str, tax_year: str | None) -> str:
    if not tax_year or not tax_year.isdigit():
        raise SystemExit("A numeric tax_year is required to build FTB form URLs.")
    return f"{FTB_BASE}/{tax_year}/{filename}"


def selected_forms(plan: dict, include_review: bool, requested_forms: set[str]) -> list[dict]:
    forms = []
    for form in plan.get("forms", []):
        if not isinstance(form, dict):
            continue
        form_id = str(form.get("form_id", ""))
        if requested_forms and form_id not in requested_forms:
            continue
        status = form.get("status")
        if status == "required" or (include_review and status == "review") or requested_forms:
            forms.append(form)
    return forms


def download_url(url: str, output_path: Path, overwrite: bool, require_pdf: bool) -> int:
    if output_path.exists() and not overwrite:
        return output_path.stat().st_size
    request = Request(url, headers={"User-Agent": "us-tax-return-prep/0.1"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
    if require_pdf and not body.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded content is not a PDF: {url}")
    output_path.write_bytes(body)
    return len(body)


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download blank California FTB forms from tax_forms/required_state_forms.yaml."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--plan", help="Path to required_state_forms.yaml.")
    parser.add_argument(
        "--output-dir",
        help="Directory for blank California PDFs. Defaults to tax_forms/workpapers/blank_forms/ca.",
    )
    parser.add_argument("--tax-year", help="Tax year for FTB URLs.")
    parser.add_argument("--include-review", action="store_true", help="Also download forms marked status: review.")
    parser.add_argument("--include-instructions", action="store_true", help="Also download instruction URLs listed in the plan.")
    parser.add_argument("--form", action="append", default=[], help="Only download a specific form_id. Repeatable.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing downloads.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned downloads without network access.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    plan_path = Path(args.plan).expanduser().resolve() if args.plan else tax_forms / "required_state_forms.yaml"
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else tax_forms / "workpapers" / "blank_forms" / "ca"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = load_yaml(plan_path)
    tax_year = args.tax_year or str(plan.get("tax_year", ""))
    downloads = []
    for form in selected_forms(plan, args.include_review, set(args.form)):
        pdf = form.get("pdf")
        if pdf:
            downloads.append((form, "form", str(pdf), form.get("url") or ftb_url(str(pdf), tax_year), True))
        if args.include_instructions and form.get("instruction_url"):
            url = str(form["instruction_url"])
            filename = Path(url.split("?", 1)[0]).name or f"{form.get('form_id')}_instructions.html"
            downloads.append((form, "instructions", filename, url, url.lower().endswith(".pdf")))

    results = []
    for form, kind, filename, url, require_pdf in downloads:
        output_path = output_dir / filename
        record = {
            "form_id": form.get("form_id"),
            "jurisdiction": form.get("jurisdiction", "CA"),
            "title": form.get("title"),
            "kind": kind,
            "status": form.get("status"),
            "url": url,
            "path": relative_to_root(output_path, root),
        }
        if args.dry_run:
            record["downloaded"] = False
            record["dry_run"] = True
            print(f"{filename}: {url}")
        else:
            try:
                size = download_url(url, output_path, args.overwrite, require_pdf=require_pdf)
            except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
                record["downloaded"] = False
                record["error"] = str(exc)
                print(f"FAILED {filename}: {exc}")
            else:
                record["downloaded"] = True
                record["size_bytes"] = size
                print(f"Downloaded {filename} -> {output_path}")
        results.append(record)

    manifest = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_plan": relative_to_root(plan_path, root),
        "downloads": results,
    }
    manifest_path = output_dir / "download_manifest.yaml"
    dump_yaml(manifest, manifest_path)
    print(f"Wrote {manifest_path}")

    failures = [result for result in results if not result.get("downloaded") and not args.dry_run]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
