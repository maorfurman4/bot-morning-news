#!/usr/bin/env python3
"""
בריף חדשות בוקר — נתוני שוק אמיתיים + חדשות ממקורות אמינים, מסוכמים בעברית.
הודעה נפרדת לכל נושא. המספרים מחושבים בקוד; ה-AI רק בוחר, מתרגם ומסביר — ורק מתוך הכתבות שקיבל,
וכל ידיעה נבדקת מול הכתבה שהקישור שלה מוצג.
הרצה מקומית בלי שליחה: python bot.py --dry-run
"""

import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

# =============================================================================
# ─── הגדרות וסודות ───────────────────────────────────────────────────────────
# =============================================================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_NEWS", "").strip()
CHAT_ID = os.environ.get("CHAT_ID_NEWS", "").strip()        # אתה — המניות שלך ודוח תקלות
CHANNEL_ID = os.environ.get("NEWS_CHANNEL_ID", "").strip()  # ערוץ הבריף (@שם או -100...); ריק — הכל אליך

IL_TZ = ZoneInfo("Asia/Jerusalem")
MAX_AGE = timedelta(hours=26)
PER_TOPIC = 50   # תקרה לנושא — עוד מקורות = יותר גיוון, לא יותר טוקנים
PER_FEED = 6     # כמה כתבות לקחת מכל מקור (לפי הסדר של המקור עצמו) — מספיק ל-5–8 ידיעות לנושא
DRAMATIC = 3.0   # % — מניה שזזה יותר מזה מקבלת הסבר
MODELS = ["gpt-5-mini", "gpt-4o-mini"]  # הראשון שעובד עם המפתח; mini — בערך חמישית מהמחיר

# (סימול, שם, סוג) — הסוג קובע איך מציגים את השינוי. שמות בעברית כדי שהשורה תישאר מימין לשמאל
MARKETS = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "Nasdaq", "index"),
    ("^DJI", "Dow", "index"),
    ("TA35.TA", "TA-35", "index"),
    ("^VIX", "VIX", "index"),
    ("^TNX", "US 10Y", "yield"),
    ("ILS=X", "USD/ILS", "fx"),
    ("BZ=F", "Brent", "usd"),
]

# המניות שלי: סימול → (שם לחיפוש חדשות, שם בעברית)
HOLDINGS = {
    "INTC": ("Intel", "אינטל"),
    "MBLY": ("Mobileye", "מובילאיי"),
    "TSLA": ("Tesla", "טסלה"),
    "SPCX": ("SpaceX", "ספייס אקס"),
    "TEVA": ("Teva", "טבע"),
    "NVO": ("Novo Nordisk", "נובו נורדיסק"),
    "QBTS": ("D-Wave Quantum", "די-וייב"),
    "AMZN": ("Amazon", "אמזון"),
    "GOOG": ("Alphabet", "גוגל"),
}

def gn(query: str = "", lang: str = "en", topic: str = "", when: str = "1d") -> str:
    """כתובת Google News: חיפוש (24 שעות), מדור (SPORTS/ENTERTAINMENT — מדורג לפי מה שחם עכשיו) או הכותרות הראשיות."""
    loc = "hl=he&gl=IL&ceid=IL:he" if lang == "he" else "hl=en-US&gl=US&ceid=US:en"
    if topic:
        return f"https://news.google.com/rss/headlines/section/topic/{topic}?{loc}"
    if not query:
        return f"https://news.google.com/rss?{loc}"
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:' + when)}&{loc}"

# (שם מקור, כתובת). שם None = מאגר (Google News) — שם המקור נלקח מכל כתבה ורק מקורות מ-TRUSTED נשארים
# ריאליטי — כל תוכנית בחיפוש משלה (חיפוש אחד משותף החזיר תוצאות מעורבבות, 06/11/2026). תוכנית חדשה — להוסיף כאן
REALITY_SHOWS = ['"האח הגדול"', 'הישרדות', '"הזמר במסכה"', '"רוקדים עם כוכבים"', 'חתונמי', '"חתונה ממבט ראשון"',
                 '"מאסטר שף"', '"הכוכב הבא"', '"נינג\'ה ישראל"']

FEEDS = {
    "israel": [
        (None, gn(lang="he")),  # הכותרות הראשיות בישראל, מדורגות לפי חשיבות
        ("ynet", "https://www.ynet.co.il/Integration/StoryRss2.xml"),
        ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585"),
        ("Haaretz", "https://www.haaretz.com/srv/haaretz-latest-headlines"),
        (None, gn("site:timesofisrael.com")),  # ה-RSS שלהם חוסם את שרתי GitHub
        (None, gn("site:reuters.com Israel")),
        (None, gn("site:calcalist.co.il", "he")),
        (None, gn("site:themarker.com", "he")),
        ("מעריב", "https://www.maariv.co.il/Rss/RssChadashot"),
        ("וואלה", "https://rss.walla.co.il/feed/1"),
        (None, gn("site:kan.org.il", "he")),
        (None, gn("site:mako.co.il", "he")),
        (None, gn("site:jpost.com")),
    ],
    "ai": [
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("Ars Technica", "https://arstechnica.com/ai/feed/"),
        ("Wired", "https://www.wired.com/feed/tag/ai/latest/rss"),
        ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        (None, gn("artificial intelligence")),
        ("The Decoder", "https://the-decoder.com/feed/"),
        (None, gn("site:reuters.com artificial intelligence")),
        (None, gn("OpenAI OR Anthropic OR Google Gemini")),
    ],
    "tech": [
        ("BBC", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("TechCrunch", "https://techcrunch.com/category/robotics/feed/"),
        ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/topic/robotics.rss"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Wired", "https://www.wired.com/feed/rss"),
        ("Engadget", "https://www.engadget.com/rss.xml"),
        ("The Verge", "https://www.theverge.com/rss/tech/index.xml"),
        (None, gn("robotics")),
        ("The Register", "https://www.theregister.com/headlines.atom"),
        ("Electrek", "https://electrek.co/feed/"),
        (None, gn("site:reuters.com technology")),
    ],
    "world": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        (None, gn("site:reuters.com world")),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
        (None, gn("site:apnews.com world")),
    ],
    "sport": [
        (None, gn(lang="he", topic="SPORTS"), 15),  # מה שחם עכשיו בספורט בישראל, מדורג
        (None, gn("דני אבדיה", "he")),
        (None, gn("יורוליג OR יורוקאפ", "he"), 8),
        (None, gn('"ליגת העל" OR "ליגת ווינר"', "he"), 8),
        ("ynet ספורט", "https://www.ynet.co.il/Integration/StoryRss3.xml"),
        (None, gn("ישראלי מדליה OR ג'ודו OR אליפות העולם", "he")),
        ("וואלה ספורט", "https://rss.walla.co.il/feed/156"),
        (None, gn("site:sport5.co.il", "he")),
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ],
    "ent": [
        (None, gn(lang="he", topic="ENTERTAINMENT"), 15),  # מה שחם עכשיו בבידור בישראל, מדורג
        *[(None, gn(show, "he", when="12h"), 6, show.strip('"')) for show in REALITY_SHOWS],  # מאחרי השידור
        ("ynet בידור", "https://www.ynet.co.il/Integration/StoryRss538.xml"),
        ("וואלה סלבס", "https://rss.walla.co.il/feed/3600"),
        (None, gn("site:mako.co.il ריאליטי OR האח הגדול OR הישרדות", "he")),
    ],
    "market": [
        ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        (None, gn("stock market today")),
        (None, gn("Wall Street stocks close")),
        (None, gn("Tel Aviv Stock Exchange")),
        ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
        ("גלובס", "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=1725"),
        (None, gn("site:bloomberg.com markets")),
        (None, gn("site:reuters.com markets")),
    ],
}

# מקורות מהימנים — רק הם נשארים מהמאגרים
TRUSTED = (
    "reuters", "bloomberg", "cnbc", "wall street journal", "wsj", "marketwatch", "yahoo",
    "financial times", "barron", "ap news", "associated press", "investing.com", "axios",
    "bbc", "guardian", "npr", "al jazeera", "politico", "economist", "nikkei", "semafor",
    "techcrunch", "the verge", "wired", "ars technica", "engadget", "mit technology review", "the decoder",
    "ieee", "fortune", "business insider", "the information", "new york times", "france 24", "the register",
    "times of israel", "haaretz", "jerusalem post", "i24", "ynet", "mako", "n12",
    "globes", "calcalist", "themarker", "הארץ", "גלובס", "כלכליסט", "דה מרקר",
    "מעריב", "כאן 11", "וואלה", "ישראל היום", "חדשות 13", "רשת 13", "פנאי פלוס", "sport5", "ספורט 1", "היום",
)

SEP = "〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️"
RLM = "‏"  # תו כיוון: שורה שמתחילה באנגלית (OpenAI, S&P) לא תתהפך לשמאל-לימין

def esc(text) -> str:
    return html.escape(str(text))

# ── דוח כשלונות — מצורף לסוף הבריף כדי שנדע מה לתקן ───────────────────────────

FAILURES = []

def fail(section: str, ex) -> None:
    print(f"❌ {section}: {ex}")
    # בלי כתובות — כתובת טלגרם מכילה את הטוקן
    detail = re.sub(r"https?://\S+", "<url>", str(ex))[:150]
    FAILURES.append(f"• <b>{esc(section)}</b>: {esc(detail)}")

# =============================================================================
# ─── חדשות ───────────────────────────────────────────────────────────────────
# =============================================================================

ATOM = "{http://www.w3.org/2005/Atom}"

def fetch(url: str) -> bytes:
    for wait in (3, 8, None):  # Google News מחזיר לפעמים 503/429 לרגע — מחכים ומנסים שוב (08/11/2026)
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code not in (429, 503) or wait is None:
            break
        time.sleep(wait)
    resp.raise_for_status()
    return resp.content

def _date(text: str) -> datetime | None:
    text = (text or "").strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text)  # Atom
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def _href(entry) -> str:
    link = entry.find(f"{ATOM}link")  # Element בלי ילדים הוא falsy, לכן is None
    return "" if link is None else link.get("href", "")

