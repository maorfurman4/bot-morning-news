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
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
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
PER_FEED = 6     # כמה כתבות לקחת מכל מקור (לפי הסדר של המקור עצמו) — מספיק ל-5–8 ידיעות לנושא
DRAMATIC = 3.0   # % — מניה שזזה יותר מזה מקבלת הסבר
MODELS = ["gpt-5-mini", "gpt-4o-mini"]  # הראשון שעובד עם המפתח; mini — בערך חמישית מהמחיר

# (סימול, שם, סוג) — הסוג קובע איך מציגים את השינוי. שמות בעברית כדי שהשורה תישאר מימין לשמאל
MARKETS = [
    ("^GSPC", "אס אנד פי 500", "index"),
    ("^IXIC", "נאסד\"ק", "index"),
    ("^DJI", "דאו ג'ונס", "index"),
    ("TA35.TA", "ת\"א-35", "index"),
    ("^VIX", "מדד הפחד (VIX)", "index"),
    ("^TNX", "אג\"ח ארה\"ב 10 שנים", "yield"),
    ("ILS=X", "דולר/שקל", "fx"),
    ("BZ=F", "נפט ברנט", "usd"),
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

def gn(query: str = "", lang: str = "en") -> str:
    """כתובת Google News: חיפוש (24 שעות) או הכותרות הראשיות."""
    loc = "hl=he&gl=IL&ceid=IL:he" if lang == "he" else "hl=en-US&gl=US&ceid=US:en"
    if not query:
        return f"https://news.google.com/rss?{loc}"
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&{loc}"

# (שם מקור, כתובת). שם None = מאגר (Google News) — שם המקור נלקח מכל כתבה ורק מקורות מ-TRUSTED נשארים
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
    ],
    "ai": [
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("Ars Technica", "https://arstechnica.com/ai/feed/"),
        ("Wired", "https://www.wired.com/feed/tag/ai/latest/rss"),
        ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        (None, gn("artificial intelligence")),
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
    ],
    "world": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        (None, gn("site:reuters.com world")),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ],
    "market": [
        ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        (None, gn("stock market today")),
        (None, gn("Wall Street stocks close")),
        (None, gn("Tel Aviv Stock Exchange")),
    ],
}

# מקורות מהימנים — רק הם נשארים מהמאגרים
TRUSTED = (
    "reuters", "bloomberg", "cnbc", "wall street journal", "wsj", "marketwatch", "yahoo",
    "financial times", "barron", "ap news", "associated press", "investing.com", "axios",
    "bbc", "guardian", "npr", "al jazeera", "politico", "economist", "nikkei", "semafor",
    "techcrunch", "the verge", "wired", "ars technica", "engadget", "mit technology review",
    "ieee", "fortune", "business insider", "the information",
    "times of israel", "haaretz", "jerusalem post", "i24", "ynet", "mako", "n12",
    "globes", "calcalist", "themarker", "הארץ", "גלובס", "כלכליסט", "דה מרקר",
    "מעריב", "כאן 11", "וואלה", "ישראל היום", "חדשות 13",
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
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
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

def fresh(items: list, now: datetime) -> list:
    """רק מהיממה האחרונה, בלי כפילויות; שומר על סדר המקור (Google News מדרג לפי חשיבות)."""
    seen, out = set(), []
    for i in items:
        key = i["title"].strip().lower()
        if now - i["published"] <= MAX_AGE and key not in seen:
            seen.add(key)
            out.append(i)
    return out

def read_feed(name: str | None, url: str, now: datetime, limit: int = PER_FEED) -> list:
    try:
        items = parse_rss(fetch(url), name)
    except Exception as ex:
        fail(f"מקור {name or 'Google News'}", ex)
        return []
    if name is None:
        items = [i for i in items if trusted(i["source"])]
    return fresh(items, now)[:limit]

def get_feed(category: str, now: datetime) -> list:
    with ThreadPoolExecutor(8) as pool:
        per_feed = list(pool.map(lambda f: read_feed(*f, now), FEEDS[category]))
    return fresh([i for items in per_feed for i in items], now)

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
    up = last >= prev
    icon = "🟢" if up else "🔴"
    if kind == "yield":
        return f"{icon} {name}: <b>{last:.2f}%</b> | {move(up, f'{abs(last - prev) * 100:.0f} נ\"ב')}"
    value = {"fx": f"{last:.3f} ₪", "usd": f"{last:.2f} דולר"}.get(kind, f"{last:,.2f}" if last < 100 else f"{last:,.0f}")
    return f"{icon} {name}: <b>{value}</b> | {move(up, f'{abs((last - prev) / prev * 100):.2f}%')}"

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
               "לא וול סטריט ולא חדשות עולם — גם אם פורסמו באתר ישראלי. איראן/ארה\"ב רק אם זה נוגע ישירות לישראל."),
    "ai": ("🤖", "בינה מלאכותית (AI)",
           "בינה מלאכותית: מודלים ומוצרים, חברות AI, השקעות וגיוסים, רגולציה, שבבי AI, מחקר פורץ דרך."),
    "tech": ("🦾", "טכנולוגיה ורובוטיקה",
             "טכנולוגיה ורובוטיקה שבינה מלאכותית אינה במרכזן: רובוטים, רכב חשמלי ואוטונומי, חלל, שבבים, סייבר, "
             "מוצרים וחברות טק."),
    "world": ("🌍", "אקטואליה עולמית",
              "אקטואליה עולמית: גאופוליטיקה, מלחמות, בחירות, אסונות, כלכלה עולמית. בלי ישראל — יש לה הודעה נפרדת."),
}

