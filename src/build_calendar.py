import json, re, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/sources.json"
OUT = ROOT / "public/vvk-radar.ics"
UA = "VVK-Radar/6.0"
MONTHS = {
    "januar":1,"jan":1,"februar":2,"feb":2,"märz":3,"maerz":3,"mär":3,"mar":3,
    "april":4,"apr":4,"mai":5,"may":5,"juni":6,"jun":6,"juli":7,"jul":7,
    "august":8,"aug":8,"september":9,"sep":9,"sept":9,"oktober":10,"okt":10,"oct":10,
    "november":11,"nov":11,"dezember":12,"dez":12,"dec":12
}

def fetch(url):
    req=Request(url,headers={"User-Agent":UA})
    with urlopen(req,timeout=30) as r:
        return r.read().decode("utf-8",errors="ignore")

def clean(s):
    return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",s)).strip()

def esc(s):
    return s.replace("\\","\\\\").replace("\n","\\n").replace(",","\\,").replace(";","\\;")

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="tr": self.row=[]
        elif tag.lower() in ("td","th") and self.row is not None: self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append(clean(" ".join(self.cell))); self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.row: self.rows.append(self.row)
            self.row=None

DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)"
    r"|(?<!\d)(\d{1,2})\s+(Januar|Jan|Februar|Feb|März|Maerz|Mär|Mar|April|Apr|Mai|May|Juni|Jun|Juli|Jul|August|Aug|September|Sep|Sept|Oktober|Okt|Oct|November|Nov|Dezember|Dez|Dec)\s+(20\d{2})(?!\d)",re.I)
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:Uhr)?|(?<!\d)(\d{1,2})\s*Uhr",re.I)
CALOVO_EVENT_RE = re.compile(
    r"Beginn des Termins\s+(\d{1,2})\s+([A-Za-zÄÖÜäöü]+)\s+(20\d{2})"
    r"(?:\s+[A-Za-zÄÖÜäöü]{2,5}\.)?\s*(\d{1,2}):(\d{2})\s*"
    r"(.+?)(?=\s+Beschreibung einblenden|\s+Veranstaltungsort:|\s+Details ansehen|\s+Beginn des Termins|\s+Termine aus vergangenen Jahren|\s+Weitere Kalender|$)",re.I)
VVK_KEYWORD = re.compile(r"(?i)(vorverkauf|vorverkaufstermin|verkaufsstart|mitgliedervorverkauf|freier vorverkauf|ticketverkauf|vvk-start|vente|mise en vente|ouverture de la billetterie|verkauf|venta|entradas?\s+(?:a la|für|en)\s+la|ticket sale|tickets?\s+on\s+sale)")


def parse_date_match(m, now=None):
    now=now or datetime.now()
    if m.group(1):
        day,month=int(m.group(1)),int(m.group(2)); year=int(m.group(3)) if m.group(3) else now.year
    else:
        day=int(m.group(4)); month=MONTHS.get(m.group(5).lower()); year=int(m.group(6))
    if not month: return None
    return day,month,year

def make_event(club,kind,url,dt,source_title=None):
    title=f"🔥🔥 {club} | ZWEITMARKT" if kind.startswith("second_market") else (f"🔥 {club} | VVK" if club=="FC Bayern" else f"{club} | VVK")
    if source_title:
        title += f" – {source_title}"
    uid=hashlib.sha1(f"{club}|{kind}|{dt.isoformat()}|{url}|{source_title or ''}".encode()).hexdigest()+"@vvk-radar"
    return uid,title,dt,url,kind

def detect_calovo_vvk(club,url,html):
    text=clean(html); events=[]
    for m in CALOVO_EVENT_RE.finditer(text):
        title=m.group(7).strip()
        if not VVK_KEYWORD.search(title):
            continue
        month=MONTHS.get(m.group(2).lower())
        if not month: continue
        try:
            dt=datetime(int(m.group(3)),month,int(m.group(1)),int(m.group(4)),int(m.group(5)))
        except ValueError: continue
        if dt>=datetime.now()-timedelta(days=1):
            events.append(make_event(club,"vvk",url,dt,title))
    return list({(e[0],e[2]):e for e in events}.values())

