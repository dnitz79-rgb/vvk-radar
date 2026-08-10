import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_calendar',ROOT/'src'/'build_calendar.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def test_hsv():
 html='<table><tr><td>RB Leipzig</td><td>Mitgl.-VVK: 13.08.26 ab 10 Uhr</td></tr></table>'
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-13 10:00' for e in mod.detect('HSV','vvk','https://hsv.de/tickets',html))
def test_schalke():
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-12 10:00' for e in mod.from_text('Schalke 04','https://schalke04.de/tickets','Am Mittwoch (12.8.) beginnt um 10 Uhr der nächste Vorverkauf.'))
def test_bayern_second_market():
 html='Der Ticket-Zweitmarkt wird in der Regel freigeschaltet.'
 assert mod.detect('FC Bayern','second_market','https://fcbayern.com/tickets',html)==[]
def test_bayern_specific_date():
 html='Zweitmarkt ab 07.08.2026 um 10 Uhr freigeschaltet.'
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-07 10:00' for e in mod.detect('FC Bayern','second_market','https://fcbayern.com/tickets',html))
def test_psg():
 html='Mise en vente le 18/08/2026 à 10:00 pour le grand public.'
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-18 10:00' for e in mod.detect('PSG','ticket_portal','https://billetterie.psg.fr/fr/',html))
def test_real():
 html='General public tickets on sale 20/08/2026 at 12:00.'
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-20 12:00' for e in mod.detect('Real Madrid','ticket_portal','https://www.realmadrid.com/en-US/tickets',html))
def test_real_available_soon_is_not_event():
 html='Tickets available soon for the match.'
 assert mod.detect('Real Madrid','ticket_portal','https://www.realmadrid.com/en-US/tickets',html)==[]
def test_bvb_calovo():
 html='Beginn des Termins 13 August 2026 12:00 Mitgliedervorverkauf für das Bundesliga-Heimspiel gegen den SC Paderborn 07'
 assert any(e[2].strftime('%Y-%m-%d %H:%M')=='2026-08-13 12:00' for e in mod.detect('BVB','bvb_calovo_vvk','https://calovo.de/f/borussiadortmund/vvk-kalender-bvb-mitglieder',html))