def parse_rss(content: bytes, source: str | None = None) -> list:
    """RSS או Atom. source=None: שם המקור נלקח מכל כתבה (Google News)."""
    root = ET.fromstring(content)
    raw = [
        (it.findtext("title"), it.findtext("link"), it.findtext("source"), it.findtext("pubDate"), it.findtext("description"))
        for it in root.iter("item")
    ] + [
        (e.findtext(f"{ATOM}title"), _href(e), None,
         e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated"),
         e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content"))
        for e in root.iter(f"{ATOM}entry")
    ]
    items = []
    for title, link, src, date, desc in raw:
        title, src, published = (title or "").strip(), source or (src or "").strip(), _date(date)
        if source is None and src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        if not published or not title:
            continue
        summary = html.unescape(re.sub(r"<[^>]+>", " ", desc or ""))
        items.append({
            "title": html.unescape(title), "link": (link or "").strip(), "source": src,
            "published": published, "summary": re.sub(r"\s+", " ", summary).strip()[:200],
        })
    return items

def trusted(source: str) -> bool:
    # מילה שלמה: "npr" לא אמור להתאים ל-"Nonproliferation"
    s = source.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", s) for t in TRUSTED)

def gn_ok(source: str) -> bool:
    # Google News קורא את התאריך של מעריב הפוך (11/06 = 11 ביוני ← "6 בנובמבר"); לא חוסמים את מעריב —
    # stale_links בודק את התאריך שכתוב בכתבה עצמה ופוסל כתבה ישנה (06/11/2026)
    return trusted(source)

def fresh(items: list, now: datetime) -> list:
    """רק מהיממה האחרונה, בלי כפילויות; שומר על סדר המקור (Google News מדרג לפי חשיבות)."""
    seen, out = set(), []
    for i in items:
        key = i["title"].strip().lower()
        if now - i["published"] <= MAX_AGE and key not in seen:
            seen.add(key)
            out.append(i)
    return out

def read_feed(name: str | None, url: str, now: datetime, limit: int = PER_FEED, show: str = "") -> list:
    try:
        items = parse_rss(fetch(url), name)
    except Exception as ex:
        fail(f"מקור {name or 'Google News'}", ex)
        return []
    if name is None:
        items = [i for i in items if gn_ok(i["source"])]
    if show:  # כדי שה-AI ידע לאיזו תוכנית הכתבה שייכת גם כשהכותרת לא אומרת ("שחר חסון מול אופירה אסייג")
        items = [dict(i, show=show) for i in items]
    return fresh(items, now)[:limit]

def get_feed(category: str, now: datetime) -> list:
    with ThreadPoolExecutor(8) as pool:
        per_feed = list(pool.map(lambda f: read_feed(f[0], f[1], now, *f[2:]), FEEDS[category]))
    # לסירוגין בין המקורות: הכתבה הראשונה מכל מקור, אחר כך השנייה... כך התקרה לא מוחקת מקורות שלמים
    mixed = [i for row in zip_longest(*per_feed) for i in row if i]
    return fresh(mixed, now)[:PER_TOPIC]

# =============================================================================
# ─── נתוני שוק (Yahoo Finance) ───────────────────────────────────────────────
# =============================================================================

def quote(symbol: str) -> tuple:
    closes = yf.Ticker(symbol).history(period="7d")["Close"].dropna()
    if len(closes) < 2:
        raise ValueError("אין מספיק נתונים")
    return float(closes.iloc[-1]), float(closes.iloc[-2]), closes.index[-1].date()

def move(up: bool, amount: str) -> str:
    return f"{'עלייה' if up else 'ירידה'} של {amount}"

def fmt_market(name: str, kind: str, last: float, prev: float) -> str:
    """שורה בטבלה (בתוך <pre>): 🟢 S&P 500     7,744  ▲0.28%"""
    up = last >= prev
    if kind == "yield":
        value, change = f"{last:.2f}%", f"{abs(last - prev) * 100:.0f}bp"
    else:
        value = {"fx": f"₪{last:.3f}", "usd": f"${last:.2f}"}.get(kind, f"{last:,.2f}" if last < 100 else f"{last:,.0f}")
        change = f"{abs((last - prev) / prev * 100):.2f}%"
    return f"{'🟢' if up else '🔴'} {esc(name):<{7 + len(esc(name)) - len(name)}}{value:>9}  {'▲' if up else '▼'}{change}"

def get_markets() -> tuple:
    rows, close_date = [], None
    for symbol, name, kind in MARKETS:
        try:
            last, prev, day = quote(symbol)
        except Exception as ex:
            fail(f"שוק {name}", ex)
            continue
        close_date = close_date or day
        rows.append(fmt_market(name, kind, last, prev))
    return rows, close_date

# רכישות פנים: מנהלים שקנו מניות של החברה שלהם (דיווחי Form 4 ל-SEC, דרך OpenInsider — חינמי;
# GuruFocus חוסם גישה אוטומטית ודורש API בתשלום). רק קניות, רק בכירים/דירקטורים, מעל 100 אלף דולר
INSIDERS_URL = ("http://openinsider.com/screener?fd=3&xp=1&vl=100&isceo=1&iscfo=1&ispres=1&iscoo=1&iscob=1"
                "&isdirector=1&sortcol=12&cnt=40")
ROLES = [("CEO", 'מנכ"ל'), ("CFO", 'סמנכ"ל כספים'), ("COO", 'סמנכ"ל תפעול'), ("Pres", "נשיא"),
         ("Chair", 'יו"ר'), ("COB", 'יו"ר'), ("Dir", "דירקטור")]
US_TZ = ZoneInfo("America/New_York")

def parse_insiders(page: str, now: datetime) -> list:
    table = page[page.find('class="tinytable"'):]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)[1:]:
        c = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(c) < 13 or not c[7].startswith("P"):
            continue
        try:
            filed = datetime.strptime(c[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=US_TZ)
            value = float(re.sub(r"[^\d.]", "", c[12]))
        except ValueError:
            continue
        if now - filed > MAX_AGE or re.search(r"acquisition|fund\b|trust\b", c[4], re.I):
            continue  # רק מהיממה האחרונה; בלי SPAC וקרנות — שם זו לא "ידיעה פנימית"
        role = next((he for en, he in ROLES if re.search(rf"\b{en}", c[6])), None)
        if role:
            company = re.sub(r"\s*/\w+$", "", c[4]).rstrip(" ,.")  # "Huntington Bancshares Inc /M" → בלי הסיומת
            out.append({"ticker": c[3].split(">")[-1].strip(), "company": company, "role": role, "value": value,
                        "price": c[8]})
    return sorted(out, key=lambda i: -i["value"])[:5]

def get_insiders(now: datetime) -> list:
    try:
        return parse_insiders(fetch(INSIDERS_URL).decode("utf-8", "ignore"), now)
    except Exception as ex:
        fail("רכישות פנים (OpenInsider)", ex)
        return []

def fmt_insider(i: dict) -> str:
    v = f"${i['value'] / 1e6:.1f}M" if i["value"] >= 1e6 else f"${i['value'] / 1e3:.0f}K"
    return (f'• <a href="http://openinsider.com/{esc(i["ticker"])}"><b>{esc(i["ticker"])}</b></a> ({esc(i["company"][:28].rstrip(" ,."))}) — '
            f"{i['role']} קנה ב-<b>{v}</b>, במחיר {esc(i['price'])}")

# תוצאות רשמיות של קבוצות ישראליות באירופה — כדי שהתוצאה בבלוק "אמש במגרשים" תהיה מדויקת
# (ליגת העל — אין מקור חינמי; שם התוצאה מגיעה מהכתבה)
ISRAELI = re.compile(r"Hapoel|Maccabi|Beitar|Bnei |Tel[- ]?Aviv|Jerusalem|Haifa|Be.?er|Holon|Netanya|Herzliya|Ashdod|Petah|Ness Ziona|"
                     r"Galil|Ramat Gan|Rishon|Kiryat", re.I)
EUROLEAGUE = {"E": "יורוליג", "U": "יורוקאפ"}
UEFA = {"uefa.champions": "ליגת האלופות", "uefa.europa": "הליגה האירופית", "uefa.europa.conf": "הקונפרנס ליג"}

HE_CLUBS = [(r"Hapoel.*Tel Aviv", 'הפועל ת"א'), (r"Maccabi.*Tel Aviv", 'מכבי ת"א'), (r"Hapoel.*Jerusalem", "הפועל ירושלים"),
            (r"Maccabi.*Haifa", "מכבי חיפה"), (r"Be.?er", 'הפועל ב"ש'), (r"Hapoel.*Holon", "הפועל חולון"),
            (r"Herzliya", "בני הרצליה"), (r"Beitar|Jerusalem", "בית\"ר ירושלים"), (r"Netanya", "מכבי נתניה")]

ISRAELI_HE = re.compile(r'הפועל|מכבי|בית"ר|בית״ר|בני |עירוני|ישראל|אבדיה|נבחרת')

def he_club(name: str) -> str:
    return next((he for pat, he in HE_CLUBS if re.search(pat, name, re.I)), name)

def result_line(r: dict, he: dict = {}) -> str:
    home, a, b, away = re.match(r"(.+) (\d+)-(\d+) (.+)", r["game"]).groups()
    name = lambda n: he_club(n) if he_club(n) != n else he.get(n, n)
    # "הפועל ת\"א 90, ברצלונה 93" — בלי "90:93" שמתהפך בעברית ולא ברור של מי כל מספר
    return f"• <b>{esc(r['comp'])}</b> — {esc(name(home))} {a}, {esc(name(away))} {b}"

def get_results(now: datetime) -> list:
    out = []
    season = now.year if now.month >= 8 else now.year - 1
    for code, comp in EUROLEAGUE.items():
        try:
            games = json.loads(fetch(f"https://api-live.euroleague.net/v2/competitions/{code}/seasons/{code}{season}/games"))["data"]
        except Exception as ex:
            fail(f"תוצאות {comp}", ex)
            continue
        for g in games:
            home, away = g["local"]["club"]["name"], g["road"]["club"]["name"]
            when = datetime.fromisoformat(g["utcDate"].replace("Z", "+00:00"))
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            if g.get("played") and now - when <= MAX_AGE and ISRAELI.search(home + away):
                out.append({"comp": comp, "game": f"{home} {g['local']['score']}-{g['road']['score']} {away}"})
    for league, comp in UEFA.items():
        for day in sorted({(now - timedelta(days=1)).strftime("%Y%m%d"), now.strftime("%Y%m%d")}):
            try:
                events = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={day}"))["events"]
            except Exception as ex:
                fail(f"תוצאות {comp}", ex)
                continue
            for e in events:
                c = e["competitions"][0]
                t = {x["homeAway"]: x for x in c["competitors"]}
                names = t["home"]["team"]["displayName"], t["away"]["team"]["displayName"]
                if c["status"]["type"]["completed"] and ISRAELI.search(" ".join(names)):
                    out.append({"comp": comp, "game": f"{names[0]} {t['home']['score']}-{t['away']['score']} {names[1]}"})
    return out

# ── לוח שידורים (yes): כאן 11, קשת 12, רשת 13 ─────────────────────────────────
# ה-API נותן רק מהיום והלאה — לכן כל בוקר שומרים את הלוח של היום (schedule.json, נשמר ב-git ע"י ה-workflow),
# ולמחרת בבוקר יודעים בדיוק מה שודר אמש
TV = {"CH30": "כאן 11", "CH34": "קשת 12", "CH36": "רשת 13"}
SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")

def get_schedule(day) -> list:
    """פריים טיים (18:00–01:00) של היום בשלושת הערוצים."""
    out = []
    for ch, name in TV.items():
        try:
            data = json.loads(fetch(f"https://svc.yes.co.il/api/content/broadcast-schedule/channels/{ch}"
                                    f"?date={day.year}-{day.month}-{day.day}&ignorePastItems=false"))
        except Exception as ex:
            fail(f"לוח שידורים {name}", ex)
            continue
        for it in data.get("items") or []:
            start = datetime.fromisoformat(it["starts"].replace("Z", "+00:00")).astimezone(IL_TZ)
            if start.hour >= 18 or start.hour < 1:
                out.append({"channel": name, "time": f"{start:%H:%M}", "title": it.get("title") or "",
                            "description": (it.get("description") or "")[:200]})
    return sorted(out, key=lambda x: (x["channel"], x["time"]))

def tv_last_night(today) -> list:
    try:
        with open(SCHEDULE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return []
    return saved.get("items") or [] if saved.get("date") == str(today - timedelta(days=1)) else []

def save_tv(today, items: list) -> None:
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": str(today), "items": items}, f, ensure_ascii=False, indent=1)

def get_holdings() -> dict:
    out = {}
    for ticker in HOLDINGS:
        try:
            last, prev, _ = quote(ticker)
            out[ticker] = {"last": last, "pct": (last - prev) / prev * 100}
        except Exception as ex:
            fail(f"מניה {ticker}", ex)
    return out

def fmt_holding(ticker: str, q: dict) -> str:
    up = q["pct"] >= 0
    icon = "🔥" if abs(q["pct"]) >= DRAMATIC else "🟢" if up else "🔴"
    return f"{icon} {HOLDINGS[ticker][1]} ({ticker}): <b>{q['last']:.2f} דולר</b> | {move(up, f'{abs(q['pct']):.1f}%')}"

# =============================================================================
# ─── סיכום AI — קריאה נפרדת לכל נושא ─────────────────────────────────────────
# =============================================================================

TOPICS = {
    "israel": ("🇮🇱", "ישראל",
               "רק ידיעות על ישראל עצמה: ביטחון, מדיניות ופוליטיקה, כלכלה ישראלית, חברות ישראליות, חברה. "
               "לא וול סטריט ולא חדשות עולם — גם אם פורסמו באתר ישראלי. איראן/ארה\"ב רק אם זה נוגע ישירות לישראל. "
               "בלי ספורט ובלי בידור — יש להם הודעות נפרדות."),
    "ai": ("🤖", "בינה מלאכותית (AI)",
           "בינה מלאכותית: מודלים ומוצרים, חברות AI, השקעות וגיוסים, רגולציה, שבבי AI, מחקר פורץ דרך."),
    "tech": ("🦾", "טכנולוגיה ורובוטיקה",
             "טכנולוגיה ורובוטיקה שבינה מלאכותית אינה במרכזן: רובוטים, רכב חשמלי ואוטונומי, חלל, שבבים, סייבר, "
             "מוצרים וחברות טק."),
    "world": ("🌍", "אקטואליה עולמית",
              "אקטואליה עולמית: גאופוליטיקה, מלחמות, בחירות, אסונות, כלכלה עולמית. בלי ישראל — יש לה הודעה נפרדת."),
    "sport": ("⚽", "ספורט",
              "ספורט — רק מה שבאמת מעניין, לא רשימת תוצאות. עדיפות: (1) ישראלים בחו\"ל, תמיד להבליט — דני אבדיה ו-NBA, "
              "שחקנים ישראלים באירופה — אבל רק כשיש אירוע קונקרטי (משחק עם מספרים, שיא, פציעה, טרייד), "
              "לא כתבת דעה כללית; (2) ספורטאים ישראלים בתחרויות בינלאומיות (ג'ודו, אולימפיאדה, אליפויות עולם/אירופה) — "
              "מדליה או הישג תמיד נכנסים; (3) כדורגל וכדורסל ישראלי ויורוליג — רק סיפורים מעניינים או משחקים חשובים, "
              "ואז עם התוצאה; (4) NBA ו-כדורגל עולמי — רק על הכוכבים הגדולים באמת (רונאלדו, מסי, לברון וכו') או אירועים "
              "גדולים. יורוליג, NBA וכדורסל בכלל — רק כשיש קשר לישראלים (קבוצה ישראלית, שחקן ישראלי). אסור: קבוצות חלשות, מאבקי תחתית/ירידה, הרכבים צפויים, שחקנים שוליים, תוצאות סתמיות — גם אם חסרות ידיעות. כמה כתבות על אותו שחקן או קבוצה — "
              "ידיעה אחת. תוצאות ומספרים — רק כמו שכתוב בכתבה. "
              "טון קליל וזורם, כמו מוסף ספורט — כותרות עם חיוך ופאנץ', אבל העובדות מדויקות. "
              "bottom_line: משפט או שניים קלילים (עד 40 מילים) עם העובדה המרכזית ופרט קונקרטי — מספר, שם, או מה הלאה. "
              "בלי \"המשמעות\" ובלי ניתוח."),
    "ent": ("🎬", "בידור וריאליטי",
            "סיפור על ספורטאים, קבוצות או הנבחרת — שייך לספורט ולא לכאן, גם אם יש בו מילה כמו \"האח הגדול\". "
            "בידור, סלבס וריאליטי, בעיקר ישראלי: כל ריאליטי ישראלי שרץ עכשיו (הדחות, דרמות, זוכים), סלבס ישראלים — "
            "ומהעולם רק הכי גדולים. רכילות מותרת בלי פילטרים (פרידות, קשרים, סקנדלים) — אבל רק עובדות שכתובות בכתבה, "
            "בלי להמציא. מדי פעם, כשיוצאת סדרה או סרט גדולים או מוערכים מאוד — גם זה. "
            "טון קליל וזורם, כמו מוסף סוף שבוע — כותרות עם חיוך ופאנץ'. "
            "bottom_line: משפט או שניים קלילים (עד 40 מילים) עם העובדה המרכזית ופרט קונקרטי — מספר, שם, או מה הלאה. "
              "בלי \"המשמעות\" ובלי ניתוח."),
}

RULES = """
אתה עורך חדשות בכיר שכותב בריף בוקר בעברית למאור — משקיע פרטי שרוצה להבין מה באמת קרה ולמה זה חשוב.

כללי ברזל:
1. השתמש אך ורק בכתבות שקיבלת. אסור להמציא עובדות, מספרים, שמות או סיבות.
2. source_title — העתק מילה במילה את ה-title של הכתבה שעליה הפריט מבוסס (כך מאמתים שהקישור נכון).
3. title — כותרת בסגנון עיתון איכותי: פעלית, חדה, עם העובדה המרכזית (מספר, שם), עד 10 מילים. בלי קליקבייט ובלי שאלות.
   bottom_line — 2 משפטים קצרים, עד 40 מילים: הראשון — מה קרה בדיוק (מי, מה, כמה, מתי); השני — למה זה חשוב או מה הלאה.
   עברית חיה וזורמת, כמו עיתונאי טוב שמספר לחבר — מדויק, בלי ז'רגון ובלי מילים מיותרות.
   לפתוח ישר בעובדה — בלי "הכתבה מציינת/מדווחת ש...", בלי התווית "המשמעות האמיתית:", ובלי לחזור על הכותרת.
   אסור משפטי סרק כמו "זה חשוב כי זה עשוי להשפיע על...". אם הכתבה לא מספקת משמעות — רק עובדות.
   אם בהגדרת הנושא כתוב טון אחר (ספורט, בידור) — הטון של הנושא גובר על סעיף זה.
   אסור לכתוב בטקסט את שם המקור ("YNET חשף", "רשת 13 פרסמה") או מתי פורסם (age_hours) — הם מוצגים בנפרד.
   אסור לתאר את הכתבה עצמה ("הכתבה מציינת", "פרטים נוספים לא נמסרו", "כתבות עוסקות ב...") — רק מה שקרה.
   bottom_line מוסיף מה שלא כתוב בכותרת — לא חוזר עליה במילים אחרות.
4. כמה כתבות על אותו סיפור → פריט אחד, מהכתבה המפורטת ביותר.
5. הכל בעברית עסקית וזורמת. שם באנגלית מותר בתוך משפט, לא בתחילתו.
"""

TOPIC_FORMAT = """
בחר עד 7 ידיעות לפי סדר חשיבות (יוצגו 5 הראשונות שעוברות בדיקה) — החשובות והרלוונטיות ביותר בנושא.
הכי עדכני קודם: age_hours = כמה שעות עברו מהפרסום; sources = בכמה מקורות שונים מופיע אותו סיפור.
העדף את הטרי ביותר, ואת הסיפורים עם sources גבוה —
זה מה שכולם מדברים עליו עכשיו. הכל מ-24 השעות האחרונות. אם יש פחות ידיעות שבאמת שייכות לנושא — רק אותן;
לעולם לא למלא בידיעות מנושא אחר (או ברכילות, חוץ מבנושא הבידור).

החזר JSON בלבד:
{"items": [{"id": "...", "source_title": "...", "emoji": "אימוג'י אחד שמתאים לידיעה הספציפית, לא דגל", "title": "...", "bottom_line": "..."}]}
"""

# בשישי ושבת אין שידורי ריאליטי — הבידור מתמקד במוספי סוף השבוע
WEEKEND_ENT = ("\nהיום סוף שבוע: בדרך כלל לא שודר ריאליטי אמש — התמקד בראיונות ובכתבות הגדולות של מוספי סוף השבוע "
               "ובשיאים של השבוע בריאליטי (מי הודח השבוע, הרגעים שכולם דיברו עליהם).")

# בלוק קבוע בראש ההודעה: "מה קרה אמש" — רק לנושאים האלה; ריק → לא מוצג
RECAP = {
    "sport": ("🏟️", "אמש במגרשים",
              "המשחקים שב-results (תוצאות רשמיות) כבר מוצגים אוטומטית — אל תכתוב עליהם שורה ב-recap ולא ידיעה ב-items. "
              "חובה: לכל משחק מאמש שיש עליו כתבה — שורה ב-recap ולא ידיעה ב-items. "
              "ב-recap — המשחקים החשובים האחרים מאמש: קבוצות ישראליות באירופה (יורוליג, יורוקאפ, מפעלי אירופה בכדורגל), משחקי צמרת "
              "בליגת העל, נבחרת ישראל; אבדיה וישראלים בחו\"ל — רק אם היה משחק מטורף או חדשה מרהיבה. "
              "label = המפעל בלבד: יורוליג / יורוקאפ / ליגת האלופות / הליגה האירופית / הקונפרנס ליג / ליגת העל / NBA / נבחרת "
              "(ישראלי בחו\"ל — לפי המפעל של הקבוצה שלו); text = בעברית, כל קבוצה עם התוצאה שלה (\"מכבי ת\"א 2, הפועל ב\"ש 1\"), "
              "המנצחת קודם, + חצי משפט. "
              "רק משחקים עם קבוצה או שחקן ישראלי. בלי משחקים סתמיים. "
              "וגם \"he_names\": {\"<שם קבוצה באנגלית מ-results>\": \"<השם המקובל בעברית>\"} לכל קבוצה ב-results"),
    "ent": ("📺", "אמש בריאליטי",
            "aired_last_night = לוח השידורים של אמש (כאן 11, קשת 12, רשת 13). אם הוא לא ריק — שורה לכל תוכנית "
            "ריאליטי ששודרה בו, ורק מהן: text = מה קרה בפרק — קודם מהכתבות (מי הודח, נחשף, ניצח, מה הסעיר), "
            "ואם אין כתבה — מתיאור הפרק בלוח (אז ids ריק). מי הודח/נחשף/ניצח — רק אם כתבה אומרת את זה במפורש; "
            "לעולם לא להסיק מתיאור הפרק בלוח (\"פרק הדחה משוגע\" לא אומר מי הודח). text — עד 20 מילים, מה שקרה ותו לא. אם aired_last_night ריק — "
            "כל ריאליטי שמדברים עליו ב-24 השעות האחרונות (פרק של אתמול, הדחה, דרמה, ריב עם השופטים): "
            "found_by_search = על איזו תוכנית חיפשנו כשהכתבה נמצאה — רמז, לא ודאות. "
            "רק תוכנית שיש לה תוצאה (מי הודח/נחשף/ניצח/עלה שלב) — בלי תוצאה, אין שורה. "
            "label = שם התוכנית, text = רק העובדה, עד 8 מילים, בלי הסברים ובלי לחזור על שם התוכנית: "
            "\"אבי שושן הודח\", ובזמר במסכה — מי נחשף מאחורי איזו מסכה: \"הארנב נחשף: <השם>\" (השם — רק אם כתוב בכתבה). "
            "תוכנית שאין עליה כתבה מה-24 שעות האחרונות ולא בלוח — לא להזכיר. "
            "ל-recap: reality_articles (כתבות מחיפושי הריאליטי) והלוח. ה-items — רק מ-articles: בידור וסלבס, "
            "לא הריאליטי שכבר בבלוק (כדי שיהיו 5 ידיעות נוספות). שורת \"הערב\" נבנית בקוד — לא לכתוב אותה."),
}
RECAP_FIELDS = {  # הדוגמה ל-AI חייבת להתאים לכלל, אחרת הוא מתבלבל ולא מחזיר כלום (09/11/2026)
    "sport": '{"label": "...", "text": "...", "ids": ["..."]}',
    "ent": '{"label": "...", "text": "...", "ids": ["..."]}',
}
RECAP_FORMAT = """
בנוסף החזר באותו JSON: "recap": [{fields}] — {rule}.
שורה קצרה לכל פריט, רק ממה שכתוב בכתבות; אם אין — רשימה ריקה. ה-items לא חוזרים על מה שב-recap.
"""

MARKET_FORMAT = """
קיבלת מספרי שוק אמיתיים (markets), את המניות שלי ושינוי יומי (holdings), כתבות שוק (market) וכתבות לכל מניה.

החזר JSON בלבד:
{
  "headline": "...",   // היום בשוק במשפט אחד פשוט, עד 8 מילים (למשל: "ת\"א זינקה 3%, וול סטריט מעורבת")
  "market_why": [{"label": "...", "text": "...", "ids": ["..."]}],
      // אתמול: 2 הגורמים שהכי הזיזו את השוק. label — 1-3 מילים (למשל "הפד", "נפט", "דוחות טק"); text — משפט אחד, עד 14 מילים
  "watch": [{"label": "...", "text": "...", "ids": ["..."]}],
      // קדימה: 2 האירועים או הסיכונים שעלולים לטלטל את השוק בימים הקרובים — ריבית, אינפלציה ותעסוקה, דוחות צפויים,
      // גאופוליטיקה, נפט. אותו פורמט. רק ממה שמופיע בכתבות
  "market_news": [{"id": "...", "source_title": "...", "emoji": "...", "title": "...", "bottom_line": "..."}],
      // ידיעת השוק הבולטת שלא הוזכרה למעלה (אחת, לא על המניות שלי)
  "companies": [{"ticker": "...", "id": "... או null", "source_title": "... או null", "emoji": "...", "title": "...", "bottom_line": "..."}]
      // חובה פריט לכל מניה עם dramatic=true (אם אין כתבה שמסבירה: id=null ו-bottom_line "אין סיבה מדווחת בכתבות מהיממה האחרונה");
      // ועוד כל ידיעה משמעותית על המניות שלי
}
אסור לחזור על אותו סיפור פעמיים: כל סיפור מופיע רק בחלק אחד — market_why (מה כבר קרה), watch (מה צפוי)
או market_news (סיפור שלא הוזכר בשניהם). אם אין סיפור חדש — market_news ריק.
כתיבה: עברית פשוטה וברורה, כמו כתב כלכלי טוב שמסביר לחבר. כל text — משפט אחד קצר, בלי מקף נוסף בתוכו, בלי לחזור
על ה-label, בלי ז'רגון ובלי מילים באנגלית בתעתיק ("קורלציות", "רפרובשן", "סנטימנט") — במילים רגילות.
"""

ITEMS = {}  # id → כתבה, כדי שהקישורים והמקורות יגיעו מהנתונים ולא מה-AI

def split_reality(entries: list) -> tuple:
    """בידור: כתבות מחיפושי הריאליטי — רק לבלוק; שאר הכתבות — ל-5 הידיעות (אחרת ה-AI בוחר ריאליטי גם לידיעות)."""
    return [e for e in entries if not e.get("found_by_search")], [e for e in entries if e.get("found_by_search")]

def coverage(items: list) -> list:
    """לכל כתבה: בכמה מקורות שונים מופיע אותו סיפור (3+ מילים משותפות בכותרת) — "כולם מדברים על זה"."""
    words = [set(re.findall(r"\w{3,}", i["title"].lower())) for i in items]
    return [len({b["source"] for b, wb in zip(items, words) if len(wa & wb) >= 3}) for wa in words]

def register(prefix: str, items: list, now: datetime | None = None) -> list:
    out = []
    counts = coverage(items) if now else [1] * len(items)
    for n, i in enumerate(items, 1):
        ITEMS[f"{prefix}{n}"] = i
        entry = {"id": f"{prefix}{n}", "source": i["source"], "title": i["title"]}
        if i.get("show"):
            entry["found_by_search"] = i["show"]  # רמז: נמצאה בחיפוש על התוכנית הזו (עלול להיות גם רעש)
        if now:  # כדי שה-AI יעדיף את הטרי ביותר ואת מה שכולם מדברים עליו
            entry["age_hours"] = max(0, round((now - i["published"]).total_seconds() / 3600))
            if counts[n - 1] > 1:
                entry["sources"] = counts[n - 1]
        if not i["summary"].startswith(i["title"][:40]):  # ב-Google News התקציר הוא שוב הכותרת — טוקנים לפח
            entry["summary"] = i["summary"]
        out.append(entry)
    return out

# ── תאריך אמיתי: Google News לפעמים מתארך כתבות ישנות כחדשות (מעריב, 06/11/2026) ──

PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"|article:published_time"\s+content="([^"]+)"')

