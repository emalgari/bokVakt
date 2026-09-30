# Firmabok — lokal bokföring för enskild firma

Local-first bookkeeping, VAT (moms) and invoicing for a **Swedish sole
proprietorship (enskild firma)**. Everything runs on your own machine —
**no cloud, no external APIs, no telemetry**. Data lives in a local SQLite
database plus an uploads folder.

> ⚠️ **Scope**: Firmabok is bookkeeping *support material* (underlag).
> It computes moms according to Swedish rules and maps the figures to the
> momsdeklaration (SKV 4700) boxes, but **you** review and file everything
> in Skatteverket's e-services. Income tax is intentionally **not**
> calculated; the NE-bilaga export is support material only.

---

## The VAT rule this system enforces

Moms is calculated on **taxable sales**, never on profit:

| Concept | Definition in Firmabok |
|---|---|
| Gross income (brutto) | Sales **incl.** VAT |
| Net income (nettoomsättning) | Sales **excl.** VAT |
| Output VAT (utgående moms) | VAT on sales at 25/12/6 % |
| Input VAT (ingående moms) | **Deductible** VAT on purchases |
| VAT payable/refund (fält 49) | Output − Input |
| Expense cost | Gross − deductible VAT (non-deductible VAT is a cost) |
| Profit (resultat) | Net income − expense costs |
| Egna uttag/insättningar | Tracked separately — **never** income/expense, no VAT effect |

A "simplified mode" exists for comparison only. It is **disabled by
default**, requires typing `JAG FÖRSTÅR` to enable, and is clearly labelled
**EJ KORREKT / not for Skatteverket** wherever its numbers appear.

## Tech stack (and why)

- **FastAPI + Uvicorn** — modern Python web framework with first-class
  Pydantic validation and a simple dependency system; Flask would work but
  FastAPI gives typed forms/validation for free. Server-rendered pages +
  light **HTMX**, styled with **Pico.css** (both vendored locally — no
  Node/npm, no CDN).
- **SQLite** via **SQLAlchemy 2.0** + **Alembic** migrations. Money is
  stored as exact decimal text through a custom `MoneyType` — SQLite never
  sees floats. All arithmetic uses `Decimal` with half-up rounding to öre.
- **Jinja2 + WeasyPrint** for PDF invoices/reports (HTML+CSS → PDF).
- **Local auth**: scrypt-hashed password, server-side sessions (HttpOnly
  cookie), CSRF tokens on every mutating request, audit trail of all
  changes to financial data.

```
app/
  main.py            FastAPI app factory + startup migrations/seeding
  models.py          SQLAlchemy data model (17 tables)
  money.py           Decimal helpers, Swedish formatting (1 234,56 kr)
  swedish.py         org.nr/VAT-nr validation, OCR (LUHN), fiscal periods
  vat.py             VAT codes + momsdeklaration box engine (SKV 4700)
  invoices.py        numbering, totals, finalize, credit notes
  reports.py         monthly/yearly totals, P&L, CSV exports
  pdf.py             WeasyPrint rendering
  backup.py          backup/restore CLI (also: firma backup)
  security.py        auth, sessions, CSRF
  audit.py           audit trail
  routers/           one module per UI area
  templates/         Jinja2 pages + PDF templates
migrations/          Alembic (0001 = full initial schema)
tests/               65+ tests: VAT math, boxes, rounding, numbering, web flows
docs/                daily use, Skatteverket reporting, backup
```

## Run on NixOS (recommended)

Requirements: NixOS with **flakes enabled** (or use `shell.nix` with
`nix-shell`). WeasyPrint's native dependencies (pango, cairo, gdk-pixbuf,
harfbuzz, fontconfig, glib, libffi, zlib, libjpeg, openjpeg, freetype,
libxml2, libxslt) and fonts (DejaVu, Liberation) come from the flake.

```bash
cd firma
nix develop            # enters shell with python312 + uv + all native libs
uv sync                # installs pinned Python deps (uv.lock)
uv run uvicorn app.main:app --reload
# open http://127.0.0.1:8000  → first-run wizard creates your local login
```

Your company profile is already configured from your Skatteverket documents
(Registerutdrag SKV 4621 + Beslut debiterad preliminärskatt) by running:

```bash
uv run python scripts/set_company_profile.py   # already applied to data/firma.db
```

Applied settings: **Saddam Hussain**, org.nr **830116-0571**, momsreg.nr
**SE830116057101**, **Godkänd för F-skatt** (fr.o.m. 2026-09-14),
momsregistrerad fr.o.m. 2026-09-15, **kvartalsvis** momsredovisning med
**bokslutsmetoden (kontantmetoden)**, kalenderår, betalningsvillkor 10 dagar
(enligt din fakturamall). **Bankuppgifter saknas medvetet** — Bankgiron på
samplefakturan tillhör ett annat företag (Nordic Taxi och Gods Transport AB);
fyll i dina egna under Inställningar. Telefon/e-post fanns inte i dokumenten.

Demo data (separate throwaway profile) can still be tried with:

```bash
uv run python -m app.seed
```

### Install as a package (offline runtime, no dev shell)

```bash
nix profile install .          # from the project directory
firmabok init                  # create/migrate DB in ~/.local/share/firmabok
firmabok serve                 # http://127.0.0.1:8000
firmabok backup                # timestamped backup
```

