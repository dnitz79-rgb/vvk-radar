import json, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/sources.json"
OUT = ROOT / "public/vvk-radar.ics"
UA = "VVK-Radar/4.0"


def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


class TableParser(HTMLParser):
    """Extract HTML table rows while keeping cell boundaries."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.buf = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(clean(" ".join(self.cell)))
            self.cell = None
            self.buf = []
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)")
DATE_SHORT_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?![./-]\d)")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:Uhr)?|(?<!\d)(\d{1,2})\s*Uhr")


def parse_date_time(text, default_year=None, default_hour=10):
    """Return all explicit date/time pairs found in a VVK cell."""
    out = []
    date_matches = list(DATE_RE.finditer(text))
    if not date_matches:
        date_matches = list(DATE_SHORT_RE.finditer(text))

    for m in date_matches:
        day, month = int(m.group(1)), int(m.group(2))
        raw_year = m.group(3) if len(m.groups()) >= 3 else None
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000
        else:
            year = default_year or datetime.now().year

        window = text[m.end():m.end() + 40]
        tm = TIME_RE.search(window)
        if tm:
            hour = int(tm.group(1) or tm.group(3))
            minute = int(tm.group(2) or 0)
        else:
            hour, minute = default_hour, 0

        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            continue

        # A ticket drop should not be generated for a weekend unless the
        # source explicitly contains a VVK date in a structured VVK cell.
        out.append(dt)
    return out


def detect_from_tables(club, kind, html, url):
    """Prefer structured VVK columns over free-text date matching.

    This prevents match dates such as 15.08. or 29.08. from being mistaken
    for ticket-sale dates. BVB and HSV publish their VVK information in
    structured tables, so only cells containing VVK labels are considered.
    """
    if kind != "vvk":
        return []

    parser = TableParser()
    try:
        parser.feed(html)
    except Exception:
        return []

    events = []
    now = datetime.now()
    for row in parser.rows:
        row_text = " | ".join(row)
        if not re.search(r"(?i)vvk|vorverkauf|verkaufsstart", row_text):
            continue

        # Only inspect cells that explicitly describe the sale. This is the
        # critical difference from the old parser, which scanned the whole
        # page and picked up ordinary match dates.
        sale_cells = [c for c in row if re.search(r"(?i)vvk|vorverkauf|verkaufsstart", c)]
        for cell in sale_cells:
            for dt in parse_date_time(cell, default_year=now.year):
                if dt < now - timedelta(days=1):
                    continue
                # VVK dates are normally weekday business times. If a source
                # ever publishes a weekend sale explicitly in a VVK cell, we
                # still keep it because the date came from the authoritative
                # VVK field rather than from a match listing.
                title = f"🔥 {club} | VVK" if club == "FC Bayern" else f"{club} | VVK"
                uid = hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}".encode()).hexdigest() + "@vvk-radar"
                events.append((uid, title, dt, url, kind))

    return list({(e[0], e[2]): e for e in events}.values())


def detect_fallback(club, kind, url, html):
    """Legacy fallback for sources without usable VVK tables.

    Keep this conservative: ordinary weekend match dates are never emitted
    as VVK events. Structured table extraction above is preferred whenever
    possible.
    """
    text = clean(html)
    keyword = {
        "vvk": r"(?i)(vorverkauf|vorverkaufstermin|verkaufsstart|mitglieder|freier vorverkauf|ticketverkauf)",
        "second_market": r"(?i)(zweitmarkt|ticket exchange|ticketbörse|resale)",
        "second_market_status": r"(?i)(zweitmarkt|ticket exchange|ticketbörse|resale|verkaufsstart)"
    }.get(kind, r"(?i)ticket")
    if not re.search(keyword, text):
        return []

    date_pat = r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](20\d{2}))?"
    time_pat = r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:Uhr)?"
    events = []
    for m in re.finditer(date_pat, text):
        window = text[max(0, m.start()-180):min(len(text), m.end()+260)]
        if not re.search(keyword, window):
            continue
        year = int(m.group(3) or datetime.now().year)
        day, month = int(m.group(1)), int(m.group(2))
        tm = re.search(time_pat, window)
        hour, minute = (int(tm.group(1)), int(tm.group(2))) if tm else (10, 0)
        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        if dt < datetime.now() - timedelta(days=1):
            continue
        # The old free-text method is too prone to treating match dates as
        # VVK dates. Never publish weekend events from this fallback.
        if kind == "vvk" and dt.weekday() >= 5:
            continue
        if kind.startswith("second_market"):
            title = f"🔥🔥 {club} | ZWEITMARKT"
        elif club == "FC Bayern":
            title = f"🔥 {club} | VVK"
        else:
            title = f"{club} | VVK"
        uid = hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}".encode()).hexdigest() + "@vvk-radar"
        events.append((uid, title, dt, url, kind))
    return list({(e[0], e[2]): e for e in events}.values())


def detect(club, kind, url, html):
    structured = detect_from_tables(club, kind, html, url)
    if structured:
        return structured
    return detect_fallback(club, kind, url, html)


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
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VVK Radar V4//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:⚽ VVK Radar","X-WR-TIMEZONE:Europe/Berlin"]
    for e in sorted(unique.values(), key=lambda x: x[2]):
        lines += event_lines(*e)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\r\n".join(lines)+"\r\n", encoding="utf-8")
    print(f"Wrote {len(unique)} events")

if __name__ == "__main__":
    main()
