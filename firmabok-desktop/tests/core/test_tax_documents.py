"""Feature D: tax documents storage, key figures, user-parameter estimates."""
import json
from datetime import date
from decimal import Decimal

import pytest

from firmabok.core import taxdocs
from firmabok.core.models import TaxDocument, TaxParameters


@pytest.fixture()
def sample_file(tmp_path):
    p = tmp_path / "beslut.pdf"
    p.write_bytes(b"%PDF-1.4 fake content for tests")
    return p


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(TaxDocument).delete()
    db.commit()
    yield
    for d in db.query(TaxDocument).all():
        f = taxdocs.stored_path(d)
        if f.exists():
            f.unlink()
    db.query(TaxDocument).delete()
    db.commit()


def test_upload_stores_in_xdg_uploads(db, sample_file):
    doc = taxdocs.save_document(db, sample_file, "slutlig_skatt",
                                title="Beslut 2026", issued=date(2026, 6, 1),
                                period_text="2026")
    db.commit()
    assert doc.id is not None
    stored = taxdocs.stored_path(doc)
    assert stored.exists()
    assert stored.parent == taxdocs.taxdoc_dir()
    assert "taxdocs" in str(stored)
    assert doc.size_bytes > 0 and doc.original_name == "beslut.pdf"


def test_unknown_type_rejected(db, sample_file):
    with pytest.raises(ValueError):
        taxdocs.save_document(db, sample_file, "hemlig_typ")


def test_extracted_figures_manual_and_correctable(db, sample_file):
    doc = taxdocs.save_document(db, sample_file, "preliminar")
    taxdocs.set_extracted(db, doc, {"preliminary_paid": "24000.00"})
    db.commit()
    assert taxdocs.get_extracted(doc)["preliminary_paid"] == "24000.00"
    # correction overwrites; empty removes
    taxdocs.set_extracted(db, doc, {"preliminary_paid": "26500.50"})
    taxdocs.set_extracted(db, doc, {"free_text": "Korrigerat enligt brev"})
    db.commit()
    ex = taxdocs.get_extracted(doc)
    assert ex["preliminary_paid"] == "26500.50" and ex["free_text"] == "Korrigerat enligt brev"
    taxdocs.set_extracted(db, doc, {"free_text": ""})
    db.commit()
    assert "free_text" not in taxdocs.get_extracted(doc)


def test_estimate_uses_only_user_parameters(db):
    p = db.get(TaxParameters, 1)
    p.municipal_tax_pct = Decimal("30.00")
    p.church_pct = Decimal("1.00")
    p.burial_pct = Decimal("0.25")
    p.extra_deduction = Decimal("5000.00")
    db.commit()

    est = taxdocs.estimate_income_tax(db, Decimal("100000"), Decimal("20000"))
    assert est["combined_pct"] == Decimal("31.25")
    assert est["gross_tax"] == Decimal("31250.00")
    assert est["tax_after_deduction"] == Decimal("26250.00")
    assert est["to_pay_or_refund"] == Decimal("6250.00")   # pay
    # user changes their own rates → estimate follows (nothing hardcoded)
    p.municipal_tax_pct = Decimal("29.00")
    db.commit()
    est2 = taxdocs.estimate_income_tax(db, Decimal("100000"), Decimal("20000"))
    assert est2["to_pay_or_refund"] == Decimal("5250.00")
    # refund case
    est3 = taxdocs.estimate_income_tax(db, Decimal("100000"), Decimal("40000"))
    assert est3["to_pay_or_refund"] == Decimal("-14750.00")


def test_prepaid_sum_from_documents(db, sample_file, tmp_path):
    d1 = taxdocs.save_document(db, sample_file, "preliminar")
    taxdocs.set_extracted(db, d1, {"preliminary_paid": "10000"})
    f2 = tmp_path / "brev.pdf"
    f2.write_bytes(b"%PDF x")
    d2 = taxdocs.save_document(db, f2, "slutlig_skatt")
    taxdocs.set_extracted(db, d2, {"preliminary_paid": "2500.50", "final_tax": "99999"})
    db.commit()
    assert taxdocs.sum_prepaid_from_documents(db) == Decimal("12500.50")


def test_delete_removes_file_and_row(db, sample_file):
    doc = taxdocs.save_document(db, sample_file, "ovrigt")
    db.commit()
    path = taxdocs.stored_path(doc)
    taxdocs.delete_document(db, doc)
    db.commit()
    assert not path.exists()
    assert db.query(TaxDocument).count() == 0


def test_extracted_json_survives_roundtrip(db, sample_file):
    doc = taxdocs.save_document(db, sample_file, "momsdeklaration", period_text="2026-Q1")
    taxdocs.set_extracted(db, doc, {"vat_net": "-1234.56"})
    db.commit()
    fresh = db.get(TaxDocument, doc.id)
    assert json.loads(fresh.extracted)["vat_net"] == "-1234.56"
    assert fresh.period_text == "2026-Q1"
