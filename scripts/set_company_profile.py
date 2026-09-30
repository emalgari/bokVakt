"""One-time: apply company data extracted from the user's Skatteverket documents.

Sources:
  * Registerutdrag SKV 4621 (2026-09-15): F-skatt fr.o.m. 2026-09-14,
    momsregistrerad fr.o.m. 2026-09-15, momsreg.nr SE830116057101,
    redovisningsperiod: varje kalenderkvartal, redovisningsmetod:
    bokslutsmetoden (kontantmetoden), räkenskapsår: kalenderår (bokslut
    31 dec), SNI 49.320 + 62.100, huvudsaklig verksamhet: icke-reguljär
    vägtransport, passagerartrafik.
  * Beslut debiterad preliminärskatt (2026-09-14): namn/adress.
  * sample_Faktura.pdf: mall-layout, betalningsvillkor 10 dagar,
    dröjsmålsräntetext.

OBS: Bankuppgifter (Bankgiro 5360-6224 m.m.) på samplefakturan tillhör
Nordic Taxi och Gods Transport AB — ett ANNAT företag — och har därför
MEDVETET inte övertagits. Fyll i dina egna bankuppgifter i Inställningar.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_session_factory
from app.invoices import get_profile
from app.main import run_migrations, seed_reference_data
from app.swedish import normalize_org_nr, normalize_vat_number, vat_matches_org_nr


def apply() -> None:
    run_migrations()
    db = get_session_factory()()
    try:
        seed_reference_data(db)
        p = get_profile(db)

        p.company_name = "Saddam Hussain"
        p.org_nr = normalize_org_nr("830116-0571")            # LUHN-validerad
        p.vat_number = normalize_vat_number("SE830116057101")  # SE + orgnr + 01
        assert vat_matches_org_nr(p.vat_number, p.org_nr), "momsreg.nr stämmer inte med org.nr"

        p.f_skatt_registered = True
        p.f_skatt_text = "Godkänd för F-skatt"

        p.address_line1 = "Friherregatan 48 lgh 1102"
        p.postal_code = "165 58"
        p.city = "Hässelby"
        p.country = "Sverige"
        # phone/email/website: finns ej i dokumenten — fyll i Inställningar

        p.business_description = "Icke-reguljär vägtransport, passagerartrafik"
        p.sni_codes = "49.320, 62.100"

        # Bokföring (enligt registerutdraget)
        p.fiscal_year_start_month = 1          # kalenderår, bokslut 31 dec
        p.vat_period = "quarter"               # varje kalenderkvartal
        p.vat_method = "bokslut"               # bokslutsmetoden (kontantmetoden)
        p.input_vat_on_payment = False         # förenklingsregeln (omsättning < 1 Mkr)
        p.default_vat_rate = p.default_vat_rate or 25

        # Faktura (enligt sample_Faktura.pdf)
        p.payment_terms_days = 10              # 2026-07-20 → 2026-07-30
        p.late_interest_text = ("Vid betalning efter förfallodagen debiteras "
                                "ränta enligt räntelagen.")
        p.invoice_number_prefix = ""
        p.invoice_number_digits = 4
        p.invoice_number_start = 1
        p.round_total_to_krona = False         # "Avrundning 0,00" som i mallen

        # Bankuppgifter MEDVETET tomma (se modulens docstring)
        db.commit()
        print("Företagsprofil uppdaterad från Skatteverket-dokumenten:")
        print(f"  Namn:        {p.company_name}")
        print(f"  Org.nr:      {p.org_nr}  (LUHN OK)")
        print(f"  Momsreg.nr:  {p.vat_number}  (matchar org.nr)")
        print(f"  F-skatt:     {p.f_skatt_text}")
        print(f"  Moms:        kvartalsvis, bokslutsmetoden, kalenderår")
        print("  Bank:        TOMT — fyll i dina egna uppgifter i Inställningar!")
    finally:
        db.close()


if __name__ == "__main__":
    apply()