def real_url(link: str) -> str | None:
    """קישור של Google News → כתובת הכתבה עצמה.
    shortcut: ממשק לא רשמי של גוגל (batchexecute) — אם ישתנה, נחזיר None והכתבה פשוט לא תיבדק"""
    if "news.google.com" not in link:
        return link
    aid = link.split("/articles/")[1].split("?")[0]
    page = fetch(f"https://news.google.com/articles/{aid}").decode("utf-8", "ignore")
    sg, ts = re.search(r'data-n-a-sg="([^"]+)"', page), re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    req = [["Fbv4je", json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                                                   None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                                  aid, int(ts.group(1)), sg.group(1)]), None, "generic"]]
    resp = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                         data="f.req=" + quote_plus(json.dumps([req])))
    m = re.search(r'\[\\"garturlres\\",\\"(https?://[^\\]+)', resp.text)
    return m.group(1) if m else None

def real_date(link: str) -> datetime | None:
    """התאריך שכתוב בכתבה עצמה; None אם אי אפשר לדעת (אתר שחוסם, אין תאריך בדף) — ואז לא פוסלים."""
    try:
        url = real_url(link)
        m = url and PUBLISHED_RE.search(fetch(url).decode("utf-8", "ignore"))
        if not m:
            return None
        d = datetime.fromisoformat(next(g for g in m.groups() if g).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=IL_TZ)
    except Exception:
        return None

