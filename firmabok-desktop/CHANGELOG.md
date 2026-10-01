# Changelog

## Unreleased — Phase 2: auth UI (login, signup, recovery, forgot password)

Additive only: no schema change (no migration), no existing screen, core rule
or translation altered. The legacy app lock (`ui/lock.py` + `core/auth.py`)
and the first-run wizard are untouched and still work exactly as before.

### Added
- `ui/auth/` package: `AuthGate` startup dialog + six bilingual screens
  (SV/EN, instant switch via a light-variant language pill):
  - **Login** — centered 420px card, email + password, "Remember me"
    (stores ONLY the email in settings.json — never a password/session),
    "Forgot password?" and "Create account" links, and visible rate-limit
    feedback: the keyed `auth.too_many_attempts` banner plus a live
    countdown ("Wait {n} s…") that disables the form while locked.
  - **Signup** — display name, email, password + confirm, live strength
    meter (pure deterministic 0–4 estimator with a small common-password
    blocklist), show/hide eye toggles, inline validation; core `AuthError`
    keys are mapped to the offending field.
  - **Recovery code** — the single-use 24-char code (6 × 4 groups) shown
    exactly once: monospace selectable display, copy / download (.txt) /
    print, prominent warning, and a required "I have saved my recovery
    code" checkbox that gates Continue.
  - **Forgot password** — 3 steps (email → recovery code → new password);
    step 1 never reveals account existence; on success the consumed code is
    replaced, the NEW code is shown once, then the user is logged in
    automatically.
  - **Recovery code lost** — honest offline message (no email resets, no
    backdoor; data stays on disk; a .bokvakt backup can be imported on a
    fresh install) + back to login.
  - **First-run welcome** — Create account / Import existing data (restores
    a Phase-1 `.bokvakt` archive: password prompt → `restore_backup_archive`
    → engine dispose → re-migrate → Login; adopts the restored language).
- `ui/main.py` wiring (additive): accounts exist → Login gate; true first
  run (no accounts) → Welcome gate, then the existing FirstRunWizard as
  before; users with no accounts and a completed wizard never see the gate
  (byte-identical legacy flow, incl. the old lock screen).
- `core/accounts.py`: public `validate_email_format()` (UI inline checks)
  and public `CODE_GROUPS`/`CODE_GROUP_LEN` constants (UI input mask).
- Approved change: recovery codes upgraded 16 → **24 characters**
  (`XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`, 6 groups of 4): `_CODE_GROUPS` 4→6;
  the normalizer already accepted any group count, and one approved test
  line changed (`CODE_RE` `{3}`→`{5}` in `test_accounts.py`).
- `ui/theme.py`: appended `QToolButton#langBtnLight` QSS (light-background
  variant of the header language pill, same design tokens).
- 9 new Lucide-style icons: eye, eye-off, copy, printer, key-round,
  arrow-left, user-plus, log-in, shield-check.
- i18n: +48 keys in both catalogs (1062 → 1110, parity tested).
- Tests: `tests/ui/test_auth_screens.py` (30) + `tests/ui/test_auth_gate.py`
  (14) + 2 new core tests; approved one-line `CODE_RE` update.

### Notes / decisions
- "Remember me" deliberately remembers only the email; persistent
  stay-logged-in sessions (and persistent rate limiting) are deferred to
  the Phase 3 security settings work.
- Core auth calls run synchronously (same pattern as the legacy lock
  screen); an Argon2id verify takes a few hundred ms — acceptable pre-app,
  with a "Logging in…" busy state on the button.
- Esc = back on sub-screens; Esc on Login/Welcome/Recovery quits (same
  semantics as cancelling the first-run wizard). The recovery screen has no
  back button — it is the one and only showing of the code.
- Legacy vs new auth coexist until the consolidation phase: logging in via
  `AuthGate` skips the legacy lock screen at startup, but the header Logout
  button still routes to the legacy lock (documented, planned for the
  consolidation phase).

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
