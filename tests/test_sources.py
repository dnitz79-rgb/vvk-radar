import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_calendar", ROOT / "src" / "build_calendar.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_hsv_table_style_vvk():
    html = """
    <table><tr><td>So., 13.09.26 15.30 Uhr</td><td>RB Leipzig</td>
    <td>Mitgl.-VVK: 13.08.26 ab 10 Uhr Kein freier VVK</td></tr></table>
    """
    events = mod.detect_vvk_from_tables("HSV", "https://hsv.de/tickets", html)
    assert any(e[2].strftime("%Y-%m-%d %H:%M") == "2026-08-13 10:00" for e in events)


def test_schalke_news_style_vvk():
    html = "Am Mittwoch (12.8.) beginnt um 10 Uhr der nächste Vorverkauf."
    events = mod.from_text("Schalke 04", "https://schalke04.de/tickets", html)
    assert any(e[2].strftime("%Y-%m-%d %H:%M") == "2026-08-12 10:00" for e in events)


def test_bayern_does_not_invent_second_market_start():
    html = "Tickets werden in der Spielwoche angeboten. Der Ticket-Zweitmarkt wird in der Regel freigeschaltet."
    assert mod.detect("FC Bayern", "second_market", "https://fcbayern.com/tickets", html) == []


def test_psg_french_sale_keyword():
    html = "Mise en vente le 18/08/2026 à 10:00 pour le grand public."
    events = mod.from_text("PSG", "https://billetterie.psg.fr/fr/", html)
    assert any(e[2].strftime("%Y-%m-%d %H:%M") == "2026-08-18 10:00" for e in events)


def test_real_madrid_english_sale_keyword():
    html = "General public tickets on sale 20/08/2026 at 12:00."
    events = mod.from_text("Real Madrid", "https://www.realmadrid.com/en-US/tickets", html)
    assert any(e[2].strftime("%Y-%m-%d %H:%M") == "2026-08-20 12:00" for e in events)


def test_bvb_calovo_fixture():
    html = "Beginn des Termins 13 August 2026 12:00 Mitgliedervorverkauf für das Bundesliga-Heimspiel gegen den SC Paderborn 07"
    events = mod.detect_calovo_vvk("BVB", "https://calovo.de/f/borussiadortmund/vvk-kalender-bvb-mitglieder", html)
    assert any(e[2].strftime("%Y-%m-%d %H:%M") == "2026-08-13 12:00" for e in events)