### WeasyPrint/PDF troubleshooting on NixOS

If the PDF button reports missing pango/cairo/gobject libraries, your server
process lacks `LD_LIBRARY_PATH`. Bullet-proof starter (works in *any* shell,
with or without nix-shell, activates `.venv` automatically):

```bash
scripts/run.sh                 # computes LD_LIBRARY_PATH from nixpkgs, starts uvicorn
```

The app also self-heals: if WeasyPrint fails to load its libs on NixOS, it
computes the path via `nix-instantiate` and re-executes itself once.

### Without Nix (any Linux/macOS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# WeasyPrint needs system libs: pango cairo gdk-pixbuf harfbuzz fontconfig …
# (Debian/Ubuntu: sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0)
uvicorn app.main:app --reload
```

## First steps

> **Troubleshooting:** if `uv sync` fails with `TOML parse error … missing
> field 'distribution'`, your `uv` is too old (nixos-stable channels ship an
> ancient one). Fix: use `nix develop` (the flake provides a modern uv), or
> skip uv: `python3 -m venv .venv && source .venv/bin/activate &&
> pip install -r requirements.txt`, or let the old uv re-resolve:
> `rm uv.lock && uv sync`.

1. Open `http://127.0.0.1:8000` → create your local user (first run).
2. **Inställningar** → fill in company profile: namn, org.nr (`XXXXXX-XXXX`,
   LUHN-validated), momsreg.nr (`SE` + org.nr + `01`, validated), F-skatt,
   address, bank (Bankgiro/Plusgiro/IBAN/BIC), logo, invoice defaults.
3. **Inställningar → Bokföring**: fiscal year (calendar by default,
   brutet år supported), momsperiod (**kvartalsvis** default, also
   månadsvis/årsvis), standard VAT rate.
4. Register income under **Intäkter** (per week/month — date driven),
   expenses under **Utgifter** (receipt upload supported).
5. Create invoices under **Fakturor**: draft → review → **Fastställ**
   (assigns the next sequential number `ÅÅÅÅ-NNNN`, due date, OCR) →
   download PDF. Corrections: **kreditfaktura** (never delete/edit a
   finalized invoice — gapless numbering is a legal requirement).
6. **Moms**: pick period → see declaration boxes (fält 05–62) → export
   CSV/PDF → **Spara & lås** when filed.
7. **Rapporter**: P&L, monthly grid, category breakdown; CSV exports for
   bokföringsorder and NE-bilaga support material.
8. **Ägare**: record egna uttag/insättningar (kept out of P&L and VAT).
9. **Data**: one-click backup (DB + uploads + sha256 manifest), restore,
   JSON export, audit log.

## Invoice numbering

- Series per fiscal year: `2026-0001`, `2026-0002`, … (prefix/digits/start
  configurable).
- Numbers are consumed **only when an invoice is finalized** → drafts can
  be deleted without creating gaps.
- Finalized invoices are immutable and undeletable; fix mistakes with a
  credit note (gets its own number, negative lines, references original,
  marks the original "Krediterad").
- OCR = invoice-number digits + LUHN check digit ( Swedish bank standard).

## Tests

```bash
uv run pytest        # 65+ tests
```

Covers: öre-exact VAT math and half-up rounding, the "VAT is never 25 % of
profit" regression, all momsdeklaration box mappings (incl. reverse charge,
imports, exempt/EU sales), box 49 whole-kronor rule, gapless numbering,
credit notes, P&L (owner transactions excluded), CSV exports, auth/CSRF,
and full web flows.

## Backup & restore

```bash
uv run python -m app.backup backup     # or scripts/backup.sh (cron-friendly)
uv run python -m app.backup list
uv run python -m app.backup restore <backup-name>   # stop the app first
```

Backups are plain directories in `data/backups/` containing a consistent
SQLite copy (online backup API, WAL-safe), the uploads folder and a
`manifest.json` with a sha256 checksum. Restoring automatically takes a
safety copy of the current state first. See `docs/backup_restore.md`.

## Compliance notes

- **Bokslutsmetoden (kontantmetoden)** is implemented per your SKV
  registration: output VAT is reported when the customer has **paid**
  (payment date), and unpaid items are swept into the fiscal year's last
  period at the latest. Input VAT defaults to the simplification rule
  (deduct when booked, turnover < 1 Mkr); a setting switches it to
  payment-date basis. **Remember to register payment dates on income!**
- Momsdeklaration boxes follow Skatteverket's current form (SKV 4700):
  sales boxes 05–08, output VAT 10–12, reverse-charge purchases 20–24 with
  output VAT 30–32, exempt/EU sales 35–42, input VAT 48, import 50 with
  60–62, and box 49 = (10+11+12+30+31+32+60+61+62) − 48 in whole kronor
  (ML 1994:200 1 kap. 7 § — the ledger keeps öre precision).
- Reverse charge sales (byggtjänster, EU B2B services/goods) are supported
  per invoice line: text "Omvänd skattskyldighet" on the PDF, no VAT
  charged, correct box mapping (41/39/35/36/40).
- Non-deductible VAT (e.g. representation above the deduction limit) is
  handled by the per-expense "avdragsgill moms" field — the remainder
  becomes part of the cost, as it should for an enskild firma.
- Swedish formatting everywhere: `YYYY-MM-DD`, `1 234,56 kr`.
