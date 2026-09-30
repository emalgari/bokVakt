"""Invoice domain service: totals, gapless numbering, finalize, credit notes.

Rules enforced here
-------------------
* Line VAT is computed per line from the net amount (half-up to öre).
* Totals = sums of line values (so invoice is always internally consistent).
* Invoice numbers are sequential per fiscal-year series (e.g. 2026-0001),
  assigned only on finalize → no gaps, no reuse.
* Finalized invoices are immutable and can never be deleted; corrections
  are made with credit notes (kreditfaktura) that get their own number.
* OCR = invoice-number digits + LUHN check digit (Swedish bank practice).
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import vat as vatmod
from .errors import InvoiceError  # noqa: F401  (re-export for callers)
from .models import (
    CompanyProfile,
    IncomeEntry,
    Invoice,
    InvoiceLine,
    InvoiceSeries,
    InvoiceStatus,
    PaymentStatus,
)
from .money import ZERO, line_net, q2, sum_money, vat_amount
from .swedish import make_ocr

# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

def get_series(db: Session, year: int) -> InvoiceSeries:
    series = db.execute(select(InvoiceSeries).where(InvoiceSeries.series_year == year)).scalar_one_or_none()
    if series is None:
        profile = get_profile(db)
        series = InvoiceSeries(series_year=year, next_seq=max(1, profile.invoice_number_start))
        db.add(series)
        db.flush()
    return series


def format_number(profile: CompanyProfile, year: int, seq: int) -> str:
    digits = max(2, min(8, profile.invoice_number_digits or 4))
    return f"{profile.invoice_number_prefix}{year}-{seq:0{digits}d}"


def peek_next_number(db: Session, year: int) -> str:
    profile = get_profile(db)
    series = get_series(db, year)
    return format_number(profile, year, series.next_seq)


def consume_number(db: Session, year: int) -> str:
    """Atomically take the next number for `year` (call within a transaction
    that is guaranteed to commit — i.e. only during finalize)."""
    profile = get_profile(db)
    series = get_series(db, year)
    number = format_number(profile, year, series.next_seq)
    series.next_seq += 1
    db.flush()
    return number


# ---------------------------------------------------------------------------
# Profile helper
# ---------------------------------------------------------------------------

def get_profile(db: Session) -> CompanyProfile:
    profile = db.get(CompanyProfile, 1)
    if profile is None:
        profile = CompanyProfile(id=1)
        db.add(profile)
        db.flush()
    return profile


# ---------------------------------------------------------------------------
# Line & total calculation
# ---------------------------------------------------------------------------

def recalc_line(line: InvoiceLine) -> InvoiceLine:
    info = vatmod.get_code(line.vat_code)
    net = line_net(line.quantity or Decimal(1), line.unit_price or ZERO)
    if line.invoice and line.invoice.is_credit_note:
        net = -abs(net)
    if info.side == "sale" and not info.domestic_sale_vat:
        v = ZERO  # exempt / EU / reverse-charge sales: no Swedish VAT
    else:
        v = vat_amount(net, line.vat_rate or ZERO)
    line.line_net = q2(net)
    line.line_vat = q2(v)
    line.line_gross = q2(net + v)
    return line


def recalc_invoice(inv: Invoice, round_to_krona: bool = False) -> Invoice:
    from .money import round_kronor
    for i, line in enumerate(inv.lines):
        line.position = i
        recalc_line(line)
    inv.net_total = sum_money([ln.line_net for ln in inv.lines]) or ZERO
    inv.vat_total = sum_money([ln.line_vat for ln in inv.lines]) or ZERO
    inv.gross_total = q2(inv.net_total + inv.vat_total)
    if round_to_krona:
        inv.rounding_amount = q2(Decimal(round_kronor(inv.gross_total)) - inv.gross_total)
    else:
        inv.rounding_amount = ZERO
    return inv


def vat_breakdown(inv: Invoice) -> list[dict]:
    """Per-rate VAT breakdown for display on the invoice:
    [{rate, base, vat}] sorted descending."""
    groups: dict[Decimal, dict] = {}
    for ln in inv.lines:
        rate = q2(ln.vat_rate or 0)
        g = groups.setdefault(rate, {"rate": rate, "base": ZERO, "vat": ZERO, "code": ln.vat_code})
        g["base"] = q2(g["base"] + (ln.line_net or ZERO))
        g["vat"] = q2(g["vat"] + (ln.line_vat or ZERO))
    return [groups[r] for r in sorted(groups, reverse=True)]


def customer_snapshot(inv: Invoice) -> dict:
    c = inv.customer
    if c is None:
        try:
            return json.loads(inv.customer_snapshot or "{}")
        except json.JSONDecodeError:
            return {}
    return {
        "name": c.name,
        "customer_no": c.customer_no,
        "org_nr": c.org_nr,
        "vat_number": c.vat_number,
        "address_line1": c.address_line1,
        "address_line2": c.address_line2,
        "postal_code": c.postal_code,
        "city": c.city,
        "country": c.country,
        "reference": inv.customer_reference or c.reference,
        "email": c.email,
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def finalize_invoice(db: Session, inv: Invoice, username: str = "",
                     book_income: bool = True) -> Invoice:
    """Fastställ faktura: validates, assigns the next sequential number,
    sets due date/OCR, freezes the customer snapshot, and (optionally)
    books linked income entries so the VAT report sees the sale."""
    from .audit import log as audit_log

    if inv.status != InvoiceStatus.DRAFT.value:
        raise InvoiceError("inv.finalize.not_draft")
    if not inv.lines:
        raise InvoiceError("inv.finalize.no_lines")
    if inv.invoice_date is None:
        raise InvoiceError("inv.finalize.no_date")
    if inv.customer_id is None:
        raise InvoiceError("inv.finalize.no_customer")
    for ln in inv.lines:
        if not (ln.description or "").strip():
            raise InvoiceError("inv.finalize.line_no_desc")

    recalc_invoice(inv, round_to_krona=bool(get_profile(db).round_total_to_krona))
    profile = get_profile(db)

    from .swedish import fiscal_year_of
    year = fiscal_year_of(inv.invoice_date, profile.fiscal_year_start_month)

    inv.number = consume_number(db, year)
    inv.series_year = year
    inv.due_date = inv.invoice_date + timedelta(days=max(0, inv.payment_terms_days or 0))
    if inv.delivery_date is None:
        inv.delivery_date = inv.invoice_date
    inv.ocr = make_ocr(inv.number)
    inv.customer_snapshot = json.dumps(customer_snapshot(inv), ensure_ascii=False)
    inv.status = InvoiceStatus.FINALIZED.value
    inv.finalized_at = datetime.now(UTC)

    if book_income:
        book_invoice_income(db, inv)

    if inv.is_credit_note and inv.credit_note_for_id:
        original = db.get(Invoice, inv.credit_note_for_id)
        if original is not None:
            original.status = InvoiceStatus.CREDITED.value

    audit_log(db, username, "finalize", "Invoice", inv.id,
              summary=f"Faktura {inv.number} fastställd, {inv.gross_total} kr inkl moms")
    db.flush()
    return inv


def book_invoice_income(db: Session, inv: Invoice) -> list[IncomeEntry]:
    """Create (or refresh) income entries linked to a finalized invoice so
    income/VAT reports include it exactly once. One entry per line, same
    date as the invoice."""
    existing = [e for e in inv.income_entries]
    if existing:
        return existing
    entries = []
    cust_name = inv.customer.name if inv.customer else ""
    for ln in inv.lines:
        e = IncomeEntry(
            entry_date=inv.invoice_date,
            customer_id=inv.customer_id,
            customer_name=cust_name,
            description=(ln.description or "")[:500],
            vat_code=ln.vat_code,
            net_amount=q2(ln.line_net),
            vat_rate=q2(ln.vat_rate),
            vat_amount=q2(ln.line_vat),
            gross_amount=q2(ln.line_gross),
            payment_status=(PaymentStatus.PAID.value if inv.status == InvoiceStatus.PAID.value
                            else PaymentStatus.UNPAID.value),
            invoice_ref=inv.number or "",
            invoice_id=inv.id,
            notes="Auto-bokförd från faktura",
        )
        db.add(e)
        entries.append(e)
    db.flush()
    # refresh the relationship so callers see the new entries immediately
    db.refresh(inv, attribute_names=["income_entries"])
    return entries


def create_credit_note(db: Session, original: Invoice, username: str = "",
                       reason: str = "", full: bool = True) -> Invoice:
    """Kreditfaktura: a new invoice document with negated lines that
    references the original. The original is marked 'credited' when the
    credit note is finalized."""
    from .audit import log as audit_log

    if original.status not in (InvoiceStatus.FINALIZED.value, InvoiceStatus.SENT.value,
                               InvoiceStatus.PAID.value, InvoiceStatus.CREDITED.value):
        raise InvoiceError("inv.credit.not_finalized")
    if original.is_credit_note:
        raise InvoiceError("inv.credit.of_credit")

    credit = Invoice(
        is_credit_note=True,
        credit_note_for_id=original.id,
        status=InvoiceStatus.DRAFT.value,
        invoice_date=date.today(),
        payment_terms_days=original.payment_terms_days,
        customer_id=original.customer_id,
        customer_reference=original.customer_reference,
        our_reference=original.our_reference,
        notes=(reason or "Kreditfaktura till {n}").format(n=original.number or "") +
              ("\n\n" + (original.notes or "") if original.notes else ""),
        currency=original.currency,
    )
    db.add(credit)
    db.flush()
    for ln in original.lines:
        cl = InvoiceLine(
            invoice_id=credit.id,
            position=ln.position,
            article_no=ln.article_no,
            description=f"Kreditering: {ln.description}",
            quantity=-abs(ln.quantity or Decimal(1)) if full else ln.quantity,
            unit=ln.unit,
            unit_price=ln.unit_price,
            vat_code=ln.vat_code,
            vat_rate=ln.vat_rate,
        )
        db.add(cl)
    db.flush()
    recalc_invoice(credit, round_to_krona=bool(get_profile(db).round_total_to_krona))
    audit_log(db, username, "create", "Invoice", credit.id,
              summary=f"Utkast till kreditfaktura för {original.number}")
    return credit


def mark_paid(db: Session, inv: Invoice, amount: Decimal | None = None,
              payment_date: date | None = None) -> Invoice:
    paid = q2(amount if amount is not None else inv.amount_to_pay)
    inv.amount_paid = q2((inv.amount_paid or ZERO) + paid)
    if inv.amount_paid >= q2((inv.gross_total or ZERO) + (inv.rounding_amount or ZERO)):
        inv.status = InvoiceStatus.PAID.value
        for e in inv.income_entries:
            e.payment_status = PaymentStatus.PAID.value
            e.payment_date = payment_date or date.today()
    else:
        for e in inv.income_entries:
            e.payment_status = PaymentStatus.PARTIAL.value
    return inv


def delete_draft(db: Session, inv: Invoice) -> None:
    """Only drafts (unnumbered) may be deleted — guarantees gapless series."""
    if inv.status != InvoiceStatus.DRAFT.value or inv.number:
        raise InvoiceError("inv.delete.finalized")
    db.delete(inv)
