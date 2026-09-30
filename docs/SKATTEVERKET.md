# Skatteverket-reporting guide (moms & NE)

> Firmabok är underlag. Du lämnar alltid deklarationerna själv i
> Skatteverkets e-tjänster och ansvarar för att uppgifterna stämmer.

## 1. Momsdeklaration (SKV 4700) — fältmappning

Firmabok mappar varje post via **momskoder** till deklarationens fält.
Belopp i deklarationen anges i **hela kronor** (ML 1994:200 1 kap. 7 §);
avrundning sker per fält (halvupp), och fält 49 beräknas på de avrundade
fälten precis som på blanketten.

### Försäljning (intäkter & fakturarader)

| Momskod | Används till | Fält (underlag) | Fält (moms) |
|---|---|---|---|
| `SE25` / `SE12` / `SE6` / `SE0` | Momspliktig försäljning i Sverige | 05 | 10 / 11 / 12 / – |
| `EXEMPT` | Momsfri försäljning (bidrag, momsfri hyra m.m.) | 42 | – |
| `EU_GOODS` | Varor till EU-företag med giltigt VAT-nr | 35 | – (även periodisk sammanställning!) |
| `EXPORT_GOODS` | Export utanför EU | 36 | – |
| `EU_SERVICES` | Tjänster till EU-företag (huvudregeln) | 39 | – (även periodisk sammanställning) |
| `SERVICES_ABROAD` | Övriga tjänster tillhandahållna utomlands | 40 | – |
| `SE_REVERSE_SALE` | Omvänd skattskyldighet i Sverige (t.ex. byggtjänster) | 41 | – (köparen redovisar) |

### Inköp (utgifter)

| Momskod | Används till | Fält (underlag) | Utgående | Ingående |
|---|---|---|---|---|
| `SE25_P`/`SE12_P`/`SE6_P`/`SE0_P` | Vanliga svenska inköp | – | – | 48 (avdragsgill del) |
| `NON_DEDUCTIBLE_P` | Inköp utan avdragsrätt | – | – | – (momsen blir kostnad) |
| `EU_GOODS_ACQ` | EU-inköp av varor | 20 | 30/31/32 | 48 |
| `EU_SERVICES_ACQ` | EU-inköp av tjänster (huvudregeln) | 21 | 30/31/32 | 48 |
| `NON_EU_SERVICES_ACQ` | Tjänster från land utanför EU | 22 | 30/31/32 | 48 |
| `SE_RC_GOODS_P` | Varor i Sverige m. omvänd skattskyldighet | 23 | 30/31/32 | 48 |
| `SE_RC_SERVICES_P` | Byggtjänster m.m. i Sverige m. omvänd skattskyldighet | 24 | 30/31/32 | 48 |
| `IMPORT_P` | Import (momsen till Skatteverket, ej Tullen) | 50 | 60/61/62 | 48 |

Vid omvänd skattskyldighet på inköp tar Firmabok upp utgående moms
(30–32/60–62) och avdrag i fält 48 — nettot blir 0 kr att betala, precis
som det ska.

### Fält 49

```
Fält 49 = (10+11+12) + (30+31+32) + (60+61+62) − 48
```
Positivt = moms att **betala**; negativt = moms att **få tillbaka**.
Beräknas på avrundade krontal (som Skatteverkets blankett).

### Din registrering (enligt registerutdrag 2026-09-15)

- Godkänd för F-skatt fr.o.m. **2026-09-14**
- Momsregistrerad fr.o.m. **2026-09-15**, momsreg.nr **SE830116057101**
- Redovisningsperiod: **varje kalenderkvartal**
- Momsdeklaration lämnas **den 12 i andra månaden** efter periodens utgång
  (Q1 → 12 maj, Q2 → 12 aug, Q3 → 12 nov, Q4 → 12 feb)
- Redovisningsmetod: **bokslutsmetoden (kontantmetoden)**
- Räkenskapsår: kalenderår (bokslut 31 december)
- Ej registrerad som arbetsgivare

### Bokslutsmetoden i Firmabok

