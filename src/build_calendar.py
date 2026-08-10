import json,re,hashlib
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data/sources.json'; OUT=ROOT/'public/vvk-radar.ics'
TZ=ZoneInfo('Europe/Berlin'); UCL_DRAW_DATE=datetime(2026,8,27,tzinfo=TZ)
MONTHS={'januar':1,'jan':1,'februar':2,'feb':2,'märz':3,'maerz':3,'mär':3,'mar':3,'april':4,'apr':4,'mai':5,'may':5,'juni':6,'jun':6,'juli':7,'jul':7,'august':8,'aug':8,'september':9,'sep':9,'sept':9,'oktober':10,'okt':10,'oct':10,'november':11,'nov':11,'dezember':12,'dez':12,'dec':12}
VVK=re.compile(r'(?i)(vorverkauf|vorverkaufstermin|verkaufsstart|mitgliedervorverkauf|freier vorverkauf|freier verkauf|ticketverkauf|vvk[- ]?start|vente|mise en vente|ouverture de la billetterie|verkauf|venta|ticket sale|tickets?\s+on\s+sale)')
UCL=re.compile(r'(?i)(uefa\s+champions\s+league|champions\s+league|\bucl\b|ligaphase|league\s+phase)')
DATE=re.compile(r'(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?(?!\d)|(?<!\d)(\d{1,2})\s+(Januar|Jan|Februar|Feb|März|Maerz|Mär|Mar|April|Apr|Mai|May|Juni|Jun|Juli|Jul|August|Aug|September|Sep|Sept|Oktober|Okt|Oct|November|Nov|Dezember|Dez|Dec)\s+(20\d{2})(?!\d)',re.I)
TIME=re.compile(r'(?<!\d)(\d{1,2}):(\d{2})\s*(?:Uhr)?|(?<!\d)(\d{1,2})\s*Uhr',re.I)
CALOVO=re.compile(r'Beginn des Termins\s+(\d{1,2})\s+([A-Za-zÄÖÜäöü]+)\s+(20\d{2})(?:\s+[A-Za-zÄÖÜäöü]{2,5}\.)?\s*(\d{1,2}):(\d{2})\s*(.+?)(?=\s+Beschreibung einblenden|\s+Veranstaltungsort:|\s+Details ansehen|\s+Beginn des Termins|\s+Weitere Kalender|$)',re.I)
def now(): return datetime.now(TZ)
def clean(s): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',s)).strip()
def esc(s): return s.replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')
def fetch(url):
 req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; VVK-Radar/8.0)','Accept-Language':'de-DE,de;q=0.9,en;q=0.8'})
 with urlopen(req,timeout=30) as r:return r.read().decode('utf-8',errors='ignore')