def stale_links(ai: dict, now: datetime) -> set:
    """קישורי Google News שה-AI בחר והכתבה עצמה ישנה מ-MAX_AGE."""
    picked = {ITEMS[i]["link"] for k in TOPICS for r in ai.get(f"{k}_recap") or [] for i in r.get("ids") or [] if i in ITEMS}
    picked |= {item["link"] for k in TOPICS for e in ai.get(k) or [] if (item := resolve(e))}
    picked = [l for l in picked if "news.google.com" in l]
    with ThreadPoolExecutor(16) as pool:
        dates = dict(zip(picked, pool.map(real_date, picked)))
    stale = {l for l, d in dates.items() if d and now - d > MAX_AGE}
    print(f"🗓️ real dates: {sum(d is not None for d in dates.values())}/{len(picked)} checked, {len(stale)} stale")
    return stale

SPORTY = re.compile(r"נבחרת|כדורגל|כדורסל|ספורטאי|שחקני ה")

def move_sporty(ai: dict) -> None:
    """ידיעה על ספורט שה-AI שם בבידור — עוברת לסוף רשימת הספורט (ה-AI לא תמיד מקשיב לכלל)."""
    sporty = [e for e in ai.get("ent") or [] if SPORTY.search(f"{e.get('title')} {e.get('bottom_line')}")]
    ai["ent"] = [e for e in ai.get("ent") or [] if e not in sporty]
    ai["sport"] = (ai.get("sport") or []) + sporty

