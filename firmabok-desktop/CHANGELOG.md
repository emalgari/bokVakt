# Changelog

## Unreleased — Phase 1 foundation: accounts + single-file backups (core only, no UI)

Additive only: one new migration (`0006` → revision `c3a7f10b0006`), no
changes to existing tables' columns, VAT logic, invoice numbering, PDF rules
or translations. No UI yet — this phase is pure Python core + tests.

### Added
- `core/accounts.py`: local user accounts in a new `user_accounts` table —
  Argon2id password & recovery-code hashing (argon2-cffi, never plaintext /
  SHA / MD5 / bcrypt), single-use recovery codes (`XXXX-XXXX-XXXX-XXXX`,
  unambiguous alphabet, shown exactly once), password change / recovery
  reset / code regeneration, and in-memory login rate limiting (5 failed
  attempts → 60 s cooldown). All errors carry `auth.*` translation keys.
  Login never reveals whether an account exists.
- `core/backup.py`: single-file `.bokvakt` backups alongside the legacy
  directory backups (which are untouched): `create_backup_archive`,
  `restore_backup_archive`, `list_backup_archives`, `prune_old_backups`.
  One file = SQLite DB (online-backup snapshot) + uploads + settings.json +
  manifest.json. Encryption: AES-256-GCM with an Argon2id-derived key; the
  KDF header is bound as GCM additional data, so wrong passwords and any
  tampering are rejected (`backup.wrong_password` / `backup.corrupt` /
  `backup.checksum`) and never yield partial data. Restore verifies the
  archive first, then ALWAYS writes an unencrypted safety archive to
  `$XDG_STATE_HOME/bokVakt/safety-backups/` before replacing live data.
  Default file name: `bokVakt-backup-YYYY-MM-DD-HHMM.bokvakt`.
- `tax_parameters` (existing table since 0004) gains two user-owned columns:
  `kommun_name` (which municipality the rates belong to) and `total_rate`.
  Existing columns keep their roles (municipal_rate ≙ `municipal_tax_pct`,
  funeral_rate ≙ `burial_pct`); the tax-estimate logic is unchanged.
- `config.py`: `BRAND_NAME` ("bokVakt"), `brand_state_dir()`,
  `reload_settings()`; `errors.py`: `AuthError`.
- Dependencies: `argon2-cffi>=23.1`, `cryptography>=42.0` (pyproject,
  `packaging/app.nix`, `shell.nix`; CI installs them via `pip install -e .`).
- Tests: `test_accounts.py`, `test_backup_archive.py`,
  `test_migration_0006.py` (migration up/down/up + schema assertions).

### Notes / decisions
- `invoice_income_link` was NOT added: invoices already link to income via
  `income_entries.invoice_id` (set on finalize) — a second link table would
  duplicate the relationship.
- Migration numbering: the repository head before this phase was `0004`
  (`525c59bcf550`); there is no `0005`. Per the phase plan the file is named
  `0006_...` and chains directly onto `0004` (the gap is cosmetic — Alembic
  chains by revision id).
- Approved one-line change in `tests/core/test_migrations.py`: the 0004
  downgrade target is pinned to revision `a9e5e7d2d9d8` instead of relative
  `"-1"`, so that test keeps verifying 0004 as new head migrations arrive.
  All assertions unchanged; 0006 has its own dedicated migration test.

## 1.1.1 — invoice template CSS fix (2026-09-29)

### Fixed
- Removed the `@media screen and (max-width: 215mm)` rule from
  `invoice_pdf.html`: WeasyPrint supports media *types* (screen/print/all)
  but not media *feature* queries, so the rule was ignored with two
  `Invalid media type` warnings on every invoice PDF render. PDF output is
  unchanged (screen rules never applied to print media).
- Version bumped to match the 1.1.0 feature release (was still 1.0.0).

## 1.1.0 — gig income, vehicles, quarterly VAT overview, tax documents, payroll

Additive release: one new migration (`0004`), no changes to existing tables'
columns, no changes to VAT logic, invoice numbering or the invoice PDF.

### Added
- Platform/gig income: source type on income entries, user-configurable
  platform list, filters, invoice-to-platform-customer via normal flow.