def detect_vvk_from_tables(club,url,html):
    parser=TableParser()
    try: parser.feed(html)
    except Exception: return []
    events=[]; now=datetime.now()
    for row in parser.rows:
        for cell in [c for c in row if VVK_KEYWORD.search(c)]:
            for m in DATE_RE.finditer(cell):
                parsed=parse_date_match(m,now)
                if not parsed: continue
                day,month,year=parsed; tm=TIME_RE.search(cell[m.end():m.end()+50])
                if not tm: continue
                try: dt=datetime(year,month,day,int(tm.group(1) or tm.group(3)),int(tm.group(2) or 0))
                except ValueError: continue
                if dt>=now-timedelta(days=1): events.append(make_event(club,"vvk",url,dt))
    return list({(e[0],e[2]):e for e in events}.values())

def detect_vvk_fallback(club,url,html):
    text=clean(html); events=[]; now=datetime.now()
    if not VVK_KEYWORD.search(text): return []
    for m in DATE_RE.finditer(text):
        window=text[max(0,m.start()-220):min(len(text),m.end()+320)]
        if not VVK_KEYWORD.search(window): continue
        parsed=parse_date_match(m,now)
        if not parsed: continue
        day,month,year=parsed; tm=TIME_RE.search(window)
        if not tm: continue
        try: dt=datetime(year,month,day,int(tm.group(1) or tm.group(3)),int(tm.group(2) or 0))
        except ValueError: continue
        if dt>=now-timedelta(days=1): events.append(make_event(club,"vvk",url,dt))
    return list({(e[0],e[2]):e for e in events}.values())

def detect_second_market(club,kind,url,html):
    return []

def detect(club,kind,url,html):
    if kind in ("bvb_calovo_vvk","calovo_vvk"):
        return detect_calovo_vvk(club,url,html)
    if kind in ("vvk","news_vvk","ticket_request","ticket_portal","ucl_vvk"):
        structured=detect_vvk_from_tables(club,url,html)
        return structured if structured else detect_vvk_fallback(club,url,html)
    if kind.startswith("second_market"):
        return detect_second_market(club,kind,url,html)
    return []

def event_lines(uid,title,dt,url,kind):
    end=dt+timedelta(minutes=30)
    lines=["BEGIN:VEVENT",f"UID:{uid}",f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",f"DTSTART;TZID=Europe/Berlin:{dt.strftime('%Y%m%dT%H%M%S')}",f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",f"SUMMARY:{esc(title)}",f"DESCRIPTION:{esc('Art: '+kind+'\\nQuelle: '+url)}",f"URL:{url}","STATUS:CONFIRMED","TRANSP:OPAQUE"]
    for days,label in [(5,"🔔 VVK in 5 Tagen"),(3,"🔔 VVK in 3 Tagen")]:
        lines += ["BEGIN:VALARM",f"TRIGGER:-P{days}D","ACTION:DISPLAY",f"DESCRIPTION:{label}","END:VALARM"]
    lines += ["BEGIN:VALARM","TRIGGER:-PT30M","ACTION:DISPLAY","DESCRIPTION:🚨 VVK/Zweitmarkt startet in 30 Minuten","END:VALARM","END:VEVENT"]
    return lines

def main():
    sources=json.loads(DATA.read_text(encoding="utf-8"))["sources"]; events=[]
    for s in sources:
        try:
            found=detect(s["club"],s["type"],s["url"],fetch(s["url"]))
            print(f"{s['club']}: {len(found)} VVK events")
            events+=found
        except Exception as exc:
            print("source failed",s["club"],exc)
    unique={e[0]:e for e in events if e[2]>=datetime.now()}
    lines=["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VVK Radar V6.0//DE","CALSCALE:GREGORIAN","METHOD:PUBLISH","X-WR-CALNAME:⚽ VVK Radar","X-WR-TIMEZONE:Europe/Berlin"]
    for e in sorted(unique.values(),key=lambda x:x[2]): lines+=event_lines(*e)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(exist_ok=True); OUT.write_text("\r\n".join(lines)+"\r\n",encoding="utf-8")
    print(f"Wrote {len(unique)} events")

if __name__=="__main__": main()
