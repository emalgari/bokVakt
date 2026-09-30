# Changelog — invoice PDF template fix (2026-09-29)

## WeasyPrint @media warnings removed
- `app/templates/invoice_pdf.html`: dropped the
  `@media screen and (max-width: 215mm)` block. WeasyPrint supports media
  types (screen/print/all) but not media feature queries, so the rule was
  ignored and logged `Invalid media type` warnings on every invoice PDF
  render. PDF output is byte-for-byte unaffected (screen rules never apply
  to print media); the browser preview HTML file is separate and untouched.

# Changelog — UI/i18n polish (2026-09-29)

## 1. Language toggle (redesigned)
- Replaced the ad-hoc SV/EN links with an accessible **segmented pill toggle**
  (`role="group"`, `aria-label`, `aria-pressed`, `lang`/`hreflang`, visible
  focus ring, active segment highlighted with the accent colour).
- Height/typography matched to the navbar (32 px pill, 0.78 rem labels);
  compact variant under 600 px.
- Persisted in the `firma_lang` cookie (1 year) — survives reloads,
  navigation and HTMX fragments (all fragments are server-rendered with the
  same cookie).

## 2. Navbar
- Rebuilt as a flex navbar: brand block (ellipsis-truncated company name),
  scrollable menu strip on desktop/tablet, **hamburger dropdown on mobile**
  (`aria-expanded`/`aria-controls`, closes on navigate and Escape).
- `white-space: nowrap` on items + horizontal scroll prevents wrapping,
  clipping and overlap for long Swedish words ("Inställningar",
  "Granskningslogg").
- Active page highlighted with background + accent underline and
  `aria-current="page"`.

## 3. Full language switching
- Catalogs centralized in **`app/locales/sv.json` / `app/locales/en.json`**
  (764 keys, key-parity enforced by test). Swedish is the default and the
  fallback for missing keys; missing EN keys log a warning when
  `FIRMA_DEBUG=1`.
- Swept **all** templates: nav, titles, headings, table headers, form
  labels, placeholders, help texts, select options, badges, empty states,
  confirmation dialogs (`confirm()`), footers, info paragraphs.
- Swept **all routers**: flash/success/warning/error and validation
  messages now go through `L(request, …)`.
- SKV box descriptions and VAT-code labels are translated in EN mode
  (box *numbers* and code identifiers stay language-neutral).
- Locale-aware formatting: SV `1 234,56 kr` (NBSP thousands, comma decimal);
  EN `1,234.56 SEK` (comma thousands, dot decimal). Dates ISO `YYYY-MM-DD`
  in both languages. Month names localized. Formats never mixed.
- CSV exports (journal, NE-bilaga, momsdeklaration) and the **report PDFs**
  follow the UI language. **The invoice PDF remains Swedish-only** (legal
  document; explicit product decision) — enforced by test.
- Language switching never touches stored data, invoice numbers, VAT math
  or numbering (regression test asserts identical figures in both langs).

## 4. UI/UX polish
- Zebra striping + hover on all data tables; sticky headers on long lists
  (income, expenses, invoices, audit) inside scroll containers.
- Consistent radii/spacing via CSS variables; clearer card hierarchy.
- Loading spinners (`data-loading`) on slow actions: PDF download, CSV/PDF
  exports, DB download/JSON export, backup creation (`app.js`).
- Success flashes auto-dismiss after 6 s; all flashes are `role="status"`.
- Skip-link, `:focus-visible` outlines, semantic landmarks, aria-current.
- Destructive actions keep translated native confirm dialogs.
- Empty states with call-to-action links on all list pages.
- Responsive: 1200/900/600 px breakpoints; navbar collapses to hamburger;
  grids collapse 4→2→1; tables scroll horizontally; compact controls.

## 5. Functional verification (all re-tested)
- Income/expense CRUD, monthly+yearly totals, VAT output/input/net
  (never on profit), invoice-from-income, gapless per-year numbering,
  PDF invoice template, reports (month/quarter/year/moms/categories),
  CSV/PDF exports, owner transactions excluded from P&L and VAT.
- Test suite: **95 passed, 1 skipped** (skip = WeasyPrint byte-level PDF
  check, requires pango; provided by the Nix flake).

## Notes / keys needing human review (EN)
Accounting terms chosen pragmatically — please review:
- "Bokslutsmetoden (kontantmetoden)" → "Cash method (bokslutsmetoden)"
  (kept the Swedish term in parentheses for recognisability).
- "Förenklingsregeln" → "simplification rule (3 kap. 36 § ML)".
- "Egna uttag / egna insättningar" → "owner withdrawals / contributions".
- "Granskningslogg" → "audit log".
- SKV box descriptions are informative translations only; the authoritative
  Swedish wording remains in SV mode and on Skatteverket's form.
- Restore confirmation word remains the Swedish "ÅTERSTÄLL" in both
  languages (safety word, typed explicitly).