Firmabok följer din registrerade metod automatiskt (Inställningar →
Bokföring → Redovisningsmetod = Bokslutsmetoden):

| Situation | Redovisas i period |
|---|---|
| Intäkt markerad **Betald** (med betalningsdatum) | betalningsdatumets period |
| Intäkt **delbetald** | betalningsdatumets period + varning (kontrollera allocation manuellt) |
| Intäkt **obetald** | senast räkenskapsårets **sista** period (bokslutet) |
| Utgift (ingående moms) | bokföringsdatum — förenklingsregeln 3 kap. 36 § ML vid omsättning < 1 Mkr |
| Utgift med "Ingående moms per betalningsdatum" på | betalningsdatum (kräver betalningsdatum på utgiften) |

**Viktigt:** registrera betalningsdatum på intäkter (✓ Betald-knappen eller
fakturans "Registrera betalning") — annars hamnar momsen i bokslutsperioden.
En decemberfaktura som betalas i januari redovisas i Q1 nästa år — korrekt
enligt kontantprincipen.

### Arbetsflöde per period (standard: kvartal)

1. Se till att alla intäkter/utgifter för perioden är registrerade
   (fakturor fastställda med "bokför intäkt" ikryssad).
2. **Moms** → välj period → granska fält och varningar.
3. Exportera `CSV (fält för fält)` eller skriv av siffrorna i e-tjänsten
   **Lämna momsdeklaration**. (Firmabok lämnar inte in något.)
4. Efter inlämning: **Spara & lås** perioden. Vid rättning: lås upp,
   korrigera underlaget, generera om och rätta deklarationen hos
   Skatteverket.

### Periodisk sammanställning (EU)

Om du har försäljning med `EU_GOODS` (fält 35) eller `EU_SERVICES`
(fält 39) till momsregistrerade köpare ska du **även** lämna en periodisk
sammanställning. Underlag: filtrera intäkter på dessa koder i
bokföringsorder-CSV:n. Firmabok lämnar inte in denna automatiskt.

## 2. Inkomstdeklaration / NE-bilaga

Firmabok beräknar **ingen inkomstskatt** (medvetet). Systemet ger i stället
underlag:

- `Rapporter → NE-bilaga underlag (CSV)`:
  - Omsättning netto (försäljning exkl. moms)
  - Kostnader per kategori (exkl. avdragsgill moms — icke avdragsgill moms
    ingår i kostnaden, korrekt enligt huvudregeln)
  - Resultat före skatt
  - Egna uttag/insättningar (memo — påverkar inte resultatet)
- `Rapporter → Bokföringsorder (CSV)`: alla verifikat i datumordning,
  användbart för förenklat årsbokslut (K1) eller som underlag till
  bokföringsposterna i NE.

Kontrollera alltid mot Skatteverkets aktuella blankett/instruktion och
särskilda regler (t.ex. periodiseringsfond, expansionsfond, räntefördelning
— dessa hanteras INTE av Firmabok).

## 3. Bokföringslagens krav som systemet hjälper till med

- **Löpande nummerserie utan luckor** på fakturor (nummer ges först vid
  fastställande; utkast kan raderas; fastställda kan bara krediteras).
- **Verifikat/kvitto**: kvitton kan bifogas varje utgift (lokal lagring).
- **Spårbarhet**: granskningslogg (vem/what/när, före/efter) för alla
  ändringar i bokföringsdata.
- **Sjuårsregeln**: radera inte gamla databasfiler — använd backup och
  behåll årsvisa kopior (`data/backups/` + egen extern lagring).

## 4. Avrundningsprinciper

| Var | Princip |
|---|---|
| Rader/intäkter/utgifter | Exakt till öre, halvöresavrundning (ROUND_HALF_UP) per rad |
| Fakturatotaler | Summa av radbelopp (netto+moms=brutto alltid exakt) |
| Momsdeklarationens fält | Hela kronor, halvupp per fält |
| Fält 49 | Summa avrundade utgående fält − avrundat fält 48 |
| Bokslut/rapporter | Öre-exakta belopp |
