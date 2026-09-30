# Daglig användning / Daily use

## Starta

```bash
cd firma
nix develop
uv run uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

Första gången: skapa ditt lokala konto (endast ett konto behövs för en
enskild firma). Lösenordet hashas med scrypt och lagras bara lokalt.

## Veckorutin (5–10 minuter)

1. **Intäkter** → `+ Ny intäkt`
   - Datum, kund (eller fritextnamn), beskrivning (t.ex. "Konsult v39").
   - Ange belopp **exkl.** eller **inkl.** moms — systemet räknar resten
     (halvöresavrundning per rad, exakt till öret).
   - Momskod: vanlig 25/12/6 %, eller EU/export/omvänd skattskyldighet/
     momsfri (ingen svensk moms tas då ut — rätt deklarationsfält används).
   - Betalstatus: obetald/betald. Markera betald med ✓-knappen i listan.
2. **Utgifter** → `+ Ny utgift`
   - Datum, leverantör, kategori, beskrivning.
   - Ange kvittots totalsumma (inkl. moms) — netto och moms räknas ut.
   - **Avdragsgill moms**: tom = hela momsen (normalt). Minska beloppet vid
     t.ex. representation eller blandad privat/business-användning. Resten
     blir automatiskt en del av kostnaden.
   - Ladda upp kvitto (bild/PDF) — filen sparas lokalt under `data/uploads`.
3. **Ägare** → registrera egna uttag/insättningar när du flyttar pengar
   mellan firmakontot och privatkontot. Dessa påverkar varken resultat
   eller moms (helt korrekt — de är privata transaktioner).

## Fakturera

1. **Fakturor** → `+ Ny faktura` (eller `📄 Faktura`-knappen på en intäkt).
2. Fyll i rader: beskrivning, antal, enhet, pris exkl. moms, momskod.
   (Raderna summeras live i sidfoten av utkastet.)
3. **Fastställ** → fakturan får nästa löpande nummer (`2026-0001`),
   förfallodatum (betalningsvillkor), OCR (fakturanimret + LUHN-siffra) och
   intäkterna bokförs automatiskt (kryssruta, rekommenderat — annars måste
   du lägga in intäkten manuellt under Intäkter).
4. `⬇ Ladda ner PDF` → A4-faktura med svensk formatering, säljarinfo,
   F-skatt-text, momsspecifikation, betalningsbox (BG/PG/IBAN/OCR) och
   dröjsmålsräntetext.
5. Skickad? → `📤 Markera som skickad`. Betald? → `💰 Registrera betalning`
   (delbetalning stöds).
6. Fel i en fastställd faktura? → `↩ Skapa kreditfaktura`. Kreditfakturan
   får ett eget löpande nummer, negativa rader, och originalet markeras
   "Krediterad". Fastställda fakturor kan **aldrig** raderas eller ändras
   (krav på löpande nummerserie utan luckor).

### Omvänd skattskyldighet på faktura

Välj momskod per rad:
- `SE_REVERSE_SALE` — byggtjänster m.m. i Sverige (fält 41). PDF:en skriver
  "Omvänd skattskyldighet: köparen är betalningsskyldig…".
- `EU_GOODS` — varor till EU-företag med giltigt VAT-nr (fält 35;
  periodisk sammanställning krävs — lämnas separat hos Skatteverket).
- `EU_SERVICES` — tjänster till EU-företag, huvudregeln (fält 39).
- `EXPORT_GOODS` / `SERVICES_ABROAD` — försäljning utanför EU (36/40).

Ingen svensk moms läggs på dessa rader — korrekt.

## Moms (kvartalsvis, bokslutsmetoden — din registrering)

**Bokslutsmetoden innebär:** momsen på en försäljning redovisas när kunden
**betalar**, inte när du fakturerar. Obetalda fakturor redovisas senast i
årets sista period (Q4). Registrera därför alltid betalningar
(✓ Betald på intäkter / 💰 Registrera betalning på fakturor) — annars
väntar momsen till bokslutet. Deklaration lämnas senast den 12 i andra
månaden efter periodens slut (Q1 → 12 maj osv).

1. **Moms** → välj periodtyp/år/period.
2. Sidan visar deklarationens fält (05–62) i **hela kronor** (avrundat per
   fält) + exakta öre-belopp, utgående/ingående moms och **fält 49**
   (att betala/få tillbaka).
3. Granska varningarna (t.ex. momsfri kod med pålagd moms).
4. `Spara & lås` när du lämnat deklarationen i Skatteverkets e-tjänst —
   siffrorna fryses (öppna vid rättning).
5. `⬇ CSV` ger fält-för-fält-underlag; `⬇ PDF` en läsbar rapport.

Varningar du bör åtgärda innan deklaration visas överst på sidan.

## Rapporter & deklarationsstöd

- **Dashboard**: månadsrutnät (intäkter, kostnader, moms, resultat per
  månad) + veckointäkter för vald månad + status för aktuell momsperiod.
- **Rapporter**: resultaträkning, kostnadskategorier, månadsöversikt.
  - `Bokföringsorder (CSV)` — alla verifikat i datumordning (intäkter,
    utgifter, ägartransaktioner) med exkl./moms/inkl.-belopp.
  - `NE-bilaga underlag (CSV)` — omsättning, kostnader, resultat,
    momssummor. **Ingen inkomstskatt beräknas** (medvetet).
  - `Resultatrapport (PDF)`.
- CSV:erna använder semikolon + BOM och öppnas korrekt i svensk
  Excel/LibreOffice.

## Inställningar

- **Företagsprofil**: namn, org.nr (valideras med LUHN), momsreg.nr
  (valideras SE+orgnr+01), F-skatt, adress, kontakt, bank, logotyp.
- **Faktura**: betalningsvillkor, dröjsmålsränta, nummerprefix/siffror/
  start, standardnotering.
- **Bokföring**: räkenskapsår (kalender eller brutet), momsperiod,
  standardmomssats.
- **Förenklat läge**: AVSTÄNGT som standard. Aktivering kräver att du
  skriver `JAG FÖRSTÅR`. Läget visar 25 % av vinsten som "moms" —
  medvetet FEL enligt svensk rätt, tydligt märkt, endast för privat
  fingervisning. Momsmodulen visar alltid korrekta siffror.

## Granskningslogg

**Data → Granskningslogg**: varje skapad/ändrad/raderad post loggas med
användare, tidstämpel och före/efter-värden (JSON). Fastställanden av
fakturor och låsning av momsperioder loggas särskilt.
