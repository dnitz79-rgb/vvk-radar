import json, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/sources.json"
OUT = ROOT / "public/vvk-radar.ics"
UA = "VVK-Radar/5.0"

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12
}


def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(clean(" ".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:Uhr)?|(?<!\d)(\d{1,2})\s*Uhr")
CALOVO_EVENT_RE = re.compile(
    r"Beginn des Termins\s+(\d{1,2})\s+"
    r"(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+"
    r"(20\d{2})\s+(?:[A-Za-zÄÖÜäöü]+\.?\s*)?"
    r"(\d{1,2}):(\d{2})\s+(.+?)(?=\s+(?:Beschreibung einblenden|Veranstaltungsort:|Details ansehen|Beginn des Termins|Termine aus vergangenen Jahren|Weitere Kalender))",
    re.IGNORECASE
)


def make_event(club, kind, url, dt, source_title=None):
    if kind.startswith("second_market"):
        title = f"🔥🔥 {club} | ZWEITMARKT"
    elif club == "FC Bayern":
        title = f"🔥 {club} | VVK"
    else:
        title = f"{club} | VVK"
    uid = hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}|{source_title or ''}".encode()).hexdigest() + "@vvk-radar"
    return uid, title, dt, url, kind


def detect_bvb_calovo(url, html):
    """Read the official BVB member VVK calendar published through Calovo.

    Calovo identifies the calendar as an official BVB calendar feed and its
    event start ('Beginn des Termins') is the actual VVK timestamp. We use
    that timestamp, not the match date contained in the description. This is
    the primary BVB source because it is purpose-built for VVK dates.
    """
    text = clean(html)
    events = []
    for m in CALOVO_EVENT_RE.finditer(text):
        title = m.group(5).strip()
        if not re.search(r"(?i)vorverkauf|vorverkaufstermin|verkaufsstart|mitgliedervorverkauf|freier vorverkauf", title):
            continue
        month = MONTHS[m.group(2).lower()]
        try:
            dt = datetime(int(m.group(3)), month, int(m.group(1)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            continue
        if dt < datetime.now() - timedelta(days=1):
            continue
        events.append(make_event("BVB", "vvk", url, dt, title))
    return list({(e[0], e[2]): e for e in events}.values())


def detect_vvk_from_tables(club, url, html):
    parser = TableParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    events = []
    now = datetime.now()
    for row in parser.rows:
        sale_cells = [c for c in row if re.search(r"(?i)vvk|vorverkauf|verkaufsstart", c)]
        for cell in sale_cells:
            for m in DATE_RE.finditer(cell):
                day, month = int(m.group(1)), int(m.group(2))
                year = int(m.group(3)) if m.group(3) else now.year
                tm = TIME_RE.search(cell[m.end():m.end() + 40])
                hour = int(tm.group(1) or tm.group(3)) if tm else 10
                minute = int(tm.group(2) or 0) if tm else 0
                try:
                    dt = datetime(year, month, day, hour, minute)
                except ValueError:
                    continue
                if dt >= now - timedelta(days=1):
                    events.append(make_event(club, "vvk", url, dt))
    return list({(e[0], e[2]): e for e in events}.values())


def detect_vvk_fallback(club, url, html):
    """Conservative fallback. Never turn ordinary weekend match dates into VVK."""
    text = clean(html)
    keyword = re.compile(r"(?i)(vorverkauf|vorverkaufstermin|verkaufsstart|mitglieder|freier vorverkauf|ticketverkauf)")
    if not keyword.search(text):
        return []
    events = []
    for m in DATE_RE.finditer(text):
        window = text[max(0, m.start()-180):min(len(text), m.end()+260)]
        if not keyword.search(window):
            continue
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        tm = TIME_RE.search(window)
        hour = int(tm.group(1) or tm.group(3)) if tm else 10
        minute = int(tm.group(2) or 0) if tm else 0
        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        if dt < datetime.now() - timedelta(days=1) or dt.weekday() >= 5:
            continue
        events.append(make_event(club, "vvk", url, dt))
    return list({(e[0], e[2]): e for e in events}.values())


def detect_second_market(club, kind, url, html):
    # Do not manufacture dates from ordinary match listings.
    return []


def detect(club, kind, url, html):
    if kind == "bvb_calovo_vvk":
        return detect_bvb_calovo(url, html)
    if kind == "vvk":
        structured = detect_vvk_from_tables(club, url, html)
        return structured if structured else detect_vvk_fallback(club, url, html)
    if kind.startswith("second_market"):
        return detect_second_market(club, kind, url, html)
    return []


def event_lines(uid, title, dt, url, kind):
    end = dt + timedelta(minutes=30)
    lines = [
        "BEGIN:VEVENT", f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;TZID=Europe/Berlin:{dt.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{esc(title)}",
        f"DESCRIPTION:{esc('Art: '+kind+'\\nOffizielle Quelle: '+url)}",
        f"URL:{url}", "STATUS:CONFIRMED", "TRANSP:OPAQUE"
    ]
    for days, label in [(5,"🔔 VVK in 5 Tagen"),(3,"🔔 VVK in 3 Tagen"),(1,"🔔 VVK morgen")]:
        lines += ["BEGIN:VALARM", f"TRIGGER:-P{days}D", "ACTION:DISPLAY", f"DESCRIPTION:{label}", "END:VALARM"]
    lines += ["BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", "DESCRIPTION:🚨 VVK/Zweitmarkt startet in 30 Minuten", "END:VALARM", "END:VEVENT"]
    return lines


def main():
    sources = json.loads(DATA.read_text(encoding="utf-8"))["sources"]
    events = []
    for s in sources:
        try:
            events += detect(s["club"], s["type"], s["url"], fetch(s["url"]))
        except Exception as exc:
            print("source failed", s["club"], exc)
    unique = {e[0]: e for e in events if e[2] >= datetime.now()}
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VVK Radar V5//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:⚽ VVK Radar","X-WR-TIMEZONE:Europe/Berlin"]
    for e in sorted(unique.values(), key=lambda x: x[2]):
        lines += event_lines(*e)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\r\n".join(lines)+"\r\n", encoding="utf-8")
    print(f"Wrote {len(unique)} events")

if __name__ == "__main__":
    main()
