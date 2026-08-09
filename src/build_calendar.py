import json, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/sources.json"
OUT = ROOT / "public/vvk-radar.ics"
UA = "VVK-Radar/4.1"


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


def parse_date_time(text, default_year=None, default_hour=10):
    out = []
    for m in DATE_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        raw_year = m.group(3)
        year = int(raw_year) if raw_year else (default_year or datetime.now().year)
        if year < 100:
            year += 2000
        tm = TIME_RE.search(text[m.end():m.end() + 40])
        if tm:
            hour = int(tm.group(1) or tm.group(3))
            minute = int(tm.group(2) or 0)
        else:
            hour, minute = default_hour, 0
        try:
            out.append(datetime(year, month, day, hour, minute))
        except ValueError:
            pass
    return out


def make_event(club, kind, url, dt):
    title = f"🔥 {club} | VVK" if club == "FC Bayern" else f"{club} | VVK"
    if kind.startswith("second_market"):
        title = f"🔥🔥 {club} | ZWEITMARKT"
    uid = hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}".encode()).hexdigest() + "@vvk-radar"
    return uid, title, dt, url, kind


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
            for dt in parse_date_time(cell, default_year=now.year):
                if dt >= now - timedelta(days=1):
                    events.append(make_event(club, "vvk", url, dt))
    return list({(e[0], e[2]): e for e in events}.values())


def detect_vvk_fallback(club, url, html):
    """Conservative fallback only. Weekend dates are rejected because free text
    pages commonly contain match dates next to ticket terminology."""
    text = clean(html)
    keyword = re.compile(r"(?i)(vorverkauf|vorverkaufstermin|verkaufsstart|mitglieder|freier vorverkauf|ticketverkauf)")
    if not keyword.search(text):
        return []
    events = []
    for m in DATE_RE.finditer(text):
        window = text[max(0, m.start()-180):min(len(text), m.end()+260)]
        if not keyword.search(window):
            continue
        dt = parse_date_time(m.group(0), default_year=datetime.now().year)
        if not dt:
            continue
        value = dt[0]
        if value < datetime.now() - timedelta(days=1):
            continue
        if value.weekday() >= 5:
            continue
        events.append(make_event(club, "vvk", url, value))
    return list({(e[0], e[2]): e for e in events}.values())


def detect_second_market(club, kind, url, html):
    text = clean(html)
    keyword = re.compile(r"(?i)(zweitmarkt|ticket exchange|ticketbörse|resale)")
    if not keyword.search(text):
        return []
    # Do not manufacture dates from ordinary match listings. This source type
    # is intentionally handled conservatively until an explicit sale timestamp
    # is published by the club.
    return []


def detect(club, kind, url, html):
    if kind == "vvk":
        structured = detect_vvk_from_tables(club, url, html)
        return structured if structured else detect_vvk_fallback(club, url, html)
    if kind.startswith("second_market"):
        return detect_second_market(club, kind, url, html)
    # fixtures and other informational sources must never create VVK events.
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
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VVK Radar V4.1//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:⚽ VVK Radar","X-WR-TIMEZONE:Europe/Berlin"]
    for e in sorted(unique.values(), key=lambda x: x[2]):
        lines += event_lines(*e)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\r\n".join(lines)+"\r\n", encoding="utf-8")
    print(f"Wrote {len(unique)} events")

if __name__ == "__main__":
    main()
