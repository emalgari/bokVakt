# Firmabok Desktop — Architecture & Directory Tree (v1, planning only — no code yet)

Status: **APPROVED PLAN / AWAITING GREENLIGHT TO CODE**
Confirmed decisions: greenfield PySide6 app · English locale = `en_US` · license = **MIT** ·
first-run setup wizard for arbitrary downloaders · invoice PDF **always Swedish** ·
XDG-compliant storage · `firma/` (FastAPI web app) is a **reference implementation only**;
this repo is self-contained (own ported core + own test corpus).

---

## 1. Directory tree

```
firmabok-desktop/
├── flake.nix                     # Nix flake: packages.default, apps.default, devShells,
│                                 #   wrapQtAppsHook, x86_64-linux + aarch64-linux, flake check
├── pyproject.toml                # PEP 621; deps: PySide6, SQLAlchemy 2, Alembic, WeasyPrint;
│                                 #   console script firmabok-desktop; ruff+pytest config
├── requirements.txt              # pip fallback (no uv required)
├── alembic.ini                   # migration config (script_location = migrations)
├── LICENSE                       # MIT
├── README.md                     # install / run / uninstall (nix + pip), first-run guide
├── CHANGELOG.md
├── ARCHITECTURE.md               # this document
├── .gitignore
├── .github/
│   └── workflows/
│       └── checks.yml            # ruff · pytest (QT_QPA_PLATFORM=offscreen) · nix build ·
│                                 #   nix flake check (matrix x86_64/aarch64)
├── packaging/
│   ├── firmabok.desktop          # Exec=firmabok-desktop, Icon=firmabok, Categories=Office;Finance
│   └── firmabok.svg              # app icon → share/icons/hicolor/scalable/apps/
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py       # full schema (17 tables, ported from reference app)
├── src/
│   └── firmabok/
│       ├── __init__.py           # __version__
│       ├── core/                 # PURE PYTHON DOMAIN — zero Qt imports (import rule: ui→core only)
│       │   ├── __init__.py
│       │   ├── config.py         # XDG paths, settings.json (language, window state, prefs),
│       │   │                     #   single-instance lock path, env overrides for tests
│       │   ├── db.py             # engine/session factory, MoneyType (Decimal-as-text), WAL pragmas
│       │   ├── models.py         # SQLAlchemy 2.0 mapped classes (17 tables, Decimal money)
│       │   ├── money.py          # Decimal arithmetic, half-up öre rounding, sv/en formatters
│       │   ├── swedish.py        # org.nr LUHN, SE…01 VAT-nr, OCR check digit, fiscal periods,
│       │   │                     #   period_of(), filing_due() (12th of 2nd month after period)
│       │   ├── vat.py            # VAT codes → SKV 4700 box engine, bokslutsmetoden effective
│       │   │                     #   dates, declaration result (boxes exact + whole kronor, fält 49)
│       │   ├── invoices.py       # gapless per-fiscal-year numbering, line/total math, finalize,
│       │   │                     #   credit notes, payment registration, Avrundning option
│       │   ├── reports.py        # monthly/quarterly/yearly totals, P&L, categories,
│       │   │                     #   journal/NE/VAT CSV exporters (lang parameter)
│       │   ├── backup.py         # backup/restore (sqlite online backup + uploads + sha256
│       │   │                     #   manifest), export_for_import(), import_from_db() (wizard)
│       │   ├── errors.py         # domain exceptions carrying i18n MESSAGE KEYS + params
│       │   │                     #   (never pre-translated text) e.g. InvoiceError("inv.no_lines")
│       │   ├── pdf.py            # WeasyPrint rendering; render_invoice_pdf() HARD-LOCKED to
│       │   │                     #   locale="sv" (asserts); report PDFs accept lang param
│       │   └── templates/
│       │       ├── invoice_pdf.html      # Swedish-only legal document (replica template)
│       │       ├── vat_report_pdf.html   # follows UI language (support material)
│       │       └── report_pdf.html       # follows UI language
│       ├── i18n/
│       │   ├── __init__.py       # catalog loader, tr(key, **fmt), I18n singleton with
│       │   │                     #   .language property + .changed signal (plain callback bus;
│       │   │                     #   Qt signal wired in ui layer), QLocale factory (sv_SE/en_US),
│       │   │                     #   fmt helpers: money/date/qty/int per locale
│       │   └── locales/
│       │       ├── sv.json       # source-of-truth keys (Swedish strings), identity map
│       │       └── en.json       # English translations (seeded from reference app's 764 keys,
│       │                         #   extended for desktop-only strings; parity-tested)
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── main.py           # entry point: QApplication, XDG bootstrap, single-instance
│       │   │                     #   guard, offscreen-safe init, exit codes
│       │   ├── app.py            # MainWindow: header + QStackedWidget pages + status bar;
│       │   │                     #   changeEvent(LanguageChange) → retranslate cascade
│       │   ├── header.py         # TOP BAR: text/logo brand (aspect-safe, ≤38 px), segmented
│       │   │                     #   nav (overflow QMenu below width threshold), right cluster:
│       │   │                     #   SV|EN pill toggle + Logout (icon+label, returns to lock/
│       │   │                     #   wizard screen); equal heights, hover/focus/active states
│       │   ├── theme.py          # QPalette + QSS from design tokens (see §5), icon loader
│       │   ├── toasts.py         # snackbar widget (success/warning/error/info, auto-dismiss)
│       │   ├── workers.py        # QThread workers: PDF render, backup, restore, import,
│       │   │                     #   exports — progress + done/failed signals, no UI blocking
│       │   ├── translatable.py   # mixin: register retranslate(); LanguageChange walks registry
│       │   ├── models_qt.py      # QAbstractTableModel adapters: localized headerData(),
│       │   │                     #   sortable, right-aligned Decimal columns via delegate
│       │   ├── widgets/
│       │   │   ├── cards.py      # StatCard, SectionCard (shadow, radius, header/body)
│       │   │   ├── tables.py     # DataTable base (zebra, hover, sticky header, empty state
│       │   │   │                 #   overlay with icon + CTA button)
│       │   │   ├── forms.py      # LabeledField (label above input, inline error text),
│       │   │   │                 #   MoneySpinBox/DateEdit with locale masks
│       │   │   └── empty.py      # EmptyState widget
│       │   ├── wizard/
│       │   │   ├── first_run.py  # QWizard: 1 Language → 2 Welcome/License(MIT note) →
│       │   │   │                 #   3 Data location & optional import → 4 Company profile →
│       │   │   │                 #   5 VAT & bookkeeping → 6 Invoice defaults → 7 Summary/Finish
│       │   │   └── import_page.py# pick source DB (web firma.db or other desktop DB), dry-run
│       │   │                     #   counts preview, one-time guard (target must be empty)
│       │   ├── auth/             # Phase 2: startup account gate (core.accounts UI)
│       │   │   ├── gate.py       # AuthGate QDialog: entry decision (accounts → Login,
│       │   │   │                 #   first run → Welcome), navigation, .bokvakt import,
│       │   │   │                 #   auto-login after reset; accounts_exist()
│       │   │   ├── common.py     # AuthScreenBase (centered 420px card), LanguageToggle,
│       │   │   │                 #   PasswordField (eye toggle), strength meter (pure fn)
│       │   │   ├── login_screen.py        # email+password, remember-EMAIL only, lockout
│       │   │   │                          #   banner + countdown (core rate-limit feedback)
│       │   │   ├── signup_screen.py       # name/email/password/confirm, inline validation,
│       │   │   │                          #   AuthError→field mapping
│       │   │   ├── recovery_code_screen.py# 24-char code (6×4) shown once: copy/download/print,
│       │   │   │                          #   required "I saved it" checkbox gates Continue
│       │   │   ├── forgot_password_screen.py # email → code → new password (3 steps)
│       │   │   ├── recovery_lost_screen.py   # honest offline message, back to login
│       │   │   └── welcome_screen.py         # first run: Create account / Import data
│       │   ├── dialogs/
│       │   │   ├── settings_dialog.py   # tabs: Company · Invoice · Bookkeeping · Appearance/
│       │   │   │                        #   Language · Data paths; applies live
│       │   │   ├── about_dialog.py      # version, license MIT, links, runtime info
│       │   │   └── confirm.py           # translated confirm/warn/error dialog helpers
│       │   ├── pages/
│       │   │   ├── dashboard.py  # year selector, month grid, week income, VAT period card,
│       │   │   │                 #   compliance warnings card, simplified-mode banner (off default)
│       │   │   ├── income.py     # list + filters + form dialog + mark-paid + create-invoice
│       │   │   ├── expenses.py   # list + filters + form dialog (receipt attach) + categories
│       │   │   ├── vat.py        # period selector, SKV box table, lock/unlock, CSV/PDF export
│       │   │   ├── invoices.py   # list, editor (lines table), finalize, payments, credit note,
│       │   │   │                 #   PDF preview (QWebEngine-free: external viewer or embedded
│       │   │   │                 #   simple preview via QPdfWidget if available, else open file)
│       │   │   ├── customers.py  # CRUD + validation (LUHN org.nr, VAT-nr)
│       │   │   ├── owner.py      # uttag/insättningar, isolation notice card
│       │   │   ├── reports.py    # P&L, categories, monthly overview, export buttons
│       │   │   └── data_audit.py # backups list/create/restore, JSON export, audit log view
│       │   └── resources/
│       │       ├── icons/        # Lucide SVG set (bundled, one consistent family)
│       │       └── firmabok.svg  # brand mark; text-logo fallback rendered in header.py
│       └── py.typed
├── tests/
│   ├── conftest.py               # tmp XDG dirs, fresh DB per test, qtbot fixtures (offscreen)
│   ├── core/                     # ported reference corpus (95+ tests): money, swedish, vat,
│   │   ├── test_money.py         #   vat_method (bokslutsmetoden), invoices (numbering/credit/
│   │   ├── test_swedish.py       #   rounding), reports, backup/import, pdf_sv_lock
│   │   ├── test_vat.py
│   │   ├── test_vat_method.py
│   │   ├── test_invoices.py
│   │   ├── test_reports.py
│   │   ├── test_backup_import.py
│   │   └── test_pdf_swedish_lock.py   # language=en active → invoice PDF bytes/labels still SV
│   ├── ui/
│   │   ├── test_header.py        # top bar renders SV/EN, sizes 800×600…1920×1080, overflow menu
│   │   ├── test_wizard.py        # full first-run flow incl. validation + import dry-run
│   │   ├── test_language_switch.py   # every page/dialog re-rendered in EN: no SV leakage
│   │   └── test_pages_smoke.py   # each page constructs, populates, retranslate() safe
│   └── test_i18n_coverage.py     # AST scan: no hardcoded user-facing literals in ui/**;
│                                 #   catalog parity sv↔en; every tr() key exists in both
└── docs/
    ├── USAGE.md                  # daily workflow (SV+EN sections)
    ├── SKATTEVERKET.md           # box mapping, bokslutsmetoden, deadlines, NE support
    └── PACKAGING.md              # nix run/profile install, desktop file, uninstall
```

