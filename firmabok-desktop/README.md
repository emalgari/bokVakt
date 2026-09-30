# Firmabok Desktop

Local-first **Qt 6 / PySide6** bookkeeping, VAT (moms) and invoicing app for
Swedish sole proprietorships (**enskild firma**). Fully bilingual
**Svenska/English** UI — invoice PDFs are always Swedish (legal requirement).
No cloud, no external APIs, no telemetry. MIT licensed.

> ⚠️ Firmabok is bookkeeping *support material*. It computes moms per Swedish
> rules and maps figures to the momsdeklaration (SKV 4700) boxes, but you
> review and file everything yourself in Skatteverket's e-services. Income
> tax is intentionally **not** calculated.

## Features

- Dashboard: year/month totals, current VAT period, compliance warnings
- Income & expenses: VAT codes → SKV boxes, per-row öre-exact Decimal math,
  receipts, deductible-VAT handling (representation etc.)
- VAT: monthly/quarterly/yearly declarations, **fakturametoden &
  bokslutsmetoden (kontantmetoden)**, lock/unlock filed periods, CSV/PDF export
- Invoices: gapless per-fiscal-year numbering (`2026-0001`), finalize →
  immutable, credit notes, OCR (LUHN, toggleable), Avrundning option,
  Bankgiro/Plusgiro/bank-account destination choice, **Swedish A4 PDF**
  (WeasyPrint) rendered only from persisted DB state
- Owner finances: egna uttag/insättningar kept out of P&L and VAT
- Reports: P&L, categories, monthly grid, journal/NE-bilaga CSV, report PDFs
  (follow UI language)
- Data: backups (sha256 manifest), restore, JSON export, audit log
- First-run **setup wizard** incl. one-time import from an existing Firmabok DB
- Optional local password (scrypt) with lock screen
- **Gig/platform income (1.1):** income source "Direct customer" vs
  "Platform" with a fully user-configurable platform list (nothing is
  pre-seeded); weekly/monthly aggregate rows flow into totals, VAT and
  reports like any income; invoices to platform companies use the normal
  customer/invoice flow
- **Vehicle expenses (1.1):** vehicles registry, expenses attributable to a
  vehicle and/or an employee, mileage field, and default (renamable/removable)
  categories: Transportstyrelsen, trängselskatt & vägtullar, bränsle &
  laddning, bilfinansiering, parkering, fordonsförsäkring, service &
  reparation, övrigt
- **Quarterly VAT overview (1.1):** all four quarters on one page
  (output/input/net per quarter), mark as filed with filing date, per-quarter
  CSV/PDF export; deadlines come from user-editable defaults, not hardcoded law
- **Tax documents (1.1):** upload Skatteverket documents (slutlig skatt,
  preliminärskatt, momsdeklarationer, correspondence) into the local XDG
  uploads folder; key figures are user-entered/correctable; transparent income
  tax estimate built ONLY from your own parameters — **not tax advice**
- **Employees & salary slips (1.1):** employee records (personnummer stored
  locally and masked), employment types (fixed monthly, hourly, % of revenue,
  contract), sequential per-fiscal-year slip numbering (separate series from
  invoices), **Swedish-only lönespecifikation PDF** (same rule as invoices),
  employer contributions from user-editable rates (labelled Skatteverket 2026
  defaults incl. the temporary youth reduction — verify yourself), personnel
  cost booked as expense only when the slip is marked paid (cash method), and
  per-employee car-cost summaries

## Install & run (NixOS / Nix)

```bash
nix run .                                          # from this directory
nix run github:USERNAME/firmabok-desktop           # or straight from GitHub
nix profile install github:USERNAME/firmabok-desktop
firmabok-desktop                                   # after install
```

If your Nix has flakes disabled (error: *experimental feature 'nix-command'
is disabled*), either pass flags once:

```bash
nix --extra-experimental-features 'nix-command flakes' run .
```

enable them per-user (no root, no configuration.nix):

```bash
mkdir -p ~/.config/nix
echo 'experimental-features = nix-command flakes' >> ~/.config/nix/nix.conf
```

