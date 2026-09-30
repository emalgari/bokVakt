"""Skatteverket tax documents (feature D).

Files are stored in the existing XDG upload folder; metadata and user-entered
key figures live in the database. NOTHING here contains tax rates, brackets or
legal rules — every number used in estimates comes from ``TaxParameters``
(user-editable) or from figures the user enters for a document.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config as core_config
from .models import TaxDocument, TaxParameters
from .money import ZERO, q2

DOC_TYPES = ("slutlig_skatt", "preliminar", "momsdeklaration", "ovrigt")
MAX_SIZE = 25 * 1024 * 1024  # 25 MB, local files


def taxdoc_dir() -> Path:
    d = core_config.UPLOAD_DIR / "taxdocs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_document(db: Session, src_path: str | Path, doc_type: str,
                  title: str = "", issued: date | None = None,
                  period_text: str = "", notes: str = "") -> TaxDocument:
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type: {doc_type}")
    size = src.stat().st_size
    if size > MAX_SIZE:
        raise ValueError("file_too_large")
    stored = f"{uuid.uuid4().hex[:12]}{src.suffix.lower()}"
    shutil.copy2(src, taxdoc_dir() / stored)
    doc = TaxDocument(
        doc_type=doc_type, title=title or src.name,
        issued_date=issued, period_text=period_text, notes=notes,
        stored_name=stored, original_name=src.name[:250],
        content_type="", size_bytes=size, extracted="{}")
    db.add(doc)
    db.flush()
    return doc


def stored_path(doc: TaxDocument) -> Path:
    return taxdoc_dir() / doc.stored_name


def get_extracted(doc: TaxDocument) -> dict:
    try:
        data = json.loads(doc.extracted or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def set_extracted(db: Session, doc: TaxDocument, values: dict) -> None:
    merged = get_extracted(doc)
    for k, v in values.items():
        if v is None or v == "":
            merged.pop(k, None)
        else:
            merged[k] = str(v)
    doc.extracted = json.dumps(merged, ensure_ascii=False)
    db.flush()


def delete_document(db: Session, doc: TaxDocument) -> None:
    p = stored_path(doc)
    if p.exists():
        p.unlink()
    db.delete(doc)


def get_params(db: Session) -> TaxParameters:
    from .migrate import ensure_tax_parameters
    return ensure_tax_parameters(db)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    try:
        return q2(Decimal(str(value)))
    except Exception:
        return ZERO


def estimate_income_tax(db: Session, taxable_income: Decimal,
                        prepaid_tax: Decimal) -> dict:
    """Transparent estimate from USER-PROVIDED parameters only.

    tax = taxable × (municipal + church + burial)% − user deductions − prepaid.
    No brackets, no legal rules — the user owns every rate in Settings.
    """
    p = get_params(db)
    pct = _dec(p.municipal_tax_pct) + _dec(p.church_pct) + _dec(p.burial_pct)
    gross_tax = q2(_dec(taxable_income) * pct / Decimal("100"))
    after_deduction = q2(max(ZERO, gross_tax - _dec(p.extra_deduction)))
    to_pay = q2(after_deduction - _dec(prepaid_tax))
    return {
        "taxable_income": _dec(taxable_income),
        "combined_pct": q2(pct),
        "gross_tax": gross_tax,
        "deduction": _dec(p.extra_deduction),
        "tax_after_deduction": after_deduction,
        "prepaid_tax": _dec(prepaid_tax),
        "to_pay_or_refund": to_pay,   # >0 pay, <0 refund
    }


def sum_prepaid_from_documents(db: Session) -> Decimal:
    """Sum user-entered 'preliminary_paid' key figures over all documents."""
    total = ZERO
    for doc in db.execute(select(TaxDocument)).scalars():
        total = q2(total + _dec(get_extracted(doc).get("preliminary_paid")))
    return total
