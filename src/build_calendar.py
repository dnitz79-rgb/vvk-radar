import json, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/sources.json"
OUT = ROOT / "public/vvk-radar.ics"
UA = "VVK-Radar/3.0"


def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def esc(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def detect(club, kind, url, html):
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
        window = text[max(0, m.start()-220):min(len(text), m.end()+320)]
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
        if kind.startswith("second_market"):
            title = f"🔥🔥 {club} | ZWEITMARKT"
        elif club == "FC Bayern":
            title = f"🔥 {club} | VVK"
        else:
            title = f"{club} | VVK"
        uid = hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}".encode()).hexdigest() + "@vvk-radar"
        events.append((uid, title, dt, url, kind))
    return list({(e[0], e[2]): e for e in events}.values())


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
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VVK Radar V3//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:⚽ VVK Radar","X-WR-TIMEZONE:Europe/Berlin"]
    for e in sorted(unique.values(), key=lambda x: x[2]):
        lines += event_lines(*e)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\r\n".join(lines)+"\r\n", encoding="utf-8")
    print(f"Wrote {len(unique)} events")

if __name__ == "__main__":
    main()