def drop_stale(ai: dict, stale: set) -> None:
    for k in TOPICS:
        ai[k] = [e for e in ai.get(k) or [] if (resolve(e) or {}).get("link") not in stale]
        for r in ai.get(f"{k}_recap") or []:
            r["ids"] = [i for i in r.get("ids") or [] if i in ITEMS and ITEMS[i]["link"] not in stale]

EDITOR = """
אתה עורך-על של בריף בוקר בעברית. קיבלת את כל הידיעות שנבחרו, לפי נושא. תקן רק ניסוח וכפילויות:
1. אותו סיפור פעמיים — באותו נושא או בין נושאים: drop=true לכפול (השאר את הראשון). ידיעה שחוזרת על שורה
   ב-recap או על משחק ב-fixed — drop לידיעה. שורות recap לא מוחקים בגלל כפילות — אבל שורת recap שלא עוסקת
   בתוכנית עצמה (רק מזכירה אותה, למשל "הוזכר בהקשר של...") — drop.
2. מחק פתיחות כמו "YNET חשף", "הכתבה מציינת", "לפי הדיווח", זמני פרסום ("פורסם לפני X שעות") והתווית "המשמעות:".
3. טון: בספורט ובבידור — קליל וזורם; בשאר — ענייני ומדויק.
   בספורט ובבידור — לא להוריד ידיעה אם יישארו פחות מ-5, אלא אם היא כפולה או שוברת כלל מפורש.
   בספורט — drop לידיעה על הרכב, חזרה לסגל או כשירות לקראת משחק (חוץ מפציעה של כוכב גדול), drop לידיעה בלי עובדה קונקרטית (תוצאה, מספר, אירוע — לא "ממשיך להשפיע"), ולידיעת כדורסל/יורוליג/NBA
   בלי קשר לקבוצה או שחקן ישראלי.
4. אסור להוסיף עובדות, מספרים, שמות או תוצאות שלא כתובים בטקסט שקיבלת, ואסור לשנות תוצאות.
החזר JSON בלבד, באותו מבנה: {"topics": [{"topic": "...", "items": [{"id": "...", "title": "...", "bottom_line": "...",
"drop": false}], "recap": [{"n": 0, "text": "...", "drop": false}]}]}
"""

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PROOF = """אתה מגיה לשוני של בריף חדשות בעברית. קיבלת רשימת טקסטים קצרים (texts). תקן בכל אחד רק לשון:
שגיאות כתיב, דקדוק, התאם מין ומספר, סדר מילים שבור, מילה באנגלית שנתקעה באמצע משפט עברי (תרגם), צירוף חסר פשר,
ושם מוכר שנכתב לא נכון (למשל "ביינים" → Binance, "רת'מן" → רוטמן).
אסור: לשנות עובדות, מספרים, שמות או משמעות; להוסיף או למחוק מידע; לשנות טון או לקצר. טקסט תקין — מחזירים בדיוק כמו שהוא.
אל תיגע בסימני פיסוק ובמקפים שאינם שגויים, ואל תפרש ראשי תיבות או מונחים מקובלים (API, AI, מנכ"ל).
החזר JSON בלבד: {"texts": ["...", ...]} — אותו מספר פריטים, באותו סדר."""

def ask_gemini(system: str, payload: dict) -> dict:
    for wait in (10, 30, None):  # Gemini מחזיר לפעמים 503 (עומס) — מחכים ומנסים שוב
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY}, timeout=120,
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
                  "generationConfig": {"responseMimeType": "application/json", "temperature": 0,
                                       "thinkingConfig": {"thinkingBudget": 0}}})  # בלי "חשיבה" — היא עלתה פי 3 מהתשובה
        if resp.status_code not in (429, 500, 503) or wait is None:
            break
        time.sleep(wait)
    if not resp.ok:
        raise RuntimeError(f"Gemini {resp.status_code}: {resp.text[:200]}")
    u = resp.json().get("usageMetadata") or {}
    print(f"💰 Gemini {GEMINI_MODEL}: in={u.get('promptTokenCount')} out={u.get('candidatesTokenCount')} thoughts={u.get('thoughtsTokenCount')}")
    return json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])

def safe_fix(old: str, new) -> str:
    """תיקון של המגיה מתקבל רק אם לא נגע במספרים ולא שינה את האורך בצורה חריגה."""
    new = as_text(new).strip()
    if not new or re.findall(r"\d+", new) != re.findall(r"\d+", old) or not 0.6 <= len(new) / max(1, len(old)) <= 1.5:
        return old
    return new

def proof_slots(ai: dict) -> list:
    """כל הטקסטים שה-AI כתב: (מילון, שדה)."""
    slots = [(e, f) for k in TOPICS for e in ai.get(k) or [] for f in ("title", "bottom_line") if isinstance(e.get(f), str)]
    slots += [(r, "text") for k in RECAP for r in ai.get(f"{k}_recap") or [] if isinstance(r.get("text"), str)]
    slots += [(w, f) for part in ("market_why", "watch") for w in ai.get(part) or [] for f in ("label", "text") if isinstance(w.get(f), str)]
    slots += [(e, f) for part in ("market_news", "companies") for e in ai.get(part) or [] for f in ("title", "bottom_line") if isinstance(e.get(f), str)]
    if isinstance(ai.get("headline"), str):
        slots.append((ai, "headline"))
    return slots

def proofread(ai: dict) -> None:
    """מגיה לשוני (Gemini) על כל הבריף, בקריאה אחת. בלי מפתח או אם נכשל — הטקסט נשאר כמו שהוא."""
    slots = proof_slots(ai)
    if not GEMINI_API_KEY or not slots:
        return
    texts = [d[f] for d, f in slots]
    try:
        fixed = ask_gemini(PROOF, {"texts": texts}).get("texts")
        if not isinstance(fixed, list) or len(fixed) != len(texts):
            raise ValueError(f"expected {len(texts)} texts, got {len(fixed) if isinstance(fixed, list) else type(fixed).__name__}")
    except Exception as ex:
        fail("מגיה (Gemini)", ex)
        return
    changed = rejected = 0
    for (d, f), old, new in zip(slots, texts, fixed):
        ok = safe_fix(old, new)
        if ok != old:
            changed += 1
            if "--dry-run" in sys.argv:
                print(f"✏️ {old}\n → {ok}")
            d[f] = ok
        elif as_text(new).strip() != old:
            rejected += 1
            print(f"✋ proof rejected (numbers/length changed): {old[:60]!r} → {as_text(new)[:60]!r}")
    print(f"✏️ proofread: {changed} fixed, {rejected} rejected, {len(texts) - changed - rejected} unchanged")

def edit_pass(ai: dict) -> None:
    """עורך שני על הטקסט הסופי; אם נכשל — נשאר הטקסט המקורי."""
    payload = {"topics": [{"topic": TOPICS[k][1], "key": k,
                           "items": [{"id": e.get("id"), "title": e.get("title"), "bottom_line": e.get("bottom_line")}
                                     for e in ai.get(k) or []],
                           "recap": [{"n": n, "label": r.get("label"), "text": r.get("text")}
                                     for n, r in enumerate(ai.get(f"{k}_recap") or [])],
                           "fixed": [r["game"] for r in ai.get(f"{k}_results") or []]} for k in TOPICS if ai.get(k)]}
    try:
        edited = {t.get("key") or t.get("topic"): t for t in ask_ai(EDITOR, payload).get("topics") or []}
    except Exception as ex:
        fail("עורך", ex)
        return
    for k in TOPICS:
        t = edited.get(k) or edited.get(TOPICS[k][1]) or {}
        fixes = {x.get("id"): x for x in t.get("items") or []}
        kept = []
        for e in ai.get(k) or []:
            x = fixes.get(e.get("id"), {})
            if x.get("drop"):
                continue
            e.update({f: x[f] for f in ("title", "bottom_line") if isinstance(x.get(f), str) and x[f].strip()})
            kept.append(e)
        ai[k] = kept
        rows = ai.get(f"{k}_recap") or []
        drops = set()
        for x in t.get("recap") or []:
            n = x.get("n")
            if isinstance(n, int) and 0 <= n < len(rows):
                if x.get("drop"):
                    drops.add(n)
                elif isinstance(x.get("text"), str) and x["text"].strip():
                    rows[n]["text"] = x["text"]
        if rows:
            ai[f"{k}_recap"] = [r for n, r in enumerate(rows) if n not in drops]

def ask_ai(system: str, payload: dict) -> dict:
    last_error = None
    for model in MODELS:
        body = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        body.update({"reasoning_effort": "low"} if model.startswith("gpt-5") else {"temperature": 0.2})
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json=body, timeout=300,
            )
        except requests.RequestException as ex:  # חיבור שנפל — כמו כל תקלה: עוברים למודל הבא
            last_error = f"{model}: {type(ex).__name__}"
            print(f"⚠️ {last_error} — trying next model")
            continue
        if resp.ok:
            return json.loads(resp.json()["choices"][0]["message"]["content"])
        last_error = f"{model}: {resp.status_code} {resp.text[:150]}"
        print(f"⚠️ {last_error} — trying next model")
    raise RuntimeError(last_error)