class Tables(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None
 def handle_starttag(self,tag,attrs):
  if tag.lower()=='tr':self.row=[]
  elif tag.lower() in ('td','th') and self.row is not None:self.cell=[]
 def handle_data(self,data):
  if self.cell is not None:self.cell.append(data)
 def handle_endtag(self,tag):
  tag=tag.lower()
  if tag in ('td','th') and self.cell is not None and self.row is not None:self.row.append(clean(' '.join(self.cell)));self.cell=None
  elif tag=='tr' and self.row is not None:
   if self.row:self.rows.append(self.row)
   self.row=None
def parsed(m):
 n=now()
 if m.group(1):return int(m.group(1)),int(m.group(2)),int(m.group(3) or n.year)
 return int(m.group(4)),MONTHS.get(m.group(5).lower()),int(m.group(6))
def make_event(club,kind,url,dt,label=''):
 title=f'🔥🔥 {club} | ZWEITMARKT' if kind.startswith('second') else f'🔥 {club} | VVK'
 if label:title+=f' – {clean(label)[:220]}'
 uid=hashlib.sha1(f'{club}|{kind}|{dt.isoformat()}|{url}|{label}'.encode()).hexdigest()+'@vvk-radar'
 return uid,title,dt,url,kind
def from_text(club,url,text,require_ucl=False):
 text=clean(text);out=[];n=now()
 for m in DATE.finditer(text):
  window=text[max(0,m.start()-450):min(len(text),m.end()+650)]
  if not VVK.search(window) or (require_ucl and not UCL.search(window)):continue
  d,mo,y=parsed(m);tm=TIME.search(window)
  if not mo or not tm:continue
  try:dt=datetime(y,mo,d,int(tm.group(1) or tm.group(3)),int(tm.group(2) or 0),tzinfo=TZ)
  except ValueError:continue
  if dt>=n-timedelta(days=1):out.append(make_event(club,'vvk',url,dt,window))
 return list({(e[0],e[2]):e for e in out}.values())
def detect_calovo(club,url,html):
 out=[]
 for m in CALOVO.finditer(clean(html)):
  mo=MONTHS.get(m.group(2).lower())
  if not mo:continue
  try:dt=datetime(int(m.group(3)),mo,int(m.group(1)),int(m.group(4)),int(m.group(5)),tzinfo=TZ)
  except ValueError:continue
  if dt>=now()-timedelta(days=1):out.append(make_event(club,'vvk',url,dt,m.group(6)))
 return list({(e[0],e[2]):e for e in out}.values())
def detect(club,kind,url,html):
 if kind in ('bvb_calovo_vvk','calovo_vvk'):return detect_calovo(club,url,html)
 if kind=='ucl_vvk':return [] if now()<UCL_DRAW_DATE else from_text(club,url,html,True)
 if kind in ('vvk','news_vvk','ticket_request','ticket_portal'):
  p=Tables()
  try:p.feed(html)
  except Exception:pass
  out=[]
  for row in p.rows:out+=from_text(club,url,' | '.join(row))
  return list({(e[0],e[2]):e for e in (out or from_text(club,url,html))}.values())
 return []
def alarms():
 a=[]
 for days,label in ((5,'🔔 VVK in 5 Tagen'),(3,'🔔 VVK in 3 Tagen'),(1,'🔔 VVK MORGEN')):a+=['BEGIN:VALARM',f'TRIGGER:-P{days}D','ACTION:DISPLAY',f'DESCRIPTION:{label}','END:VALARM']
 return a+['BEGIN:VALARM','TRIGGER:-PT30M','ACTION:DISPLAY','DESCRIPTION:🚨 VVK startet in 30 Minuten','END:VALARM']
def event_lines(e):
 uid,title,dt,url,kind=e;end=dt+timedelta(minutes=30)
 return ['BEGIN:VEVENT',f'UID:{uid}',f'DTSTAMP:{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}',f'DTSTART;TZID=Europe/Berlin:{dt.strftime("%Y%m%dT%H%M%S")}',f'DTEND;TZID=Europe/Berlin:{end.strftime("%Y%m%dT%H%M%S")}',f'SUMMARY:{esc(title)}',f'DESCRIPTION:{esc("Art: "+kind+"\\nQuelle: "+url)}',f'URL:{url}','STATUS:CONFIRMED','TRANSP:OPAQUE']+alarms()+['END:VEVENT']
def main():
 sources=json.loads(DATA.read_text(encoding='utf-8'))['sources'];found=[]
 for s in sources:
  try:
   got=detect(s['club'],s['type'],s['url'],fetch(s['url']));print(f"{s['club']}: {len(got)} events");found+=got
  except Exception as ex:print(f"source failed {s['club']}: {ex}")
 n=now();unique={e[0]:e for e in found if e[2]>=n};cal=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//VVK Radar V8.0//DE','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:⚽ VVK Radar','X-WR-TIMEZONE:Europe/Berlin']
 for e in sorted(unique.values(),key=lambda x:x[2]):cal+=event_lines(e)
 OUT.parent.mkdir(exist_ok=True);OUT.write_text('\r\n'.join(cal+['END:VCALENDAR'])+'\r\n',encoding='utf-8');print(f'Wrote {len(unique)} events')
if __name__=='__main__':main()