## 2. Layering & dependency rules

1. `ui → core → (sqlalchemy, weasyprint)`; **`core` never imports Qt or i18n catalogs.**
2. `core` raises exceptions with **message keys + params** (`core/errors.py`); the ui layer
   translates at the boundary (`tr(exc.key, **exc.params)`). Core exporters (CSV/report PDF)
   take an explicit `lang` argument; `render_invoice_pdf()` takes **no** language argument
   and internally asserts `locale == "sv"`.
3. `i18n` is imported by `ui` only (plus tests). Formatting lives in `i18n.fmt` backed by
   `QLocale(sv_SE | en_US)`; `core.money` keeps pure-SV formatters for the PDF path so the
   PDF cannot drift with UI language.
4. Money is `Decimal` end-to-end; DB stores exact decimal text (`MoneyType`); Qt models
   display via `fmt.money()`; editors parse locale-tolerantly (accept `1 234,50` and
   `1,234.50`) but store Decimal.

## 3. Data & config (XDG)

- `$XDG_CONFIG_HOME/firmabok/settings.json` — language, locale override, window geometry,
  last page, theme accent, wizard-completed flag. (Language persists across restarts.)
- `$XDG_DATA_HOME/firmabok/app.db` — SQLite (WAL). `$XDG_DATA_HOME/firmabok/uploads/` —
  logos/receipts. `$XDG_STATE_HOME/firmabok/logs/` — rotating logs.
  `$XDG_DATA_HOME/firmabok/backups/` — backup sets (manifest + sha256).
