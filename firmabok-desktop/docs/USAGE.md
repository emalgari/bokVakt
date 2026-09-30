# Daglig användning / Daily use (Desktop)

## Start
`firmabok-desktop` (or `nix run .`). First launch opens the setup wizard.

## Veckorutin / Weekly routine
1. **Income**: register sales with date, customer, VAT code and amount
   (enter excl. or incl. VAT — the app computes the rest, half-up per row).
   Mark paid (💰/✓) with the payment date — required for bokslutsmetoden.
2. **Expenses**: receipt total (incl. VAT), category, VAT code, deductible
   VAT (reduce for representation/mixed use), attach the receipt file.
3. **Owner**: record egna uttag/insättningar — never touches profit or VAT.

## Invoicing
New invoice → lines (Art.nr, qty, unit, price, VAT code) → *Finalize on
save* (default) assigns the next sequential number, due date and OCR.
Download the Swedish A4 PDF. Register payments later; correct mistakes with
a credit note (finalized invoices are immutable — gapless numbering is a
legal requirement).

## VAT (moms)
Choose period type/year/number. The page shows your registered method
(faktura/bokslut), the filing deadline (12th of the second month after the
period), SKV boxes in whole kronor + exact öre, and warnings. Lock the
period after filing; unlock only to amend. Export CSV (box-by-box) or PDF.

## Reports
P&L, categories, monthly grid; journal CSV, NE-bilaga CSV, P&L PDF.
CSV/PDF exports follow the UI language; invoice PDFs never do.

## Data
Backups (consistent SQLite copy + uploads + sha256 manifest), restore with
safety copy, JSON export, and the audit log (who/what/when + before/after).
