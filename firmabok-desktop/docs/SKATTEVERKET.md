# Skatteverket reporting (moms & NE)

Firmabok produces support material; you file in Skatteverket's e-services.

## Momsdeklaration (SKV 4700) box mapping
Sales codes: SE25/SE12/SE6/SE0 → box 05 (base) + 10/11/12 (VAT);
EXEMPT → 42; EU_GOODS → 35 (+ periodisk sammanställning); EXPORT_GOODS → 36;
EU_SERVICES → 39 (+ PS); SERVICES_ABROAD → 40; SE_REVERSE_SALE → 41
("Omvänd skattskyldighet" printed on the invoice, no Swedish VAT charged).

Purchase codes: domestic → box 48 (deductible part); NON_DEDUCTIBLE_P → no
deduction (VAT becomes cost); EU_GOODS_ACQ → 20; EU_SERVICES_ACQ → 21;
NON_EU_SERVICES_ACQ → 22; SE_RC_GOODS_P → 23; SE_RC_SERVICES_P → 24 (byggtjänster);
IMPORT_P → 50; reverse-charge/import output VAT → 30–32 / 60–62 with the
matching deduction in 48 (nets to zero).

Fält 49 = (10+11+12+30+31+32+60+61+62) − 48, on whole-kronor boxes
(ML 1994:200 1 kap. 7 §). The ledger keeps öre precision (ROUND_HALF_UP/row).

## Redovisningsmetod
- **Fakturametoden**: sales report on invoice date.
- **Bokslutsmetoden (kontantmetoden)** — the common registration for enskild
  firma: sales report when **paid**; unpaid items no later than the fiscal
  year's last period. Input VAT defaults to the simplification rule
  (deduct when booked, turnover < 1 Mkr); switchable to payment-date.
  Register payment dates on income — otherwise VAT waits to the year-end.

## Deadlines
Declaration due the **12th of the second month** after the period ends
(monthly/quarterly/yearly). Shown in-app per period.

## NE-bilaga
`Reports → NE-bilaga support material (CSV)`: net turnover, costs per
category (excl. deductible VAT), result before tax, VAT sums, owner
transactions as memo. **No income tax is calculated.** Periodiseringsfond,
expansionsfond och räntefördelning hanteras inte av Firmabok.

## Bokföringslagen
Gapless invoice numbering (numbers only at finalize; credit notes for
corrections), receipts attachable per expense, audit trail with before/after
values, backups for the 7-year retention rule.
