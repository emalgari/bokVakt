# Backup & restore

All data finns på två ställen:

| Vad | Var |
|---|---|
| Databas (SQLite, WAL) | `data/firma.db` |
| Filer (logotyp, kvitton) | `data/uploads/` |
| Backuper | `data/backups/firma-backup-ÅÅÅÅMMDD-HHMMSS/` |

## Skapa backup

Tre likvärdiga sätt:

```bash
# 1) Webb-UI:  Data → 💾 Skapa backup nu
# 2) CLI:
uv run python -m app.backup backup        # eller: firma backup
# 3) Skript (cron-vänligt):
scripts/backup.sh
```

Innehållet i varje backup:

```
firma-backup-20260929-210000/
├── firma.db          # konsekvent kopia via SQLite online backup API (WAL-säker)
├── uploads/          # logotyp + alla kvitton
└── manifest.json     # tidpunkt, storlek, sha256-kontrollsumma
```

### Automatisk daglig backup (cron på NixOS)

```cron
0 21 * * *  /home/DITTANVÄNDARE/firma/scripts/backup.sh >> /home/DITTANVÄNDARE/firma-backup.log 2>&1
```

**Viktigt**: kopiera `data/backups/` regelbundet till extern disk/moln du
litar på — en backup på samma disk skyddar inte vid diskhaveri.

## Återställ

1. **Stoppa appen** (Ctrl-C / stäng uvicorn).
2. Antingen CLI:

   ```bash
   uv run python -m app.backup list
   uv run python -m app.backup restore firma-backup-20260929-210000
   ```

   eller webb-UI: **Data → Återställ** (skriv `ÅTERSTÄLL` för att bekräfta).
3. Starta om appen och logga in.

Säkerhet:
- Kontrollsumman (sha256) verifieras mot manifestet innan återställning.
- Nuvarande data sparas automatiskt som `pre-restore-…`-backup innan
  något skrivs över.

## Flytta till en annan dator

1. Stoppa appen på gamla datorn, kör en backup.
2. Kopiera backup-mappen (eller hela `data/`-katalogen) till nya datorn.
3. Installera (t.ex. `nix profile install .`), kör `firmabok restore <namn>`
   eller placera `firma.db` + `uploads/` i `FIRMA_DATA_DIR`
   (standard för paketet: `~/.local/share/firmabok`).

## Export (maskinläsbart)

- **Data → Exportera allt (JSON)**: alla tabeller (kunder, intäkter,
  utgifter, fakturor, momsposter, ägartransaktioner) — för arkiv eller
  migration.
- **Data → Ladda ner databasfil**: konsekvent `.db`-kopia.
- **Rapporter → Bokföringsorder (CSV)** per år/månad.