# =============================================================================
# ─── בניית ההודעות (העיצוב המקורי של הבריף) ──────────────────────────────────
# =============================================================================

def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()[:60]

def resolve(e: dict):
    """הכתבה שהפריט באמת מבוסס עליה — לפי source_title, גם אם ה-AI התבלבל ב-id."""
    want = _norm(e.get("source_title"))
    if not want:
        return None
    item = ITEMS.get(e.get("id"))
    if item and _norm(item["title"]) == want:
        return item
    return next((i for i in ITEMS.values() if _norm(i["title"]) == want), None)

META = re.compile(r"הכתבה|בכתבה|הדיווח|בדיווח|לפי הדיווח|הידיעה|פרטים נוספים לא|כתבות עוסקות|מקורות מדווחים|פורסם ב")

def as_text(v) -> str:
    """שדה מה-AI כטקסט — לפעמים הוא מחזיר רשימה במקום מחרוזת (הבריף קרס כך ב-08/11/2026)."""
    if isinstance(v, (list, tuple)):
        return " ".join(as_text(x) for x in v)
    return "" if v is None else str(v)

JARGON = [(r"\bCFO\b", 'סמנכ"ל הכספים'), (r"\bCEO\b", 'מנכ"ל'), (r"לוק[\s־-]?אפ", "תום תקופת החסימה"),
          (r"\bה?סשן\b", "יום המסחר"), (r"\bהמפגש(?= (החזק|החלש|הטוב|הגרוע))", "יום המסחר"),
          (r"\bה?סנטימנט\b", "מצב הרוח בשוק")]

def plain_hebrew(text) -> str:
    """ז'רגון ותרגומים עקומים → עברית ("CFO" → סמנכ"ל הכספים, "לוק-אפ" → תום תקופת החסימה) — ה-AI לא תמיד מקשיב."""
    text = re.sub("[\U0001F1E6-\U0001F1FF]", "", as_text(text))  # בלי דגלים
    for pat, he in JARGON:
        text = re.sub(pat, he, text)
    return text

def clean_text(text, title="") -> str:
    """מוחק משפטים שמדברים על הכתבה ("הכתבה רושמת...", "פרטים נוספים לא נמסרו"), ומשפט ראשון שרק חוזר על הכותרת."""
    text, title = plain_hebrew(text), plain_hebrew(title)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    parts = [re.sub(r"^המשמעות(\s+(?![—–-])\S+)?\s*[:—–-]\s*", "", p) for p in parts]  # "המשמעות המיידית:" / "המשמעות —" → בלי התווית
    kept = [p for p in parts if not META.search(p)] or parts
    if title and len(kept) > 1:
        tw = set(re.findall(r"\w{3,}", title))
        fw = set(re.findall(r"\w{3,}", kept[0]))
        if tw and len(tw & fw) >= 0.8 * len(tw):  # רק משפט שכמעט זהה לכותרת (ב-0.6 נמחקו גם עובדות)
            kept = kept[1:]  # גוף שחוזר על הכותרת — מתחילים ממה שחדש
    return " ".join(kept)

LIGHT = {"sport", "ent"}  # פורמט קליל: כותרת + משפט אחד, בלי "השורה התחתונה"

def article(e: dict, need_id: bool = True, light: bool = False) -> str:
    e = dict(e, **{f: as_text(e.get(f)) for f in ("title", "bottom_line", "emoji") if e.get(f) is not None})
    item = resolve(e)
    if not e.get("title") or not e.get("bottom_line") or (not item and (need_id or e.get("id"))):
        print(f"🚫 dropped (no matching article): id={e.get('id')} source_title={e.get('source_title')!r}")
        return ""  # פריט שלא מתאים לכתבה אמיתית — לא מציגים
    emoji = re.sub("[\U0001F1E6-\U0001F1FF]", "", e.get("emoji") or "")  # בלי דגלים
    out = f"🔹 <b>{esc(emoji) + ' ' if emoji.strip() else ''}{esc(plain_hebrew(e['title']))}</b>\n" + (
        esc(clean_text(e["bottom_line"], e["title"])) if light
        else f"💡 <i>השורה התחתונה:</i> {esc(clean_text(e['bottom_line'], e['title']))}")
    if item:
        out += f"\n🔗 <a href=\"{esc(item['link'])}\">לקריאת הכתבה המלאה</a> · {esc(item['source'])}"
    return out

def _plain(text: str) -> str:
    return re.sub(r"[\"'״׳]", "", text or "").strip()

SHOW_NAMES = [_plain(x) for x in REALITY_SHOWS]
PREMIERE = re.compile(r"פרק 1\b|פרק הבכורה|בכורה|עונה חדשה|פתיחת העונה")

REALITY_PROMPT = """לפניך לוח שידורים (ערוצים 11, 12, 13). אילו מהתוכניות הן ריאליטי או תחרות טלוויזיה
(למשל הישרדות, הזמר במסכה, האח הגדול, תוכניות שירה, בישול, ריקוד או היכרויות)? ריאליטי = מתמודדים אמיתיים
בתחרות עם הדחה, חשיפה או זוכה. לא חדשות, לא סדרות דרמה או קומדיה, לא תוכניות אירוח, סאטירה, תעודה או דוקו-ריאליטי,
ולא שעשועוני טריוויה/חידונים.
השתמש בתיאור כדי להחליט; לא בטוח — אל תכלול.
החזר JSON בלבד: {"reality": ["<שם התוכנית בלבד, בלי שם הפרק — כמו שהוא מופיע בלוח>"]}"""

def reality_names(tv: list) -> list:
    """שמות תוכניות הריאליטי בלוח — כל תוכנית, גם חדשה שלא ברשימה."""
    titles = [_plain(x.get("title")) for x in tv]
    names = []
    if titles:
        try:
            got = ask_ai(REALITY_PROMPT, {"schedule": [{"title": x.get("title"), "description": (x.get("description") or "")[:120]}
                                                      for x in tv]}).get("reality") or []
            got = [_plain(n).split(" - ")[0].strip() for n in got if isinstance(n, str)]  # בלי שם הפרק
            names = [n for n in got if n and any(n in t for t in titles)]
        except Exception as ex:
            fail("זיהוי ריאליטי בלוח השידורים", ex)
    known = [n for n in SHOW_NAMES if any(n in t for t in titles)]  # גיבוי ותוספת: הרשימה הידועה
    return list(dict.fromkeys(names + known))

def reality_on(tv: list, names: list = SHOW_NAMES) -> list:
    """(שם התוכנית, פריט בלוח) לכל ריאליטי בלוח."""
    return [(name, x) for x in tv for name in names or SHOW_NAMES if name in _plain(x.get("title"))][:8]

def short_fact(label: str, text: str) -> str:
    """שורה בבלוק הריאליטי = רק העובדה ("אבי שושן הודח", "הארנב נחשף: X"): בלי שם התוכנית שוב, בלי הסבר
    אחרי ';' או אחרי המשפט הראשון, ובלי "כפי שנרשם בלוח השידורים"."""
    t, label = as_text(text).strip(), as_text(label)
    name = _plain(label)
    if name and _plain(t).startswith(name):  # "הישרדות: אבי שושן הודח" → "אבי שושן הודח"
        t = re.sub(r"^\s*[\"'״׳]?" + re.escape(label.strip('"\'״׳')) + r"[\"'״׳]?\s*[:—–-]\s*", "", t)
    t = re.split(r";|(?<=[.!?])\s", t)[0]
    t = re.sub(r"\s*(כפי ש(נרשם|מופיע|נכתב) ב?לוח( השידורים)?|לפי (ה)?לוח( השידורים)?|בלוח השידורים)", "", t)
    return t.strip(" .")

OUTCOME = re.compile(r"הודח|הודחה|הודחו|נחשף|נחשפה|נחשפו|ניצח|ניצחה|זכה|זכתה|זכו|עלו? (?:ל)?שלב|עלתה (?:ל)?שלב|"
                     r"עלו? לגמר|עלתה לגמר|נבחר|נבחרה|"
                     r"פרש|פרשה|עזב|עזבה|נתפס|נתפסה|אלוף|אלופה")  # "פרק הדחה"/"אירוע הגמר" — לא תוצאה

def schedule_line(name: str, x: dict) -> str:
    """שורה מהלוח עצמו, כשאין כתבה טרייה: מה שכתוב בכותרת הפרק ("הארנב נתפס ונחשף"), בלי ניחושים."""
    title = x.get("title") or ""
    part = title.split(" - ", 1)[1].strip() if " - " in title else ""
    return part.rstrip("!") or "שודר פרק"

def in_tv(label: str, tv: list) -> bool:
    name = re.sub(r"[\"'״׳]", "", label).strip()
    return bool(name) and any(name in re.sub(r"[\"'״׳]", "", t) for t in tv)

def contradicts(text: str) -> bool:
    """שורת משחק שאומרת שקבוצה ניצחה, כשלפי המספרים שבשורה היא הפסידה (או להפך)."""
    pairs = re.findall(r"([^,—\d]+?)\s(\d+)(?=,|\s—|$)", text)
    if len(pairs) < 2:
        return False
    (a, sa), (b, sb) = [(_plain(t).strip(" •—-"), int(n)) for t, n in pairs[:2]]
    if sa == sb:
        return False
    winner, loser = (a, b) if sa > sb else (b, a)
    rest = _plain(text.split("—", 1)[1]) if "—" in text else ""
    won = re.search(r"(\S+(?: \S+)?) (?:חגגה? ניצחון|ניצחה?|גברה? על)", rest)
    return bool(won and loser and (won.group(1) in loser or loser.endswith(won.group(1))) and won.group(1) not in winner)