- Vehicles registry + expense attribution (vehicle, employee, mileage) and
  new default expense categories (all renameable/removable).
- Quarterly VAT overview page: per-quarter output/input/net, mark-as-filed
  with filing date, CSV/PDF export per quarter, configurable deadline defaults.
- Tax documents section (XDG uploads) with user-entered key figures and a
  transparent income-tax estimate from user-owned parameters (not tax advice).
- Employees & salary slips: employment types (monthly/hourly/% of
  revenue/contract), sequential per-year slip series, Swedish-only slip PDF,
  employer contributions & youth reduction from editable parameters
  (labelled Skatteverket 2026-03-31 defaults), personnel cost booked only
  on payment (cash method), per-employee car-cost summaries.
- Settings → "Listor & standardvärden": platforms, vehicles, categories,
  payroll & tax parameters.
- i18n: ~150 new keys, SV/EN parity enforced by the existing gates.
- Tests: +53 (148 total) incl. migration up/down, salary PDF Swedish-lock
  under EN session, youth-reduction math, attribution and filing flows.

## 1.0.0 — initial desktop release

Greenfield PySide6/Qt 6 desktop edition of Firmabok for Swedish enskild
firma, built per approved architecture (ARCHITECTURE.md). Business logic
ported from the battle-tested reference implementation (FastAPI web app,
95-test corpus) — not rewritten semantics: same VAT engine (SKV 4700 box
mapping, fakturametoden + bokslutsmetoden), same gapless invoice numbering,
same öre-exact Decimal math, same Swedish-only invoice PDF template.

### Highlights
- Full SV/EN UI with instant runtime switching (JSON catalogs, 880 keys,
  parity + coverage gates in tests; QLocale sv_SE / en_US formatting).
- Invoice PDF hard-locked to Swedish; report PDFs/CSVs follow UI language.
- First-run wizard: language → data/import → company (LUHN/SE…01 validated)
  → bookkeeping/VAT method → invoice defaults → optional app password.
- Design system (QSS tokens, cards, tables, toasts, empty states, loading
  workers) + responsive top bar with overflow menu, accessible SV|EN pill
  toggle (aria-pressed), settings gear, logout → lock screen.
- XDG-only storage; single-instance lock; Alembic migrations; audit log;
  backups with sha256 manifest; one-time DB import.
- Nix: flake with packages.default/apps.default/checks/devShell
  (x86_64 + aarch64), wrapQtAppsHook, Wayland+X11, desktop file + icon,
  GitHub Actions (ruff, pytest offscreen, nix flake check, nix build).
- Quality gates: **95 tests passed / 0 skipped** in a pango-equipped env
  (2 PDF byte-tests run when WeasyPrint native libs exist; they are
  `importorskip`-guarded otherwise), ruff clean.

### Visual verification round (offscreen screenshots, `scripts/screenshots.py`)
Rendered every key page at 800×600 / 1280×800 / 1920×1080 in SV and EN and
inspected the PNGs. Defects found and fixed:
- SVG icons invisible (`currentColor` + QBuffer path) → render via
  QSvgRenderer/QByteArray with explicit stroke color.
- Nav collapsed to overflow too early → added a compact text-only nav stage
  between full and overflow; overflow menu-indicator arrow removed.
- QSpinBox arrows visually detached → native spin chrome retained.
- Pages squashed at short window heights → every page wrapped in a
  QScrollArea; stat cards reflow 4→2→1 columns; tables scroll internally
  instead of widening the page (no horizontal page scroll at 800 px).
- Month tables sorted alphabetically by month name → chronological
  (sorting disabled on month grids; kept where keys are ISO dates/numbers).
- Page navigation did not switch the stacked widget after the scroll-area
  refactor → fixed + regression test `test_navigation_shows_requested_page`.
- EN mode mixed Swedish unit ("11725 kr") → locale unit via tr('kr') and
  grouped thousands (fmt.int).
Verified artifacts: `preview/desktop/*.png` + `faktura_sample_en_session.pdf`
(single A4 page, fully Swedish under an EN session).