- Env overrides (`FIRMABOK_CONFIG/DATA/STATE`) for tests and portable use; never write into
  the Nix store or the repo.
- Single-instance: lock file in `$XDG_STATE_HOME/firmabok/` (advisory, stale-safe).

## 4. First-run wizard (any GitHub downloader)

Steps: Language (SV/EN, persists immediately) → Welcome (MIT notice, links) → Data
(new XDG store **or** import from an existing Firmabok DB — web `firma.db` or another desktop
DB; dry-run shows counts; import allowed only into an empty target; runs in a worker thread)
→ Company profile (name, org.nr with LUHN check, VAT-nr with SE…01 cross-check, F-skatt,
address, contact, bank destination choice: Bankgiro/Plusgiro/bank account, logo file with
aspect-safe preview) → Bookkeeping (fiscal year start, VAT period month/quarter/year,
redovisningsmetod faktura/bokslut + input-VAT rule) → Invoice defaults (terms days, late
interest text, numbering prefix/digits/start, OCR on/off, Avrundning on/off) → Summary +
Finish (writes profile, stamps wizard-completed, opens Dashboard).
Every wizard string goes through `tr()`; validation messages are keys; the wizard is
re-runnable from Settings → "Run setup wizard again".

## 5. Design system (tokens → QPalette + QSS)