or use the **legacy, flake-free** entry points:

```bash
nix-build          # -> ./result/bin/firmabok-desktop
./result/bin/firmabok-desktop
nix-shell          # legacy dev shell (then: uv sync && uv run firmabok-desktop)
```

The flake provides `packages.default`, `apps.default`, `checks.default` and a
devShell for x86_64-linux and aarch64-linux, with `wrapQtAppsHook` (Qt
platform plugins, image formats, styles), Wayland + X11 support
(`qt6.qtwayland`), and WeasyPrint's native libraries wired in. No changes to
`configuration.nix`, Home Manager or nix-ld are needed.

**Uninstall:** `nix profile remove firmabok-desktop`, then optionally delete
`~/.local/share/firmabok`, `~/.config/firmabok`, `~/.local/state/firmabok`.

## Install & run (pip / uv, any Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # installs deps AND the firmabok-desktop command
firmabok-desktop
# without installing: PYTHONPATH=src python3 -m firmabok.ui.main
```
WeasyPrint needs system libs (pango, cairo, gdk-pixbuf, harfbuzz, fontconfig,
glib, libffi, freetype, libjpeg, openjpeg, libxml2, libxslt). On NixOS use the
flake or `nix-shell` instead.

## First run

1. Pick language (SV/EN) — switchable any time from the header pill or
   Visa → Språk; persisted in `$XDG_CONFIG_HOME/firmabok/settings.json`.
2. Choose data location; optionally **import** an existing Firmabok database.
3. Enter company details (org.nr LUHN-validated, momsreg.nr `SE…01`
   cross-checked), bookkeeping settings (fiscal year, VAT period,
   redovisningsmetod) and invoice defaults.
4. Optionally set an app password (lock screen).

## Data locations (XDG)

| What | Where |
|---|---|
| Settings | `$XDG_CONFIG_HOME/firmabok/settings.json` |
| Database | `$XDG_DATA_HOME/firmabok/app.db` |
| Uploads (logos, receipts) | `$XDG_DATA_HOME/firmabok/uploads/` |
| Backups | `$XDG_DATA_HOME/firmabok/backups/` |
| Logs | `$XDG_STATE_HOME/firmabok/logs/` |

Nothing is ever written inside the Nix store or the repository.

## Development

```bash
nix develop                                   # python312 + PySide6 + ruff + uv
uv sync
uv run firmabok-desktop                       # run the app
QT_QPA_PLATFORM=offscreen uv run pytest       # tests (95)
uv run python3 scripts/screenshots.py         # offscreen UI screenshots + sample PDF
uv run ruff check src tests                   # lint
nix flake check                               # lint+tests+build via nix
```

CI (GitHub Actions `.github/workflows/checks.yml`): ruff · pytest (offscreen)
· `nix flake check` · `nix build` on x86_64 + aarch64.

## Compliance notes

- VAT = output VAT on taxable sales − deductible input VAT. **Never on profit.**
- Momsdeklaration boxes per current SKV 4700 (05–08, 10–12, 20–24, 30–32,
  35–42, 48, 49, 50, 60–62); box 49 from whole-kronor boxes (ML 1994:200
  1 kap. 7 §); ledger keeps öre precision (ROUND_HALF_UP per row).
- Invoice numbering: sequential per fiscal year, numbers consumed only at
  finalize; finalized invoices immutable (corrections via credit notes).
- Invoice PDF always Swedish, always rendered from persisted DB state.
- **Salary slip (lönespecifikation) PDF always Swedish**, same rule; both are
  rendered only from persisted DB state.
- No Swedish legal values are hardcoded: employer-contribution rates, youth
  reduction parameters, VAT deadline day/offset and income-tax percentages are
  user-editable settings shipped with clearly-labelled defaults
  (source note: Skatteverket 2026-03-31). The tax-documents estimates are
  user-provided data and **not tax advice**.

See `docs/SKATTEVERKET.md` and `docs/USAGE.md`.

## License

MIT — see LICENSE.
