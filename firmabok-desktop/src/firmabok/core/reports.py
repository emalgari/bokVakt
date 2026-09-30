"""Bookkeeping reports: monthly/yearly summaries, P&L, expense categories,
and CSV exports for momsredovisning and the NE-bilaga (income declaration
support material).

Definitions (compliant mode — the default):
* Gross income (bruttoinkomst) = sales incl. VAT (kundens totalbelopp).
* Net income/revenue (nettoomsättning) = sales excl. VAT.
* Output VAT (utgående moms) = VAT on taxable sales.
* Input VAT (ingående moms) = deductible VAT on purchases.
* VAT payable/refund = output − input.  (NEVER VAT on profit!)
* Expense cost = gross − deductible VAT (non-deductible VAT is a cost).
* Profit (årets resultat före skatt) = net income − expense costs.
  Egna uttag/insättningar are NOT income/expenses and never affect profit.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import vat as vatmod
from .models import Expense, IncomeEntry, OwnerTransaction, OwnerTxType, VatReport
from .money import ZERO, q2
from .swedish import fiscal_year_bounds, period_of, periods_of_year

# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

@dataclass
class Totals:
    gross_income: Decimal = ZERO     # incl. VAT
    net_income: Decimal = ZERO       # excl. VAT
    output_vat: Decimal = ZERO
    expense_net: Decimal = ZERO      # expense bases (excl. VAT)
    expense_cost: Decimal = ZERO     # gross − deductible VAT  → P&L cost
    expense_vat_total: Decimal = ZERO
    input_vat: Decimal = ZERO        # deductible
    non_deductible_vat: Decimal = ZERO
    net_vat: Decimal = ZERO          # output − input
    profit: Decimal = ZERO           # net income − expense cost
    owner_withdrawals: Decimal = ZERO
    owner_contributions: Decimal = ZERO

    def as_dict(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items()}


def compute_totals(db: Session, start: date, end: date,
                   include_owner: bool = True, platform: str | None = None) -> Totals:
    """Platform filter (feature: gig income): None → all (legacy behaviour),
    "*" → platform income only, "" → direct customers only, name → that platform."""
    t = Totals()
    inc_q = (select(IncomeEntry)
             .where(IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end))
    if platform == "*":
        inc_q = inc_q.where(IncomeEntry.source_type == "platform")
    elif platform == "":
        inc_q = inc_q.where(IncomeEntry.source_type == "direct")
    elif platform:
        inc_q = inc_q.where(IncomeEntry.platform_name == platform)
    incomes = db.execute(inc_q).scalars().all()
    expenses = db.execute(
        select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
    ).scalars().all()

    for e in incomes:
        t.net_income += q2(e.net_amount or 0)
        t.gross_income += q2(e.gross_amount or 0)
        info = vatmod.get_code(e.vat_code)
        if info.domestic_sale_vat:
            t.output_vat += q2(e.vat_amount or 0)

    for x in expenses:
        gross = q2(x.gross_amount or 0)
        vat_amt = q2(x.vat_amount or 0)
        deductible = q2(x.deductible_vat if x.deductible_vat is not None else vat_amt)
        if deductible > vat_amt:
            deductible = vat_amt
        t.expense_net += q2(x.net_amount or 0)
        t.expense_vat_total += vat_amt
        t.input_vat += deductible
        t.non_deductible_vat += q2(vat_amt - deductible)
        t.expense_cost += q2(gross - deductible)

    t.net_vat = q2(t.output_vat - t.input_vat)
    t.profit = q2(t.net_income - t.expense_cost)

    if include_owner:
        owners = db.execute(
            select(OwnerTransaction).where(OwnerTransaction.tx_date >= start, OwnerTransaction.tx_date <= end)
        ).scalars().all()
        for o in owners:
            if o.tx_type == OwnerTxType.UTTAG.value:
                t.owner_withdrawals += q2(o.amount or 0)
            else:
                t.owner_contributions += q2(o.amount or 0)

    # quantize everything
    for k, v in list(t.__dict__.items()):
        setattr(t, k, q2(v))
    return t


def monthly_summary(db: Session, fiscal_year: int, fy_start_month: int = 1) -> list[dict]:
    """One row per fiscal month: totals + period label."""
    rows = []
    for p in periods_of_year("month", fiscal_year, fy_start_month):
        t = compute_totals(db, p.start, p.end, include_owner=True)
        rows.append({
            "period": p,
            "totals": t,
            "calendar_month": p.start.month,
        })
    return rows


def yearly_summary(db: Session, fiscal_year: int, fy_start_month: int = 1) -> Totals:
    start, end = fiscal_year_bounds(fiscal_year, fy_start_month)
    return compute_totals(db, start, end)


def weekly_summary(db: Session, year: int, month: int) -> list[dict]:
    """Income grouped by ISO week within a calendar month."""
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)
    from datetime import timedelta
    end = end - timedelta(days=1)
    incomes = db.execute(
        select(IncomeEntry).where(IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end)
        .order_by(IncomeEntry.entry_date)
    ).scalars().all()
    weeks: dict[tuple[int, int], dict] = {}
    for e in incomes:
        iso = e.entry_date.isocalendar()
        key = (iso[0], iso[1])
        w = weeks.setdefault(key, {"year": iso[0], "week": iso[1], "net": ZERO, "vat": ZERO,
                                   "gross": ZERO, "count": 0, "first": e.entry_date, "last": e.entry_date})
        w["net"] += q2(e.net_amount or 0)
        w["vat"] += q2(e.vat_amount or 0)
        w["gross"] += q2(e.gross_amount or 0)
        w["count"] += 1
        w["last"] = max(w["last"], e.entry_date)
    out = sorted(weeks.values(), key=lambda w: (w["year"], w["week"]))
    for w in out:
        for k in ("net", "vat", "gross"):
            w[k] = q2(w[k])
    return out


def expense_by_category(db: Session, start: date, end: date) -> list[dict]:
    expenses = db.execute(
        select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
    ).scalars().all()
    groups: dict[str, dict] = {}
    for x in expenses:
        name = x.category_name or "Övrigt"
        g = groups.setdefault(name, {"category": name, "cost": ZERO, "vat": ZERO,
                                     "deductible": ZERO, "gross": ZERO, "count": 0})
        deductible = q2(min(x.deductible_vat or 0, x.vat_amount or 0))
        g["cost"] += q2((x.gross_amount or 0) - deductible)
        g["gross"] += q2(x.gross_amount or 0)
        g["vat"] += q2(x.vat_amount or 0)
        g["deductible"] += deductible
        g["count"] += 1
    out = sorted(groups.values(), key=lambda g: g["cost"], reverse=True)
    for g in out:
        for k in ("cost", "vat", "deductible", "gross"):
            g[k] = q2(g[k])
    return out


def pl_report(db: Session, start: date, end: date) -> dict:
    """Profit & loss (resultaträkning) support material.
    Revenue split by VAT code; expenses by category; owner transactions
    listed separately (memo only — they never affect profit)."""
    incomes = db.execute(
        select(IncomeEntry).where(IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end)
    ).scalars().all()
    rev_by_code: dict[str, Decimal] = {}
    for e in incomes:
        label = vatmod.get_code(e.vat_code).label_sv
        rev_by_code[label] = q2(rev_by_code.get(label, ZERO) + (e.net_amount or 0))
    revenue_rows = [{"label": k, "amount": v} for k, v in
                    sorted(rev_by_code.items(), key=lambda kv: kv[1], reverse=True)]

    totals = compute_totals(db, start, end, include_owner=True)
    cats = expense_by_category(db, start, end)
    return {
        "start": start, "end": end,
        "revenue_rows": revenue_rows,
        "revenue_total": totals.net_income,
        "expense_rows": cats,
        "expense_total": totals.expense_cost,
        "profit": totals.profit,
        "owner_withdrawals": totals.owner_withdrawals,
        "owner_contributions": totals.owner_contributions,
        "output_vat": totals.output_vat,
        "input_vat": totals.input_vat,
        "net_vat": totals.net_vat,
    }


# ---------------------------------------------------------------------------
# VAT report persistence
# ---------------------------------------------------------------------------

def build_vat_report(db: Session, kind: str, fiscal_year: int, number: int,
                     fy_start_month: int = 1, vat_method: str = "faktura",
                     input_vat_on_payment: bool = False):
    import json
    p = period_of(kind, fiscal_year, number, fy_start_month)
    # Fetch a wider window than the period itself: under bokslutsmetoden an
    # entry booked earlier (e.g. December) but PAID inside the period (e.g.
    # January) belongs to this period. compute_declaration filters precisely
    # by effective date.
    from datetime import timedelta
    fetch_start = p.start - timedelta(days=400)
    incomes = db.execute(
        select(IncomeEntry).where(IncomeEntry.entry_date >= fetch_start, IncomeEntry.entry_date <= p.end)
    ).scalars().all()
    expenses = db.execute(
        select(Expense).where(Expense.expense_date >= fetch_start, Expense.expense_date <= p.end)
    ).scalars().all()
    decl = vatmod.compute_declaration(
        incomes, expenses, p.start, p.end,
        method=vat_method, fy_start_month=fy_start_month,
        input_vat_on_payment=input_vat_on_payment)

    report = db.execute(
        select(VatReport).where(
            VatReport.period_kind == kind,
            VatReport.fiscal_year == fiscal_year,
            VatReport.period_number == number,
        )
    ).scalar_one_or_none()
    if report is None:
        report = VatReport(period_kind=kind, fiscal_year=fiscal_year, period_number=number,
                           start_date=p.start, end_date=p.end)
        db.add(report)
    if report.locked:
        return report, decl, p  # locked reports keep their filed snapshot
    report.boxes = json.dumps({b: str(v) for b, v in decl.boxes.items()})
    report.output_vat = decl.output_vat
    report.input_vat = decl.input_vat
    report.net_vat = decl.net_vat
    report.generated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    db.flush()
    return report, decl, p


def boxes_kronor_from_report(report: VatReport) -> dict[str, int]:
    """Declaration-ready whole-kronor boxes for a stored report snapshot."""
    import json

    from .money import round_kronor
    boxes = {b: Decimal(v) for b, v in json.loads(report.boxes or "{}").items()}
    kronor = {b: round_kronor(boxes.get(b, ZERO)) for b in boxes}
    kronor["49"] = (
        sum(kronor.get(b, 0) for b in ("10", "11", "12", "30", "31", "32", "60", "61", "62"))
        - kronor.get("48", 0)
    )
    return kronor


# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------

def _csv(headers: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")  # semicolon: opens correctly in Swedish Excel/LibreOffice
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def export_journal_csv(db: Session, start: date, end: date, lang: str = "sv") -> str:
    """Bokföringsorder (journal) — all income, expenses and owner
    transactions in date order. Suitable support material for the
    NE-bilaga / simplified annual accounts (förenklat årsbokslut).
    Amounts: net (excl VAT), VAT, gross, deductible VAT."""
    rows: list[list] = []
    incomes = db.execute(select(IncomeEntry).where(
        IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end
    ).order_by(IncomeEntry.entry_date)).scalars().all()
    from .catalog import translate as _t
    for e in incomes:
        rows.append([e.entry_date.isoformat(), _t(lang, "INTÄKT"), e.customer_name or "",
                     (e.description or "")[:200], vatmod.get_code(e.vat_code).label_sv,
                     f"{e.net_amount:.2f}", f"{e.vat_amount:.2f}", f"{e.gross_amount:.2f}",
                     "", e.invoice_ref or "", e.payment_status])
    expenses = db.execute(select(Expense).where(
        Expense.expense_date >= start, Expense.expense_date <= end
    ).order_by(Expense.expense_date)).scalars().all()
    for x in expenses:
        rows.append([x.expense_date.isoformat(), _t(lang, "UTGIFT"), x.supplier or "",
                     (x.description or "")[:200], x.category_name or "",
                     f"{x.net_amount:.2f}", f"{x.vat_amount:.2f}", f"{x.gross_amount:.2f}",
                     f"{x.deductible_vat:.2f}", x.payment_method or "", ""])
    owners = db.execute(select(OwnerTransaction).where(
        OwnerTransaction.tx_date >= start, OwnerTransaction.tx_date <= end
    ).order_by(OwnerTransaction.tx_date)).scalars().all()
    for o in owners:
        typ = _t(lang, "EGNA UTTAG") if o.tx_type == OwnerTxType.UTTAG.value else _t(lang, "EGNA INSÄTTNINGAR")
        rows.append([o.tx_date.isoformat(), typ, "", (o.description or "")[:200],
                     _t(lang, "Ej intäkt/kostnad"), "", "", f"{o.amount:.2f}", "", o.reference or "", ""])
    rows.sort(key=lambda r: r[0])
    return _csv([_t(lang, h) for h in (
        "Datum", "Typ", "Motpart", "Beskrivning", "Kategori/Momskod",
        "Belopp exkl moms", "Moms", "Belopp inkl moms", "Avdragsgill moms",
        "Referens", "Status")], rows)


def export_vat_declaration_csv(decl: vatmod.DeclarationResult, lang: str = "sv") -> str:
    """Momsdeklaration per fält (whole kronor) — for transfer into
    Skatteverket's e-service 'Lämna momsdeklaration'."""
    from .catalog import translate as _t
    rows = []
    for b in vatmod.ALL_BOXES:
        kronor = decl.boxes_kronor.get(b, 0)
        rows.append([b, _t(lang, vatmod.BOX_LABELS_SV.get(b, "")), kronor, f"{decl.boxes.get(b, ZERO):.2f}"])
    return _csv([_t(lang, h) for h in (
        "Fält", "Beskrivning", "Belopp (hela kronor)", "Exakt belopp (öre)")], rows)