- Type scale 12/14/16/20/24/32 px, one family (system UI stack; Nix: DejaVu/Liberation
  guaranteed present), weights 400/600/700.
- Colors: primary #10314F, accent #FFD166, success #1D5C2B, warning #7A5B00, danger #8C1D1D,
  bg #F5F7FA, surface #FFFFFF, border #D7DDE4, text #1A1D21, muted #667.
- Radii 8 (cards) / 6 (inputs) / 4 (badges); spacing 4/8/12/16/24/32; shadows subtle
  (QGraphicsDropShadowEffect on cards/menus only).
- Buttons: primary/secondary/ghost/danger + disabled + loading (spinner icon swap);
  min height 32 px (target 40 px); icons Lucide SVG, always icon+text for actions.
- Tables: header 12 px semibold muted, row separators 1 px border, hover tint, zebra off by
  default (subtle), numeric columns right-aligned + tabular, sortable via header click.
- Feedback: status bar transient messages + toasts for async results; confirms on every
  destructive action (delete, restore, credit, unlock period).

## 6. i18n mechanics

- JSON catalogs (`sv.json` identity keys, `en.json` translations), parity-tested.
- `tr(key, **params)`; missing key → Swedish fallback + `logging.warning` (dev) + test gate.
- Runtime switch: `I18n.language = "en"` emits `changed`; `Translatable` mixin registry
  re-runs `retranslateUi()`-equivalents on all live widgets; Qt models emit
  `headerDataChanged`; open dialogs subscribe; status/toast text re-issued.
- QLocale: `sv_SE` → `2026-09-29`, `1 234,56 kr`; `en_US` → `2026-09-29`, `1,234.56 SEK`.
  One English locale only; never mixed within a language.
- Accelerators: defined per-language in catalogs with conflict check test (Alt+key unique
  per menu in both languages).
- **Invoice PDF exempt** — see §7.

## 7. Invoice PDF rule (legal)

- `core/pdf.render_invoice_pdf(session, invoice_id)` renders from **persisted DB state only**
  (finalized invoice rows, frozen customer snapshot, company profile) with `locale="sv"`
  hard-coded + asserted; template `invoice_pdf.html` contains no `tr()` calls.
- Test `test_pdf_swedish_lock.py`: set UI language to EN, render, assert Swedish labels and
  byte-identical output vs SV render; assert VAT/numbering fields unaffected by language.
- Report PDFs/CSVs accept `lang` (support material), clearly separated from the invoice path.

## 8. Threading & responsiveness

- All slow work (PDF, backup/restore/import, exports) in `workers.py` QThreads with
  progress/cancel; buttons enter loading state; UI never blocks >50 ms.
- Layouts only (no absolute geometry); QScrollArea wrappers; QSplitter on list/detail pages;
  verified 800×600 → 4K (test matrix asserts no widget `isVisible()` clipping via sizeHints
  and offscreen renders at 4 sizes).

## 9. Packaging & CI

- `flake.nix`: `packages.default` = `buildPythonApplication` (python312, PySide6, weasyprint
  native libs pango/cairo/gdk-pixbuf/harfbuzz/fontconfig/glib/libffi/zlib/libjpeg/openjpeg/
  freetype/libxml2/libxslt), `wrapQtAppsHook`, `QT_QPA_PLATFORM_PLUGIN_PATH` for X11+Wayland
  (qt6.qtwayland in closure), desktop file + hicolor icon installed; `apps.default`;
  `devShells.default` (python, PySide6, ruff, pytest, pytest-qt, uv); systems
  x86_64-linux + aarch64-linux; `nix flake check` runs ruff + pytest + build.
- `.github/workflows/checks.yml`: ruff · pytest (offscreen) · nix build · nix flake check.
- Uninstall: `nix profile remove` + XDG dir removal instructions in README.

## 10. Milestones (implementation order, each gated by tests)

M1 skeleton+core port+tests green · M2 XDG/config/i18n/wizard · M3 shell+top bar+theme ·
M4 pages (dashboard→data/audit) + dialogs · M5 PDF/exports/workers · M6 responsiveness+
design polish pass · M7 packaging/CI/docs/license · final report per acceptance criteria.