RULES = """
אתה עורך חדשות בכיר שכותב בריף בוקר בעברית למאור — משקיע פרטי שרוצה להבין מה באמת קרה ולמה זה חשוב.

כללי ברזל:
1. השתמש אך ורק בכתבות שקיבלת. אסור להמציא עובדות, מספרים, שמות או סיבות.
2. source_title — העתק מילה במילה את ה-title של הכתבה שעליה הפריט מבוסס (כך מאמתים שהקישור נכון).
3. title — כותרת עברית חדה וקצרה. bottom_line — 2 משפטים עם עובדות קונקרטיות מהכתבה (מי, מה, כמה, מתי)
   ואז המשמעות האמיתית. אסור משפטי סרק כמו "זה חשוב כי זה עשוי להשפיע על...". אם הכתבה לא מספקת משמעות — רק עובדות.
4. כמה כתבות על אותו סיפור → פריט אחד, מהכתבה המפורטת ביותר.
5. הכל בעברית עסקית וזורמת. שם באנגלית מותר בתוך משפט, לא בתחילתו.
"""

TOPIC_FORMAT = """
בחר את 5 עד 8 הידיעות החשובות ביותר בנושא, לפי סדר חשיבות. אם יש פחות מ-5 ידיעות שבאמת שייכות לנושא — רק אותן;
לעולם לא למלא בידיעות מנושא אחר או ברכילות.

החזר JSON בלבד:
{"items": [{"id": "...", "source_title": "...", "emoji": "🛡️", "title": "...", "bottom_line": "..."}]}
"""

MARKET_FORMAT = """
קיבלת מספרי שוק אמיתיים (markets), את המניות שלי ושינוי יומי (holdings), כתבות שוק (market) וכתבות לכל מניה.

החזר JSON בלבד:
{
  "market_why": [{"text": "...", "ids": ["..."]}],   // 2-3 משפטים: מה זז באמת בשווקים ולמה, מבוסס על המספרים והכתבות
  "watch": [{"text": "...", "ids": ["..."]}],        // 2-4 דברים לשים לב אליהם: מה עלול לטלטל את השוק בימים הקרובים —
      // החלטות ריבית, נתוני אינפלציה ותעסוקה, דוחות של חברות גדולות, גאופוליטיקה, נפט. רק ממה שמופיע בכתבות
  "market_news": [{"id": "...", "source_title": "...", "emoji": "...", "title": "...", "bottom_line": "..."}],
      // 3-5 הידיעות החשובות על השוק הכללי (לא על המניות שלי) — מה קרה ולמה זה חשוב למשקיע
  "companies": [{"ticker": "...", "id": "... או null", "source_title": "... או null", "emoji": "...", "title": "...", "bottom_line": "..."}]
      // חובה פריט לכל מניה עם dramatic=true (אם אין כתבה שמסבירה: id=null ו-bottom_line "אין סיבה מדווחת בכתבות מהיממה האחרונה");
      // ועוד כל ידיעה משמעותית על המניות שלי
}
"""

ITEMS = {}  # id → כתבה, כדי שהקישורים והמקורות יגיעו מהנתונים ולא מה-AI

def register(prefix: str, items: list) -> list:
    out = []
    for n, i in enumerate(items, 1):
        ITEMS[f"{prefix}{n}"] = i
        entry = {"id": f"{prefix}{n}", "source": i["source"], "title": i["title"]}
        if not i["summary"].startswith(i["title"][:40]):  # ב-Google News התקציר הוא שוב הכותרת — טוקנים לפח
            entry["summary"] = i["summary"]
        out.append(entry)
    return out

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
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json=body, timeout=300,
        )
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