def export_ne_bilaga_csv(db: Session, fiscal_year: int, fy_start_month: int = 1,
                         lang: str = "sv") -> str:
    """Support material for the NE-bilaga (inkomstdeklaration för enskild
    firma). NOTE: income tax is intentionally NOT computed; this is
    bookkeeping support material, not an official filing format."""
    start, end = fiscal_year_bounds(fiscal_year, fy_start_month)
    t = yearly_summary(db, fiscal_year, fy_start_month)
    cats = expense_by_category(db, start, end)
    from .catalog import translate as _t
    def T(k):
        return _t(lang, k)
    rows = [
        [T("Omsättning netto (försäljning exkl. moms)"), f"{t.net_income:.2f}"],
        [T("Övriga intäkter (momsfria, ingår ovan)"), ""],
        [T("Årets inköp/kostnader (exkl. avdragsgill moms)"), f"{t.expense_cost:.2f}"],
    ]
    for c in cats:
        rows.append([f"{T('varav')} {c['category']}", f"{c['cost']:.2f}"])
    rows += [
        [T("Resultat före skatt (nettoinkomst − kostnader)"), f"{t.profit:.2f}"],
        [T("Utgående moms (periodens)"), f"{t.output_vat:.2f}"],
        [T("Ingående moms, avdragsgill (periodens)"), f"{t.input_vat:.2f}"],
        [T("Moms att betala/få tillbaka (periodens)"), f"{t.net_vat:.2f}"],
        [T("Egna uttag (påverkar EJ resultatet)"), f"{t.owner_withdrawals:.2f}"],
        [T("Egna insättningar (påverkar EJ resultatet)"), f"{t.owner_contributions:.2f}"],
        ["", ""],
        [T("OBS: Underlag för NE-bilaga — ej inlämningsformat. Beräkna inte inkomstskatt i detta system."), ""],
    ]
    return _csv([T("Post"), T("Belopp (SEK)")], rows)
