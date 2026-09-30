"""SQLAlchemy 2.0 data model.

Money is stored via MoneyType (exact decimal text in SQLite, Decimal in
Python). VAT rates are percentages (Decimal(5,2)). Every row that can
appear in a VAT report stores: net amount, VAT amount and gross amount
consistently (gross = net + vat).

Sales/purchase classification uses VAT codes (see app.vat) which map onto
Skatteverket momsdeklaration boxes (SKV 4700).
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, Money


# --------------------------------------------------------------------------
# Enums (stored as strings for portability)
# --------------------------------------------------------------------------

class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"       # Obetald
    PAID = "paid"           # Betald
    PARTIAL = "partial"     # Delbetald


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"          # Utkast (no number yet — can be deleted)
    FINALIZED = "finalized"  # Fastställd (numbered — immutable, no deletion)
    SENT = "sent"            # Skickad
    PAID = "paid"            # Betald
    CREDITED = "credited"    # Krediterad (credit note issued)


class OwnerTxType(str, enum.Enum):
    UTTAG = "uttag"          # Egna uttag (withdrawal)
    INSATTNING = "insattning"  # Egna insättningar (contribution)


class VatPeriod(str, enum.Enum):
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    password_salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    flash: Mapped[str] = mapped_column(Text, default="")  # JSON-encoded flash messages


# --------------------------------------------------------------------------
# Company profile & settings (singletons)
# --------------------------------------------------------------------------

class CompanyProfile(Base):
    __tablename__ = "company_profile"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    company_name: Mapped[str] = mapped_column(String(200), default="")
    org_nr: Mapped[str] = mapped_column(String(16), default="")            # XXXXXX-XXXX
    vat_number: Mapped[str] = mapped_column(String(16), default="")        # SE…01
    f_skatt_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    f_skatt_text: Mapped[str] = mapped_column(
        String(200), default="Godkänd för F-skatt")

    address_line1: Mapped[str] = mapped_column(String(200), default="")
    address_line2: Mapped[str] = mapped_column(String(200), default="")
    postal_code: Mapped[str] = mapped_column(String(16), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(64), default="Sverige")

    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    logo_path: Mapped[str] = mapped_column(String(500), default="")  # relative to uploads

    # Bank details
    bank_name: Mapped[str] = mapped_column(String(120), default="")
    bankgiro: Mapped[str] = mapped_column(String(32), default="")
    plusgiro: Mapped[str] = mapped_column(String(32), default="")
    iban: Mapped[str] = mapped_column(String(64), default="")
    bic: Mapped[str] = mapped_column(String(16), default="")
    bank_account_number: Mapped[str] = mapped_column(String(64), default="")  # kontonummer
    # Which payment destination to print on invoices:
    # 'bankgiro' | 'plusgiro' | 'bankaccount'
    payment_display: Mapped[str] = mapped_column(String(16), default="bankgiro")
    invoice_show_ocr: Mapped[bool] = mapped_column(Boolean, default=True)

    # Invoice defaults
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    late_interest_rate: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("8.00"))  # %
    invoice_notes: Mapped[str] = mapped_column(Text, default="")
    invoice_number_prefix: Mapped[str] = mapped_column(String(16), default="")  # e.g. "" -> 2026-0001
    invoice_number_digits: Mapped[int] = mapped_column(Integer, default=4)
    invoice_number_start: Mapped[int] = mapped_column(Integer, default=1)
    default_city_for_dates: Mapped[str] = mapped_column(String(100), default="")

    # Bookkeeping settings
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)  # 1 = calendar year
    vat_period: Mapped[str] = mapped_column(String(10), default=VatPeriod.QUARTER.value)
    # Momsredovisningsmetod: 'faktura' (fakturametoden) | 'bokslut' (boksluts-/kontantmetoden).
    # Enskild firma registreras normalt med bokslutsmetoden: utgående moms redovisas
    # när kunden betalat; obetalda poster redovisas senast i årets sista period.
    vat_method: Mapped[str] = mapped_column(String(10), default="faktura")
    # Dra av ingående moms först när utgiften betalats (annars: förenklingsregeln
    # vid bokslutsmetoden — avdrag när inköpet bokförs, omsättning < 1 Mkr).
    input_vat_on_payment: Mapped[bool] = mapped_column(Boolean, default=False)
    simplified_vat_mode: Mapped[bool] = mapped_column(Boolean, default=False)  # NON-COMPLIANT demo mode
    default_vat_rate: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("25"))
    currency: Mapped[str] = mapped_column(String(8), default="SEK")

    # Invoice text/behaviour (matches the user's template)
    late_interest_text: Mapped[str] = mapped_column(
        Text, default="Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.")
    round_total_to_krona: Mapped[bool] = mapped_column(Boolean, default=False)  # "Avrundning"-rad
    sni_codes: Mapped[str] = mapped_column(String(64), default="")
    business_description: Mapped[str] = mapped_column(String(200), default="")

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SettingsKV(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_no: Mapped[str] = mapped_column(String(32), default="", index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    is_business: Mapped[bool] = mapped_column(Boolean, default=True)
    org_nr: Mapped[str] = mapped_column(String(24), default="")   # org.nr or personnr
    vat_number: Mapped[str] = mapped_column(String(24), default="")  # EU VAT ID (e.g. DK12345678)
    address_line1: Mapped[str] = mapped_column(String(200), default="")
    address_line2: Mapped[str] = mapped_column(String(200), default="")
    postal_code: Mapped[str] = mapped_column(String(16), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(64), default="Sverige")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")  # Er referens
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")
    income_entries: Mapped[list["IncomeEntry"]] = relationship(back_populates="customer")


# --------------------------------------------------------------------------
# VAT rates / codes
# --------------------------------------------------------------------------

class VatRate(Base):
    """Lookup table of VAT rates/codes used in dropdowns. Seeded at startup
    from app.vat.CODES; kept in DB so users can see labels in their language."""
    __tablename__ = "vat_rates"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)   # e.g. SE25
    label_sv: Mapped[str] = mapped_column(String(200))
    percent: Mapped[Decimal] = mapped_column(Money(2))
    side: Mapped[str] = mapped_column(String(10))  # 'sale' | 'purchase'
    skv_boxes: Mapped[str] = mapped_column(String(64), default="")  # human-readable mapping
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------
# Income
# --------------------------------------------------------------------------

class IncomeEntry(Base):
    """A recorded sale (bokförd intäkt). The single source of truth for
    output VAT in reports. Invoices link here, never the other way round."""
    __tablename__ = "income_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")  # free-text fallback/snapshot
    description: Mapped[str] = mapped_column(String(500), default="")
    vat_code: Mapped[str] = mapped_column(String(32), default="SE25", index=True)
    net_amount: Mapped[Decimal] = mapped_column(Money(2))            # exkl. moms
    vat_rate: Mapped[Decimal] = mapped_column(Money(2))              # %
    vat_amount: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    gross_amount: Mapped[Decimal] = mapped_column(Money(2))          # inkl. moms
    payment_status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.UNPAID.value)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_ref: Mapped[str] = mapped_column(String(64), default="")  # invoice no / external ref
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[Customer | None] = relationship(back_populates="income_entries")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="income_entries")

    @property
    def week(self) -> int:
        return self.entry_date.isocalendar()[1]


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------

class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    bas_account_hint: Mapped[str] = mapped_column(String(16), default="")  # suggested BAS konto
    default_vat_code: Mapped[str] = mapped_column(String(32), default="SE25_P")
    notes: Mapped[str] = mapped_column(Text, default="")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    supplier: Mapped[str] = mapped_column(String(200), default="", index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    category_name: Mapped[str] = mapped_column(String(100), default="Övrigt", index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    vat_code: Mapped[str] = mapped_column(String(32), default="SE25_P", index=True)
    net_amount: Mapped[Decimal] = mapped_column(Money(2))
    vat_rate: Mapped[Decimal] = mapped_column(Money(2))
    vat_amount: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    gross_amount: Mapped[Decimal] = mapped_column(Money(2))
    deductible_vat: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))  # avdragsgill moms (<= vat_amount)
    payment_method: Mapped[str] = mapped_column(String(64), default="")
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # för kontant-/bokslutsmetoden
    receipt_path: Mapped[str] = mapped_column(String(500), default="")  # relative to uploads/receipts
    receipt_original_name: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    category: Mapped[ExpenseCategory | None] = relationship()

    @property
    def book_cost(self) -> Decimal:
        """Cost in the P&L = gross - deductible VAT.
        Non-deductible VAT is part of the cost (correct for enskild firma)."""
        return (self.gross_amount or Decimal(0)) - (self.deductible_vat or Decimal(0))

# --------------------------------------------------------------------------
# Owner finances (NEGALE — never business income/expense)
# --------------------------------------------------------------------------

class OwnerTransaction(Base):
    """Egna uttag / egna insättningar. Tracked separately; excluded from
    P&L and VAT entirely (they are not business income or expenses)."""
    __tablename__ = "owner_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tx_date: Mapped[date] = mapped_column(Date, index=True)
    tx_type: Mapped[str] = mapped_column(String(16))  # uttag | insattning
    amount: Mapped[Decimal] = mapped_column(Money(2))  # positive
    description: Mapped[str] = mapped_column(String(500), default="")
    reference: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------
# Invoices
# --------------------------------------------------------------------------

class InvoiceSeries(Base):
    """Per-fiscal-year sequential counter. Numbers are only consumed on
    finalize (fastställ), which guarantees gapless numbering: drafts carry
    no number, finalized invoices can never be deleted (only credited)."""
    __tablename__ = "invoice_series"
    __table_args__ = (UniqueConstraint("series_year", name="uq_invoice_series_year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    series_year: Mapped[int] = mapped_column(Integer)
    next_seq: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    series_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.DRAFT.value, index=True)
    is_credit_note: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_note_for_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)

    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # Leveransdatum
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)

    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    # Snapshot of customer address at issue time (immutability for finalized docs)
    customer_snapshot: Mapped[str] = mapped_column(Text, default="")  # JSON

    ocr: Mapped[str] = mapped_column(String(32), default="")
    our_reference: Mapped[str] = mapped_column(String(120), default="")
    customer_reference: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str] = mapped_column(String(8), default="SEK")

    net_total: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    vat_total: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    gross_total: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    rounding_amount: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))  # Avrundning till hela kronor
    amount_paid: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))

    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[Customer | None] = relationship(back_populates="invoices")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.position")
    income_entries: Mapped[list[IncomeEntry]] = relationship(back_populates="invoice")
    credit_note_for: Mapped["Invoice | None"] = relationship(remote_side="Invoice.id")

    @property
    def amount_to_pay(self) -> Decimal:
        """Att betala = summa inkl. moms + avrundning − betalt."""
        return ((self.gross_total or Decimal(0)) + (self.rounding_amount or Decimal(0))
                - (self.amount_paid or Decimal(0)))


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    article_no: Mapped[str] = mapped_column(String(32), default="")   # Art.nr
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Money(3), default=Decimal("1.000"))
    unit: Mapped[str] = mapped_column(String(16), default="st")
    unit_price: Mapped[Decimal] = mapped_column(Money(2))   # exkl. moms
    vat_code: Mapped[str] = mapped_column(String(32), default="SE25")
    vat_rate: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("25"))
    line_net: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    line_vat: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    line_gross: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


# --------------------------------------------------------------------------
# VAT reports (snapshots)
# --------------------------------------------------------------------------

class VatReport(Base):
    __tablename__ = "vat_reports"
    __table_args__ = (UniqueConstraint("period_kind", "fiscal_year", "period_number", name="uq_vat_report_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    period_kind: Mapped[str] = mapped_column(String(10))   # month | quarter | year
    fiscal_year: Mapped[int] = mapped_column(Integer)
    period_number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    boxes: Mapped[str] = mapped_column(Text, default="{}")  # JSON: {"05": "1234.56", ...} exact öre
    output_vat: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    input_vat: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))
    net_vat: Mapped[Decimal] = mapped_column(Money(2), default=Decimal("0.00"))  # att betala(+)/få tillbaka(-)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)   # period locked after filing
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------
# Attachments & audit
# --------------------------------------------------------------------------

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # logo | receipt | other
    entity_type: Mapped[str] = mapped_column(String(32), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stored_name: Mapped[str] = mapped_column(String(255))       # random name on disk
    original_name: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(32))     # create | update | delete | finalize | login | ...
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    changes: Mapped[str] = mapped_column(Text, default="{}")  # JSON {"field": {"before": ..., "after": ...}}