def article(e: dict, need_id: bool = True) -> str:
    item = resolve(e)
    if not e.get("title") or not e.get("bottom_line") or (not item and (need_id or e.get("id"))):
        return ""  # פריט שלא מתאים לכתבה אמיתית — לא מציגים
    out = f"🔻 <b>{esc(e.get('emoji', ''))} {esc(e['title'])}</b>\n💡 <i>השורה התחתונה:</i> {esc(e['bottom_line'])}"
    if item:
        out += f"\n🔗 <a href=\"{esc(item['link'])}\">לקריאת הכתבה המלאה</a> · {esc(item['source'])}"
    return out

def render(today: datetime, market_rows: list, close_date, holdings: dict, ai: dict, channel: bool = False) -> tuple:
    """(הודעות לערוץ, הודעות פרטיות). בערוץ — בריף כללי בלבד; המניות שלך ודוח התקלות — רק בפרטי."""
    def notes(entries) -> list:
        out = []
        for w in entries or []:
            src = " · ".join(f'<a href="{esc(ITEMS[i]["link"])}">{esc(ITEMS[i]["source"])}</a>' for i in w.get("ids") or [] if i in ITEMS)
            if w.get("text"):
                out.append(f"• {esc(w['text'])}" + (f" ({src})" if src else ""))
        return out
    why, watch = notes(ai.get("market_why")), notes(ai.get("watch"))

    market = [
        "📊 <b>מצב השוק</b>" + (f" <i>(סגירה {close_date:%d/%m})</i>" if close_date else "") + "\n" + "\n".join(market_rows)
        if market_rows else "",
        "💡 <b>מה זז באמת:</b>\n" + "\n".join(why) if why else "",
        "⚠️ <b>על מה לשים לב:</b>\n" + "\n".join(watch) if watch else "",
        *[article(e) for e in ai.get("market_news") or []],
    ]
    mine = [
        "\n".join(fmt_holding(t, q) for t, q in sorted(holdings.items(), key=lambda kv: abs(kv[1]["pct"]), reverse=True)),
        *[article(c, need_id=False) for c in ai.get("companies") or []],
    ]

    date = f"<i>{today:%d/%m/%Y}</i>"
    public = [(f"{icon} <b>{name}</b> · {date}", [article(e) for e in ai.get(key) or []]) for key, (icon, name, _) in TOPICS.items()]
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
    return "\n".join(RLM + line if line else line for line in text.split("\n"))

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

    print("📥 News...")
    news = {cat: register(cat[0], get_feed(cat, now)) for cat in FEEDS}
    with ThreadPoolExecutor(8) as pool:
        per_stock = dict(zip(HOLDINGS, pool.map(lambda h: read_feed(None, gn(f'"{h[0]}" stock'), now, 3), HOLDINGS.values())))
    stock_news = {t: register(f"h{t}_", items) for t, items in per_stock.items()}
    print("📰 " + ", ".join(f"{k}: {len(v)}" for k, v in news.items()) + f", stocks: {sum(map(len, stock_news.values()))}")

    jobs = {key: (RULES + f"\nהנושא: {name} — {rule}\n" + TOPIC_FORMAT, {"articles": news[key]})
            for key, (_, name, rule) in TOPICS.items()}
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
    public, private = render(now.astimezone(IL_TZ), market_rows, close_date, holdings, ai, channel=bool(CHANNEL_ID))
    print("✅ shown: " + ", ".join(f"{m[1 if i == 0 else 0][:12]}: {sum(b.startswith('🔻') for b in m)}" for i, m in enumerate(public)))
    return [part for msg in public for part in chunks(msg)], [part for msg in private for part in chunks(msg)]

if __name__ == "__main__":
    try:
        public, private = build()
    except Exception as ex:
        if "--dry-run" not in sys.argv:
            send_to_telegram(f"⚠️ בוט החדשות נכשל ולא שלח בריף היום:\n{esc(type(ex).__name__)}: {esc(str(ex)[:300])}")
        raise
    for msg, chat in [(m, CHANNEL_ID) for m in public] + [(m, CHAT_ID) for m in private]:
        if "--dry-run" in sys.argv:
            print(f"[{'channel' if chat == CHANNEL_ID and CHANNEL_ID else 'private'}]", msg, "\n" + "=" * 40)
        else:
            send_to_telegram(msg, chat)
    print("🏁 Run complete.")