def recap_rows(key: str, rows: list, results: list = (), shown: set = frozenset(),
               tv_last: list = (), tv_tonight: list = (), names: list = ()) -> list:
    """השורות של ה-AI שבאמת יוצגו בבלוק: (שורה, ids). שורה אחת לכל תוכנית.
    בבידור, כשיש לוח של אמש: רק ריאליטי ששודר אמש (גם עם כתבה — תוכנית שלא שודרה לא נכנסת)."""
    out, shows = [], []
    aired = [n for n, _ in reality_on(tv_last_items(tv_last), names)] if key == "ent" else []
    for r in rows or []:
        ids = [i for i in r.get("ids") or [] if i in ITEMS]
        text = clean_text(r.get("text"))
        if key == "sport" and contradicts(text):
            print(f"🚫 recap {key}: contradiction: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # "הפועל ירושלים 59, העמק 65 — הפועל ירושלים חגגה ניצחון": תוצאה הפוכה, לא מציגים
        label = plain_hebrew(r.get("label")).strip(" —–-")
        if label == "הערב":
            print(f"🚫 recap {key}: premiere row: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # "הערב" נבנה בקוד מהלוח (premiere_line)
        if aired:
            if not any(n in _plain(label) or _plain(label) in n for n in aired):
                print(f"🚫 recap {key}: not aired last night: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
                continue  # לא שודר אמש
            if not ids:
                print(f"🚫 recap {key}: outcome without an article: {label[:20]!r} {text[:50]!r}")
                continue  # מי הודח/נחשף — רק מכתבה ("אבי שושן הודח" חזר 5 ימים אחרי, בלי מקור, 12/11/2026)
        elif not ids and not in_tv(label, [x["title"] for x in tv_last_items(tv_last)]):
            print(f"🚫 recap {key}: no article and not on TV: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # רק שורה שמבוססת על כתבה אמיתית או על תוכנית שבאמת בלוח השידורים
        if not (label and text):
            print(f"🚫 recap {key}: empty label/text: {as_text(r.get('label'))[:20]!r}")
            continue
        r = dict(r, label=label, text=short_fact(label, text) if key == "ent" else text)
        if not r["text"]:
            print(f"🚫 recap {key}: empty label/text: {as_text(r.get('label'))[:20]!r}")
            continue
        show = re.sub(r"[\"'״׳]", "", label).split(" - ")[0].split(" (")[0].strip()
        if key == "ent" and any(show.startswith(x) or x.startswith(show) for x in shows):
            print(f"🚫 recap {key}: duplicate show: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # שורה אחת לכל תוכנית (בספורט — כמה משחקים באותו מפעל זה בסדר)
        if key == "ent" and not OUTCOME.search(r["text"]):
            print(f"🚫 recap {key}: no outcome: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # רק תוצאה קונקרטית — מי הודח/נחשף/ניצח, לא תיאור של התוכנית
        shows.append(show)
        if any(all(n in re.findall(r"\d+", text) for n in re.findall(r"\d+", x["game"])[-2:]) for x in results):
            print(f"🚫 recap {key}: same as official result: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # אותו משחק כמו תוצאה רשמית — כבר מוצג
        if key == "sport" and not ISRAELI_HE.search(text):
            print(f"🚫 recap {key}: no Israeli team: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # בספורט — רק משחקים עם קבוצה או שחקן ישראלי
        if key != "sport" and SPORTY.search(text):
            print(f"🚫 recap {key}: sporty in entertainment: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # ספורט לא נכנס לבלוק הבידור
        if ids and not aired and all(ITEMS[i]["link"] in shown for i in ids):
            print(f"🚫 recap {key}: already shown: {as_text(r.get('label'))[:20]!r} {as_text(r.get('text'))[:50]!r} ids={r.get('ids')}")
            continue  # כבר הוצג בנושא קודם (בבלוק הריאליטי — הכתבות שמורות לו מראש, ראה render)
        out.append((r, ids))
    return out

def tv_last_items(tv: list) -> list:
    """הלוח יכול להגיע כרשימת כותרות או כרשימת פריטים מלאים."""
    return [x if isinstance(x, dict) else {"title": x} for x in tv or []]

def recap_block(key: str, rows: list, results: list = (), he: dict = {}, shown: set = frozenset(),
                tv_last: list = (), tv_tonight: list = (), names: list = ()) -> str:
    icon, title, _ = RECAP[key]
    out = [result_line(r, he) for r in results]  # תוצאות רשמיות — תמיד, ראשונות
    got = recap_rows(key, rows, results, shown, tv_last, tv_tonight, names)
    for r, ids in got:
        line = f'• <b>{esc(r["label"])}</b> — {esc(r["text"])}'
        if ids:
            line += f' · <a href="{esc(ITEMS[ids[0]]["link"])}">{esc(ITEMS[ids[0]]["source"])}</a>'
        out.append(line)
    if key == "ent":
        have = [_plain(r["label"]) for r, _ in got]
        for name, x in reality_on(tv_last_items(tv_last), names):  # ששודר אמש ואין עליו שורה — מהלוח עצמו
            if not any(name in h or h in name for h in have) and OUTCOME.search(schedule_line(name, x)):
                out.append(f"• <b>{esc(name)}</b> — {esc(schedule_line(name, x))}")
                have.append(name)
        for name, x in reality_on(tv_last_items(tv_tonight), names):  # הערב — רק פתיחת עונה
            if PREMIERE.search(f"{x.get('title')} {x.get('description', '')[:80]}"):
                where = f" · {x['channel']}, {x['time']}" if x.get("channel") else ""
                out.append(f"• <b>הערב</b> — {esc(name)}, עונה חדשה{esc(where)}")
    return f"{icon} <b>{title}</b>\n" + "\n".join(out) if out else ""

COMMON_MARKET = {"נתוני", "נתונים", "שוק", "השוק", "מניות", "מדדי", "מדד", "חששות", "דוחות", "ישיבת", "משבר"}

SOURCE_NAMES = [(r"globes|גלובס", "גלובס"), (r"calcalist|כלכליסט", "כלכליסט"), (r"themarker|דה ?מרקר", "TheMarker"),
                (r"ynet", "ynet"), (r"yahoo", "Yahoo"), (r"bloomberg", "Bloomberg")]

def short_source(name: str) -> str:
    return next((short for pat, short in SOURCE_NAMES if re.search(pat, name, re.I)), name.split(" - ")[0].strip())

COMMON = {"הפועל", "מכבי", "נבחרת", "ניצחון", "משחק", "אחרי", "לאחר", "ליגת", "הליגה", "העונה", "ישראל", "שחקן", "מאמן",
          "בעקבות", "חדשה", "חדש", "הראשון", "הראשונה", "סדרה", "עונה", "פרק"}  # מילים נפוצות — לא "אותו כוכב"

def topic_blocks(key: str, ai: dict, shown: set | None = None) -> list:
    """בלוק "אמש" (אם יש) + עד 5 ידיעות; כתבה שכבר בבלוק או כבר הוצגה (גם בנושא אחר) — מדלגים לבאה בתור."""
    seen = shown if shown is not None else set()
    block = ""
    if key in RECAP:
        rows, results = ai.get(f"{key}_recap") or [], ai.get(f"{key}_results") or []
        tv = ai.get(f"{key}_tv_last") or [], ai.get(f"{key}_tv_tonight") or [], ai.get(f"{key}_reality") or []
        block = recap_block(key, rows, results, ai.get(f"{key}_he") or {}, frozenset(seen), *tv)
        shown_rows = recap_rows(key, rows, results, frozenset(seen), *tv)
        seen |= {ITEMS[i]["link"] for _, ids in shown_rows for i in ids}
        labels = [re.sub(r"[\"'״׳]", "", r["label"]) for r, _ in shown_rows if r["label"] != "הערב"]
    else:
        labels = []
    out, per_source, names = [], {}, set()
    titles = [set(re.findall(r"\w{4,}", as_text(e.get("title")))) for e in ai.get(key) or []]
    rare = {w for t in titles for w in t if sum(w in x for x in titles) >= 2} - COMMON if key in LIGHT else set()
    for e, words in zip(ai.get(key) or [], titles):
        if words & rare & names:
            continue  # עוד ידיעה על אותו שחקן/כוכב — אחת מספיקה
        if key == "sport" and "אבדיה" in as_text(e.get("title")) and not re.search(r"\d", f"{e.get('title')} {e.get('bottom_line')}"):
            continue  # אבדיה — רק עם משהו קונקרטי (נקודות, תוצאה), לא "רצף מרשים"

        item = resolve(e) or {}
        link, src = item.get("link"), short_source(item.get("source") or "")
        if link in seen or len(out) == 5 or (src and per_source.get(src, 0) >= 2):
            continue  # עד 2 ידיעות מאותו מקור בנושא (טכנולוגיה, 09/11/2026: 4 מתוך 5 מ-Yahoo Finance)
        if any(l and l in re.sub(r"[\"'״׳]", "", e.get("title") or "") for l in labels):
            continue  # התוכנית כבר בבלוק — בלי כפילות
        if a := article(e, light=key in LIGHT):
            out.append(a)
            seen.add(link)
            per_source[src] = per_source.get(src, 0) + 1
            names |= words & rare
    return [block, *out]

def render(today: datetime, market_rows: list, close_date, holdings: dict, ai: dict, channel: bool = False,
           insiders: list = ()) -> tuple:
    """(הודעות לערוץ, הודעות פרטיות). בערוץ — בריף כללי בלבד; המניות שלך ודוח התקלות — רק בפרטי."""
    used = []  # כתבות שהוזכרו — לא חוזרות כידיעה נפרדת, ומופיעות פעם אחת בשורת המקורות

    def notes(entries) -> list:
        out = []
        for w in (entries or [])[:2]:
            used.extend(i for i in w.get("ids") or [] if i in ITEMS and i not in used)
            text = re.sub(r"\s+[—–]\s+", ", ", clean_text(w.get("text")))  # מקף אחד בשורה — רק אחרי הכותרת
            label = re.sub(r"\s+[—–-]\s+", " ", plain_hebrew(w.get("label"))).strip(" —–-")
            if text:
                out.append(f"• <b>{esc(label)}</b> — {esc(text)}" if label else f"• {esc(text)}")
        return out
    stem = lambda x: re.sub(r"^[בלהומשכ](?=\w{4})", "", x)  # "בנבידיה" = "נבידיה"
    words = lambda w: {stem(x) for x in re.findall(r"\w{4,}", plain_hebrew(w.get("label")).lower())} - COMMON_MARKET
    watch_words = set().union(*[words(w) for w in (ai.get("watch") or [])[:2]])
    why_entries = [w for w in ai.get("market_why") or [] if not words(w) & watch_words]  # "אינפלציה" פעמיים — רק ב"לשים לב"
    why, watch = notes(why_entries), notes(ai.get("watch"))
    seen = {ITEMS[i]["link"] for i in used}
    news = [e for e in ai.get("market_news") or [] if (resolve(e) or {}).get("link") not in seen][:max(0, 5 - len(why) - len(watch))]
    sources = {}
    for i in used:  # "Globes - Israel Business News" ו"גלובס" — אותו מקור, שם קצר
        sources.setdefault(short_source(ITEMS[i]["source"]), ITEMS[i]["link"])
    sources = dict(list(sources.items())[:3])

    market = [
        f"🧭 <b>{esc(plain_hebrew(ai['headline']))}</b>" if ai.get("headline") else "",
        "📊 <b>סגירה" + (f" {close_date:%d/%m}" if close_date else "") + "</b>\n<pre>" + "\n".join(market_rows) + "</pre>"
        if market_rows else "",
        "🔎 <b>מה הזיז את השוק</b>\n" + "\n".join(why) if why else "",
        "⚠️ <b>על מה לשים לב</b>\n" + "\n".join(watch) if watch else "",
        "🕵️ <b>רכישות פנים</b> <i>— מנהלים שקנו מניות של החברה שלהם (דיווחי SEC)</i>\n" + "\n".join(map(fmt_insider, insiders))
        if insiders else "",
        *[article(e) for e in news],
        "📚 <i>מקורות:</i> " + " · ".join(f'<a href="{esc(l)}">{esc(n)}</a>' for n, l in sources.items()) if sources else "",
    ]
    mine = [
        "\n".join(fmt_holding(t, q) for t, q in sorted(holdings.items(), key=lambda kv: abs(kv[1]["pct"]), reverse=True)),
        *[article(c, need_id=False) for c in ai.get("companies") or []],
    ]

    date = f"<i>{today:%d/%m/%Y}</i>"
    shown = set()  # כתבה שהוצגה בנושא אחד לא חוזרת בנושא אחר
    ent_tv = ai.get("ent_tv_last") or [], ai.get("ent_tv_tonight") or [], ai.get("ent_reality") or []
    if reality_on(tv_last_items(ent_tv[0]), ent_tv[2]):  # יש לוח של אמש — כתבות הבלוק שמורות לו
        shown |= {ITEMS[i]["link"] for _, ids in recap_rows("ent", ai.get("ent_recap") or [], (), frozenset(), *ent_tv)
                  for i in ids}  # "הארנב נחשף: איתי שכטר" מכתבה של Sport5 — נשאר בבלוק, לא בספורט
    public = [(f"{icon} <b>{name}</b> · {date}", topic_blocks(key, ai, shown)) for key, (icon, name, _) in TOPICS.items()]
    public.append((f"📈 <b>שוק ההון</b> · {date}", market))
    private = [
        (f"💼 <b>המניות שלך</b> · {date}", mine if holdings else []),
        ("⚠️ <b>בוט החדשות — מה לא עבד היום:</b>", ["\n".join(FAILURES)] if FAILURES else []),
    ]
    to_messages = lambda topics: [[title, SEP, *[b for b in blocks if b]] for title, blocks in topics if any(blocks)]
    public_msgs, private_msgs = to_messages(public), to_messages(private)
    if public_msgs:
        public_msgs[0].insert(0, f"🌅 <b>בוקר טוב{'' if channel else ' מאור'} — בריף בוקר</b> ☕")
    return public_msgs, private_msgs

def rtl(text: str) -> str:
    out, pre = [], False
    for line in text.split("\n"):
        out.append(line if not line or pre else RLM + line)
        pre = (pre or "<pre>" in line) and "</pre>" not in line
    return "\n".join(out)

def chunks(blocks: list, limit: int = 3900) -> list:
    """הודעה אחת לנושא; רק אם היא ארוכה מהמותר בטלגרם — מפוצלת בין כתבות."""
    # shortcut: בלוק בודד ארוך מ-4096 תווים עדיין ייכשל; לפצל לפי שורות אם זה יקרה
    out, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) + 2 > limit:
            out.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    return [rtl(c) for c in (out + [cur] if cur else out)]

# =============================================================================
# ─── שליחה ───────────────────────────────────────────────────────────────────
# =============================================================================

def send_to_telegram(text: str, chat_id: str = "") -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    if resp.status_code != 200:
        # בלי זה ההרצה ב-Actions מסומנת כהצלחה גם כשההודעה לא הגיעה
        raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:300]}")

def build() -> list:
    now = datetime.now(timezone.utc)
    print("📊 Market data...")
    market_rows, close_date = get_markets()
    holdings = get_holdings()
    insiders = get_insiders(datetime.now(timezone.utc))

    today_il = now.astimezone(IL_TZ).date()
    tv_last, tv_tonight = tv_last_night(today_il), get_schedule(today_il)
    if tv_tonight:
        save_tv(today_il, tv_tonight)  # מחר בבוקר — "אמש"
    reality = reality_names(tv_last + tv_tonight)
    aired = [n for n, _ in reality_on(tv_last, reality)]
    print(f"📺 TV: last night {len(tv_last)}, tonight {len(tv_tonight)}, reality: {reality}, aired: {aired}")
    if aired:  # חיפוש לכל ריאליטי ששודר אמש, רק כתבות מאז תחילת הפריים טיים — במקום הרשימה הקבועה
        since = datetime.combine(today_il - timedelta(days=1), datetime.min.time(), IL_TZ).replace(hour=18)
        hours = max(6, int((now - since).total_seconds() // 3600) + 1)
        FEEDS["ent"] = [f for f in FEEDS["ent"] if len(f) < 4] + [
            (None, gn(f'"{n}"', "he", when=f"{hours}h"), 8, n) for n in dict.fromkeys(aired)]

    print("📥 News...")
    news = {cat: register(cat[0], get_feed(cat, now), now) for cat in FEEDS}
    with ThreadPoolExecutor(8) as pool:
        per_stock = dict(zip(HOLDINGS, pool.map(lambda h: read_feed(None, gn(f'"{h[0]}" stock'), now, 3), HOLDINGS.values())))
    stock_news = {t: register(f"h{t}_", items) for t, items in per_stock.items()}
    print("📰 " + ", ".join(f"{k}: {len(v)}" for k, v in news.items()) + f", stocks: {sum(map(len, stock_news.values()))}")

    results = get_results(now)
    weekend = now.astimezone(IL_TZ).weekday() in (4, 5)  # שישי, שבת
    jobs = {key: (RULES + f"\nהנושא: {name} — {rule}\n" + (WEEKEND_ENT if key == "ent" and weekend else "")
                  + TOPIC_FORMAT.replace("עד 7", "10 (לפחות 8 אם יש)" if key in LIGHT else "עד 7")
                  + (RECAP_FORMAT.format(rule=RECAP[key][2], fields=RECAP_FIELDS[key]) if key in RECAP else ""),
                  {"articles": news[key], **({"results": results} if key == "sport" else {})})
            for key, (_, name, rule) in TOPICS.items()}
    general, reality_items = split_reality(news["ent"])
    jobs["ent"][1].update({"articles": general, "reality_articles": reality_items,
                           "aired_last_night": [x for _, x in reality_on(tv_last, reality)]})
    jobs["market"] = (RULES + MARKET_FORMAT, {
        "markets": [re.sub(r"<[^>]+>", "", r) for r in market_rows],
        "holdings": [
            {"ticker": t, "name": HOLDINGS[t][0], "change_pct": round(q["pct"], 2), "dramatic": abs(q["pct"]) >= DRAMATIC}
            for t, q in holdings.items()
        ],
        "market": news["market"],
        "stock_news": stock_news,
    })

    print("🧠 Summarizing...")
    ai = {}
    with ThreadPoolExecutor(len(jobs)) as pool:
        futures = {key: pool.submit(ask_ai, *job) for key, job in jobs.items()}
    for key, fut in futures.items():
        try:
            result = fut.result()
        except Exception as ex:
            fail(f"סיכום AI ({key})", ex)
            continue
        if key == "market":
            ai.update(result)
        else:
            ai[key] = result.get("items", [])
            if key in RECAP:
                ai[f"{key}_recap"] = result.get("recap") or []
                ai[f"{key}_he"] = result.get("he_names") if isinstance(result.get("he_names"), dict) else {}
    ai["sport_results"] = results
    ai["ent_tv_last"], ai["ent_tv_tonight"], ai["ent_reality"] = tv_last, tv_tonight, reality
    count = lambda: {k: len(ai.get(k) or []) for k in ("sport", "ent")}
    print(f"🔎 candidates: {count()}")
    drop_stale(ai, stale_links(ai, now))
    move_sporty(ai)
    print(f"🔎 after date check + sport move: {count()}")
    edit_pass(ai)
    print(f"🔎 after editor: {count()}")
    proofread(ai)
    print("🧠 AI returned: " + ", ".join(f"{k}: {len(v)}" for k, v in ai.items() if isinstance(v, list)) + f", insiders: {len(insiders)}")
    public, private = render(now.astimezone(IL_TZ), market_rows, close_date, holdings, ai, channel=bool(CHANNEL_ID),
                             insiders=insiders)
    print("✅ shown: " + ", ".join(f"{m[1 if i == 0 else 0][:12]}: {sum(b.startswith('🔹') for b in m)}" for i, m in enumerate(public)))
    return [part for msg in public for part in chunks(msg)], [part for msg in private for part in chunks(msg)]

if __name__ == "__main__":
    try:
        public, private = build()
    except Exception as ex:
        if "--dry-run" not in sys.argv:
            send_to_telegram(f"⚠️ בוט החדשות נכשל ולא שלח בריף היום:\n{esc(type(ex).__name__)}: {esc(str(ex)[:300])}")
        raise
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
    if only:  # בדיקה: רק הנושאים האלה, ורק אליך בפרטי — הערוץ לא מקבל כלום
        heads = [f"{TOPICS[k][0]} <b>{TOPICS[k][1]}</b>" if k in TOPICS else "📈 <b>שוק ההון</b>" for k in only]
        public, private, CHANNEL_ID = [m for m in public if any(h in m for h in heads)], [], ""
    for msg, chat in [(m, CHANNEL_ID or CHAT_ID) for m in public] + [(m, CHAT_ID) for m in private]:
        if "--dry-run" in sys.argv:
            print(f"[{'channel' if chat == CHANNEL_ID and CHANNEL_ID else 'private'}]", msg, "\n" + "=" * 40)
        else:
            send_to_telegram(msg, chat)
    print("🏁 Run complete.")
