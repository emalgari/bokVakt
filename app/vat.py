"""Swedish VAT (moms) logic and momsdeklaration (SKV 4700) box mapping.

CRITICAL PRINCIPLE
------------------
Moms is calculated on *taxable sales* (utgående moms) minus *deductible
purchase VAT* (ingående moms). VAT is NEVER calculated on profit.

Box mapping verified against Skatteverket "Fylla i momsdeklarationen"
(skatteverket.se, retrieved 2026):

  A – Momspliktig försäljning exkl. moms
      05 momspliktig försäljning (25/12/6/0 %)
      06 momspliktiga uttag
      07 vinstmarginalbeskattning
      08 hyresinkomster vid frivillig beskattning
  B – Utgående moms på 05–08
      10 (25 %)  11 (12 %)  12 (6 %)
  C – Momspliktiga inköp vid omvänd betalningsskyldighet
      20 varor från annat EU-land
      21 tjänster från annat EU-land (huvudregeln)
      22 tjänster från land utanför EU
      23 varor i Sverige (omvänd skattskyldighet)
      24 övriga tjänster i Sverige (bl.a. byggtjänster)
  D – Utgående moms på 20–24
      30 (25 %)  31 (12 %)  32 (6 %)
  E – Försäljning undantagen från moms
      35 varor till annat EU-land   36 varor utanför EU (export)
      37/38 trepartshandel          39 tjänster till EU-beskattningsbar person
      40 övrig försäljning av tjänster utomlands
      41 försäljning där köparen är betalningsskyldig i Sverige
      42 övrig momsfri försäljning m.m.
  H/I – Import
      50 beskattningsunderlag       60/61/62 utgående moms
  F – Ingående moms
      48 ingående moms att dra av
  G – Moms att betala eller få tillbaka
      49 = (10+11+12+30+31+32+60+61+62) − 48   (hela krontal)

Declaration amounts are stated in whole kronor (ML 1994:200 1 kap. 7 §);
the ledger keeps öre precision and each box is rounded half-up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

from .money import ZERO, q2, round_kronor, sum_money, vat_amount

# Output-VAT box per rate for domestic taxable sales (section B)
SALE_VAT_BOX_BY_RATE = {Decimal("25"): "10", Decimal("12"): "11", Decimal("6"): "12"}
# Output-VAT box per rate for reverse-charge purchases (section D)
RC_VAT_BOX_BY_RATE = {Decimal("25"): "30", Decimal("12"): "31", Decimal("6"): "32"}
# Output-VAT box per rate for imports (section I)
IMPORT_VAT_BOX_BY_RATE = {Decimal("25"): "60", Decimal("12"): "61", Decimal("6"): "62"}

ALL_BOXES = [
    "05", "06", "07", "08",
    "10", "11", "12",
    "20", "21", "22", "23", "24",
    "30", "31", "32",
    "35", "36", "37", "38", "39", "40", "41", "42",
    "48", "49", "50",
    "60", "61", "62",
]

BOX_LABELS_SV = {
    "05": "Momspliktig försäljning (25/12/6/0 %)",
    "06": "Momspliktiga uttag",
    "07": "Beskattningsunderlag vid vinstmarginalbeskattning",
    "08": "Hyresinkomster vid frivillig beskattning",
    "10": "Utgående moms 25 %",
    "11": "Utgående moms 12 %",
    "12": "Utgående moms 6 %",
    "20": "Inköp av varor från annat EU-land",
    "21": "Inköp av tjänster från annat EU-land (huvudregeln)",
    "22": "Inköp av tjänster från land utanför EU",
    "23": "Inköp av varor i Sverige, omvänd betalningsskyldighet",
    "24": "Övriga inköp av tjänster i Sverige, omvänd betalningsskyldighet",
    "30": "Utgående moms 25 % på inköp (fält 20–24)",
    "31": "Utgående moms 12 % på inköp (fält 20–24)",
    "32": "Utgående moms 6 % på inköp (fält 20–24)",
    "35": "Försäljning av varor till annat EU-land",
    "36": "Försäljning av varor utanför EU (export)",
    "37": "Mellanmans inköp av varor vid trepartshandel",
    "38": "Mellanmans försäljning av varor vid trepartshandel",
    "39": "Försäljning av tjänster till beskattningsbar person i annat EU-land",
    "40": "Övrig försäljning av tjänster som tillhandahållits utomlands",
    "41": "Försäljning när köparen är betalningsskyldig i Sverige",
    "42": "Övrig försäljning med mera (momsfri)",
    "48": "Ingående moms att dra av",
    "49": "Moms att betala eller få tillbaka",
    "50": "Beskattningsunderlag vid import",
    "60": "Utgående moms 25 % vid import",
    "61": "Utgående moms 12 % vid import",
    "62": "Utgående moms 6 % vid import",
}


@dataclass(frozen=True)
class VatCodeInfo:
    code: str
    label_sv: str
    percent: Decimal            # default rate; 0 for exempt/RC-sale codes
    side: str                   # 'sale' | 'purchase'
    base_box: str | None        # declaration box for the base amount
    vat_box_map: dict | None    # rate -> output-VAT box (for purchases w/ reverse charge / import)
    domestic_sale_vat: bool     # True -> output VAT goes to boxes 10/11/12 by rate
    deductible_input: bool      # True -> deductible VAT goes to box 48
    reverse_charge: bool        # buyer self-accounts (no seller VAT / purchase w/ own output)
    sort_order: int = 0

    @property
    def boxes_text(self) -> str:
        parts = [f"Fält {self.base_box}"] if self.base_box else []
        if self.domestic_sale_vat:
            parts.append("moms fält 10/11/12")
        if self.vat_box_map:
            parts.append("moms fält 30/31/32" if "30" in self.vat_box_map.values() else "moms fält 60/61/62")
        if self.deductible_input:
            parts.append("avdrag fält 48")
        return ", ".join(parts) or "—"


# ---------------------------------------------------------------------------
# Code registry
# ---------------------------------------------------------------------------

SALE_CODES: dict[str, VatCodeInfo] = {c.code: c for c in [
    VatCodeInfo("SE25", "Försäljning 25 % moms", Decimal("25"), "sale", "05", None, True, False, False, 10),
    VatCodeInfo("SE12", "Försäljning 12 % moms", Decimal("12"), "sale", "05", None, True, False, False, 11),
    VatCodeInfo("SE6", "Försäljning 6 % moms", Decimal("6"), "sale", "05", None, True, False, False, 12),
    VatCodeInfo("SE0", "Försäljning 0 % moms (momspliktig)", Decimal("0"), "sale", "05", None, True, False, False, 13),
    VatCodeInfo("EXEMPT", "Momsfri försäljning (t.ex. bidrag, hyra)", Decimal("0"), "sale", "42", None, False, False, False, 20),
    VatCodeInfo("EU_GOODS", "Varor till annat EU-land (B2B, giltigt VAT-nr)", Decimal("0"), "sale", "35", None, False, False, True, 30),
    VatCodeInfo("EXPORT_GOODS", "Export av varor utanför EU", Decimal("0"), "sale", "36", None, False, False, True, 31),
    VatCodeInfo("EU_SERVICES", "Tjänster till EU-företag (huvudregeln)", Decimal("0"), "sale", "39", None, False, False, True, 32),
    VatCodeInfo("SERVICES_ABROAD", "Övriga tjänster tillhandahållna utomlands", Decimal("0"), "sale", "40", None, False, False, True, 33),
    VatCodeInfo("SE_REVERSE_SALE", "Försäljning m. omvänd skattskyldighet i Sverige (t.ex. byggtjänster)", Decimal("0"), "sale", "41", None, False, False, True, 34),
]}

PURCHASE_CODES: dict[str, VatCodeInfo] = {c.code: c for c in [
    VatCodeInfo("SE25_P", "Inköp Sverige 25 % moms", Decimal("25"), "purchase", None, None, False, True, False, 10),
    VatCodeInfo("SE12_P", "Inköp Sverige 12 % moms", Decimal("12"), "purchase", None, None, False, True, False, 11),
    VatCodeInfo("SE6_P", "Inköp Sverige 6 % moms", Decimal("6"), "purchase", None, None, False, True, False, 12),
    VatCodeInfo("SE0_P", "Inköp Sverige 0 % moms", Decimal("0"), "purchase", None, None, False, True, False, 13),
    VatCodeInfo("NON_DEDUCTIBLE_P", "Inköp utan avdragsrätt (moms blir kostnad)", Decimal("25"), "purchase", None, None, False, False, False, 15),
    VatCodeInfo("EU_GOODS_ACQ", "EU-inköp av varor (omvänd skattskyldighet)", Decimal("25"), "purchase", "20", RC_VAT_BOX_BY_RATE, False, True, True, 20),
    VatCodeInfo("EU_SERVICES_ACQ", "EU-inköp av tjänster (huvudregeln)", Decimal("25"), "purchase", "21", RC_VAT_BOX_BY_RATE, False, True, True, 21),
    VatCodeInfo("NON_EU_SERVICES_ACQ", "Inköp av tjänster utanför EU", Decimal("25"), "purchase", "22", RC_VAT_BOX_BY_RATE, False, True, True, 22),
    VatCodeInfo("SE_RC_GOODS_P", "Inköp av varor i Sverige m. omvänd skattskyldighet", Decimal("25"), "purchase", "23", RC_VAT_BOX_BY_RATE, False, True, True, 23),
    VatCodeInfo("SE_RC_SERVICES_P", "Inköp av byggtjänster m.m. i Sverige m. omvänd skattskyldighet", Decimal("25"), "purchase", "24", RC_VAT_BOX_BY_RATE, False, True, True, 24),
    VatCodeInfo("IMPORT_P", "Import av varor (moms till Skatteverket)", Decimal("25"), "purchase", "50", IMPORT_VAT_BOX_BY_RATE, False, True, True, 30),
]}

ALL_CODES: dict[str, VatCodeInfo] = {**SALE_CODES, **PURCHASE_CODES}


def get_code(code: str) -> VatCodeInfo:
    try:
        return ALL_CODES[code]
    except KeyError:
        raise ValueError(f"Okänd momskod: {code!r}")


def default_rate_for(code: str) -> Decimal:
    return get_code(code).percent


def compute_row_vat(net: Decimal, rate_percent: Decimal, code: str) -> Decimal:
    """VAT charged/deducted for one row. Reverse-charge and exempt *sales*
    carry 0 Swedish VAT for the seller. Reverse-charge *purchases* carry
    VAT that the buyer self-accounts (output + input, nets to zero)."""
    info = get_code(code)
    if info.side == "sale" and not info.domestic_sale_vat:
        return ZERO
    return vat_amount(net, rate_percent)


# ---------------------------------------------------------------------------
# Declaration computation
# ---------------------------------------------------------------------------

@dataclass
class RateBreakdown:
    rate: Decimal = ZERO
    base: Decimal = ZERO
    vat: Decimal = ZERO


@dataclass
class DeclarationResult:
    start: date
    end: date
    boxes: dict[str, Decimal] = field(default_factory=dict)        # exact öre
    boxes_kronor: dict[str, int] = field(default_factory=dict)     # rounded, declaration-ready
    output_vat: Decimal = ZERO        # total utgående (exact)
    input_vat: Decimal = ZERO         # total avdragsgill ingående (exact)
    net_vat: Decimal = ZERO           # output - input (exact)
    net_vat_kronor: int = 0           # box 49 (from rounded boxes, per SKV)
    sales_by_rate: list[RateBreakdown] = field(default_factory=list)
    purchase_rc_by_rate: list[RateBreakdown] = field(default_factory=list)
    sales_base_total: Decimal = ZERO  # all sales bases incl. exempt/EU (net revenue)
    input_vat_by_source: dict[str, Decimal] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def empty_boxes() -> dict[str, Decimal]:
    return {b: ZERO for b in ALL_BOXES if b != "49"}


def effective_income_date(e, method: str, fy_start_month: int = 1):
    """Date the sale enters the VAT declaration.

    Fakturametoden ('faktura'): invoice/entry date.
    Bokslutsmetoden/kontantmetoden ('bokslut') — the normal method for
    enskild firma per Skatteverket registration:
      * paid in full  → payment date
      * partially paid → payment date (WARN: verify allocation manually)
      * unpaid        → no later than the fiscal year-end (last period)
    """
    if method != "bokslut":
        return e.entry_date, None
    from .swedish import fiscal_year_bounds, fiscal_year_of
    status = getattr(e, "payment_status", "unpaid") or "unpaid"
    pdate = getattr(e, "payment_date", None)
    if status == "paid":
        if pdate:
            return pdate, None
        return e.entry_date, ("paid_no_date", e)
    if status == "partial":
        return (pdate or e.entry_date), ("partial", e)
    fy = fiscal_year_of(e.entry_date, fy_start_month)
    _, yearend = fiscal_year_bounds(fy, fy_start_month)
    return yearend, None


def effective_expense_date(x, method: str, input_vat_on_payment: bool):
    """Date the deductible input VAT enters the declaration.

    Default under bokslutsmetoden is the simplification rule (förenklings-
    regeln, 3 kap. 36 § ML): input VAT may be deducted when the purchase is
    recorded if annual turnover is below 1 Mkr. With input_vat_on_payment
    the payment date is used instead (full kontantmetod)."""
    if method == "bokslut" and input_vat_on_payment:
        pdate = getattr(x, "payment_date", None)
        if pdate:
            return pdate, None
        return x.expense_date, ("expense_no_paydate", x)
    return x.expense_date, None


def compute_declaration(
    income_entries: Iterable,
    expenses: Iterable,
    start: date,
    end: date,
    method: str = "faktura",
    fy_start_month: int = 1,
    input_vat_on_payment: bool = False,
) -> DeclarationResult:
    """Compute a momsdeklaration from booked income entries and expenses.

    Rows are assigned to the period by their *effective date* (see
    effective_income_date / effective_expense_date), which depends on the
    registered redovisningsmetod ('faktura' or 'bokslut').

    * income_entries: objects with .vat_code, .net_amount, .vat_rate,
      .vat_amount, .entry_date, .payment_status, .payment_date
    * expenses: objects with .vat_code, .net_amount, .vat_rate,
      .vat_amount, .deductible_vat, .expense_date, .payment_date

    VAT payable/refund = output VAT on sales − deductible input VAT.
    It is NOT based on profit in any way.
    """
    res = DeclarationResult(start=start, end=end)
    boxes = empty_boxes()

    sale_rates: dict[Decimal, RateBreakdown] = {}
    rc_purchase_rates: dict[Decimal, RateBreakdown] = {}
    input_by_source: dict[str, Decimal] = {"domestic": ZERO, "reverse_charge": ZERO, "import": ZERO}

    # ---- Sales (utgående moms) -------------------------------------------
    for e in income_entries:
        eff_date, warn = effective_income_date(e, method, fy_start_month)
        if warn is not None:
            kind, obj = warn
            if kind == "partial":
                res.warnings.append(
                    f"Intäkt {obj.id!s} ({obj.entry_date}) är delbetald och redovisas i sin helhet "
                    f"per betalningsdatum — kontrollera beloppet mot faktisk inbetalning.")
            else:
                res.warnings.append(
                    f"Intäkt {obj.id!s} är markerad betald men saknar betalningsdatum — "
                    f"redovisas per bokföringsdatum.")
        if not (start <= eff_date <= end):
            continue
        info = get_code(e.vat_code)
        net = q2(e.net_amount or 0)
        rate = q2(e.vat_rate or 0)
        if info.base_box:
            boxes[info.base_box] += net
        res.sales_base_total += net
        if info.domestic_sale_vat:
            v = q2(e.vat_amount if e.vat_amount is not None else vat_amount(net, rate))
            box = SALE_VAT_BOX_BY_RATE.get(rate)
            if box and v != 0:
                boxes[box] += v
            elif v != 0 and rate != 0:
                res.warnings.append(
                    f"Intäkt {e.id!s} ({e.entry_date}) har momssats {rate}% som saknar deklarationsfält — kontrollera.")
            bd = sale_rates.setdefault(rate, RateBreakdown(rate))
            bd.base += net
            bd.vat += v
        elif v_if_any := q2(e.vat_amount or 0):
            # Exempt / EU / reverse-charge sales must not carry Swedish VAT.
            if v_if_any != 0:
                res.warnings.append(
                    f"Intäkt {e.id!s} har momskod {info.code} men moms {v_if_any} kr — svensk moms ska inte tas ut, kontrollera.")

    # ---- Purchases (ingående moms + omvänd skattskyldighet) ---------------
    for x in expenses:
        eff_date, warn = effective_expense_date(x, method, input_vat_on_payment)
        if warn is not None:
            res.warnings.append(
                f"Utgift {x.id!s} saknar betalningsdatum — ingående moms redovisas per "
                f"bokföringsdatum ({x.expense_date}).")
        if not (start <= eff_date <= end):
            continue
        info = get_code(x.vat_code)
        net = q2(x.net_amount or 0)
        rate = q2(x.vat_rate or 0)
        vat_amt = q2(x.vat_amount if x.vat_amount is not None else vat_amount(net, rate))
        deductible = q2(x.deductible_vat if x.deductible_vat is not None else vat_amt)
        if deductible > vat_amt:
            deductible = vat_amt
            res.warnings.append(
                f"Utgift {x.id!s}: avdragsgill moms kan inte överstiga fakturerad moms — begränsad till {vat_amt} kr.")
        if deductible < 0:
            deductible = ZERO

        if info.base_box:
            boxes[info.base_box] += net  # RC-purchase base (20–24) or import base (50)

        if info.reverse_charge and info.vat_box_map:
            # Self-accounted output VAT on the acquisition
            own_vat = vat_amount(net, rate)
            box = info.vat_box_map.get(rate)
            if box and own_vat != 0:
                boxes[box] += own_vat
            bd = rc_purchase_rates.setdefault(rate, RateBreakdown(rate))
            bd.base += net
            bd.vat += own_vat
            if info.base_box == "50":
                input_by_source["import"] += deductible
            else:
                input_by_source["reverse_charge"] += deductible
        elif info.deductible_input and not info.reverse_charge:
            input_by_source["domestic"] += deductible

        if info.deductible_input:
            boxes["48"] += deductible
        elif vat_amt != 0:
            # Non-deductible: stays as cost; nothing in the declaration.
            pass

    # ---- Totals ------------------------------------------------------------
    res.boxes = {b: q2(v) for b, v in boxes.items()}
    res.output_vat = q2(
        sum_money([res.boxes[b] for b in ("10", "11", "12", "30", "31", "32", "60", "61", "62")]))
    res.input_vat = q2(res.boxes["48"])
    res.net_vat = q2(res.output_vat - res.input_vat)

    res.boxes_kronor = {b: round_kronor(v) for b, v in res.boxes.items()}
    # Fält 49 = summan av fälten 10,11,12,30,31,32,60,61,62 minus fält 48,
    # beräknad på avrundade krontal (SKV).
    res.net_vat_kronor = (
        sum(res.boxes_kronor[b] for b in ("10", "11", "12", "30", "31", "32", "60", "61", "62"))
        - res.boxes_kronor["48"]
    )
    res.boxes_kronor["49"] = res.net_vat_kronor

    res.sales_by_rate = [sale_rates[r] for r in sorted(sale_rates, reverse=True)]
    res.purchase_rc_by_rate = [rc_purchase_rates[r] for r in sorted(rc_purchase_rates, reverse=True)]
    res.input_vat_by_source = input_by_source
    return res
